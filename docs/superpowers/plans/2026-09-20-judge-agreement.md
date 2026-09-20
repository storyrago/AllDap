# 채점자 정확도 대조 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 박제된 평가 결과 44건에 사람이 충실성 라벨을 매기고, 채점자(LLM-as-judge)와 대조해 <어느 방향으로 얼마나> 틀리는지 낸다.

**Architecture:** DB 의 `eval_results`(run 11~16)에서 중복을 제거해 44개 케이스를 복원하고(`app/eval_cases.py`), 채점자 점수를 <뺀> 라벨 파일을 내보낸 뒤(`dump`), 사람이 채운 라벨과 DB 의 채점자 점수를 합쳐 혼동행렬·방향·전체충실성 왜곡량을 낸다(`report`). 평가를 새로 돌리지 않고, 기본 경로는 외부 API 를 부르지 않는다.

**Tech Stack:** Python 3 · psycopg(기존 `app/db.py` 풀) · 표준 라이브러리 `json`·`hashlib`·`argparse`. 새 의존성 없음.

**설계 문서:** `docs/superpowers/specs/2026-09-20-judge-agreement-design.md`

## Global Constraints

- **브랜치는 `feat/judge-agreement` 다.** 이미 만들어져 있고 설계 문서가 커밋돼 있다.
- **평가를 새로 돌리지 않는다.** run 11~16 이 원자료다. 회당 1,300 뉴런을 쓸 이유가 없다.
- 🔴 **`eval_set load --replace` 를 절대 돌리지 말 것.** `eval_results` 156행이 CASCADE 로 날아가고 이 슬라이스의 재료가 사라진다.
- **테스트는 `app/<이름>_check.py` 모듈이다.** 이 저장소에 pytest 가 없다. `python -m app.x_check` 로 돌리고, 실패는 `assert` 또는 종료코드 1 이다.
- **주석·에러 메시지·출력은 한국어.** 에러는 "무엇을 어떻게 하면 되는지" 까지 적는다.
- **em dash(—) 를 쓰지 않는다.** 쉼표·콜론·괄호로 대체한다.
- **커밋 메시지는 `<타입>: <한국어 요약>`** (feat / fix / refactor / test / docs / chore).
- 커밋 말미에 `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>` 를 붙인다.
- **라벨 값은 `0.0` / `0.5` / `1.0` 셋뿐이다.** 다른 값은 실패다.
- **대상 run 은 `[11, 12, 13, 14, 15, 16]` 이다.** 기본값으로 박아둔다.
- 작업 디렉터리는 `ai-service/` 이고 파이썬은 `.venv/bin/python` 이다.

---

## File Structure

| 파일 | 책임 | DB | 외부 API |
|---|---|---|---|
| `ai-service/app/eval_cases.py` (신규) | `eval_results` 한 행을 채점자 입력으로 되돌린다. 중복 제거. **이것 하나만 한다** | ✅ | ❌ |
| `ai-service/app/judge_agreement.py` (신규) | `dump`(블라인드 파일 내보내기) · `report`(집계). 집계 계산은 순수 함수로 분리 | ✅ | `--reasons` 일 때만 |
| `ai-service/app/judge_agreement_check.py` (신규) | 순수 함수 자체 점검. **CI 에서 돈다** | ❌ | ❌ |
| `ai-service/testdata/judge_labels.json` (신규, 사람이 채움) | 44건의 사람 라벨. 저장소에 남아야 재현된다 | - | - |
| `.github/workflows/ci.yml` (수정) | 자체 점검 목록에 추가 · 수동 목록 주석 정정(여섯 → 일곱) | - | - |
| `AGENTS.md` (수정) | 실행법과 결과 | - | - |
| `docs/BACKLOG.md` (수정) | `reason` 이 저장되지 않는 것을 남긴다 | - | - |
| `docs/decisions.md` (수정) | 결정 한 줄 | - | - |
| `ai-service/app/judge.py` (수정, Task 7) | 첫머리 TODO 를 실제 결과로 바꾼다 | - | - |

**`eval_cases.py` 를 따로 뺀 이유**: 다음 슬라이스(무관한 청크 주입 탐침)도 똑같이 "저장된 케이스를 복원해 `judge.score()` 에 다시 넣는" 일을 한다. 이것만 import 하면 파일 하나 더 쓰는 것으로 끝난다.

---

## 사실 확인 (2026-09-20 실측. 계획이 이 위에 서 있다)

```
eval_results          156행 (run 11~16, 26문항 × 6회)
  처리 실패             0건  (generated_answer IS NULL)
  중복 제거            46건  (문항 · 답변문자열 · 근거집합)
  fallback 제외        44건  ← 모집단
채점자 점수 분포       (1.0,1.0)=40 · (0.5,1.0)=1 · (0.5,0.5)=2 · (0.0,1.0)=1
참조 청크             run 11~13 은 95개, 14~16 은 100개. 전부 chunks 에 살아 있다
```

**`retrieved_chunks` 의 실제 모양** (🔴 `chunk_id` 가 <문자열>이다):

```json
[{"score": 0.6723, "chunk_id": "270", "filename": "51_생산공장_근무규정.md"}, ...]
```

**관련 스키마**

```
eval_results(id, run_id, question_id, generated_answer, retrieved_chunks jsonb,
             faithfulness numeric(4,3), relevancy numeric(4,3), created_at)
             🔴 reason 컬럼이 없다
eval_questions(id, bot_id, question, ground_truth, source_chunk_id, is_active, created_at)
chunks(id, document_id, bot_id, chunk_index, content, embedding, tokens, meta, created_at)
eval_runs(id, ..., question_count, scored_count, avg_faithfulness, ...)
```

**기존 타입** (`app/schemas.py`)

```python
Id = int

class Source(BaseModel):
    chunk_id: Id
    document_id: Id
    filename: str
    score: float
    preview: str
```

**기존 함수**

```python
# app/db.py
@contextmanager
def cursor(commit: bool = False): ...
def close_pool() -> None: ...

# app/judge.py
def score(question: str, ground_truth: str, sources: list[Source], answer: str) -> Scores | None: ...
class Scores(BaseModel):
    faithfulness: float
    relevancy: float
    reason: str = ""
```

---

### Task 1: `app/eval_cases.py` (복원 배관)

**Files:**
- Create: `ai-service/app/eval_cases.py`
- Create: `ai-service/app/judge_agreement_check.py` (순수 함수 검사. 이 태스크에서 **검사 4개**를 넣는다. Task 2 가 2개, Task 3 이 5개를 덧붙여 최종 11개가 된다)

**Interfaces:**
- Consumes: `app.db.cursor`, `app.schemas.Id`, `app.schemas.Source`
- Produces:
  - `SourceRef(chunk_id: Id, document_id: Id, filename: str, content: str)` (frozen dataclass), 메서드 `to_source() -> Source`
  - `Case(case_id: str, question_id: Id, question: str, ground_truth: str, generated_answer: str, sources: tuple[SourceRef, ...], seen_in_runs: tuple[int, ...], judge_faithfulness: float, judge_relevancy: float)` (frozen dataclass)
  - `chunk_ids_of(retrieved: object) -> list[Id]`
  - `case_key(question_id: int, answer: str, chunk_ids: list[Id]) -> str`
  - `load_cases(run_ids: list[int]) -> list[Case]`
  - `DEFAULT_RUN_IDS: list[int]`

- [ ] **Step 1: 실패하는 검사를 쓴다**

`ai-service/app/judge_agreement_check.py` 를 새로 만든다.

