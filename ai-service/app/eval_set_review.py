"""평가 질문 세트 검수 재료를 출력한다. 판정은 사람이 한다.

실행:
    cd ai-service && .venv/bin/python -m app.eval_set_review
    cd ai-service && .venv/bin/python -m app.eval_set_review --qid q1
    cd ai-service && .venv/bin/python -m app.eval_set_review --only-flagged

무엇을 답하는 도구인가
─────────────────────────────────────────────────────────────────────────────
자동 생성된 평가 질문에는 <질문이 겨냥하는 대상>과 <정답 청크가 규정하는 대상>이
어긋난 것이 섞인다. 2026-09-17 진단에서 실제로 둘 나왔다 - q1 은 "수습" 을 묻는데
정답 청크는 "인턴" 규정이고, q16 은 "업무용 컴퓨터" 를 묻는데 청크는 "개인 노트북"
규정이다. 둘 다 <봇이 거절하는 것이 옳은 동작>인데 지표는 fallback 으로 센다.

그런데 "대상이 어긋난 것" 과 "같은 대상을 다른 낱말로 부르는 것" 은 다르다.
설계문서(2026-09-18-eval-set-curation-design.md) §5.1 이 그 구분을 이렇게 세웠다.

  질문의 낱말이 정답 문서에 없고, <코퍼스의 다른 문서에는 있다>
      -> 질문이 다른 문서를 겨냥하고 있다. 결함 의심                        🔴
  질문의 낱말이 정답 문서에도 없고, <코퍼스 전체에 0건>
      -> 문서가 그 말을 아예 안 쓸 뿐이다. 대상은 같고 표현만 다르다.
         검색이 풀어야 할 정당한 난이도이므로 <남긴다>                      ⚪

이 도구는 그 판단에 필요한 네 칸(정답청크 / 정답문서 / 코퍼스 전체 / 어느 문서)만
찍는다. **verdict 를 자동으로 매기지 않는다.** 🔴 는 낱말 하나에 붙는 표시이지
문항에 대한 판정이 아니다. 판정과 사유 작성은 사람이 파일에 직접 적는다.

⚠️ 설계문서 §5.1 은 기준을 "정답청크" 로 적었는데 여기서는 "정답 문서" 로 넓혔다.
   청크에만 없고 같은 문서에는 있는 낱말까지 🔴 를 붙이면, 정답을 제대로 겨냥한
   문항에도 표시가 붙어 신호가 죽는다. 청크 기준은 표의 첫 칸으로 그대로 보인다.

DB 도 네트워크도 안 쓴다
─────────────────────────────────────────────────────────────────────────────
읽는 것은 `testdata/eval_questions.json` 과 `testdata/corpus/*.md` 파일뿐이다.
세트가 바뀔 때마다 언제든 다시 돌릴 수 있어야 하기 때문이다. 이 저장소가 반복해 낸
실수가 "검사를 안 짠 것이 아니라 짜둔 검사가 아무 데서도 안 돈 것" 이다.

🔴 낱말 추출은 `retriever._keywords` 를 <그대로 재사용한다.>
   하이브리드 검색이 보는 낱말과 검수가 보는 낱말이 갈리면 이 도구가 의미를 잃는다.
   (`retriever_check.py` 도 같은 방식으로 이 함수를 직접 가져다 쓴다)
"""
from __future__ import annotations

import argparse
import json
import unicodedata
from pathlib import Path

from .retriever import _keywords

# 이 파일은 ai-service/app/ 에 있다. parent 가 app, 그 parent 가 ai-service 다.
_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_FILE = _ROOT / "testdata" / "eval_questions.json"
_DEFAULT_CORPUS = _ROOT / "testdata" / "corpus"


