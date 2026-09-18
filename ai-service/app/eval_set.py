"""평가 질문 세트를 저장소 파일로 고정한다 (dump) / 파일에서 DB 로 되돌린다 (load).

실행:
    cd ai-service && .venv/bin/python -m app.eval_set dump --bot-id 1
    cd ai-service && .venv/bin/python -m app.eval_set load --bot-id 1
    cd ai-service && .venv/bin/python -m app.eval_set load --bot-id 1 --replace

왜 필요한가
─────────────────────────────────────────────────────────────────────────────
`V9__bigint_ids.sql` 이 전 테이블을 드롭하면서 평가 질문 16개가 사라졌다.
코퍼스는 `testdata/corpus/` 로 정확히 재현되는데 질문은 DB 에만 있었다.
그래서 2026-09-17 측정은 <새로 생성한> 질문으로 돌 수밖에 없었고, 그 표를
과거 수치와 이어 붙일 수 없게 됐다. 로컬 도커 볼륨이 또 날아가면 같은 일이 반복된다.
→ 질문 세트를 파일로 박제하고, 앞으로 평가 세트는 항상 이 파일에서 채운다.

정답 청크를 <본문 통째로> 가리키는 이유
─────────────────────────────────────────────────────────────────────────────
`eval_questions.source_chunk_id` 는 DB 가 매기는 번호라 재적재하면 바뀐다.
파일에 번호를 적으면 아무것도 가리키지 못한다. 청크 순번(`source_index: 3`)도
청킹 설정이나 코퍼스가 바뀌면 <조용히 다른 청크를 가리킨다> - 이 저장소가 여덟 번 낸
"서로 다른 사실을 한 값으로 뭉개는" 부류다. 그래서 본문 전문을 적고,
load 는 **글자가 완전히 같은** 청크만 받아들인다.

🔴 비슷한 것을 골라 넣지 않는다. 0건이어도 2건 이상이어도 <실패>한다.
   조용히 그럴듯한 것을 고르는 순간 평가셋이 무엇을 가리키는지 아무도 모르게 된다.

설계문서: docs/superpowers/specs/2026-09-18-eval-set-curation-design.md (§3 · §4 · §6.1)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import get_settings
from .db import close_pool, cursor
from .schemas import Id

# 이 파일(app/eval_set.py) 기준으로 ai-service/testdata/eval_questions.json 을 가리킨다.
# 🔴 상대 경로("testdata/...")로 쓰면 <어느 디렉터리에서 실행했는가>에 따라 다른 파일을
#    쓰게 된다. __file__ 기준으로 잡으면 실행 위치와 무관하게 같은 파일이다.
#    .resolve() 는 심볼릭 링크와 ".." 를 펴서 절대 경로로 만든다.
_AI_SERVICE_DIR = Path(__file__).resolve().parent.parent
EVAL_SET_PATH = _AI_SERVICE_DIR / "testdata" / "eval_questions.json"

# 파일의 `corpus` 칸에 적는 값. ai-service 를 기준으로 한 상대 경로다
# (절대 경로를 적으면 다른 사람 기계에서 아무 뜻이 없다).
CORPUS_DIR = "testdata/corpus"


# ─────────────────────────────────────────────────────────────────────────────
# 1. dump - DB → 파일
# ─────────────────────────────────────────────────────────────────────────────

def fetch_questions(bot_id: Id) -> list[tuple]:
    """그 봇의 질문 전부를 정답 청크·문서와 조인해 가져온다.

    LEFT JOIN 인 이유: `source_chunk_id` 는 NULL 일 수 있다
    (FK 가 `ON DELETE SET NULL` 이라 청크가 지워지면 링크만 끊긴다).
    INNER JOIN 으로 쓰면 그런 질문이 <조용히 빠진> 채로 파일이 만들어진다.
    여기서는 빠뜨리지 않고 가져온 뒤, 아래에서 경고로 드러낸다.

    ORDER BY id 로 고정하는 이유: 순서가 흔들리면 dump 를 다시 돌릴 때마다
    파일 전체가 바뀐 것처럼 보여 diff 로 <무엇이 달라졌는지>를 읽을 수 없다.
    """
    with cursor() as cur:
        cur.execute(
            """SELECT q.id, q.question, q.ground_truth, q.is_active,
                      d.filename, c.content
                 FROM eval_questions q
                 LEFT JOIN chunks c    ON c.id = q.source_chunk_id
                 LEFT JOIN documents d ON d.id = c.document_id
                WHERE q.bot_id = %s
                ORDER BY q.id""",
            (bot_id,),
        )
        return list(cur.fetchall())


def _empty_review() -> dict:
    """검수 칸의 빈 모양. 한 군데서만 만들어야 모양이 갈리지 않는다."""
    return {"verdict": "", "note": ""}


def previous_reviews() -> dict[str, dict]:
    """기존 파일에서 <질문 본문 → 검수 내용> 표를 만든다. 파일이 없으면 빈 표.

    왜 DB 가 아니라 파일에서 이어받는가
      `review.verdict`/`note` 는 사람이 적는 값이고 `eval_questions` 에 그 칸이 없다.
      즉 DB 를 아무리 읽어도 검수 결과는 나오지 않는다. 유일한 사본이 이 파일이라,
      dump 가 기존 파일을 안 읽으면 <사람이 적은 것을 dump 가 지운다.>
      설계 §7-2 의 왕복 검증(load → dump)이 §4 ②(검수 기입) 다음이라,
      순서대로 밟으면 반드시 밟게 되는 지뢰였다.

    왜 `id` 가 아니라 질문 본문으로 맞추는가
      `id` 는 파일 안에서만 쓰는 <순번>이다. 문항이 하나 추가되거나 빠지면 뒤가 전부
      밀려서, q5 의 검수 사유가 엉뚱한 질문에 붙는다. 그러면 "왜 뺐는지" 를 남기려던
      파일이 오히려 거짓말을 하게 된다. 질문 본문은 그 문항의 정체 자체라 안 밀린다.

    ⚠️ `active` 는 여기서 이어받지 않는다. DB 의 `is_active` 를 그대로 쓴다.
       load 가 `active: false` 를 `is_active=false` 로 넣으므로 <DB 가 이미 그 사실을
       갖고 있다.> 두 군데서 이어받으면 파일과 DB 가 어긋났을 때 어느 쪽이 맞는지
       알 수 없어진다 - 값을 가진 쪽이 하나여야 한다.
    """
    if not EVAL_SET_PATH.exists():
        return {}
    try:
        old = json.loads(EVAL_SET_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # 여기서 죽이지 않는다. 깨진 파일 때문에 dump 자체가 막히면 DB 의 질문을
        # 건져낼 방법이 없어진다. 대신 이어받기를 포기했다는 사실은 반드시 찍는다.
        print("⚠️  기존 평가셋 파일이 올바른 JSON 이 아니라 검수 내용을 이어받지 못했습니다.")
        return {}

    table: dict[str, dict] = {}
    duplicated: set[str] = set()
    for q in old.get("questions") or []:
        question = q.get("question")
        if not question:
            continue
        review = q.get("review") or _empty_review()
        if question in table and table[question] != review:
            # 같은 질문이 두 번 있는데 검수 내용이 다르면 어느 쪽인지 고를 수 없다.
            # 조용히 하나를 고르는 것이 이 저장소가 반복해 낸 실수라, 둘 다 버린다.
            duplicated.add(question)
        table[question] = review
    for question in duplicated:
        table.pop(question, None)
        print(f"⚠️  기존 파일에 같은 질문이 두 번 있고 검수 내용이 달라 이어받지 않았습니다: "
              f"{question[:40]}...")
    return table


def build_payload(rows: list[tuple], reviews: dict[str, dict] | None = None) -> dict:
    """DB 행들 → 파일에 쓸 dict.

    `id` 를 DB 의 번호가 아니라 순번("q1", "q2" ...)으로 매긴다.
    DB 번호는 재적재할 때마다 바뀌므로 파일에 적어봐야 다음 번엔 거짓말이 된다.
    순번은 파일 안에서만 쓰는 이름표라 재적재해도 그대로다.

    `chunking` 은 <지금 설정값>을 읽어 적는다(하드코딩하지 않는다).
    나중에 `source_text` 로 청크를 못 찾을 때, "코퍼스가 바뀐 것"과
    "자르는 규칙이 바뀐 것"을 가르는 유일한 단서다. 안 적으면 둘 다 "못 찾음"으로 뭉개진다.
    """
    s = get_settings()
    # None 을 그대로 두면 아래에서 `reviews.get(...)` 이 터진다. 기본값을 인자 자리에
    # `{}` 로 쓰지 않는 이유는 파이썬의 <가변 기본값> 함정 때문이다: 기본값 객체는
    # 함수 정의 때 한 번만 만들어져 호출들 사이에 공유된다.
    reviews = reviews or {}
    questions = []
    for n, (_db_id, question, ground_truth, is_active, filename, content) in enumerate(rows, 1):
        review = reviews.get(question)
        questions.append({
            "id": f"q{n}",
            "question": question,
            "ground_truth": ground_truth,
            # 정답 청크가 끊긴 질문은 None 으로 남긴다. 빈 문자열로 적으면
            # "본문이 빈 청크"와 "가리키는 청크가 없음"이 같은 값이 된다.
            "source_doc": filename,
            "source_text": content,
            # DB 의 is_active 를 그대로 쓴다(파일에서 이어받지 않는다). 근거는
            # previous_reviews 의 주석 마지막 문단에 있다.
            "active": bool(is_active),
            # 검수는 사람이 나중에 한다. 빈 칸을 <미리 만들어 두는> 이유는,
            # 칸이 아예 없으면 검수하는 사람이 무엇을 적어야 하는지 모르기 때문이다.
            "review": review if review is not None else _empty_review(),
        })
    return {
        "corpus": CORPUS_DIR,
        "chunking": {
            "chunk_size": s.chunk_size,
            "chunk_overlap": s.chunk_overlap,
            "chunk_split_headings": s.chunk_split_headings,
        },
        "questions": questions,
    }


def dump(bot_id: Id) -> int:
    """DB 의 질문을 파일로 쓴다. 성공하면 0, 실패하면 1(= 셸 종료코드)."""
    rows = fetch_questions(bot_id)
    if not rows:
        print(f"봇 {bot_id} 에 평가 질문이 없습니다. 먼저 질문을 생성하거나 load 로 넣어주세요.")
        return 1

    # 🔴 기존 파일을 <쓰기 전에> 읽는다. 사람이 적어둔 검수 내용을 이어받기 위해서다.
    #    이 한 줄이 없으면 설계 §7-2 의 왕복 검증(load → dump)이 검수 결과를 지운다.
    reviews = previous_reviews()
    payload = build_payload(rows, reviews)

    # 이어받은 것과 원래 빈 칸이었던 것을 <구분해서> 찍는다. 조용히 넘어가면
    # "검수를 안 한 문항" 과 "검수 내용이 날아간 문항" 이 화면에서 같은 모습이 된다.
    carried = sum(1 for _db_id, question, *_ in rows if question in reviews)
    new = len(rows) - carried
    if reviews:
        print(f"기존 파일에서 검수 내용 {carried}건을 이어받았습니다 "
              f"(파일에 없던 새 질문 {new}건은 빈 칸으로 둡니다).")
    elif EVAL_SET_PATH.exists():
        print("기존 파일에서 이어받을 검수 내용이 없어 전 문항을 빈 칸으로 씁니다.")

    # 정답 청크가 끊긴 질문은 load 로 되돌릴 수 없다. 파일은 쓰되 <반드시 드러낸다> -
    # 여기서 조용히 넘어가면 "되돌릴 수 있는 파일"이라고 착각한 채 볼륨을 날리게 된다.
    broken = [q["id"] for q in payload["questions"] if not q["source_text"]]

    EVAL_SET_PATH.parent.mkdir(parents=True, exist_ok=True)
    # ensure_ascii=False 가 없으면 한글이 전부 \uXXXX 로 박혀 사람이 못 읽는다.
    # 이 파일은 <사람이 열어서 검수하는> 것이 절반의 목적이라 그러면 안 된다.
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    EVAL_SET_PATH.write_text(text, encoding="utf-8")

    active = sum(1 for q in payload["questions"] if q["active"])
    print(f"{EVAL_SET_PATH} 에 {len(payload['questions'])}문항을 썼습니다 (활성 {active}문항).")
    if broken:
        print("⚠️  정답 청크가 끊긴 문항이 있습니다(source_chunk_id 가 NULL):")
        print(f"    {', '.join(broken)}")
        print("    이 문항들은 load 로 되돌릴 수 없습니다. 파일에서 source_text 를 직접 채우거나")
        print("    문항을 다시 만들어야 합니다.")
        return 1
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# 2. load - 파일 → DB
# ─────────────────────────────────────────────────────────────────────────────

def read_payload() -> dict:
    """파일을 읽는다. 없거나 깨졌으면 무엇을 어떻게 하면 되는지까지 알려준다."""
    if not EVAL_SET_PATH.exists():
        raise SystemExit(
            f"평가셋 파일이 없습니다: {EVAL_SET_PATH}\n"
            "먼저 `python -m app.eval_set dump --bot-id <봇번호>` 로 만들어주세요."
        )
    try:
        return json.loads(EVAL_SET_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        # 줄·열까지 그대로 전해야 사람이 그 자리를 열어볼 수 있다.
        raise SystemExit(
            f"평가셋 파일이 올바른 JSON 이 아닙니다: {EVAL_SET_PATH}\n"
            f"  {e.lineno}번째 줄 {e.colno}번째 칸: {e.msg}"
        ) from e


def warn_chunking_mismatch(payload: dict) -> None:
    """파일에 적힌 청킹 설정과 지금 설정이 다르면 경고한다.

    막지는 않는다. 다를 수 있는 것이 정상인 상황(설정을 일부러 바꿔보는 중)이 있고,
    진짜 실패는 아래 글자 대조에서 <어느 문항이 왜> 안 맞는지까지 나오기 때문이다.
    다만 안 찍으면 "코퍼스가 바뀐 것"과 "자르는 규칙이 바뀐 것"을 가를 단서가 사라진다.
    """
    s = get_settings()
    now = {
        "chunk_size": s.chunk_size,
        "chunk_overlap": s.chunk_overlap,
        "chunk_split_headings": s.chunk_split_headings,
    }
    saved = payload.get("chunking") or {}
    if saved and saved != now:
        print("⚠️  파일에 적힌 청킹 설정과 지금 설정이 다릅니다.")
        print(f"    파일: {saved}")
        print(f"    지금: {now}")
        print("    청크 본문이 안 맞는다면 코퍼스가 아니라 <자르는 규칙>이 원인일 수 있습니다.")


def resolve_chunk(bot_id: Id, source_text: str) -> list[Id]:
    """본문이 <글자까지 완전히 같은> 청크의 id 목록. 그 봇 안에서만 찾는다.

    `content = %s` 는 부분 일치도 정규화도 아닌 정확 비교다.
    LIKE 나 유사도로 느슨하게 찾으면 "비슷한 것"을 고르게 되는데,
    그 순간 평가셋의 정답 청크가 무엇을 가리키는지 아무도 알 수 없게 된다.

    `bot_id` 조건은 봇 간 격리다. 여기 빼면 남의 봇 청크를 정답으로 붙일 수 있다.
    """
    with cursor() as cur:
        cur.execute(
            "SELECT id FROM chunks WHERE bot_id = %s AND content = %s ORDER BY id",
            (bot_id, source_text),
        )
        return [r[0] for r in cur.fetchall()]


def match_all(bot_id: Id, questions: list[dict]) -> tuple[list[tuple[dict, Id]], list[str]]:
    """전 문항을 청크에 맞춰본다. (성공한 (문항, 청크id) 쌍, 실패 메시지 목록)

    🔴 **전부 맞춰본 뒤에 넣는다.** 한 문항씩 넣다가 중간에 실패하면
       "절반만 들어간 평가셋" 이 남고, 그 상태로 평가를 돌리면 문항 수가 달라
       지표가 조용히 다른 뜻이 된다. 실패는 <넣기 전에> 전부 모아서 보고한다.
    """
    matched: list[tuple[dict, Id]] = []
    errors: list[str] = []
    for q in questions:
        qid = q.get("id", "(id 없음)")
        source_text = q.get("source_text") or ""
        source_doc = q.get("source_doc") or "(문서 미상)"
        if not source_text:
            errors.append(f"[{qid}] source_text 가 비어 있습니다. 정답 청크 본문을 채워주세요.")
            continue

        ids = resolve_chunk(bot_id, source_text)
        # 본문이 길면 통째로 찍어봐야 읽기 어렵다. 어느 청크인지 알아볼 만큼만 앞머리를 보인다.
        head = source_text[:60].replace("\n", " ")
        if len(ids) == 0:
            errors.append(
                f"[{qid}] 본문이 같은 청크를 봇 {bot_id} 에서 찾지 못했습니다.\n"
                f"        문서: {source_doc}\n"
                f"        본문 앞머리: {head}...\n"
                f"        코퍼스를 이 봇에 올렸는지, 청킹 설정이 파일과 같은지 확인해주세요."
            )
        elif len(ids) > 1:
            errors.append(
                f"[{qid}] 본문이 같은 청크가 {len(ids)}개입니다(id: "
                f"{', '.join(str(i) for i in ids)}). 어느 쪽인지 알 수 없어 넣지 않습니다.\n"
                f"        문서: {source_doc}\n"
                f"        본문 앞머리: {head}...\n"
                f"        같은 문서를 두 번 올렸는지 확인해주세요."
            )
        else:
            matched.append((q, ids[0]))
    return matched, errors


def count_existing(bot_id: Id) -> tuple[int, int]:
    """(그 봇의 질문 수, 질문에 딸린 평가 결과 행 수).

    결과 행 수까지 세는 이유: `eval_results.question_id` 가 `ON DELETE CASCADE` 라
    질문을 지우면 <과거 실행 상세가 통째로> 함께 날아간다. 몇 건이 날아가는지를
    보여주지 않으면 `--replace` 가 무엇을 지우는지 모르는 채로 눌리게 된다.
    """
    with cursor() as cur:
        cur.execute("SELECT count(*) FROM eval_questions WHERE bot_id = %s", (bot_id,))
        questions = cur.fetchone()[0]
        cur.execute(
            """SELECT count(*)
                 FROM eval_results r
                 JOIN eval_questions q ON q.id = r.question_id
                WHERE q.bot_id = %s""",
            (bot_id,),
        )
        results = cur.fetchone()[0]
    return questions, results


def load(bot_id: Id, replace: bool) -> int:
    """파일의 질문을 DB 에 넣는다. 성공하면 0, 실패하면 1."""
    payload = read_payload()
    questions = payload.get("questions") or []
    if not questions:
        print(f"{EVAL_SET_PATH} 에 questions 가 비어 있습니다.")
        return 1

    warn_chunking_mismatch(payload)

    existing_q, existing_r = count_existing(bot_id)
    if existing_q and not replace:
        # 🔴 기본 동작이 "비어 있을 때만 넣는다" 인 이유가 이것이다.
        #    말없이 지우면 과거 실행 상세가 함께 사라진다.
        print(f"봇 {bot_id} 에 이미 평가 질문 {existing_q}문항이 있습니다. 넣지 않았습니다.")
        print("    덧붙이면 같은 질문이 중복되므로, 지우고 다시 넣으려면 --replace 를 붙여주세요.")
        print(f"    ⚠️ --replace 는 그 {existing_q}문항과 함께 평가 결과 {existing_r}건을 지웁니다.")
        return 1

    matched, errors = match_all(bot_id, questions)
    if errors:
        print(f"정답 청크를 확정하지 못한 문항이 {len(errors)}개 있어 <하나도> 넣지 않았습니다.")
        print("비슷한 청크를 대신 고르지 않습니다. 가리키는 대상이 틀린 평가셋은 없느니만 못합니다.\n")
        for msg in errors:
            print(f"  {msg}")
        return 1

    # 지우기와 넣기를 같은 트랜잭션 블록 안에 둔다. 중간에 실패하면 전부 롤백되므로
    # "옛 질문은 지워졌는데 새 질문은 안 들어간" 상태가 남지 않는다.
    with cursor(commit=True) as cur:
        if replace and existing_q:
            print(f"⚠️  봇 {bot_id} 의 기존 평가 질문 {existing_q}문항을 지웁니다.")
            print(f"    eval_results 가 ON DELETE CASCADE 라 과거 실행 상세 {existing_r}건도"
                  " 함께 지워집니다. 되돌릴 수 없습니다.")
            cur.execute("DELETE FROM eval_questions WHERE bot_id = %s", (bot_id,))
        for q, chunk_id in matched:
            # active: false 문항도 넣는다. 파일과 DB 가 같은 모습이어야 하고,
            # evalrun 은 이미 `WHERE is_active` 로 거르므로 평가에는 안 섞인다.
            cur.execute(
                """INSERT INTO eval_questions
                       (bot_id, question, ground_truth, source_chunk_id, is_active)
                   VALUES (%s, %s, %s, %s, %s)""",
                (bot_id, q["question"], q["ground_truth"], chunk_id,
                 bool(q.get("active", True))),
            )

    active = sum(1 for q, _ in matched if q.get("active", True))
    print(f"봇 {bot_id} 에 {len(matched)}문항을 넣었습니다 (활성 {active}문항).")
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# 3. CLI
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="평가 질문 세트를 파일로 고정하거나(dump) 파일에서 DB 로 되돌린다(load)")
    # add_subparsers(dest=...) 는 고른 하위 명령 이름을 args.command 에 담아준다.
    # required=True 가 없으면 아무 명령도 안 줬을 때 args.command 가 None 이 되어
    # 아래 분기가 조용히 아무것도 안 하고 끝난다.
    sub = parser.add_subparsers(dest="command", required=True)

    p_dump = sub.add_parser("dump", help="DB 의 질문을 testdata/eval_questions.json 으로 쓴다")
    p_dump.add_argument("--bot-id", type=int, required=True)

    p_load = sub.add_parser("load", help="testdata/eval_questions.json 의 질문을 DB 에 넣는다")
    p_load.add_argument("--bot-id", type=int, required=True)
    p_load.add_argument(
        "--replace", action="store_true",
        help="기존 질문을 지우고 넣는다 (평가 결과도 CASCADE 로 함께 지워진다)")

    args = parser.parse_args()
    if args.command == "dump":
        return dump(args.bot_id)
    return load(args.bot_id, args.replace)


if __name__ == "__main__":
    try:
        # main() 이 돌려준 값을 그대로 종료코드로 쓴다. 0 이 아니면 셸·CI 가 실패로 본다 -
        # "돌렸고 끝났다" 와 "돌리다 실패했다" 를 같은 값으로 뭉개지 않기 위해서다.
        sys.exit(main())
    finally:
        close_pool()