```python
"""채점자 대조 도구의 순수 함수 자체 점검. DB 도 외부 API 도 쓰지 않는다.

왜 이 검사가 있나
─────────────────────────────────────────────────────────────────────────────
이 도구가 내는 결론은 "채점자가 <어느 방향으로> 틀리는가" 다.
🔴 후함과 박함의 부호가 한 번 뒤집히면 결론이 정반대가 된다:
   "전체충실성이 실제보다 높게 나온다" ↔ "낮게 나온다".
숫자는 그럴듯하게 나오고 아무도 눈치채지 못한다. 그래서 부호를 검사로 못박는다.

그리고 근거 <순서>가 채점자 판단을 바꾼다는 것이 2026-09-18 에 실측됐다
(무관한 청크가 4번째에 끼자 3번째 자리의 정답을 못 봤다).
그래서 케이스를 묶는 해시가 순서를 지우면 안 된다. 그것도 검사한다.
"""
from __future__ import annotations

from .eval_cases import case_key, chunk_ids_of


def check_chunk_ids_are_parsed_as_int() -> None:
    """🔴 저장된 chunk_id 는 문자열이다. int 로 안 바꾸면 chunks 조회가 통째로 빈다.

    그러면 사람이 <근거 없이> 라벨을 매기게 되고, 그 라벨은 거짓이 된다.
    """
    raw = [{"score": 0.6, "chunk_id": "270", "filename": "a.md"},
           {"score": 0.5, "chunk_id": "319", "filename": "b.md"}]
    assert chunk_ids_of(raw) == [270, 319]


def check_chunk_ids_keep_order() -> None:
    """순서를 유지한다. 정렬하면 서로 다른 입력이 한 칸으로 뭉개진다."""
    raw = [{"chunk_id": "9"}, {"chunk_id": "2"}, {"chunk_id": "7"}]
    assert chunk_ids_of(raw) == [9, 2, 7]


def check_case_key_distinguishes_source_order() -> None:
    """근거 순서가 다르면 다른 케이스다.

    2026-09-18 실측: 같은 답변 · 같은 청크 집합인데 무관한 청크가 끼는 <자리>가
    달라지자 충실성이 1.0 에서 0.0 으로 갈렸다. 순서를 지우면 그 사실이 사라진다.
    """
    a = case_key(58, "같은 답", [1, 2, 3])
    b = case_key(58, "같은 답", [3, 2, 1])
    assert a != b


def check_case_key_is_stable() -> None:
    """같은 입력은 언제 불러도 같은 값이다. 라벨을 이어받는 근거가 이것이다."""
    assert case_key(58, "답", [1, 2]) == case_key(58, "답", [1, 2])


def main() -> None:
    checks = [
        check_chunk_ids_are_parsed_as_int,
        check_chunk_ids_keep_order,
        check_case_key_distinguishes_source_order,
        check_case_key_is_stable,
    ]
    for fn in checks:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(checks)}가지 전부 통과.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 검사를 돌려 실패를 확인한다**

```bash
cd ai-service && .venv/bin/python -m app.judge_agreement_check
```

Expected: `ModuleNotFoundError: No module named 'app.eval_cases'`

- [ ] **Step 3: `app/eval_cases.py` 를 쓴다**

```python
"""박제된 평가 결과(`eval_results`)를 <채점자 입력>으로 되돌린다.

이 모듈이 왜 따로 있나
─────────────────────────────────────────────────────────────────────────────
평가를 다시 돌리지 않고 <이미 나온 답변과 근거>로 채점자를 다시 검사하려면,
DB 에 박제된 한 행을 `judge.score(question, ground_truth, sources, answer)` 의
인자로 되돌려야 한다. 그 일 하나만 한다.

🔴 이 파일을 따로 뺀 이유는 <다음 슬라이스> 다. 무관한 청크를 한 건씩 주입해가며
   채점자가 언제 눈이 머는지 보는 탐침도 똑같이 "저장된 케이스를 복원해 다시
   넣는" 일을 한다. 2026-09-18 에 같은 일을 하는 스크립트를 스크래치패드에 두었다가
   세션이 끝나며 잃었고, 그래서 핸드오프에 표를 손으로 옮겨 적어야 했다.

외부 API 를 부르지 않는다. DB 만 읽는다.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .db import cursor
from .schemas import Id, Source

# 대조에 쓰는 실행들. 11·12·13 = 306청크 · 14·15·16 = 360청크.
# 전부 status='completed' 이고 처리 실패 0건이다(2026-09-20 확인).
DEFAULT_RUN_IDS: list[int] = [11, 12, 13, 14, 15, 16]


@dataclass(frozen=True)
class SourceRef:
    """근거 청크 하나. preview(앞 200자)가 아니라 <전문>을 들고 있다.

    🔴 preview 를 쓰면 안 되는 이유가 실측돼 있다(2026-08-02). 생성 모델은 전문을
       보고 답했는데 채점자가 preview 만 봐서, 250번째 글자에 있던 "HR-310" 을
       못 보고 <맞는 답에 0점>을 줬다. 사람이 채점자보다 덜 보면 이번에는
       <사람 라벨이> 거짓이 된다.
    """

    chunk_id: Id
    document_id: Id
    filename: str
    content: str

    def to_source(self) -> Source:
        """`judge.score` 가 받는 타입으로 바꾼다.

        `judge.score` 는 `fetch_contents` 로 본문을 다시 읽고, 못 찾으면 preview 로
        떨어진다. preview 자리에 전문을 넣어두면 어느 길로 가도 같은 것을 본다.
        score 는 채점에 쓰이지 않으므로 0.0 으로 둔다.
        """
        return Source(
            chunk_id=self.chunk_id,
            document_id=self.document_id,
            filename=self.filename,
            score=0.0,
            preview=self.content,
        )


@dataclass(frozen=True)
class Case:
    """채점자가 판정한 서로 다른 입력 하나."""

    case_id: str
    question_id: Id
    question: str
    ground_truth: str
    generated_answer: str
    sources: tuple[SourceRef, ...]
    seen_in_runs: tuple[int, ...]
    judge_faithfulness: float
    judge_relevancy: float


def chunk_ids_of(retrieved: object) -> list[Id]:
    """`retrieved_chunks`(jsonb)에서 chunk_id 를 <순서대로> 꺼낸다.

    🔴 저장된 값이 문자열이다: {"chunk_id": "270", ...}.
       int 로 바꾸지 않으면 `chunks` 조회가 통째로 비고, 그러면 사람이 근거 없이
       라벨을 매기게 된다. 조용히 비는 것이 가장 나쁜 실패라 여기서 못박는다.
    """
    if isinstance(retrieved, (str, bytes)):
        retrieved = json.loads(retrieved)
    if not isinstance(retrieved, list):
        return []
    out: list[Id] = []
    for e in retrieved:
        if isinstance(e, dict) and "chunk_id" in e:
            out.append(int(e["chunk_id"]))
    return out


def filenames_of(retrieved: object) -> dict[Id, str]:
    """chunk_id → filename. 파일명은 JSON 에 이미 있어 documents 를 다시 안 join 한다."""
    if isinstance(retrieved, (str, bytes)):
        retrieved = json.loads(retrieved)
    if not isinstance(retrieved, list):
        return {}
    return {
        int(e["chunk_id"]): str(e.get("filename", ""))
        for e in retrieved
        if isinstance(e, dict) and "chunk_id" in e
    }


def case_key(question_id: int, answer: str, chunk_ids: list[Id]) -> str:
    """같은 입력을 하나로 묶는 안정 해시 (12자).

    🔴 <순서를 유지한다.> 근거의 순서가 채점자 판단을 바꾼다는 것이 2026-09-18 에
       실측됐다(무관한 청크가 4번째에 끼자 3번째 자리의 정답을 못 봤다).
       정렬해서 묶으면 서로 다른 입력이 한 칸으로 뭉개진다.
    """
    raw = f"{question_id}\x00{answer}\x00{','.join(str(c) for c in chunk_ids)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


class MissingChunk(RuntimeError):
    """근거 청크가 `chunks` 에 없다. 사람이 근거 없이 라벨을 매기는 것을 막는다."""


def load_cases(run_ids: list[int] | None = None) -> list[Case]:
    """`eval_results` 에서 <채점자가 점수를 매긴> 서로 다른 입력을 복원한다.

    제외하는 것 둘 (이유가 서로 다르다):
      · generated_answer IS NULL  → 처리 실패. 측정 자체가 없다
      · faithfulness   IS NULL    → fallback. 채점자가 불리지 않아 대조할 상대가 없다
    """
    ids = list(run_ids or DEFAULT_RUN_IDS)
    with cursor() as cur:
        cur.execute(
            """SELECT r.run_id, r.question_id, q.question, q.ground_truth,
                      r.generated_answer, r.retrieved_chunks,
                      r.faithfulness, r.relevancy
                 FROM eval_results r
                 JOIN eval_questions q ON q.id = r.question_id
                WHERE r.run_id = ANY(%s)
                  AND r.generated_answer IS NOT NULL
                  AND r.faithfulness IS NOT NULL
                ORDER BY r.run_id, r.question_id""",
            (ids,),
        )
        rows = cur.fetchall()

        wanted: set[Id] = set()
        for row in rows:
            wanted.update(chunk_ids_of(row[5]))
        cur.execute(
            "SELECT id, document_id, content FROM chunks WHERE id = ANY(%s)",
            (sorted(wanted),),
        )
        chunks = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

    missing = sorted(wanted - set(chunks))
    if missing:
        raise MissingChunk(
            f"근거 청크 {len(missing)}개가 chunks 에 없습니다: {missing[:10]}"
            " ... 코퍼스를 다시 적재했거나 eval_set load --replace 를 돌린 것입니다."
            " 이 상태로는 사람이 근거 없이 라벨을 매기게 되므로 중단합니다."
        )

    merged: dict[str, dict] = {}
    for run_id, qid, question, gt, answer, retrieved, faith, rel in rows:
        cids = chunk_ids_of(retrieved)
        names = filenames_of(retrieved)
        key = case_key(int(qid), answer, cids)
        if key not in merged:
            merged[key] = {
                "case": Case(
                    case_id=key,
                    question_id=int(qid),
                    question=question,
                    ground_truth=gt,
                    generated_answer=answer,
                    sources=tuple(
                        SourceRef(
                            chunk_id=c,
                            document_id=chunks[c][0],
                            filename=names.get(c, ""),
                            content=chunks[c][1],
                        )
                        for c in cids
                    ),
                    seen_in_runs=(),
                    judge_faithfulness=float(faith),
                    judge_relevancy=float(rel),
                ),
                "runs": [],
            }
        merged[key]["runs"].append(int(run_id))

    out: list[Case] = []
    for key, v in merged.items():
        c: Case = v["case"]
        out.append(
            Case(
                case_id=c.case_id,
                question_id=c.question_id,
                question=c.question,
                ground_truth=c.ground_truth,
                generated_answer=c.generated_answer,
                sources=c.sources,
                seen_in_runs=tuple(sorted(set(v["runs"]))),
                judge_faithfulness=c.judge_faithfulness,
                judge_relevancy=c.judge_relevancy,
            )
        )
    return out
```

- [ ] **Step 4: 검사를 돌려 통과를 확인한다**

```bash
cd ai-service && .venv/bin/python -m app.judge_agreement_check
```

Expected: `✅` 4줄 + `4가지 전부 통과.`

- [ ] **Step 5: 진짜 DB 로 44건이 나오는지 확인한다**

```bash
cd ai-service && .venv/bin/python -c "
from app.eval_cases import load_cases
from app.db import close_pool
cs = load_cases()
print('케이스', len(cs))
print('근거 전문 최대 길이', max(len(s.content) for c in cs for s in c.sources))
print('충실성 분포', sorted({c.judge_faithfulness for c in cs}))
close_pool()"
```

Expected:
```
케이스 44
근거 전문 최대 길이 (200보다 큰 값. preview 가 아니라 전문이라는 증거)
충실성 분포 [0.0, 0.5, 1.0]
```

🔴 44 가 아니면 멈추고 원인을 찾을 것. 이 숫자가 계획 전체의 전제다.

- [ ] **Step 6: 커밋**

```bash
cd /Users/cheonjamin/projects/AllDap
git add ai-service/app/eval_cases.py ai-service/app/judge_agreement_check.py
git commit -m "$(cat <<'EOF'
feat: 박제된 평가 결과를 채점자 입력으로 되돌리는 배관을 만든다

eval_results 한 행을 judge.score 의 인자로 복원한다. 중복을 제거하면 채점자가
판정한 서로 다른 입력이 44건이고 그것이 모집단이다.

- retrieved_chunks 의 chunk_id 는 <문자열>이라 int 로 바꾼다. 안 바꾸면 chunks
  조회가 통째로 비고 사람이 근거 없이 라벨을 매기게 된다.
- 근거는 preview 가 아니라 전문을 싣는다(2026-08-02 의 200자 버그와 같은 자리).
- 케이스 해시가 근거 <순서>를 유지한다. 순서가 채점자 판단을 바꾸는 것이
  2026-09-18 에 실측됐다.
- 청크가 하나라도 없으면 MissingChunk 로 중단한다. 조용히 비는 것이 가장 나쁘다.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `dump` (블라인드 라벨 파일)

**Files:**
- Create: `ai-service/app/judge_agreement.py`
- Test: `ai-service/app/judge_agreement_check.py` (검사 2개 추가)

**Interfaces:**
- Consumes: `app.eval_cases.load_cases`, `app.eval_cases.Case`, `app.eval_cases.DEFAULT_RUN_IDS`
- Produces:
  - `LABELS: tuple[float, float, float]` = `(0.0, 0.5, 1.0)`
  - `DEFAULT_PATH: str` = `"testdata/judge_labels.json"`
  - `build_payload(cases: list[Case], carried: dict[str, dict]) -> dict`
  - `read_labels(path: str) -> dict[str, dict]` (파일이 없으면 `{}`)
  - `dump(run_ids: list[int], path: str) -> None`

- [ ] **Step 1: 실패하는 검사를 쓴다**

`ai-service/app/judge_agreement_check.py` 의 import 줄 아래에 추가한다.

```python
from .eval_cases import Case, SourceRef
from .judge_agreement import build_payload
```

그리고 `main()` 위에 검사 두 개를 넣는다.

```python
def _fake_case(case_id: str, faith: float) -> Case:
    return Case(
        case_id=case_id,
        question_id=58,
        question="질문",
        ground_truth="정답",
        generated_answer="답변",
        sources=(SourceRef(chunk_id=1, document_id=2, filename="a.md", content="본문"),),
        seen_in_runs=(11, 12),
        judge_faithfulness=faith,
        judge_relevancy=1.0,
    )


def check_dump_hides_judge_scores() -> None:
    """🔴 이 도구의 존재 이유다. 채점자 점수를 보고 매기면 앵커링되어 대조가 성립하지 않는다.

    `answerable_check` 가 홀드아웃을 기본 모드에서 <읽지도 않게> 만들어둔 것과 같은 규칙이다.
    """
    payload = build_payload([_fake_case("aaa", 0.0)], carried={})
    blob = __import__("json").dumps(payload, ensure_ascii=False)
    assert "faithfulness" not in blob
    assert "judge" not in blob
    assert payload["cases"][0]["label"] is None


def check_dump_carries_existing_labels() -> None:
    """다시 dump 해도 사람이 채운 칸을 잃지 않는다. 1.5~2시간짜리 일이라 이어 할 수 있어야 한다."""
    carried = {"aaa": {"label": 0.5, "note": "절반만 근거에 있다"}}
    payload = build_payload([_fake_case("aaa", 1.0)], carried=carried)
    assert payload["cases"][0]["label"] == 0.5
    assert payload["cases"][0]["note"] == "절반만 근거에 있다"
```

`main()` 의 `checks` 목록에 두 함수를 더한다.

- [ ] **Step 2: 검사를 돌려 실패를 확인한다**

```bash
cd ai-service && .venv/bin/python -m app.judge_agreement_check
```

Expected: `ModuleNotFoundError: No module named 'app.judge_agreement'`

- [ ] **Step 3: `app/judge_agreement.py` 를 쓴다**

```python
"""채점자(LLM-as-judge)를 사람 라벨과 대조한다.