# ── 터미널 폭 맞추기 ──────────────────────────────────────────────────────────
# 한글은 터미널에서 두 칸을 차지하는데 파이썬의 len() 은 한 글자로 센다.
# 그래서 f"{word:<10}" 같은 기본 정렬을 쓰면 한글이 섞인 표가 어긋난다.
# unicodedata.east_asian_width 가 'W'(Wide) 나 'F'(Fullwidth) 를 돌려주면 두 칸이다.
def _width(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def _pad(s: str, n: int) -> str:
    """표시 폭 기준으로 오른쪽을 공백으로 채운다. 이미 넘치면 그대로 둔다."""
    return s + " " * max(0, n - _width(s))


def _head(s: str, n: int) -> str:
    """표시 폭 n 칸까지만 자르고 잘렸으면 '...' 을 붙인다."""
    out, w = [], 0
    for c in s:
        cw = 2 if unicodedata.east_asian_width(c) in "WF" else 1
        if w + cw > n:
            return "".join(out) + "..."
        out.append(c)
        w += cw
    return s


# ── 코퍼스 ────────────────────────────────────────────────────────────────────
def load_corpus(corpus_dir: Path) -> dict[str, str]:
    """{파일명: 본문} 을 만든다. 파일 수가 50개 남짓이라 통째로 메모리에 올린다.

    dict 를 쓰는 이유: 낱말마다 전체 파일을 다시 읽으면 (낱말 수 x 파일 수) 번
    디스크를 때린다. 한 번 읽어두면 그 뒤로는 문자열 검색만 남는다.
    """
    files = sorted(corpus_dir.glob("*.md"))
    if not files:
        raise SystemExit(
            f"코퍼스에 .md 파일이 없습니다: {corpus_dir}\n"
            f"  경로가 맞는지 확인하거나 --corpus 로 다른 경로를 지정해주세요."
        )
    return {p.name: p.read_text(encoding="utf-8") for p in files}


def count_in_corpus(word: str, corpus: dict[str, str]) -> list[tuple[str, int]]:
    """그 낱말이 코퍼스의 어느 문서에 몇 번 나오는가. [(문서명, 횟수)] 등장 횟수 내림차순.

    `str.count` 는 겹치지 않는 부분 문자열의 개수를 센다. 하이브리드 검색도 LIKE
    부분 문자열 매칭이라 기준이 같다 - 검색이 보는 것과 검수가 보는 것을 일부러 맞춘 것이다.

    빈 목록이면 코퍼스 전체에 0회라는 뜻이고, 그것이 <정당한 난이도>의 판정 기준이다
    (설계 §변형 규칙 1: 다른 문서에 있으면 결함, 아무 데도 없으면 난이도).

    🔴 `eval_set_check` 가 CI 에서 이 함수를 그대로 쓴다. 검수와 CI 가 같은 기준으로
       세야 "검수에서 0회였던 낱말이 CI 에서 1회" 같은 일이 안 생긴다.
    """
    hits = [(name, text.count(word)) for name, text in corpus.items()]
    hits = [h for h in hits if h[1] > 0]
    # 등장 횟수 내림차순, 같으면 파일명 순. 어느 문서가 이 낱말의 '본거지' 인지 먼저 보인다.
    hits.sort(key=lambda h: (-h[1], h[0]))
    return hits


class WordStat:
    """낱말 하나에 대한 검수 재료.

    파이썬에서 '값 몇 개를 묶어 나르는' 용도로는 보통 dataclass 를 쓰지만,
    여기서는 계산 결과를 담는 것이 전부라 __init__ 에서 다 채우는 평범한 클래스로 뒀다.
    """

    def __init__(self, word: str, in_source: bool, in_doc: bool,
                 hits: list[tuple[str, int]]) -> None:
        self.word = word
        self.in_source = in_source          # 정답 <청크> 본문에 있는가
        self.in_doc = in_doc                # 정답 <문서> 어딘가에 있는가
        self.hits = hits                    # [(문서명, 등장 횟수)] 등장 횟수 내림차순
        self.occurrences = sum(n for _, n in hits)
        self.documents = len(hits)

    @property
    def flagged(self) -> bool:
        """🔴 결함 의심: 정답 <문서>에 아예 없는데 코퍼스의 다른 문서에는 있다.

        기준을 청크가 아니라 문서로 잡은 이유: 청크에만 없고 같은 문서에는 있는 낱말
        (q9 의 "정규직" 이 그렇다)은 질문이 다른 문서를 겨냥한다는 신호가 아니다.
        청크로 잡으면 정답을 제대로 겨냥한 문항에도 🔴 가 붙어 표시가 무의미해진다.
        """
        return not self.in_source and not self.in_doc and self.documents > 0

    @property
    def absent(self) -> bool:
        """⚪ 정당한 난이도 후보: 코퍼스 전체에 0건. 문서가 그 말을 안 쓸 뿐이다."""
        return not self.in_source and self.documents == 0


def word_stats(question: str, source_text: str, corpus: dict[str, str],
               source_doc: str = "") -> list[WordStat]:
    """질문의 낱말마다 (정답청크·정답문서 포함 여부, 코퍼스 등장 현황) 을 계산한다.

    정답 <문서> 칸을 따로 두는 이유: 낱말이 청크에는 없는데 같은 문서의 다른 조항에는
    있다면, 그것은 "질문이 다른 문서를 겨냥한다" 가 아니라 "정답 청크를 잘못 골랐다" 일
    수 있다. 둘은 처리가 다르다(전자는 문항을 뺀다, 후자는 꼬리표를 고친다).
    """
    doc_text = corpus.get(source_doc, "")
    stats = []
    for word in _keywords(question):
        hits = count_in_corpus(word, corpus)
        stats.append(WordStat(word, word in source_text, word in doc_text, hits))
    return stats


# ── 출력 ──────────────────────────────────────────────────────────────────────
def _fmt_where(stat: WordStat, source_doc: str, limit: int = 3) -> str:
    """'어디에' 칸. 정답 문서에는 ★ 를 붙여 눈에 띄게 한다.

    낱말이 정답청크에는 없는데 ★ 문서에는 있다면, 같은 문서의 <다른 조항>에 있다는 뜻이라
    대상이 어긋난 것인지 청크를 잘못 고른 것인지를 가르는 단서가 된다.
    """
    if not stat.hits:
        return ""
    shown = [f"{'★' if name == source_doc else ''}{name.removesuffix('.md')}({n})"
             for name, n in stat.hits[:limit]]
    rest = len(stat.hits) - limit
    return ", ".join(shown) + (f" 외 {rest}" if rest > 0 else "")


def print_question(item: dict, corpus: dict[str, str]) -> list[str]:
    """문항 하나의 검수 재료를 찍고, 🔴 가 붙은 낱말 목록을 돌려준다."""
    qid = item.get("id", "(id 없음)")
    question = item.get("question", "")
    source_doc = item.get("source_doc", "")
    source_text = item.get("source_text", "")
    review = item.get("review") or {}

    state = "active" if item.get("active", True) else "INACTIVE"
    verdict = review.get("verdict")
    tail = f"  판정={verdict}" if verdict else "  판정=(아직 없음)"
    print(f"\n[{qid}] {state}{tail}")
    print(f"     질문     {question}")
    if item.get("ground_truth"):
        print(f"     정답     {item['ground_truth']}")

    if not source_text:
        print("     🔴 source_text 가 비어 있어 낱말 대조를 할 수 없습니다. "
              "dump 도구로 다시 만들거나 손으로 채워주세요.")
        return []
    if source_doc and source_doc not in corpus:
        print(f"     🔴 source_doc '{source_doc}' 이 코퍼스에 없습니다. "
              f"파일명이 바뀌었는지 확인해주세요.")

    print(f"     정답청크 ({source_doc}): {_head(source_text, 76)}")

    stats = word_stats(question, source_text, corpus, source_doc)

    # 청크에는 있는데 그 청크가 나왔다는 문서에는 없는 낱말이 있다면 꼬리표가 어긋난 것이다.
    # 청크는 문서를 잘라 만든 것이므로 원리적으로 일어날 수 없는 조합이다.
    # 🔴 정밀한 검증은 이 도구의 일이 아니다 - eval_set_check 가 문서를 <다시 잘라> 확인한다.
    #    여기서는 이미 계산한 값으로 공짜로 알 수 있어서 같이 찍는다.
    mismatched = [st.word for st in stats if st.in_source and not st.in_doc]
    if mismatched:
        print(f"     🔴 이 낱말이 청크에는 있는데 {source_doc} 에는 없습니다: "
              f"{', '.join(mismatched)}")
        print("        source_text 가 그 문서에서 나온 것이 맞는지 확인해주세요.")
    if review.get("note"):
        print(f"     기록된 사유: {review['note']}")

    # 난이도 변형은 <사람이 일부러 어렵게 만든 것>이라, 검수자가 그 의도를 낱말 표와
    # 나란히 봐야 한다. rule 이 비어 있으면 생성기 원본이므로 아무것도 찍지 않는다.
    difficulty = item.get("difficulty") or {}
    if difficulty.get("rule"):
        words = ", ".join(difficulty.get("words") or []) or "(없음)"
        print(f"     난이도   규칙={difficulty['rule']} · 낱말={words}")
        if difficulty.get("note"):
            print(f"              {difficulty['note']}")

    if not stats:
        print("     (질문에서 뽑아낸 낱말이 없습니다)")
        return []

    print(f"     {_pad('낱말', 14)}{_pad('정답청크', 10)}{_pad('정답문서', 10)}"
          f"{_pad('코퍼스전체', 16)}어디에")
    for st in stats:
        mark = " 🔴" if st.flagged else (" ⚪" if st.absent else "")
        total = f"{st.occurrences}회 / {st.documents}문서"
        print(f"     {_pad(st.word, 14)}"
              f"{_pad('✓ 있음' if st.in_source else '✗ 없음', 10)}"
              f"{_pad('✓ 있음' if st.in_doc else '✗ 없음', 10)}"
              f"{_pad(total, 16)}{_fmt_where(st, source_doc)}{mark}")

    return [st.word for st in stats if st.flagged]


_LEGEND = """
표를 읽는 법
  정답청크          그 낱말이 <정답 청크 본문>에 글자 그대로 있는가
  정답문서          그 낱말이 <정답 청크가 나온 문서> 어딘가에 있는가
                    청크에는 없는데 문서에는 있다면, 질문이 다른 문서를 겨냥한 것이 아니라
                    <정답 청크를 잘못 고른 것>일 수 있다. 처리가 다르다
  코퍼스전체        코퍼스 전체에서 몇 번 나오고, 몇 개 문서에 나오는가
                    ("몇 번" 과 "몇 문서" 는 다른 사실이라 따로 찍는다)
  ★                 정답 청크가 나온 그 문서

  🔴  정답 <문서>에 아예 없는데 <다른 문서에는 있다>. 질문이 다른 문서를 겨냥하는지 의심할 것
  ⚪  코퍼스 전체에 0건. 문서가 그 말을 안 쓰는 것뿐이라면 <정당한 난이도>이므로 남긴다

🔴 는 낱말 하나에 붙는 표시일 뿐 <문항에 대한 판정이 아니다.>
   verdict 와 사유는 사람이 eval_questions.json 에 직접 적는다.

🔴 이 자주 뜨는 것은 정상이고, 이 도구의 한계다
─────────────────────────────────────────────────────────────────────────────
낱말 추출은 `retriever._keywords` 를 그대로 쓴다. 그 함수는 <조사만> 떼므로
활용형("하는", "마쳐야", "있는")도 낱말로 나오고, 그런 말은 대개 다른 문서에 있어
🔴 가 붙는다. 이것을 불용어 목록으로 걸러내지 <않는> 이유는 하나다 -
그러면 하이브리드 검색이 보는 낱말과 검수가 보는 낱말이 갈려, 이 도구가
"검색이 무엇을 보고 있는가" 를 더 이상 대변하지 못한다.

그래서 🔴 목록은 <읽을 순서>로 쓸 것. 질문이 겨냥하는 <대상>을 가리키는 명사
(수습·업무용·정규직 같은 것)에 🔴 가 붙었는지만 보면 된다.
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="평가 질문 세트 검수 재료를 출력한다 (DB·네트워크 안 씀)")
    parser.add_argument("--file", type=Path, default=_DEFAULT_FILE,
                        help=f"질문 세트 JSON (기본값: {_DEFAULT_FILE})")
    parser.add_argument("--corpus", type=Path, default=_DEFAULT_CORPUS,
                        help=f"코퍼스 디렉터리 (기본값: {_DEFAULT_CORPUS})")
    parser.add_argument("--qid", default=None, help="이 문항 하나만 본다 (예: q1)")
    parser.add_argument("--only-flagged", action="store_true",
                        help="🔴 낱말이 있는 문항만 찍는다")
    args = parser.parse_args()

    if not args.file.exists():
        raise SystemExit(
            f"질문 세트 파일이 없습니다: {args.file}\n"
            f"  `python -m app.eval_set dump --bot-id 1` 로 먼저 만들거나, "
            f"--file 로 다른 경로를 지정해주세요."
        )
    try:
        data = json.loads(args.file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(f"질문 세트 JSON 을 읽지 못했습니다: {args.file}\n  {e}")

    corpus = load_corpus(args.corpus)
    questions = data.get("questions") or []
    if args.qid:
        questions = [q for q in questions if q.get("id") == args.qid]
        if not questions:
            raise SystemExit(f"'{args.qid}' 문항이 파일에 없습니다.")

    # 파일이 기록한 청킹 설정을 먼저 찍는다. source_text 는 <그 설정으로 잘랐을 때만>
    # 실제 청크와 일치하므로, 검수자가 무엇을 전제로 보고 있는지 알아야 한다.
    print(f"질문 세트: {args.file}")
    print(f"코퍼스   : {args.corpus} ({len(corpus)}문서)")
    if data.get("chunking"):
        print(f"청킹설정 : {data['chunking']}")

    flagged: list[str] = []
    shown = 0
    for item in questions:
        if args.only_flagged:
            # 먼저 계산해보고 🔴 가 없으면 건너뛴다. 출력을 두 번 하지 않으려고
            # 판정용 계산만 미리 돌린다(코퍼스가 메모리에 있어 값싸다).
            st = word_stats(item.get("question", ""), item.get("source_text", ""),
                            corpus, item.get("source_doc", ""))
            if not any(s.flagged for s in st):
                continue
        shown += 1
        words = print_question(item, corpus)
        if words:
            flagged.append(f"{item.get('id', '?')}({', '.join(words)})")

    active = sum(1 for q in data.get("questions") or [] if q.get("active", True))
    print(f"\n문항 {len(data.get('questions') or [])}개 (활성 {active}개) · 출력 {shown}개")
    if flagged:
        print("🔴 낱말: " + " · ".join(flagged))
        print("   (활용형이 섞인다. 대상을 가리키는 명사에 붙은 것만 보면 된다. "
              "판정은 사람이 한다)")
    else:
        print("🔴 낱말이 붙은 문항이 없습니다.")
    print(_LEGEND)


if __name__ == "__main__":
    main()
