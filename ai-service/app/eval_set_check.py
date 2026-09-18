"""평가셋 파일(`testdata/eval_questions.json`) 자체 점검 - CI 에서 돈다.

실행:  cd ai-service && .venv/bin/python -m app.eval_set_check
       .venv/bin/python -m app.eval_set_check --file <다른 파일>   (점검 자체를 시험할 때)

chunker_check · parsers_check 와 같은 방식이다(`python -m` 으로 돌고 DB 도 외부 API 도
안 쓴다). 다만 보는 대상이 코드가 아니라 <데이터 파일>이라 단언(assert) 대신
틀린 것을 전부 모아서 찍고 종료코드 1 로 끝낸다 - 문항 16개 중 3개가 틀렸으면
첫 번째에서 멈추는 것보다 셋을 한 번에 보여주는 쪽이 고치기 쉽다.
(metrics_check 가 쓰는 방식과 같다)

이 점검이 닫는 축 / 안 닫는 축 (섞어서 말하지 말 것)
────────────────────────────────────────────────────────────────────
  ✅ 파일이 자기 자신에 대해 거짓말하지 않는가 (id 중복 · 빈 칸 · 문항 수)
  ✅ `source_doc` 이 코퍼스에 실재하는가
  ✅ 🔴 `source_text` 가 <실제 청크>인가 - 같은 코퍼스를 같은 설정으로 다시 잘라서 대조
  ❌ 질문이 좋은 질문인가 · 대상이 맞는가  →  사람 검수(`app/eval_set_review.py`)의 몫

🔴 왜 원문 부분 문자열 비교로는 안 되는가 (설계문서 §6.3)
────────────────────────────────────────────────────────────────────
`chunker._pack` 이 조각들을 `\\n` 으로 이어 붙이고 `strip()` 한다. 즉 청크 본문은
원문의 <글자 그대로의 부분 문자열이 아니다>(빈 줄이 한 줄로 줄어든다).
원문에 `source_text in 원문` 으로 물으면 공백 처리에서 깨진다.
반대로 청커는 순수 함수(입력이 같으면 출력이 같고 부작용이 없다)라 DB 없이 돌아가므로,
**다시 잘라서 그 결과와 대조하는 것**이 꼬리표가 실제 청크를 가리킨다는 유일한 증거다.

파일을 읽을 때 `parsers.extract_text` 를 거치는 이유도 같다. 업로드 경로
(`app/main.py` 의 `_process_document`)가 `extract_text` → `chunk_text` 순으로 돌기 때문에,
여기서 `Path.read_text()` 로 바로 읽으면 <정규화 한 겹>이 빠져 실제 적재 결과와 갈린다.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .chunker import chunk_text
from .parsers import ParseError, extract_text

# ai-service/ 디렉터리. `__file__` 은 app/eval_set_check.py 이므로 두 번 올라간다.
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FILE = ROOT / "testdata" / "eval_questions.json"

# 활성 문항 수를 <고정>한다. 설계문서 §5 의 약속이다 - 결함 문항을 뺄 때 대체 문항을
# 넣어 16개를 유지해야 한 문항의 무게(1/16 = 0.0625)가 안 바뀌고 과거 표와 축이 맞는다.
# 이 숫자를 고칠 때는 그 문서도 함께 고칠 것.
ACTIVE_EXPECTED = 16

# 문항마다 반드시 있어야 하고 비어 있으면 안 되는 칸.
REQUIRED_FIELDS = ("id", "question", "ground_truth", "source_doc", "source_text")

# 청킹 설정에 반드시 있어야 하는 칸. 설계문서 §3.2 - 이게 없으면 나중에 대조가 깨졌을 때
# "코퍼스가 바뀐 것" 과 "자르는 규칙이 바뀐 것" 이 그냥 "못 찾음" 으로 뭉개진다.
REQUIRED_CHUNKING = ("chunk_size", "chunk_overlap", "chunk_split_headings")


class _Report:
    """틀린 것을 모아뒀다가 마지막에 한꺼번에 찍는다.

    파이썬에는 테스트 러너의 '실패 수집' 이 기본으로 없어서 직접 만든다.
    `fail()` 이 호출된 적이 있으면 `exit_code` 가 1 이 된다.
    """

    def __init__(self) -> None:
        self.failures: list[str] = []

    def fail(self, message: str) -> None:
        self.failures.append(message)
        print(f"❌ {message}")

    def ok(self, message: str) -> None:
        print(f"✅ {message}")

    @property
    def exit_code(self) -> int:
        return 1 if self.failures else 0


def _load_file(path: Path, report: _Report) -> dict | None:
    """파일을 읽어 dict 로 돌려준다. 못 읽으면 None - 뒤 검사는 전부 건너뛴다.

    🔴 파일이 없으면 <통과가 아니라 실패>다. 점검 대상이 없는 것과 점검을 통과한 것은
       다른 사실인데, 없을 때 조용히 0 으로 끝내면 CI 는 초록불이면서 아무것도 안 본다.
       이 저장소가 반복해 낸 "짜둔 검사가 아무 데서도 안 돈다" 와 같은 부류다.
    """
    if not path.exists():
        report.fail(
            f"평가셋 파일이 없습니다: {path}\n"
            "   → DB 에 있는 세트를 파일로 내보내 만드세요: "
            "cd ai-service && .venv/bin/python -m app.eval_set dump --bot-id 1"
        )
        return None

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        report.fail(f"JSON 을 읽지 못했습니다 ({path}): {e.lineno}번째 줄 - {e.msg}")
        return None

    if not isinstance(raw, dict):
        report.fail(f"최상위가 객체({{...}})여야 하는데 {type(raw).__name__} 입니다: {path}")
        return None

    report.ok(f"파일을 읽었습니다: {path}")
    return raw


def _check_chunking(raw: dict, report: _Report) -> dict | None:
    """청킹 설정 칸을 확인하고, 청커에 넘길 수 있는 모양이면 돌려준다."""
    chunking = raw.get("chunking")
    if not isinstance(chunking, dict):
        report.fail("`chunking` 칸이 없거나 객체가 아닙니다. 설계문서 §3.2 의 세 값이 필요합니다.")
        return None

    missing = [k for k in REQUIRED_CHUNKING if k not in chunking]
    if missing:
        report.fail(f"`chunking` 에 빠진 값: {', '.join(missing)}")
        return None

    if not isinstance(chunking["chunk_size"], int) or not isinstance(chunking["chunk_overlap"], int):
        report.fail("`chunk_size` 와 `chunk_overlap` 은 정수여야 합니다.")
        return None
    if not isinstance(chunking["chunk_split_headings"], bool):
        report.fail("`chunk_split_headings` 는 true/false 여야 합니다.")
        return None

    report.ok(
        "청킹 설정: size={chunk_size} · overlap={chunk_overlap} · "
        "split_headings={chunk_split_headings}".format(**chunking)
    )
    return chunking


def _check_questions_shape(raw: dict, report: _Report) -> list[dict]:
    """문항 목록의 <모양>만 본다: 타입 · 빈 칸 · id 중복 · 활성 문항 수."""
    questions = raw.get("questions")
    if not isinstance(questions, list) or not questions:
        report.fail("`questions` 가 비어 있거나 배열이 아닙니다.")
        return []

    valid: list[dict] = []
    seen: dict[str, int] = {}  # id → 처음 나온 자리(1부터)

    for i, q in enumerate(questions, start=1):
        if not isinstance(q, dict):
            report.fail(f"{i}번째 문항이 객체가 아닙니다({type(q).__name__}).")
            continue

        qid = q.get("id") if isinstance(q.get("id"), str) else f"{i}번째 문항"

        # 빈 칸 검사. `not str(...).strip()` 으로 공백만 든 칸도 빈 것으로 본다 -
        # 꼬리표가 " " 이면 아래 청크 대조가 "못 찾음" 으로만 나와 원인이 흐려진다.
        blanks = [
            f for f in REQUIRED_FIELDS
            if not isinstance(q.get(f), str) or not q[f].strip()
        ]
        if blanks:
            report.fail(f"[{qid}] 비어 있거나 문자열이 아닌 칸: {', '.join(blanks)}")
            continue

        if not isinstance(q.get("active"), bool):
            report.fail(f"[{qid}] `active` 가 true/false 가 아닙니다. 빼둔 문항도 false 로 명시하세요.")
            continue

        # 🔴 설계문서에 명시된 검사는 아니지만 여기서 같이 본다.
        #    §5 가 "지우지 않고 active:false + <사유와 함께> 남긴다" 를 약속하는데,
        #    사유가 없으면 다음 사람이 왜 뺐는지 몰라 같은 질문을 다시 만든다.
        #    그 약속을 지키는지 확인하는 곳이 여기 말고는 없다.
        if q["active"] is False:
            review = q.get("review")
            if not isinstance(review, dict) or not str(review.get("note", "")).strip():
                report.fail(
                    f"[{qid}] 빼둔 문항(active:false)인데 `review.note` 에 사유가 없습니다. "
                    "왜 뺐는지를 남겨야 다음 사람이 같은 질문을 다시 만들지 않습니다."
                )
                continue

        if q["id"] in seen:
            report.fail(f"[{q['id']}] id 가 중복입니다 ({seen[q['id']]}번째 문항과 같습니다).")
            continue
        seen[q["id"]] = i

        valid.append(q)

    active = [q for q in valid if q["active"]]
    if len(active) != ACTIVE_EXPECTED:
        report.fail(
            f"활성 문항이 {len(active)}개입니다. {ACTIVE_EXPECTED}개여야 합니다 "
            f"(전체 {len(questions)}개 중). 한 문항의 무게(1/{ACTIVE_EXPECTED})가 달라지면 "
            "과거 표와 축이 어긋납니다 - 설계문서 §5."
        )
    else:
        report.ok(f"활성 문항 {len(active)}개 · 전체 {len(questions)}개 · id 중복 없음")

    return valid


def _chunks_of(doc: Path, chunking: dict) -> list[str]:
    """코퍼스 문서 하나를 <적재 때와 같은 순서로> 잘라 청크 본문 목록을 돌려준다.

    업로드 경로와 같게 `extract_text`(파싱 + 정규화) → `chunk_text` 를 태운다.
    """
    _, text = extract_text(doc.name, doc.read_bytes())
    chunks = chunk_text(
        text,
        size=chunking["chunk_size"],
        overlap=chunking["chunk_overlap"],
        split_headings=chunking["chunk_split_headings"],
    )
    return [c.content for c in chunks]


def _preview(text: str, width: int = 60) -> str:
    """오류 메시지에 본문 앞머리만 한 줄로 싣는다(개행은 ⏎ 로 보이게)."""
    one_line = text.replace("\n", "⏎")
    return one_line[:width] + ("…" if len(one_line) > width else "")


def _check_source_texts(questions: list[dict], corpus: Path, chunking: dict, report: _Report) -> None:
    """🔴 이 설계에서 가장 중요한 검증: 꼬리표가 실제 청크를 가리키는가."""
    if not corpus.is_dir():
        report.fail(f"코퍼스 디렉터리가 없습니다: {corpus}")
        return

    # 문서 하나를 여러 문항이 가리키므로 잘라둔 결과를 재사용한다(문서당 한 번만 자른다).
    cache: dict[str, list[str] | None] = {}
    checked = 0

    for q in questions:
        name = q["source_doc"]
        doc = corpus / name

        if name not in cache:
            if not doc.is_file():
                cache[name] = None
            else:
                try:
                    cache[name] = _chunks_of(doc, chunking)
                except ParseError as e:
                    report.fail(f"[{q['id']}] 코퍼스 문서를 읽지 못했습니다: {name} - {e}")
                    cache[name] = None

        chunks = cache[name]
        if chunks is None:
            if not doc.is_file():
                report.fail(
                    f"[{q['id']}] `source_doc` 이 코퍼스에 없습니다: {name}\n"
                    f"   → 찾은 곳: {corpus}"
                )
            continue

        wanted = q["source_text"]
        if wanted in chunks:
            checked += 1
            continue

        # 못 찾았을 때 <왜> 못 찾았는지를 갈라준다. 그냥 "못 찾음" 으로 뭉개면
        # 꼬리표가 잘린 것인지 · 코퍼스가 바뀐 것인지 · 청킹 설정이 다른 것인지 알 수 없다.
        partial = [c for c in chunks if wanted in c]
        if partial:
            hint = (
                f"청크의 <일부>와는 맞습니다(청크 {len(partial)}개 안에 들어 있음). "
                "꼬리표가 잘렸거나 청킹 설정이 그때와 다릅니다. 청크 전문을 그대로 넣으세요.\n"
                f"   그 청크: {_preview(partial[0], 80)}"
            )
        elif any(wanted.strip() == c.strip() for c in chunks):
            hint = "앞뒤 공백만 다릅니다. 청크 본문을 그대로 복사하세요."
        else:
            hint = (
                f"{name} 의 어느 청크와도 맞지 않습니다(청크 {len(chunks)}개). "
                "코퍼스가 바뀌었거나 다른 문서의 본문입니다.\n"
                f"   첫 청크: {_preview(chunks[0], 80)}"
            )

        report.fail(
            f"[{q['id']}] `source_text` 가 실제 청크가 아닙니다.\n"
            f"   문서: {name}\n"
            f"   꼬리표: {_preview(wanted, 80)}\n"
            f"   {hint}"
        )

    if checked:
        report.ok(f"꼬리표 {checked}개가 실제 청크와 글자까지 일치 (문서 {len(cache)}개를 다시 잘라 대조)")


def main() -> int:
    parser = argparse.ArgumentParser(description="평가셋 파일이 거짓말하지 않는지 검사한다.")
    parser.add_argument(
        "--file",
        default=str(DEFAULT_FILE),
        help=f"검사할 평가셋 JSON 경로 (기본값: {DEFAULT_FILE})",
    )
    args = parser.parse_args()

    report = _Report()
    path = Path(args.file)

    raw = _load_file(path, report)
    if raw is not None:
        chunking = _check_chunking(raw, report)
        questions = _check_questions_shape(raw, report)
        if chunking is not None and questions:
            # `corpus` 는 ai-service/ 기준 상대 경로다(예: "testdata/corpus").
            corpus = ROOT / str(raw.get("corpus", "testdata/corpus"))
            _check_source_texts(questions, corpus, chunking, report)

    if report.failures:
        print(f"\n❌ {len(report.failures)}건 실패. 위 내용을 고친 뒤 다시 돌리세요.")
    else:
        print("\n전부 통과.")
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