실행:
    cd ai-service
    .venv/bin/python -m app.judge_agreement dump     # 블라인드 라벨 파일 내보내기
    #  → testdata/judge_labels.json 의 label 칸을 사람이 0 / 0.5 / 1 로 채운다
    .venv/bin/python -m app.judge_agreement report   # 혼동행렬·방향·왜곡량
    .venv/bin/python -m app.judge_agreement report --reasons  # 불일치분만 채점자 재호출

무엇을 재는가 (두 축을 섞지 말 것)
─────────────────────────────────────────────────────────────────────────────
  정밀도  같은 입력에 같은 점수를 주는가  → 2026-09-18 에 확인됨(두 입력 15회씩, 분산 0)
  정확도  사람이 보기에 맞게 채점하는가  → <이 도구가 재는 것>

🔴 q3 에서 채점자는 <정밀하게 틀렸다>. 10회 내내 일관되게 0.0 을 줬고 그 사유가
   거짓이었다(정답 청크는 근거 3번째에 있었다). 흔들리면 반복 측정으로 걸러지는데
   일관되게 틀리면 안 걸러진다. 그래서 이쪽이 더 나쁘다.

🔴 진짜 위험은 채점자가 1.0 을 준 40건이다
─────────────────────────────────────────────────────────────────────────────
박하게 틀린 것(맞는 답에 0.0)은 눈에 띈다. 숫자가 내려가니 파보게 된다.
<후하게> 틀린 것은 화면에 "잘 되고 있다" 로만 뜨고 DB 어디를 뒤져도 나오지 않는다.
그것을 찾는 유일한 방법이 사람이 그 40건을 직접 읽는 것이고, 그것이 이 도구다.

왜 카파 하나로 결론을 말하지 않나
─────────────────────────────────────────────────────────────────────────────
44건 중 40건이 1.0 이다. 한쪽 값이 91% 를 차지하면 우연 일치 확률이 이미 0.83 쯤이라
카파의 분모가 거의 0 이 된다. 일치율 95% 인데 카파 0.3 이 나온다(카파 역설).
그래서 혼동행렬과 <방향>을 주고, 카파는 주석과 함께 부수적으로만 찍는다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .eval_cases import DEFAULT_RUN_IDS, Case, load_cases

LABELS: tuple[float, float, float] = (0.0, 0.5, 1.0)
DEFAULT_PATH = "testdata/judge_labels.json"

_README = (
    "label 칸에 0 / 0.5 / 1 만 적는다. note 는 선택이다. "
    "채점자 점수는 <일부러> 들어 있지 않다. 보고 매기면 앵커링되어 대조가 성립하지 않는다. "
    "기준: 충실성 = 답변의 모든 주장이 아래 근거에 실제로 적혀 있는가. "
    "1.0 전부 있다 / 0.5 일부만 있다 / 0.0 근거에 없는 내용을 지어냈다. "
    "답이 세상의 상식에 맞는지는 보지 않는다. 사실이더라도 근거에 없으면 깎는다."
)


def read_labels(path: str) -> dict[str, dict]:
    """이미 채워둔 라벨을 읽는다. 파일이 없으면 빈 dict."""
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {c["case_id"]: c for c in data.get("cases", [])}


def build_payload(cases: list[Case], carried: dict[str, dict]) -> dict:
    """라벨 파일 내용을 만든다. 🔴 채점자 점수를 넣지 않는다.

    순서는 case_id(해시)로 정렬한다. 문항 번호나 run 순서가 단서로 남지 않게 하려는 것이다.
    """
    out = []
    for c in sorted(cases, key=lambda x: x.case_id):
        prev = carried.get(c.case_id, {})
        out.append({
            "case_id": c.case_id,
            "question_id": c.question_id,
            "question": c.question,
            "ground_truth": c.ground_truth,
            "generated_answer": c.generated_answer,
            "sources": [
                {"chunk_id": s.chunk_id, "filename": s.filename, "content": s.content}
                for s in c.sources
            ],
            "seen_in_runs": list(c.seen_in_runs),
            "label": prev.get("label"),
            "note": prev.get("note", ""),
        })
    return {"_readme": _README, "run_ids": list(DEFAULT_RUN_IDS), "cases": out}


def dump(run_ids: list[int], path: str) -> None:
    cases = load_cases(run_ids)
    carried = read_labels(path)
    payload = build_payload(cases, carried)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    done = sum(1 for c in payload["cases"] if c["label"] is not None)
    print(f"{path} 에 {len(payload['cases'])}건을 썼습니다. (이미 채운 라벨 {done}건을 이어받았습니다)")
    print("label 칸에 0 / 0.5 / 1 을 채운 뒤 `report` 를 돌리세요.")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="채점자를 사람 라벨과 대조한다")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dump", help="블라인드 라벨 파일을 내보낸다")
    d.add_argument("--path", default=DEFAULT_PATH)
    args = p.parse_args(argv)
    if args.cmd == "dump":
        dump(DEFAULT_RUN_IDS, args.path)
    return 0


if __name__ == "__main__":
    from .db import close_pool
    try:
        sys.exit(main())
    finally:
        close_pool()
```

- [ ] **Step 4: 검사를 돌려 통과를 확인한다**

```bash
cd ai-service && .venv/bin/python -m app.judge_agreement_check
```

Expected: `✅` 6줄 + `6가지 전부 통과.`

- [ ] **Step 5: 진짜로 파일을 만들고 블라인드인지 눈으로 확인한다**

```bash
cd ai-service && .venv/bin/python -m app.judge_agreement dump
grep -c '"label": null' testdata/judge_labels.json
grep -c 'faithfulness' testdata/judge_labels.json || echo "채점자 점수 없음 ✅"
.venv/bin/python -c "
import json; d=json.load(open('testdata/judge_labels.json'))
print('케이스', len(d['cases']))
print('근거 최대 길이', max(len(s['content']) for c in d['cases'] for s in c['sources']))"
```

Expected:
```
44
채점자 점수 없음 ✅
케이스 44
근거 최대 길이 (200보다 큰 값)
```

- [ ] **Step 6: 커밋**

```bash
cd /Users/cheonjamin/projects/AllDap
git add ai-service/app/judge_agreement.py ai-service/app/judge_agreement_check.py ai-service/testdata/judge_labels.json
git commit -m "$(cat <<'EOF'
feat: 채점자 점수를 뺀 블라인드 라벨 파일을 내보낸다

dump 가 44건을 testdata/judge_labels.json 으로 내보낸다. 채점자 점수를 <일부러>
넣지 않는다. 보고 나서 매기면 앵커링되어 대조가 성립하지 않는다. answerable_check
가 홀드아웃을 기본 모드에서 읽지도 않게 해둔 것과 같은 규칙이다.

- 순서를 case_id 해시로 정렬해 문항 번호·run 순서를 단서로 남기지 않는다.
- 근거는 전문을 싣는다. 사람이 채점자보다 덜 보면 사람 라벨이 거짓이 된다.
- 다시 dump 해도 이미 채운 라벨을 case_id 로 이어받는다.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: 집계 순수 함수 (혼동행렬 · 방향 · 왜곡량 · 카파)

**Files:**
- Modify: `ai-service/app/judge_agreement.py` (함수 추가)
- Test: `ai-service/app/judge_agreement_check.py` (검사 5개 추가)

**Interfaces:**
- Produces:
  - `confusion(pairs: list[tuple[float, float]]) -> dict[tuple[float, float], int]` (키는 `(사람, 채점자)`)
  - `direction_counts(pairs: list[tuple[float, float]]) -> tuple[int, int, int]` → `(후함, 박함, 일치)`
  - `overall_faithfulness(scores: list[float], question_count: int) -> float`
  - `linear_weighted_kappa(pairs: list[tuple[float, float]]) -> float`

- [ ] **Step 1: 실패하는 검사를 쓴다**

`ai-service/app/judge_agreement_check.py` 의 import 에 추가한다.

```python
from .judge_agreement import (
    build_payload, confusion, direction_counts, linear_weighted_kappa, overall_faithfulness,
)
```

`main()` 위에 검사 다섯 개를 넣는다.

```python
def check_direction_generous_means_judge_is_higher() -> None:
    """🔴 부호가 뒤집히면 결론이 정반대가 된다. 이 검사가 이 파일의 존재 이유다.

    (사람, 채점자) = (0.0, 1.0) 은 <채점자가 후하다>. 사람이 0점을 줄 답에 1점을 줬다.
    그러면 전체충실성이 실제보다 <높게> 나온다.
    """
    generous, harsh, same = direction_counts([(0.0, 1.0)])
    assert (generous, harsh, same) == (1, 0, 0)


def check_direction_harsh_means_judge_is_lower() -> None:
    """(사람, 채점자) = (1.0, 0.0) 은 <채점자가 박하다>. q3 가 이 모양이었다.

    그러면 전체충실성이 실제보다 <낮게> 나온다.
    """
    generous, harsh, same = direction_counts([(1.0, 0.0)])
    assert (generous, harsh, same) == (0, 1, 0)


def check_confusion_counts_by_human_then_judge() -> None:
    """혼동행렬의 키는 (사람, 채점자) 순서다. 뒤집으면 표를 거꾸로 읽게 된다."""
    m = confusion([(1.0, 1.0), (1.0, 1.0), (1.0, 0.5), (0.5, 1.0)])
    assert m[(1.0, 1.0)] == 2
    assert m[(1.0, 0.5)] == 1
    assert m[(0.5, 1.0)] == 1
    assert m[(0.0, 0.0)] == 0


def check_overall_faithfulness_matches_the_repo_formula() -> None:
    """전체충실성 = avg × scored / total. 정리하면 sum / total 이다.

    이 저장소가 쓰는 식 그대로여야 채점자 기준 수치와 나란히 놓을 수 있다.
    fallback 이 많아 scored 가 작아지는 것은 정상이고, 오염 지표는 따로 있다
    (generated_answer IS NULL = 처리 실패).
    """
    # 26문항 중 24건만 채점됐고 그 평균이 1.0 이면 24/26
    assert abs(overall_faithfulness([1.0] * 24, 26) - 24 / 26) < 1e-9
    # 채점된 것이 하나도 없으면 0.0 이다(0으로 나누지 않는다)
    assert overall_faithfulness([], 26) == 0.0


def check_kappa_is_one_on_perfect_agreement() -> None:
    """완전 일치면 1.0. 다만 이 값은 참고용이다(분포 치우침 주석이 출력에 붙는다)."""
    pairs = [(1.0, 1.0)] * 8 + [(0.5, 0.5)] * 2
    assert abs(linear_weighted_kappa(pairs) - 1.0) < 1e-9
```

`main()` 의 `checks` 목록에 다섯 함수를 더한다.

- [ ] **Step 2: 검사를 돌려 실패를 확인한다**

```bash
cd ai-service && .venv/bin/python -m app.judge_agreement_check
```

Expected: `ImportError: cannot import name 'confusion' from 'app.judge_agreement'`

- [ ] **Step 3: 함수를 구현한다**

`app/judge_agreement.py` 의 `read_labels` 위에 넣는다.

```python
def confusion(pairs: list[tuple[float, float]]) -> dict[tuple[float, float], int]:
    """3×3 혼동행렬. 🔴 키는 (사람, 채점자) 순서다.

    숫자 하나로 요약하지 않고 표를 통째로 싣는 이유: 44건 중 40건이 한 칸에 몰려
    있어서, 요약 지표는 나머지 4건에 통째로 끌려다닌다. 표는 그 사실을 감추지 않는다.
    """
    m = {(h, j): 0 for h in LABELS for j in LABELS}
    for h, j in pairs:
        m[(h, j)] += 1
    return m


def direction_counts(pairs: list[tuple[float, float]]) -> tuple[int, int, int]:
    """(후함, 박함, 일치). 🔴 후함 = 채점자가 사람보다 <높게> 준 것이다.

    후하면 전체충실성이 실제보다 높게 나오고, 박하면 낮게 나온다.
    둘은 반대 방향의 결론이라 절대 한 값으로 뭉개면 안 된다.
    """
    generous = sum(1 for h, j in pairs if j > h)
    harsh = sum(1 for h, j in pairs if j < h)
    return generous, harsh, len(pairs) - generous - harsh


def overall_faithfulness(scores: list[float], question_count: int) -> float:
    """전체충실성 = avg_faithfulness × scored_count / question_count.

    정리하면 sum(scores) / question_count 다. 이 저장소가 Spring 에서 쓰는 식과
    같아야 채점자 기준 수치와 나란히 놓을 수 있다.
    """
    if question_count <= 0:
        return 0.0
    return sum(scores) / question_count


def linear_weighted_kappa(pairs: list[tuple[float, float]]) -> float:
    """선형 가중 카파. ⚠️ 이 데이터에서는 참고용이다.

    44건 중 40건이 1.0 이라 우연 일치 확률이 이미 0.83 쯤이고, 분모(1 - Pe)가
    거의 0 이 된다. 일치율이 높아도 카파가 낮게 나오는 <카파 역설>이다.
    출력에서 이 값 옆에 반드시 그 주석을 함께 찍는다.
    """
    n = len(pairs)
    if n == 0:
        return 0.0
    idx = {v: i for i, v in enumerate(LABELS)}
    k = len(LABELS)

    def w(a: int, b: int) -> float:
        return 1.0 - abs(a - b) / (k - 1)

    obs = sum(w(idx[h], idx[j]) for h, j in pairs) / n
    hc = [sum(1 for h, _ in pairs if h == v) / n for v in LABELS]
    jc = [sum(1 for _, j in pairs if j == v) / n for v in LABELS]
    exp = sum(w(a, b) * hc[a] * jc[b] for a in range(k) for b in range(k))
    if abs(1.0 - exp) < 1e-12:
        return 0.0
    return (obs - exp) / (1.0 - exp)
```

- [ ] **Step 4: 검사를 돌려 통과를 확인한다**

```bash
cd ai-service && .venv/bin/python -m app.judge_agreement_check
```

Expected: `✅` 11줄 + `11가지 전부 통과.`

- [ ] **Step 5: 커밋**

```bash
cd /Users/cheonjamin/projects/AllDap
git add ai-service/app/judge_agreement.py ai-service/app/judge_agreement_check.py
git commit -m "$(cat <<'EOF'
test: 혼동행렬·방향·전체충실성 왜곡량 계산을 검사로 못박는다

🔴 후함과 박함의 부호가 한 번 뒤집히면 결론이 정반대가 된다("실제보다 높게 나온다"
↔ "낮게 나온다"). 숫자는 그럴듯하게 나오고 아무도 눈치채지 못한다. 그래서 부호를
검사로 고정했다.

전체충실성은 이 저장소가 쓰는 식(avg × scored / total)을 그대로 쓴다. 채점자 기준
수치와 나란히 놓으려면 같은 식이어야 한다.

카파는 구현하되 참고용이다. 44건 중 40건이 1.0 이라 카파 역설에 걸린다.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: `report` 배선 (파일 + DB 조인, 실패 조건)

**Files:**
- Modify: `ai-service/app/judge_agreement.py`

**Interfaces:**
- Consumes: Task 1 의 `load_cases`, Task 3 의 네 함수
- Produces: `report(run_ids: list[int], path: str, with_reasons: bool) -> int` (종료코드)

- [ ] **Step 1: `report` 를 구현한다**

`app/judge_agreement.py` 의 `dump` 아래에 넣는다.

```python
class LabelFileProblem(RuntimeError):
    """라벨 파일이 없거나 덜 채워졌다. 부분 집계를 내지 않는다."""


def _load_pairs(path: str, cases: list[Case]) -> list[tuple[str, float, float]]:
    """(case_id, 사람 라벨, 채점자 점수) 목록. 하나라도 비면 실패한다.

    🔴 부분 집계를 내지 않는 이유: 한 번 찍힌 숫자는 결과로 인용된다.
       "44건 중 30건만 매긴 상태의 중간값" 이라는 꼬리표는 인용될 때 떨어져 나간다.
    """
    if not os.path.exists(path):
        raise LabelFileProblem(
            f"{path} 가 없습니다. 먼저 `python -m app.judge_agreement dump` 를 돌리고"
            " label 칸을 0 / 0.5 / 1 로 채우세요."
        )
    labels = read_labels(path)
    by_id = {c.case_id: c for c in cases}

    unknown = sorted(set(labels) - set(by_id))
    if unknown:
        raise LabelFileProblem(
            f"라벨 파일에 DB 에 없는 케이스 {len(unknown)}건이 있습니다: {unknown[:5]}"
            " ... 코퍼스나 평가셋이 바뀐 것입니다. `dump` 를 다시 돌리세요."
        )

    blank, bad, pairs = [], [], []
    for cid, c in by_id.items():
        rec = labels.get(cid)
        if rec is None or rec.get("label") is None:
            blank.append(cid)
            continue
        v = float(rec["label"])
        if v not in LABELS:
            bad.append((cid, rec["label"]))
            continue
        pairs.append((cid, v, c.judge_faithfulness))

    if bad:
        raise LabelFileProblem(
            f"라벨 값이 0 / 0.5 / 1 이 아닌 것이 {len(bad)}건 있습니다: {bad[:5]}"
        )
    if blank:
        raise LabelFileProblem(
            f"아직 매기지 않은 케이스가 {len(blank)}건 남았습니다"
            f" (전체 {len(by_id)}건). 남은 case_id 예: {blank[:5]}"
            " ... 전부 채운 뒤 다시 돌리세요. 부분 집계는 내지 않습니다."
        )
    return pairs


def _print_confusion(pairs: list[tuple[float, float]]) -> None:
    m = confusion(pairs)
    print("\n[1] 혼동행렬  (행 = 사람, 열 = 채점자)")
    print("            " + "".join(f"{j:>7.1f}" for j in LABELS))
    for h in LABELS:
        print(f"  사람 {h:>3.1f}   " + "".join(f"{m[(h, j)]:>7d}" for j in LABELS))


def _print_direction(pairs: list[tuple[float, float]]) -> None:
    generous, harsh, same = direction_counts(pairs)
    n = len(pairs)
    print(f"\n[2] 방향  (전체 {n}건)")
    print(f"  일치            {same:>3d}건  ({same / n:.1%})")
    print(f"  채점자가 후하다  {generous:>3d}건  → 전체충실성이 실제보다 <높게> 나온다")
    print(f"  채점자가 박하다  {harsh:>3d}건  → 전체충실성이 실제보다 <낮게> 나온다")
    kappa = linear_weighted_kappa(pairs)
    print(f"\n  선형가중 카파 {kappa:.3f}")
    print("  ⚠️ 이 값만 인용하지 말 것. 한쪽 값에 몰린 분포에서는 우연 일치 확률이")
    print("     높아 분모가 거의 0 이 되고, 일치율이 높아도 카파가 낮게 나온다(카파 역설).")


def _print_distortion(run_ids: list[int], label_of: dict[str, float]) -> None:
    """run 별로 <채점자 기준> 과 <사람 기준> 전체충실성을 나란히 놓는다."""
    from .eval_cases import case_key, chunk_ids_of

    print("\n[3] 전체충실성 왜곡량  (= avg × scored / total)")
    print("  run   문항  채점  채점자기준   사람기준      차이")
    with cursor() as cur:
        for rid in run_ids:
            cur.execute(
                """SELECT question_id, generated_answer, retrieved_chunks, faithfulness
                     FROM eval_results
                    WHERE run_id = %s AND generated_answer IS NOT NULL""",
                (rid,),
            )
            rows = cur.fetchall()
            total = len(rows)
            j_scores, h_scores = [], []
            for qid, answer, retrieved, faith in rows:
                if faith is None:
                    continue  # fallback. 양쪽 모두 분자에서 빠진다
                cid = case_key(int(qid), answer, chunk_ids_of(retrieved))
                j_scores.append(float(faith))
                h_scores.append(label_of[cid])
            j = overall_faithfulness(j_scores, total)
            h = overall_faithfulness(h_scores, total)
            print(f"  {rid:>3d}   {total:>4d}  {len(j_scores):>4d}"
                  f"    {j:>8.4f}   {h:>8.4f}   {h - j:>+8.4f}")
    print("\n  ⚠️ 실측 편차 폭은 0.032 다. 차이가 그보다 크면 이 저장소의 before/after")
    print("     비교표가 <채점자 오차 안에서> 움직였다는 뜻이 된다.")


def report(run_ids: list[int], path: str, with_reasons: bool) -> int:
    cases = load_cases(run_ids)
    triples = _load_pairs(path, cases)
    pairs = [(h, j) for _, h, j in triples]
    label_of = {cid: h for cid, h, _ in triples}
    by_id = {c.case_id: c for c in cases}

    print(f"사람 라벨 {len(pairs)}건 · 채점자 {len(pairs)}건  (run {run_ids})")
    _print_confusion(pairs)
    _print_direction(pairs)
    _print_distortion(run_ids, label_of)

    mismatched = [(cid, h, j) for cid, h, j in triples if h != j]
    print(f"\n[4] 불일치 상세  {len(mismatched)}건")
    if not mismatched:
        print("  없음.")
    for cid, h, j in sorted(mismatched, key=lambda t: abs(t[2] - t[1]), reverse=True):
        c = by_id[cid]
        arrow = "후함" if j > h else "박함"
        print(f"\n  · {cid}  q{c.question_id}  사람 {h} / 채점자 {j}  ({arrow})")
        print(f"    질문: {c.question}")
        print(f"    기대: {c.ground_truth}")
        print(f"    답변: {c.generated_answer[:200]}")
        print(f"    근거: {[s.chunk_id for s in c.sources]}")
    return 0
```

파일 상단 import 에 `from .db import cursor` 를 더한다.

`main()` 의 서브커맨드에 `report` 를 더한다.

```python
    r = sub.add_parser("report", help="사람 라벨과 채점자를 대조한다")
    r.add_argument("--path", default=DEFAULT_PATH)
    r.add_argument("--reasons", action="store_true",
                   help="불일치 케이스만 채점자를 다시 불러 사유를 받는다 (외부 API 를 부른다)")
```

그리고 분기를 더한다.

```python
    if args.cmd == "report":
        try:
            return report(DEFAULT_RUN_IDS, args.path, args.reasons)
        except LabelFileProblem as e:
            print(f"❌ {e}", file=sys.stderr)
            return 1
```

- [ ] **Step 2: 라벨이 비어 있을 때 실패하는지 확인한다**

```bash
cd ai-service && .venv/bin/python -m app.judge_agreement report; echo "종료코드 $?"
```

Expected: `❌ 아직 매기지 않은 케이스가 44건 남았습니다 ...` 와 `종료코드 1`

- [ ] **Step 3: 라벨을 가짜로 다 채워 집계가 도는지 확인한다 (임시 파일로)**

```bash
cd ai-service && .venv/bin/python -c "
import json, shutil
shutil.copy('testdata/judge_labels.json', '/tmp/jl.json')
d = json.load(open('/tmp/jl.json'))
for c in d['cases']:
    c['label'] = 1.0
json.dump(d, open('/tmp/jl.json','w'), ensure_ascii=False)
print('임시로 전부 1.0 을 채웠습니다')"
.venv/bin/python -m app.judge_agreement report --path /tmp/jl.json
```

Expected: 네 덩어리가 전부 찍힌다. 전부 1.0 으로 채웠으므로 **박함 4건**(채점자가 0.0·0.5 를 준 것들)이 나오고 후함은 0건이다. `[3]` 의 차이가 전부 양수(`+`)다.

🔴 부호가 반대로 나오면 멈출 것. `direction_counts` 나 `_print_distortion` 이 뒤집힌 것이다.

```bash
rm /tmp/jl.json
```

- [ ] **Step 4: 커밋**

```bash
cd /Users/cheonjamin/projects/AllDap
git add ai-service/app/judge_agreement.py
git commit -m "$(cat <<'EOF'
feat: report 가 혼동행렬·방향·전체충실성 왜곡량을 낸다

라벨 파일과 DB 의 채점자 점수를 합쳐 네 덩어리를 찍는다.

실패로 다루는 것 넷: 파일이 없다 / 덜 채웠다 / 값이 0·0.5·1 이 아니다 /
DB 에 없는 케이스가 파일에 있다. 🔴 부분 집계를 내지 않는 이유는 한 번 찍힌
숫자가 결과로 인용되기 때문이다. "30건만 매긴 중간값" 이라는 꼬리표는 인용될 때
떨어져 나간다.

[3] 이 결론이다. run 별로 같은 식(avg × scored / total)을 채점자 점수와 사람
라벨로 각각 계산해 나란히 놓는다. 실측 편차 0.032 와 견줘 읽을 수 있다.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: `--reasons` (불일치분만 채점자 재호출)

**Files:**
- Modify: `ai-service/app/judge_agreement.py`

**Interfaces:**
- Consumes: `app.judge.score`, `app.eval_cases.SourceRef.to_source`
- Produces: `fetch_reasons(cases: list[Case], mismatched_ids: list[str]) -> dict[str, tuple[float, str]]`

**왜 필요한가:** `eval_results` 에 `reason` 컬럼이 없다. `judge.score()` 가 사유를 파싱해 `Scores` 에 담는데 `evalrun.py` 의 INSERT 가 그것을 버린다. 사유 없이는 "틀렸다" 와 "거짓 사유를 댔다" 를 가를 수 없다(q3 가 그 예다).

- [ ] **Step 1: 구현한다**

`app/judge_agreement.py` 에 더한다.

```python
def fetch_reasons(cases: list[Case], mismatched_ids: list[str]) -> dict[str, tuple[float, str]]:
    """불일치 케이스만 채점자를 다시 불러 (점수, 사유)를 받는다.

    🔴 왜 다시 부르나: `eval_results` 에 reason 컬럼이 없다. judge.score 가 사유를
       파싱해 Scores 에 담는데 evalrun 의 INSERT 가 그것을 버린다. 사유가 없으면
       <틀린 것>과 <거짓 사유를 댄 것>을 가를 수 없다. q3 가 정확히 그 경우였다.

    🔴 덤으로 결정성 점검이 된다. 2026-09-18 에 확인한 것은 두 입력에서 15회씩
       안 흔들렸다는 것까지다. 재호출 점수가 DB 값과 다르면 <그 자체가 발견>이라
       조용히 넘기지 않고 찍는다.

    비용: 불일치분만이라 보통 수 건이고 회당 약 25 뉴런이다.
    """
    from .judge import score as judge_score

    by_id = {c.case_id: c for c in cases}
    out: dict[str, tuple[float, str]] = {}
    for cid in mismatched_ids:
        c = by_id[cid]
        s = judge_score(
            question=c.question,
            ground_truth=c.ground_truth,
            sources=[src.to_source() for src in c.sources],
            answer=c.generated_answer,
        )
        if s is None:
            out[cid] = (float("nan"), "(채점 호출 실패)")
            continue
        out[cid] = (s.faithfulness, s.reason)
    return out
```

`report` 의 `[4]` 출력 직전에 더한다.

```python
    reasons: dict[str, tuple[float, str]] = {}
    if with_reasons and mismatched:
        print(f"\n  채점자를 {len(mismatched)}건 다시 부릅니다 (약 {len(mismatched) * 25} 뉴런)...")
        reasons = fetch_reasons(cases, [cid for cid, _, _ in mismatched])
```

그리고 불일치 상세 루프 끝에 더한다.

```python
        if cid in reasons:
            again, why = reasons[cid]
            print(f"    사유: {why}")
            if again != j:
                print(f"    🔴 재호출 점수가 DB 값과 다릅니다: DB {j} vs 재호출 {again}")
                print("       채점자가 결정적이라는 전제가 이 입력에서는 성립하지 않습니다.")
```

- [ ] **Step 2: 기본 경로가 외부 API 를 안 부르는지 확인한다**

```bash
cd ai-service && grep -n "from .judge import" app/judge_agreement.py
```

Expected: `fetch_reasons` **안쪽**에서만 import 한다(늦은 import). 모듈 최상단에 있으면 안 된다. `local_reranker_check` 가 무거운 의존성을 늦게 import 하는 것과 같은 규칙이다.

- [ ] **Step 3: 커밋**

```bash
cd /Users/cheonjamin/projects/AllDap
git add ai-service/app/judge_agreement.py
git commit -m "$(cat <<'EOF'
feat: --reasons 가 불일치 케이스만 채점자를 다시 불러 사유를 받는다

eval_results 에 reason 컬럼이 없다. judge.score 가 사유를 파싱해 Scores 에 담는데
evalrun 의 INSERT 가 그것을 버린다. 사유가 없으면 <틀린 것>과 <거짓 사유를 댄 것>을
가를 수 없고, q3 가 정확히 그 경우였다(정답 청크가 근거 3번째에 있는데 "없다"고 했다).

불일치분만 부르므로 보통 수 건이고 회당 약 25 뉴런이다. 기본 report 는 여전히 외부
API 를 부르지 않는다(judge import 가 함수 안쪽에 있다).

덤으로 결정성 점검이 된다. 재호출 점수가 DB 값과 다르면 그 자체가 발견이라 찍는다.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: CI 와 문서

**Files:**
- Modify: `.github/workflows/ci.yml` (자체 점검 목록 · 수동 목록 주석)
- Modify: `docs/BACKLOG.md` (`reason` 미저장)

- [ ] **Step 1: CI 의 자체 점검 목록에 더한다**

`.github/workflows/ci.yml` 의 `자체 점검 (DB·외부 API 없이 도는 것만)` 단계 마지막 줄 뒤에 더한다.

```yaml
          python -m app.judge_agreement_check
```

- [ ] **Step 2: 수동 목록 주석을 고친다**

같은 파일에서 아래 블록을 찾는다.

```
      #         · app.local_reranker_e2e_check  진짜 모델 1.1GB + requirements-lab.txt
      #       이 여섯은 사람이 손으로 돌린다(AGENTS.md 의 해당 절에 실행 방법이 있다).
```

이렇게 바꾼다.

```
      #         · app.local_reranker_e2e_check  진짜 모델 1.1GB + requirements-lab.txt
      #         · app.judge_agreement           DB(cursor). 🔴 <외부 API 는 안 부른다>
      #       이 일곱은 사람이 손으로 돌린다(AGENTS.md 의 해당 절에 실행 방법이 있다).
```

그리고 바로 아래 Postgres 문단을 고친다. 지금 이렇게 적혀 있다.

```
      #    ⚠️ Postgres 서비스 컨테이너는 <일부러> 띄우지 않았다.
      #       DB 가 필요한 점검 4개가 하나같이 외부 API 도 함께 부르기 때문에,
      #       DB 를 띄워줘도 그 넷 중 어느 것도 CI 에서 돌 수 없다.
      #       즉 컨테이너를 띄우는 대가만 치르고 태울 수 있는 점검은 0개다.
```

이렇게 바꾼다.

```
      #    ⚠️ Postgres 서비스 컨테이너는 <일부러> 띄우지 않았다.
      #       DB 가 필요한 점검 4개는 하나같이 외부 API 도 함께 부르므로
      #       DB 를 띄워줘도 그 넷은 CI 에서 돌 수 없다.
      #       🔴 app.judge_agreement 은 그 문장의 예외다 (2026-09-20).
      #          DB 만 쓰고 외부 API 를 부르지 않는다 (채점자 점수가 eval_results 에
      #          이미 박제돼 있어 다시 부를 일이 없다).
      #          그래도 CI 에서 못 도는 이유는 API 가 아니라 <그 DB 안의 측정 결과가
      #          CI 에 없기> 때문이다. 빈 스키마를 띄워봐야 대조할 run 이 0개다.
      #       즉 컨테이너를 띄우는 대가만 치르고 태울 수 있는 점검은 여전히 0개다.
```

- [ ] **Step 3: `docs/BACKLOG.md` 에 남긴다**

`## 6. 문서 · 정리` 의 표 마지막 줄 뒤에 더한다(`### 6-1` 바로 앞).

```markdown
| 채점자 사유(`reason`)가 저장되지 않는다 | `judge.score` 가 파싱해 `Scores.reason` 에 담는데 `evalrun.py` 의 INSERT 가 버린다(`eval_results` 에 컬럼이 없다). 저장소 어디에서도 쓰이지 않는다. 있으면 "틀린 것" 과 "거짓 사유를 댄 것" 을 사후에 가를 수 있다. 🔴 추가하려면 Flyway `V10` 이 필요해 별개 PR 이다. 지금은 `judge_agreement report --reasons` 가 불일치분만 다시 불러 메운다 |
```

- [ ] **Step 4: CI 점검이 실제로 도는지 로컬에서 확인한다**

```bash
cd ai-service && .venv/bin/python -m app.judge_agreement_check
```

Expected: `11가지 전부 통과.`

- [ ] **Step 5: 커밋**

```bash
cd /Users/cheonjamin/projects/AllDap
git add .github/workflows/ci.yml docs/BACKLOG.md
git commit -m "$(cat <<'EOF'
chore: judge_agreement_check 를 CI 에 태우고 수동 목록 주석을 정정한다

🔴 주석이 "DB 가 필요한 점검은 하나같이 외부 API 도 함께 부른다" 고 단언하고 있었는데
judge_agreement 이 그 문장을 깬다. DB 만 쓰고 외부 API 를 안 부른다(채점자 점수가
이미 박제돼 있다). 그래도 CI 에서 못 도는 이유가 API 가 아니라 <그 DB 안의 측정
결과가 CI 에 없기> 때문이라, 이유를 바꿔 적었다. 수도 여섯에서 일곱으로 고쳤다
(그 주석이 스스로 "개수를 고칠 것" 이라고 경고해 두었다).

BACKLOG 에 reason 미저장을 남겼다. 컬럼 추가는 Flyway V10 이 필요해 별개 PR 이다.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: 🔴 사람이 44건을 라벨링하고 결과를 남긴다

**이 태스크는 개발자가 직접 하는 것이다. 에이전트가 라벨을 채우면 이 슬라이스가 무의미해진다.**

**Files:**
- Modify: `ai-service/testdata/judge_labels.json` (사람이 채운다)
- Modify: `ai-service/app/judge.py` (첫머리 TODO)
- Modify: `AGENTS.md`
- Modify: `docs/decisions.md`

- [ ] **Step 1: 라벨을 매긴다**

```bash
cd ai-service && .venv/bin/python -m app.judge_agreement dump
```

`testdata/judge_labels.json` 을 에디터로 열고 `label` 칸을 채운다.

**기준 (파일 `_readme` 와 같다)**: 충실성 = **답변의 모든 주장이 그 아래 근거에 실제로 적혀 있는가.**

| 값 | 뜻 |
|---|---|
| `1.0` | 답변의 모든 주장이 근거에 있다 |
| `0.5` | 일부는 근거에 있고 일부는 없다 |
| `0.0` | 근거에 없는 내용을 지어냈다 |

⚠️ **답이 세상의 상식에 맞는지는 보지 않는다.** 사실이더라도 근거에 없으면 깎는다.
이것이 `judge.py` 의 `SYSTEM_PROMPT` 가 채점자에게 준 기준과 같아야 한다. 기준이
다르면 불일치가 "채점자가 틀렸다" 가 아니라 "둘이 다른 것을 쟀다" 가 된다.

🔴 **채점자 점수를 보지 말 것.** DB 에 있지만 보면 대조가 성립하지 않는다.
중간에 끊어도 되고, 다시 `dump` 를 돌려도 채운 칸은 보존된다.

- [ ] **Step 2: 집계를 돌린다**

```bash
cd ai-service && .venv/bin/python -m app.judge_agreement report --reasons
```

Expected: 네 덩어리가 전부 찍히고 종료코드 0.

- [ ] **Step 3: 결과를 `AGENTS.md` 에 남긴다**

"난이도 확보 시도" 절 <아래>에 새 절을 만든다. 반드시 담을 것:

1. 혼동행렬 표 그대로
2. **후함 N건 / 박함 N건** 과 그 방향이 전체충실성을 어느 쪽으로 미는지
3. run 별 왜곡량 표와 **실측 편차 0.032 와의 비교**
4. 불일치 케이스의 사유 (`--reasons` 결과). 특히 **사유가 사실과 다른 것이 있는지**
5. ⚠️ 한계: 44건은 **한 봇 · 한 코퍼스 · 한 채점 모델**이다. "이 채점자가 일반적으로 정확하다" 가 아니라 "이 저장소의 비교표를 만든 그 입력들에서 정확했는가" 까지만 말한다
6. 🔴 **결론이 어느 쪽이든 적을 것.** 오차가 편차보다 작으면 "비교표가 그대로 유효하다" 이고 그것도 결론이다. "효과가 없다" 가 아니라 "부작용이 없다" 로 읽어야 하는 자리다(2026-09-06 게이트 때와 같다)

- [ ] **Step 4: `judge.py` 첫머리 TODO 를 실제 결과로 바꾼다**

`ai-service/app/judge.py` 의 이 문단을 찾는다.

```
⚠️ 아직 <사람 라벨과 대조하지 않았다>. "채점을 어떻게 믿느냐"에 답하려면
   사람이 매긴 30~50건과의 일치율(카파)이 필요하다. TODO(W4).
   지금 있는 근거는 위 3케이스뿐이고, 그건 "쓸 수 있다"까지만 말해준다.
```

실제 수치로 바꾸고, 재현 명령(`python -m app.judge_agreement report`)과
`AGENTS.md` 의 해당 절을 가리킨다.

🔴 **이 단계를 빠뜨리지 말 것.** 이 저장소가 반복해 빠뜨린 자리가 "기능을 끝내고
그것을 <설명하는 자리>를 안 고치는 것" 이다. `system_prompt` 전달을 2026-08-13 에
끝냈는데 설정 화면은 2026-09-07 까지 "반영되지 않습니다" 라고 안내하고 있었다.

- [ ] **Step 5: `docs/decisions.md` 에 한 줄 남긴다**

형식: `날짜 | 무엇을 | 왜 그렇게 | 검토한 대안`

담을 것: 44건 전수를 택한 것(표본이 아니라 모집단), 카파 하나로 결론을 말하지 않은 것
(카파 역설), 채점 모델을 <바꾸지 않은> 것(바꾸면 2026-08-03 이후 모든 표의 축이 어긋난다).

- [ ] **Step 6: 커밋하고 PR 을 연다**

```bash
cd /Users/cheonjamin/projects/AllDap
git add ai-service/testdata/judge_labels.json ai-service/app/judge.py AGENTS.md docs/decisions.md
git commit -m "$(cat <<'EOF'
feat: 채점자를 사람 라벨 44건과 대조한 결과를 남긴다

judge.py 가 2026-08-02 부터 달고 있던 TODO 를 닫는다.

(여기에 실제 수치를 적는다: 후함 N건 / 박함 N건, run 별 왜곡량, 편차 0.032 와의 비교)

한계: 44건은 한 봇 · 한 코퍼스 · 한 채점 모델이다. "이 채점자가 일반적으로
정확하다" 가 아니라 "이 저장소의 비교표를 만든 그 입력들에서 정확했는가" 까지다.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

그리고 PR 을 연다. 본문은 `.github/PULL_REQUEST_TEMPLATE.md` 를 채우되
**한계 & 트레이드오프** 와 **검토한 대안과 선택 이유** 두 칸을 반드시 채운다.
**어떻게 해결했나요** 칸에는 `report` 의 실제 출력을 붙인다.

```bash
gh pr create --title "feat: 채점자(LLM-as-judge)를 사람 라벨과 대조한다" --body-file <(cat)
```

⚠️ PR 을 올리는 데까지가 이 계획의 끝이다. CI 결과를 기다리지 않는다.

---

## 완료 조건 (스펙 §7)

- [ ] `judge_agreement dump` 가 44건을 **채점자 점수 없이** 파일로 내보낸다
- [ ] 사람이 44건 전부에 0 / 0.5 / 1 을 매긴다 (빈칸 0)
- [ ] `judge_agreement report` 가 네 덩어리를 찍는다
- [ ] `judge_agreement_check` 가 CI 에서 돈다
- [ ] 결과가 `AGENTS.md` · `docs/decisions.md` 에 있고, **`judge.py` 의 TODO 가 실제 결과로 바뀌었다**
