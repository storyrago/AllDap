# 무관한 청크 주입 탐침 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사람 1.0 · 채점자 1.0 이 일치한 38건에 무관한 청크를 끝에 더해가며 채점자를 다시 불러, 채점자가 <장수>와 <비슷한 내용> 중 무엇에 약한지 잰다.

**Architecture:** `app/inject_probe.py` 하나에 순수 함수(선택 · 조립 · 집계)와 DB · 외부 API 를 쓰는 얇은 명령(`run` · `report`)을 둔다. 순수 함수는 `app/inject_probe_check.py` 가 CI 에서 검사한다. 결과는 `testdata/inject_probe_results.jsonl` 에 한 줄씩 붙여 쓰고 커밋한다.

**Tech Stack:** Python 3 표준 라이브러리(`argparse` · `json` · `random` · `dataclasses`), 기존 `app.eval_cases` · `app.judge` · `app.retriever` · `app.db`.

## Global Constraints

- 설계 원본: `docs/superpowers/specs/2026-09-26-inject-probe-design.md`
- **`app/judge.py` 는 한 줄도 고치지 않는다** (운영 평가와 같은 채점자여야 한다)
- 조건 8개, 이름 고정: `base` · `near+1` · `near+2` · `near+4` · `far+1` · `far+2` · `far+4` · `near+1@front`
- 대상: `judge_labels.json` 의 `label == 1.0` 이고 `Case.judge_faithfulness == 1.0` 인 케이스 (38건)
- 주입 후보에서 제외: 그 케이스의 원래 근거 청크 · 정답 문서(`eval_questions.source_chunk_id` 가 속한 문서)의 청크
- `near`: 벡터 거리 오름차순, `distance <= max_distance`(0.55, `retriever.search` 의 컷과 같은 비교) 만. 최대 4장
- `far`: 거리 순위 아래쪽 절반에서 `random.Random(question_id)` 로 4장 표본
- `+k` 조건은 고른 청크가 k 장 이상일 때만 만든다. 모자라면 그 조건은 채점하지 않는다
- 채점 실패는 `"faithfulness": null`. **0점으로 세지 않는다**
- 사람 확인 값은 `무관` · `모순` · `뒷받침` 셋뿐
- 새 의존성 금지. 테스트는 이 저장소 관례대로 `python -m app.<name>_check` (pytest 아님)
- 주석 · 출력 · 에러 메시지는 한국어. **em dash(—) 금지** (쉼표 · 콜론 · 괄호로)
- Python 코드에는 왜 그렇게 쓰는지(문법 · 관용구 포함) 짧게 주석을 붙인다 (AGENTS.md: 개발자가 Python 에 약하다)
- 모든 명령은 `ai-service/` 에서 `.venv/bin/python` 으로 돌린다

---

## 파일 구조

| 파일 | 책임 |
|---|---|
| `ai-service/app/inject_probe.py` (새) | 대상 선택 · 주입 청크 선택 · 조건 조립 · 결과 파일 읽기/쓰기 · 집계 · `run` / `report` 명령 |
| `ai-service/app/inject_probe_check.py` (새) | 위 순수 함수들의 자체 점검. DB · 외부 API 없음 |
| `ai-service/testdata/inject_probe_results.jsonl` (새, Task 5 에서 생긴다) | 채점 한 번에 한 줄 |
| `.github/workflows/ci.yml` (수정) | 자체 점검 목록에 한 줄 |

파일을 둘로만 나눈 이유: `judge_agreement.py` 가 같은 모양(순수 함수 + 얇은 명령 한 파일, 점검 한 파일)이고, 이 도구는 400줄 안쪽이다.

---

### Task 1: 대상 선택 · 주입 청크 선택 · 조건 조립 (순수 함수)

**Files:**
- Create: `ai-service/app/inject_probe.py`
- Create: `ai-service/app/inject_probe_check.py`

**Interfaces:**
- Consumes: `app.eval_cases.Case`, `app.eval_cases.SourceRef` (필드: `chunk_id`, `document_id`, `filename`, `content`), `app.schemas.Id`
- Produces:
  - `CONDITIONS: tuple[str, ...]`, `INJECT_MAX = 4`
  - `@dataclass(frozen=True) Candidate(chunk_id: Id, document_id: Id, filename: str, content: str, distance: float)` + `to_ref() -> SourceRef`
  - `select_targets(cases: list[Case], labels: dict[str, dict]) -> list[Case]`
  - `pick_near(ranked: list[Candidate], exclude_ids: set[Id], exclude_docs: set[Id], max_distance: float, n: int = INJECT_MAX) -> list[Candidate]`
  - `pick_far(ranked: list[Candidate], exclude_ids: set[Id], exclude_docs: set[Id], seed: int, n: int = INJECT_MAX) -> list[Candidate]`
  - `build_conditions(original: tuple[SourceRef, ...], near: list[Candidate], far: list[Candidate]) -> dict[str, tuple[tuple[SourceRef, ...], tuple[Candidate, ...]]]` (조건 이름 → (채점자에게 줄 근거, 주입한 청크))

- [ ] **Step 1: 실패하는 점검을 쓴다**

`ai-service/app/inject_probe_check.py`:

```python
"""무관한 청크 주입 탐침의 순수 함수 자체 점검. DB 도 외부 API 도 쓰지 않는다.

왜 이 검사가 있나
─────────────────────────────────────────────────────────────────────────────
이 탐침의 결론은 "채점자가 무엇에 약한가" 다. 그런데 조건을 잘못 조립하면
결론이 조용히 거짓이 된다. 예를 들어:
  · 끝에 붙인다면서 원래 근거의 순서가 바뀌면, "주입 때문" 과 "순서 때문" 이 섞인다
  · 주입 청크에 정답 문서가 섞이면, 무관한 종이가 아니라 <답을 뒷받침하는> 종이다
  · 채점 실패(None)를 0점으로 세면, 한도에 걸린 것이 "채점자가 무너졌다" 로 둔갑한다
숫자는 그럴듯하게 나오고 아무도 눈치채지 못한다. 그래서 검사로 못박는다.
"""
from __future__ import annotations

from .eval_cases import Case, SourceRef
from .inject_probe import (
    CONDITIONS, Candidate, build_conditions, pick_far, pick_near, select_targets,
)


def _ref(cid: int) -> SourceRef:
    return SourceRef(chunk_id=cid, document_id=cid * 10, filename=f"{cid}.md", content=f"본문{cid}")


def _cand(cid: int, doc: int, dist: float) -> Candidate:
    return Candidate(chunk_id=cid, document_id=doc, filename=f"{cid}.md", content=f"본문{cid}", distance=dist)


def _case(case_id: str, judge: float) -> Case:
    return Case(
        case_id=case_id, question_id=3, question="질문", ground_truth="정답",
        generated_answer="답", sources=tuple(_ref(i) for i in (1, 2, 3, 4, 5)),
        seen_in_runs=(11,), judge_faithfulness=judge, judge_relevancy=1.0,
    )


def check_targets_need_both_human_and_judge_at_one() -> None:
    """출발점이 "맞는 답을 맞다고 채점한 상태" 여야 떨어진 것을 채점자 실수라 부를 수 있다."""
    cases = [_case("a", 1.0), _case("b", 0.5), _case("c", 1.0), _case("d", 1.0)]
    labels = {"a": {"label": 1.0}, "b": {"label": 1.0}, "c": {"label": 0.5}, "d": {"label": None}}
    assert [c.case_id for c in select_targets(cases, labels)] == ["a"]


def check_near_is_closest_first_and_respects_cut() -> None:
    ranked = [_cand(10, 100, 0.30), _cand(11, 101, 0.40), _cand(12, 102, 0.55), _cand(13, 103, 0.56)]
    got = pick_near(ranked, set(), set(), max_distance=0.55)
    # 0.55 는 들어간다. retriever.search 도 `distance > max_distance` 만 버린다
    assert [c.chunk_id for c in got] == [10, 11, 12]


def check_near_excludes_original_chunks_and_gold_document() -> None:
    """정답 문서가 섞이면 무관한 종이가 아니라 답을 뒷받침하는 종이다."""
    ranked = [_cand(1, 10, 0.2), _cand(20, 999, 0.3), _cand(21, 200, 0.35), _cand(22, 201, 0.4)]
    got = pick_near(ranked, exclude_ids={1}, exclude_docs={999}, max_distance=0.55)
    assert [c.chunk_id for c in got] == [21, 22]


def check_near_takes_at_most_four() -> None:
    ranked = [_cand(i, 100 + i, 0.1 + i * 0.01) for i in range(10)]
    assert len(pick_near(ranked, set(), set(), max_distance=0.55)) == 4


def check_far_comes_from_bottom_half_and_is_reproducible() -> None:
    ranked = [_cand(i, 100 + i, i / 100) for i in range(20)]  # 0~9 위쪽, 10~19 아래쪽
    a = pick_far(ranked, set(), set(), seed=3)
    b = pick_far(ranked, set(), set(), seed=3)
    assert a == b, "같은 씨앗이면 같은 청크여야 다시 돌려도 같은 실험이다"
    assert len(a) == 4
    assert all(c.chunk_id >= 10 for c in a), "위쪽 절반에서 뽑으면 딴 얘기가 아니다"


def check_far_excludes_original_chunks_and_gold_document() -> None:
    ranked = [_cand(i, 100 + i, i / 100) for i in range(10)]  # 아래쪽 절반은 5~9
    got = pick_far(ranked, exclude_ids={5, 6}, exclude_docs={107}, seed=1)
    assert sorted(c.chunk_id for c in got) == [8, 9]


def check_appended_conditions_keep_original_order() -> None:
    """끝에 붙이면 원래 근거의 번호가 그대로다. 바뀐 것은 주입한 청크뿐이어야 한다."""
    original = tuple(_ref(i) for i in (1, 2, 3, 4, 5))
    near = [_cand(i, 100 + i, 0.3) for i in (11, 12, 13, 14)]
    far = [_cand(i, 200 + i, 0.9) for i in (21, 22, 23, 24)]
    conds = build_conditions(original, near, far)
    assert set(conds) == set(CONDITIONS)
    for name in ("near+1", "near+2", "near+4", "far+1", "far+2", "far+4"):
        srcs, _ = conds[name]
        assert srcs[:5] == original, name
    assert [s.chunk_id for s in conds["near+2"][0]] == [1, 2, 3, 4, 5, 11, 12]
    assert conds["base"] == (original, ())


def check_conditions_are_nested() -> None:
    """+1 ⊂ +2 ⊂ +4. 처음 무너진 조건에서 새로 들어온 청크가 범인으로 좁혀진다."""
    original = tuple(_ref(i) for i in (1, 2, 3, 4, 5))
    near = [_cand(i, 100 + i, 0.3) for i in (11, 12, 13, 14)]
    far = [_cand(i, 200 + i, 0.9) for i in (21, 22, 23, 24)]
    conds = build_conditions(original, near, far)
    for kind in ("near", "far"):
        one, two, four = (conds[f"{kind}+{k}"][1] for k in (1, 2, 4))
        assert two[:1] == one and four[:2] == two


def check_front_condition_puts_near_first() -> None:
    original = tuple(_ref(i) for i in (1, 2, 3, 4, 5))
    near = [_cand(11, 111, 0.3)]
    conds = build_conditions(original, near, [])
    srcs, injected = conds["near+1@front"]
    assert [s.chunk_id for s in srcs] == [11, 1, 2, 3, 4, 5]
    assert [c.chunk_id for c in injected] == [11]


def check_short_picks_skip_unfillable_conditions() -> None:
    """3장뿐이면 +4 는 만들지 않는다. 3장짜리를 +4 라고 부르면 표가 거짓말을 한다."""
    original = tuple(_ref(i) for i in (1, 2, 3, 4, 5))
    near = [_cand(i, 100 + i, 0.3) for i in (11, 12, 13)]
    conds = build_conditions(original, near, [])
    assert "near+2" in conds and "near+4" not in conds
    assert "far+1" not in conds
    assert "near+1@front" in conds


def main() -> None:
    checks = [
        check_targets_need_both_human_and_judge_at_one,
        check_near_is_closest_first_and_respects_cut,
        check_near_excludes_original_chunks_and_gold_document,
        check_near_takes_at_most_four,
        check_far_comes_from_bottom_half_and_is_reproducible,
        check_far_excludes_original_chunks_and_gold_document,
        check_appended_conditions_keep_original_order,
        check_conditions_are_nested,
        check_front_condition_puts_near_first,
        check_short_picks_skip_unfillable_conditions,
    ]
    for fn in checks:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(checks)}가지 전부 통과.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 실패를 확인한다**

Run: `cd ai-service && .venv/bin/python -m app.inject_probe_check`
Expected: `ModuleNotFoundError: No module named 'app.inject_probe'`

- [ ] **Step 3: 최소 구현을 쓴다**

`ai-service/app/inject_probe.py`:

```python
"""무관한 청크 주입 탐침 (2026-09-26).

설계: docs/superpowers/specs/2026-09-26-inject-probe-design.md

무엇을 재나
─────────────────────────────────────────────────────────────────────────────
2026-09-18 에 q3 한 문항에서, 답변을 고정한 채 근거에 무관한 청크 하나가 끼자
채점자 충실성이 1.0 에서 0.0 으로 떨어졌다. 정답 청크는 그대로 3번째에 있었다.
이 도구는 그것이 일반적인지, 그리고 채점자가 <장수>에 약한지
<헷갈리게 비슷한 내용>에 약한지를 가른다.

  base          원래 근거 5장 그대로 (지금 다시 채점해도 1.0 인가)
  near+1/2/4    끝에 <질문과 벡터 거리가 가까운> 청크를 1·2·4장
  far+1/2/4     끝에 <거리 순위 아래쪽 절반>의 청크를 1·2·4장 (대조군)
  near+1@front  near 1장을 맨 앞에 (자리가 중요한가)

🔴 답변은 끝까지 글자 하나 안 바뀐다. 대상은 사람도 채점자도 1.0 을 준 케이스뿐이라,
   주입 뒤 점수가 떨어지면 정의상 채점자 실수다.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from .eval_cases import Case, SourceRef
from .schemas import Id

# 튜플(tuple)로 둔 이유: 리스트와 달리 바꿀 수 없어서, 어딘가에서 실수로
# append 해 조건 목록이 늘어나는 일이 원천적으로 막힌다.
CONDITIONS: tuple[str, ...] = (
    "base",
    "near+1", "near+2", "near+4",
    "far+1", "far+2", "far+4",
    "near+1@front",
)
INJECT_MAX = 4
_STEPS = (1, 2, 4)


# frozen=True: 만든 뒤 필드를 못 바꾸는 불변 객체. 같은 값이면 == 로 같다고 나오고
# set 에도 넣을 수 있다. 점검에서 "같은 씨앗 → 같은 결과" 를 == 로 비교하는 근거다.
@dataclass(frozen=True)
class Candidate:
    """주입 후보 청크 하나. distance 는 <그 질문>과의 벡터 거리다."""

    chunk_id: Id
    document_id: Id
    filename: str
    content: str
    distance: float

    def to_ref(self) -> SourceRef:
        """채점자 입력 타입으로 바꾼다. 거리는 채점에 안 쓰이므로 버린다."""
        return SourceRef(
            chunk_id=self.chunk_id,
            document_id=self.document_id,
            filename=self.filename,
            content=self.content,
        )


def select_targets(cases: list[Case], labels: dict[str, dict]) -> list[Case]:
    """사람 1.0 · 채점자 1.0 인 케이스만 남긴다.

    출발점이 0.5 나 0.0 이면 "주입 때문에 떨어졌다" 와 "원래 틀린 답을 뒤늦게 잡았다" 를
    가를 수 없다. 둘 다 1.0 이어야 떨어진 것이 곧 채점자 실수다.
    """
    out: list[Case] = []
    for c in cases:
        rec = labels.get(c.case_id)
        if rec is None or rec.get("label") is None:
            continue
        if float(rec["label"]) == 1.0 and c.judge_faithfulness == 1.0:
            out.append(c)
    return out


def _eligible(ranked: list[Candidate], exclude_ids: set[Id], exclude_docs: set[Id]) -> list[Candidate]:
    """원래 근거와 정답 문서를 뺀다. 정답 문서가 섞이면 <답을 뒷받침하는> 종이가 된다."""
    return [r for r in ranked if r.chunk_id not in exclude_ids and r.document_id not in exclude_docs]


def pick_near(
    ranked: list[Candidate],
    exclude_ids: set[Id],
    exclude_docs: set[Id],
    max_distance: float,
    n: int = INJECT_MAX,
) -> list[Candidate]:
    """비슷한 동네: 거리가 가까운 순으로, 거리 컷 안에 드는 것만 최대 n 장.

    `ranked` 는 거리 오름차순이어야 한다. 컷 밖 청크는 실제 서비스에서 근거에
    절대 들어오지 않으므로 현실성이 없다. `<=` 인 이유는 retriever.search 가
    `distance > max_distance` 만 버리기 때문이다(같은 경계를 써야 한다).
    """
    pool = [r for r in _eligible(ranked, exclude_ids, exclude_docs) if r.distance <= max_distance]
    return pool[:n]


def pick_far(
    ranked: list[Candidate],
    exclude_ids: set[Id],
    exclude_docs: set[Id],
    seed: int,
    n: int = INJECT_MAX,
) -> list[Candidate]:
    """딴 얘기: 거리 순위 아래쪽 절반에서 무작위 n 장.

    random.Random(seed) 는 전역 난수와 분리된 <자기만의> 난수 생성기다.
    씨앗을 question_id 로 고정하면 다시 돌려도 같은 청크가 나온다.
    sample 은 중복 없이 뽑고 뽑힌 순서를 돌려준다. 그 순서대로 +1 · +2 · +4 에 쌓는다.
    """
    bottom = ranked[len(ranked) // 2:]
    pool = _eligible(bottom, exclude_ids, exclude_docs)
    return random.Random(seed).sample(pool, min(n, len(pool)))


def build_conditions(
    original: tuple[SourceRef, ...],
    near: list[Candidate],
    far: list[Candidate],
) -> dict[str, tuple[tuple[SourceRef, ...], tuple[Candidate, ...]]]:
    """조건 이름 → (채점자에게 줄 근거, 주입한 청크).

    🔴 더하기이지 바꿔 끼우기가 아니다. 원래 근거는 하나도 빠지지 않고 순서도 그대로다.
       바꿔 끼우면 "엉뚱한 종이가 들어와서" 와 "원래 종이가 빠져서" 가 섞인다.
    k 장이 안 차는 조건은 만들지 않는다. 3장짜리를 +4 라고 부르면 표가 거짓말을 한다.
    """
    base = tuple(original)
    out: dict[str, tuple[tuple[SourceRef, ...], tuple[Candidate, ...]]] = {"base": (base, ())}
    for kind, picks in (("near", near), ("far", far)):
        for k in _STEPS:
            if len(picks) >= k:
                injected = tuple(picks[:k])
                out[f"{kind}+{k}"] = (base + tuple(c.to_ref() for c in injected), injected)
    if near:
        first = near[0]
        out["near+1@front"] = ((first.to_ref(),) + base, (first,))
    return out
```

- [ ] **Step 4: 통과를 확인한다**

Run: `cd ai-service && .venv/bin/python -m app.inject_probe_check`
Expected: `✅` 10줄 뒤 `10가지 전부 통과.`

- [ ] **Step 5: 커밋**

```bash
git add ai-service/app/inject_probe.py ai-service/app/inject_probe_check.py
git commit -m "feat: 주입 탐침의 대상 선택과 조건 조립을 만든다"
```

---

### Task 2: 결과 파일 · 이어 돌리기 · `run` 명령

**Files:**
- Modify: `ai-service/app/inject_probe.py` (아래 코드 추가)
- Modify: `ai-service/app/inject_probe_check.py` (점검 3개 추가, `main` 목록에 등록)

**Interfaces:**
- Consumes: Task 1 전부, `app.judge.score(question, ground_truth, sources: list[Source], answer) -> Scores | None`, `app.judge.Scores(faithfulness, relevancy, reason)`, `app.eval_cases.load_cases(run_ids) -> list[Case]`, `app.eval_cases.DEFAULT_RUN_IDS`, `app.judge_agreement.read_labels(path) -> dict[str, dict]`, `app.judge_agreement.DEFAULT_PATH`, `app.retriever.embed_one(text) -> list[float]`, `app.config.get_settings().max_distance`, `app.db.cursor`
- Produces:
  - `DEFAULT_RESULTS = "testdata/inject_probe_results.jsonl"`
  - `make_record(case: Case, condition: str, injected: tuple[Candidate, ...], scores: Scores | None) -> dict`
  - `read_results(path: str) -> list[dict]`
  - `latest(records: list[dict]) -> dict[tuple[str, str], dict]` (같은 (case_id, condition) 이 여러 줄이면 마지막 줄)
  - `done_keys(records: list[dict]) -> set[tuple[str, str]]` (채점에 <성공한> 키만)
  - `run(bot_id: Id, results_path: str, labels_path: str, limit: int | None) -> int`
  - `main(argv: list[str] | None = None) -> int` 의 `run` 하위 명령

- [ ] **Step 1: 실패하는 점검을 추가한다**

`inject_probe_check.py` 의 import 를 바꾸고 점검 3개를 `main` 앞에 추가한다:

```python
from .judge import Scores
from .inject_probe import (
    CONDITIONS, Candidate, build_conditions, done_keys, latest, make_record,
    pick_far, pick_near, select_targets,
)
```

```python
def check_failed_scoring_is_null_not_zero() -> None:
    """🔴 채점 실패는 0점이 아니다. 0점으로 적으면 한도(429)에 걸린 것이
    "채점자가 무너졌다" 로 둔갑한다. 이 저장소의 "낸 버그" 표 다섯 번째가 이것이었다."""
    rec = make_record(_case("a", 1.0), "near+1", (_cand(11, 111, 0.3),), None)
    assert rec["faithfulness"] is None and rec["relevancy"] is None
    assert rec["review"] is None
    ok = make_record(_case("a", 1.0), "base", (), Scores(faithfulness=1.0, relevancy=1.0, reason="r"))
    assert ok["faithfulness"] == 1.0 and ok["injected"] == []


def check_resume_skips_only_successful_keys() -> None:
    """성공한 것만 건너뛴다. 실패(null)는 다음 실행에서 다시 부른다."""
    recs = [
        {"case_id": "a", "condition": "base", "faithfulness": 1.0},
        {"case_id": "a", "condition": "near+1", "faithfulness": None},
        {"case_id": "b", "condition": "base", "faithfulness": 0.0},
    ]
    assert done_keys(recs) == {("a", "base"), ("b", "base")}


def check_latest_line_wins() -> None:
    """실패 뒤 재시도가 성공하면 파일에 두 줄이 남는다. 집계는 마지막 줄을 본다."""
    recs = [
        {"case_id": "a", "condition": "near+1", "faithfulness": None},
        {"case_id": "a", "condition": "near+1", "faithfulness": 1.0},
    ]
    assert latest(recs)[("a", "near+1")]["faithfulness"] == 1.0
    assert done_keys(recs) == {("a", "near+1")}
```

`main()` 의 `checks` 목록 끝에 세 함수를 추가한다.

- [ ] **Step 2: 실패를 확인한다**

Run: `cd ai-service && .venv/bin/python -m app.inject_probe_check`
Expected: `ImportError: cannot import name 'done_keys' from 'app.inject_probe'`

- [ ] **Step 3: 구현을 추가한다**

`inject_probe.py` 의 import 를 바꾼다:

```python
import argparse
import json
import os
import random
import sys
from dataclasses import dataclass

from .config import get_settings
from .db import cursor
from .eval_cases import DEFAULT_RUN_IDS, Case, SourceRef, load_cases
from .judge import Scores, score
from .judge_agreement import DEFAULT_PATH as LABELS_PATH
from .judge_agreement import read_labels
from .retriever import embed_one
from .schemas import Id
```

상수 옆에 추가:

```python
DEFAULT_RESULTS = "testdata/inject_probe_results.jsonl"
# 연달아 이만큼 실패하면 멈춘다. 하루 한도(429)에 걸리면 이후 호출이 전부 실패하는데,
# 계속 돌면 남은 수백 건이 전부 null 줄로 쌓여 파일만 지저분해진다.
_STOP_AFTER_FAILURES = 3
```

파일 끝에 추가:

```python
# ── 결과 파일 ────────────────────────────────────────────────────────────────
# JSON Lines(.jsonl): 한 줄에 JSON 하나. 통째로 다시 쓰는 JSON 과 달리 <끝에 붙이기만>
# 하면 되므로, 한 건 채점할 때마다 바로 저장할 수 있고 중간에 죽어도 앞의 줄은 멀쩡하다.


def make_record(case: Case, condition: str, injected: tuple[Candidate, ...], scores: Scores | None) -> dict:
    """채점 한 번을 한 줄로. 🔴 실패는 null 이지 0.0 이 아니다."""
    return {
        "case_id": case.case_id,
        "question_id": case.question_id,
        "condition": condition,
        "injected": [
            {"chunk_id": c.chunk_id, "filename": c.filename, "distance": round(c.distance, 4)}
            for c in injected
        ],
        "faithfulness": None if scores is None else scores.faithfulness,
        "relevancy": None if scores is None else scores.relevancy,
        "reason": "" if scores is None else scores.reason,
        # 사람이 채운다: 무관 / 모순 / 뒷받침. run 은 이 칸을 쓰기만 하고 다시 건드리지 않는다.
        "review": None,
    }


def read_results(path: str) -> list[dict]:
    """파일이 없으면 빈 목록. 빈 줄은 건너뛴다(사람이 손으로 고치다 남길 수 있다)."""
    if not os.path.exists(path):
        return []
    out: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def latest(records: list[dict]) -> dict[tuple[str, str], dict]:
    """(case_id, condition) 마다 <마지막> 줄. 실패 뒤 재시도가 성공하면 그것이 남는다."""
    out: dict[tuple[str, str], dict] = {}
    for r in records:
        out[(r["case_id"], r["condition"])] = r
    return out


def done_keys(records: list[dict]) -> set[tuple[str, str]]:
    """이미 <성공한> 키. 실패(null)는 넣지 않아 다음 실행이 다시 부른다."""
    return {k for k, r in latest(records).items() if r["faithfulness"] is not None}


# ── DB · 외부 API ────────────────────────────────────────────────────────────


def _gold_documents(question_ids: list[int]) -> dict[int, Id]:
    """question_id → 정답 청크가 속한 문서. source_chunk_id 가 NULL 이면 빠진다."""
    with cursor() as cur:
        cur.execute(
            """SELECT q.id, c.document_id
                 FROM eval_questions q JOIN chunks c ON c.id = q.source_chunk_id
                WHERE q.id = ANY(%s)""",
            (question_ids,),
        )
        return {int(qid): doc for qid, doc in cur.fetchall()}


def _ranked(bot_id: Id, question: str) -> list[Candidate]:
    """그 봇의 <전체> 청크를 질문과의 벡터 거리 오름차순으로.

    `<=>` 는 pgvector 의 코사인 거리 연산자다. retriever.search 와 같은 거리라
    max_distance 컷을 그대로 댈 수 있다. 임베딩은 질문당 1회라 비용은 무시할 수준이다.
    """
    qvec = embed_one(question)
    with cursor() as cur:
        cur.execute(
            """SELECT c.id, c.document_id, d.filename, c.content,
                      c.embedding <=> %s::vector AS distance
                 FROM chunks c JOIN documents d ON d.id = c.document_id
                WHERE c.bot_id = %s AND c.embedding IS NOT NULL
                ORDER BY distance""",
            (qvec, bot_id),
        )
        return [Candidate(r[0], r[1], r[2], r[3], float(r[4])) for r in cur.fetchall()]


def run(bot_id: Id, results_path: str, labels_path: str, limit: int | None) -> int:
    """대상 케이스마다 조건을 조립해 채점하고, 한 번마다 즉시 한 줄 붙인다."""
    s = get_settings()
    targets = select_targets(load_cases(DEFAULT_RUN_IDS), read_labels(labels_path))
    if limit is not None:
        targets = targets[:limit]
    gold = _gold_documents(sorted({c.question_id for c in targets}))
    done = done_keys(read_results(results_path))
    print(f"대상 {len(targets)}건 · 이미 끝난 채점 {len(done)}회")

    failures = 0
    calls = 0
    # "a" 모드: 파일 끝에 붙인다. 기존 줄(사람이 적은 review 포함)은 건드리지 않는다.
    with open(results_path, "a", encoding="utf-8") as out:
        for i, case in enumerate(targets, 1):
            exclude_ids = {src.chunk_id for src in case.sources}
            exclude_docs = {gold[case.question_id]} if case.question_id in gold else set()
            ranked = _ranked(bot_id, case.question)
            near = pick_near(ranked, exclude_ids, exclude_docs, s.max_distance)
            far = pick_far(ranked, exclude_ids, exclude_docs, seed=case.question_id)
            conds = build_conditions(case.sources, near, far)
            if len(near) < INJECT_MAX:
                print(f"  ⚠️ q{case.question_id} ({case.case_id}) near 가 {len(near)}장뿐이라 일부 조건을 건너뜁니다")
            for name in CONDITIONS:
                if name not in conds or (case.case_id, name) in done:
                    continue
                sources, injected = conds[name]
                result = score(
                    case.question, case.ground_truth,
                    [src.to_source() for src in sources], case.generated_answer,
                )
                calls += 1
                out.write(json.dumps(make_record(case, name, injected, result), ensure_ascii=False) + "\n")
                # flush: 버퍼에 쌓아두지 말고 지금 디스크로. 이게 없으면 죽을 때 마지막 몇 줄이 사라진다.
                out.flush()
                failures = failures + 1 if result is None else 0
                if failures >= _STOP_AFTER_FAILURES:
                    print(f"❌ 채점이 {failures}번 연달아 실패해 멈춥니다(하루 한도일 가능성이 큽니다)."
                          " 한도가 풀린 뒤 같은 명령을 다시 돌리면 이어서 합니다.", file=sys.stderr)
                    return 1
            print(f"  [{i}/{len(targets)}] q{case.question_id} 끝")
    print(f"채점 {calls}회. 결과: {results_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="무관한 청크를 주입해 채점자를 다시 부른다")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="채점한다 (외부 API 를 부른다. 이어 돌리기 가능)")
    r.add_argument("--bot-id", type=int, required=True)
    r.add_argument("--results", default=DEFAULT_RESULTS)
    r.add_argument("--labels", default=LABELS_PATH)
    r.add_argument("--limit", type=int, default=None, help="앞에서 N건만 (시험 삼아 돌릴 때)")
    args = p.parse_args(argv)
    if args.cmd == "run":
        return run(args.bot_id, args.results, args.labels, args.limit)
    return 0


if __name__ == "__main__":
    from .db import close_pool
    try:
        sys.exit(main())
    finally:
        close_pool()
```

- [ ] **Step 4: 점검 통과를 확인한다**

Run: `cd ai-service && .venv/bin/python -m app.inject_probe_check`
Expected: `13가지 전부 통과.`

- [ ] **Step 5: 한 건만 진짜로 돌려본다 (약 200 뉴런)**

사전 조건: `docker compose up -d` (저장소 루트). uvicorn 은 필요 없다.

Run:
```bash
cd ai-service
.venv/bin/python -m app.inject_probe run --bot-id 1 --limit 1 --results "$TMPDIR/probe_smoke.jsonl"
wc -l "$TMPDIR/probe_smoke.jsonl"
.venv/bin/python -c "import json;[print(json.loads(l)['condition'], json.loads(l)['faithfulness'], [i['filename'] for i in json.loads(l)['injected']]) for l in open('"$TMPDIR/probe_smoke.jsonl"')]"
```
Expected: `대상 1건`, 8줄(near 가 모자라면 그보다 적고 ⚠️ 줄이 찍힌다), `base` 의 faithfulness 가 `1.0`, near 의 파일명이 far 보다 질문 주제에 가깝다(눈으로 확인).

그 다음 **같은 명령을 한 번 더** 돌린다.
Expected: `이미 끝난 채점 8회`(또는 앞에서 찍힌 수), `채점 0회`. 이어 돌리기가 실제로 건너뛴다는 확인이다.

확인 뒤 `"$TMPDIR/probe_smoke.jsonl"` 은 지운다(커밋하지 않는다).

- [ ] **Step 6: 커밋**

```bash
git add ai-service/app/inject_probe.py ai-service/app/inject_probe_check.py
git commit -m "feat: 주입 탐침을 이어 돌릴 수 있게 결과를 한 줄씩 남긴다"
```

---

### Task 3: 집계와 `report` 명령

**Files:**
- Modify: `ai-service/app/inject_probe.py`
- Modify: `ai-service/app/inject_probe_check.py` (점검 4개 추가)

**Interfaces:**
- Consumes: Task 2 의 `read_results`, `latest`, `DEFAULT_RESULTS`
- Produces:
  - `REVIEW_VALUES = ("무관", "모순", "뒷받침")`
  - `bucket(v: float | None) -> str` (`"1.0"` · `"0.5"` · `"0.0"` · `"기타"` · `"못 잼"`)
  - `unstable_bases(lm: dict[tuple[str, str], dict]) -> dict[str, float | None]` (base 가 1.0 이 아닌 case_id → 그 값)
  - `distribution(lm, condition: str, skip: set[str]) -> dict[str, int]`
  - `first_drop(lm, case_id: str, kind: str) -> str | None`
  - `drops(lm, skip: set[str]) -> list[dict]`
  - `bad_reviews(records: list[dict]) -> list[str]`
  - `report(results_path: str) -> int` 과 `main` 의 `report` 하위 명령

- [ ] **Step 1: 실패하는 점검을 추가한다**

import 에 `REVIEW_VALUES, bad_reviews, bucket, distribution, drops, first_drop, unstable_bases` 를 추가하고, 점검 4개를 `main` 앞에 둔다:

```python
def _lm(rows: list[tuple[str, str, float | None, str | None]]) -> dict:
    return latest([
        {"case_id": c, "condition": k, "faithfulness": f, "review": rv, "injected": [], "reason": ""}
        for c, k, f, rv in rows
    ])


def check_distribution_counts_null_separately() -> None:
    """🔴 못 잰 것은 0.0 칸이 아니라 <못 잼> 칸이다."""
    lm = _lm([("a", "near+1", 0.0, None), ("b", "near+1", None, None), ("c", "near+1", 1.0, None)])
    d = distribution(lm, "near+1", skip=set())
    assert d["0.0"] == 1 and d["못 잼"] == 1 and d["1.0"] == 1
    assert bucket(0.7) == "기타"


def check_unstable_base_is_excluded_from_drops() -> None:
    """base 가 이미 1.0 이 아니면 "끼워서 떨어졌다" 와 "원래 떨어져 있었다" 가 섞인다."""
    lm = _lm([
        ("a", "base", 0.5, None), ("a", "near+1", 0.0, None),
        ("b", "base", 1.0, None), ("b", "near+1", 0.0, None),
        ("c", "base", None, None),
    ])
    skip = set(unstable_bases(lm))
    assert skip == {"a", "c"}
    assert [r["case_id"] for r in drops(lm, skip)] == ["b"]


def check_first_drop_is_the_earliest_step() -> None:
    lm = _lm([("a", "near+1", 1.0, None), ("a", "near+2", 0.5, None), ("a", "near+4", 0.0, None),
              ("a", "far+1", 1.0, None), ("a", "far+2", None, None), ("a", "far+4", 1.0, None)])
    assert first_drop(lm, "a", "near") == "near+2"
    assert first_drop(lm, "a", "far") is None, "못 잰 것은 무너진 것이 아니다"


def check_review_values_are_restricted() -> None:
    recs = [{"case_id": "a", "condition": "near+1", "review": "무관"},
            {"case_id": "b", "condition": "near+1", "review": None},
            {"case_id": "c", "condition": "near+2", "review": "관련있음"}]
    bad = bad_reviews(recs)
    assert len(bad) == 1 and "관련있음" in bad[0]
    assert REVIEW_VALUES == ("무관", "모순", "뒷받침")
```

`main()` 의 목록 끝에 네 함수를 등록한다.

- [ ] **Step 2: 실패를 확인한다**

Run: `cd ai-service && .venv/bin/python -m app.inject_probe_check`
Expected: `ImportError: cannot import name 'REVIEW_VALUES'`

- [ ] **Step 3: 구현을 추가한다**

`inject_probe.py` 상수 옆에:

```python
REVIEW_VALUES: tuple[str, ...] = ("무관", "모순", "뒷받침")
_BUCKETS = ("1.0", "0.5", "0.0", "기타", "못 잼")
```

`run` 앞(결과 파일 절 끝)에 집계 함수를 추가:

```python
# ── 집계 (순수 함수) ─────────────────────────────────────────────────────────


def bucket(v: float | None) -> str:
    """점수를 칸으로. 채점자는 0 / 0.5 / 1 을 주도록 지시받지만 다른 값이 올 수 있어 기타를 둔다."""
    if v is None:
        return "못 잼"
    for name in ("1.0", "0.5", "0.0"):
        if float(v) == float(name):
            return name
    return "기타"


def unstable_bases(lm: dict[tuple[str, str], dict]) -> dict[str, float | None]:
    """base 가 1.0 이 아닌 케이스(못 잰 것 포함). 이 케이스들은 탐침 집계에서 뺀다."""
    return {cid: r["faithfulness"] for (cid, cond), r in lm.items()
            if cond == "base" and r["faithfulness"] != 1.0}


def distribution(lm: dict[tuple[str, str], dict], condition: str, skip: set[str]) -> dict[str, int]:
    out = {b: 0 for b in _BUCKETS}
    for (cid, cond), r in lm.items():
        if cond == condition and cid not in skip:
            out[bucket(r["faithfulness"])] += 1
    return out


def first_drop(lm: dict[tuple[str, str], dict], case_id: str, kind: str) -> str | None:
    """그 종류에서 처음 1.0 미만이 된 조건. 못 잰 조건은 건너뛴다(무너진 것이 아니다)."""
    for k in (1, 2, 4):
        r = lm.get((case_id, f"{kind}+{k}"))
        if r is not None and r["faithfulness"] is not None and r["faithfulness"] < 1.0:
            return f"{kind}+{k}"
    return None


def drops(lm: dict[tuple[str, str], dict], skip: set[str]) -> list[dict]:
    """주입 조건에서 1.0 미만이 된 줄. 사람이 review 를 적을 대상이다."""
    return [r for (cid, cond), r in sorted(lm.items())
            if cond != "base" and cid not in skip
            and r["faithfulness"] is not None and r["faithfulness"] < 1.0]


def bad_reviews(records: list[dict]) -> list[str]:
    """허용하지 않는 review 값. 오타 하나가 조용히 "무관 아님" 으로 세지면 결론이 바뀐다."""
    return [f"{r['case_id']} {r['condition']}: {r['review']!r}"
            for r in records
            if r.get("review") is not None and r["review"] not in REVIEW_VALUES]
```

`run` 뒤에 `report` 를 추가:

```python
def report(results_path: str) -> int:
    """결과 파일만 읽는다. 외부 API 를 부르지 않는다."""
    records = read_results(results_path)
    if not records:
        print(f"❌ {results_path} 가 없거나 비어 있습니다. 먼저 run 을 돌리세요.", file=sys.stderr)
        return 1
    bad = bad_reviews(records)
    if bad:
        print("❌ review 칸에는 무관 / 모순 / 뒷받침 만 적을 수 있습니다:", file=sys.stderr)
        for line in bad:
            print(f"   {line}", file=sys.stderr)
        return 1

    lm = latest(records)
    unstable = unstable_bases(lm)
    skip = set(unstable)
    cases = sorted({cid for cid, _ in lm} - skip)

    print(f"\n[1] 조건별 분포 (집계 대상 {len(cases)}건, base 불안정으로 뺀 것 {len(skip)}건)")
    print(f"  {'조건':<14}" + "".join(f"{b:>7}" for b in _BUCKETS) + f"{'하락 중 무관':>12}")
    dropped = drops(lm, skip)
    for cond in CONDITIONS:
        d = distribution(lm, cond, skip)
        irrelevant = sum(1 for r in dropped if r["condition"] == cond and r.get("review") == "무관")
        print(f"  {cond:<14}" + "".join(f"{d[b]:>7}" for b in _BUCKETS) + f"{irrelevant:>12}")

    print("\n[2] 문항별 붕괴 지점 (처음 1.0 미만이 된 조건. - 는 끝까지 1.0 이거나 못 잼)")
    for cid in cases:
        qid = lm.get((cid, "base"), {}).get("question_id", "?")
        print(f"  q{qid:<4} {cid}  near={first_drop(lm, cid, 'near') or '-':<8} far={first_drop(lm, cid, 'far') or '-'}")

    print("\n[3] 자리 비교: near+1 (끝) vs near+1@front (맨 앞)")
    both = [cid for cid in cases if (cid, "near+1") in lm and (cid, "near+1@front") in lm]
    same = sum(1 for cid in both if bucket(lm[(cid, "near+1")]["faithfulness"])
               == bucket(lm[(cid, "near+1@front")]["faithfulness"]))
    print(f"  같은 칸 {same} / {len(both)}건")
    for cid in both:
        a, b = lm[(cid, "near+1")]["faithfulness"], lm[(cid, "near+1@front")]["faithfulness"]
        if bucket(a) != bucket(b):
            print(f"  갈림  {cid}  끝={bucket(a)}  앞={bucket(b)}")

    print(f"\n[4] 떨어진 건 {len(dropped)}개 (사람이 review 를 적을 대상)")
    pending = 0
    for r in dropped:
        pending += r.get("review") is None
        names = ", ".join(f"{i['chunk_id']}:{i['filename']}" for i in r["injected"])
        print(f"  {r['case_id']} {r['condition']:<13} {bucket(r['faithfulness'])}  "
              f"review={r.get('review') or '(미확인)'}  주입=[{names}]")
        print(f"      사유: {r['reason'][:160]}")
    if pending:
        print(f"  ⚠️ 사람 확인 필요 {pending}건. 결과 파일의 해당 줄 review 칸에 무관 / 모순 / 뒷받침 을 적으세요.")

    print(f"\n[5] base 가 1.0 이 아닌 케이스 {len(unstable)}건 (집계에서 뺐다)")
    for cid, v in sorted(unstable.items()):
        print(f"  {cid}  base={bucket(v)}")
    return 0
```

`main` 에 하위 명령을 추가(`args = p.parse_args(argv)` 줄 앞):

```python
    rp = sub.add_parser("report", help="결과를 집계한다 (외부 API 를 부르지 않는다)")
    rp.add_argument("--results", default=DEFAULT_RESULTS)
```

그리고 `if args.cmd == "run":` 블록 뒤에:

```python
    if args.cmd == "report":
        return report(args.results)
```

- [ ] **Step 4: 점검 통과를 확인한다**

Run: `cd ai-service && .venv/bin/python -m app.inject_probe_check`
Expected: `17가지 전부 통과.`

- [ ] **Step 5: Task 2 의 한 건짜리 결과로 보고서를 찍어본다**

Task 2 Step 5 를 다시 돌려 `"$TMPDIR/probe_smoke.jsonl"` 을 만든 뒤(이미 지웠다면 약 200 뉴런 추가):
Run: `cd ai-service && .venv/bin/python -m app.inject_probe report --results "$TMPDIR/probe_smoke.jsonl"`
Expected: [1]~[5] 다섯 덩어리가 찍힌다. [1] 의 `base` 줄이 `1.0` 칸에 1. 에러 없이 종료코드 0.

그리고 그 파일 한 줄의 review 를 손으로 `"관련있음"` 으로 바꾼 뒤 다시 돌린다.
Expected: `❌ review 칸에는 ...` 과 종료코드 1. 확인 뒤 파일을 지운다.

- [ ] **Step 6: 커밋**

```bash
git add ai-service/app/inject_probe.py ai-service/app/inject_probe_check.py
git commit -m "feat: 주입 탐침 결과를 다섯 덩어리로 집계한다"
```

---

### Task 4: CI 에 자체 점검을 태운다

**Files:**
- Modify: `.github/workflows/ci.yml` (자체 점검 목록 · 그 위 주석)

- [ ] **Step 1: 목록에 한 줄 추가**

`python -m app.judge_agreement_check` 바로 아래에:

```yaml
          python -m app.inject_probe_check
```

- [ ] **Step 2: 주석에 이유를 남긴다**

`app.judge_agreement` 예외를 설명하는 주석 문단 바로 아래에 추가:

```yaml
      #       🔴 app.inject_probe 도 같은 이유로 여기서 못 돈다 (2026-09-26).
      #          게다가 이쪽은 채점자를 실제로 부른다(약 300회). 순수 함수만
      #          app.inject_probe_check 로 태운다.
```

- [ ] **Step 3: requirements.txt 만 깔린 상태에서 import 가 되는지 확인**

Run: `cd ai-service && .venv/bin/python -m app.inject_probe_check`
Expected: `17가지 전부 통과.` (CI 잡은 `requirements.txt` 만 깐다. 새 import 는 전부 기존 모듈이라 늘어난 의존성이 없다)

- [ ] **Step 4: 커밋**

```bash
git add .github/workflows/ci.yml
git commit -m "chore: 주입 탐침 자체 점검을 CI 에 태운다"
```

---

### Task 5: 본 실행 (약 8,000 뉴런, 이틀에 걸칠 수 있다)

**Files:**
- Create: `ai-service/testdata/inject_probe_results.jsonl`

🔴 **이 태스크는 사람이 명령을 돌린다.** 하루 한도(10,000 뉴런)에 가까워 실행 시점을 사람이 정한다. 같은 날 다른 평가를 돌렸으면 다음 날로 미룬다.

- [ ] **Step 1: 실행**

```bash
docker compose up -d        # 저장소 루트
cd ai-service
.venv/bin/python -m app.inject_probe run --bot-id 1
```
Expected: `대상 38건`. 끝까지 가면 `채점 N회` (N 은 300 안팎, near 가 모자란 문항만큼 적다).
중간에 `❌ 채점이 3번 연달아 실패해 멈춥니다` 가 나오면 한도다. 한도가 풀린 뒤(소진 약 24~33시간 뒤, AGENTS.md "회당 비용" 절) **같은 명령**을 다시 돌린다.

- [ ] **Step 2: 완주 확인**

Run: `.venv/bin/python -m app.inject_probe run --bot-id 1`
Expected: `채점 0회`. 모든 키가 성공으로 채워졌다는 뜻이다.

- [ ] **Step 3: 커밋**

```bash
git add ai-service/testdata/inject_probe_results.jsonl
git commit -m "feat: 주입 탐침 본 실행 결과를 남긴다 (38건 × 8조건)"
```

---

### Task 6: 사람 확인 → 보고 → 기록 → PR

**Files:**
- Modify: `ai-service/testdata/inject_probe_results.jsonl` (review 칸)
- Modify: `AGENTS.md` (새 절 + "낸 버그" 표 아홉 번째 문단의 "아직 닫히지 않았다" 갱신 여부 검토)
- Modify: `docs/decisions.md` (2026-09-26 항목)
- Modify: `docs/BACKLOG.md` §5
- Create: `docs/superpowers/handoff-2026-09-26.md`

- [ ] **Step 1: 떨어진 건 목록을 뽑는다**

Run: `cd ai-service && .venv/bin/python -m app.inject_probe report`
[4] 의 목록을 사람이 본다. 각 줄의 주입 청크 본문은:
```bash
docker exec -i alldap-db psql -U alldap alldap -c "SELECT id, left(content, 400) FROM chunks WHERE id IN (<chunk_id들>);"
```

- [ ] **Step 2: 사람이 review 를 적는다**

결과 파일에서 해당 (case_id, condition) 의 **마지막 줄**의 `"review": null` 을 `"무관"` · `"모순"` · `"뒷받침"` 중 하나로 바꾼다.
기준: 그 청크가 질문의 답과 **같은 사실을 말하면 뒷받침**, **다른 값을 말하면 모순**, **둘 다 아니면 무관**.

- [ ] **Step 3: 보고서를 다시 돌린다**

Run: `.venv/bin/python -m app.inject_probe report`
Expected: `⚠️ 사람 확인 필요` 줄이 없다. 종료코드 0.

- [ ] **Step 4: 설계 §6 의 해석표에 대입한다**

`review = 무관` 인 하락만 세서, 네 칸(`far` 에서도 떨어진다 / `near` 에서만 / 둘 다 38건 중 1건 이하 / `@front` 에서만) 중 어느 것이 맞는지 적는다. 여러 칸이 맞으면 전부 적는다. 🔴 표에 없는 모양이 나오면 억지로 칸에 넣지 않고 "표에 없는 모양" 이라고 적는다.

- [ ] **Step 5: 기록한다**

- `AGENTS.md`: "채점자를 사람 라벨과 대조했다" 절 뒤에 새 절 `### 무관한 청크 주입 탐침 (2026-09-26)`. [1] 표 · 해석표 대입 결과 · 한계(한 봇 · 한 채점 모델 · 조건당 1회 · `near` 는 벡터 거리만으로 정의) · 재현 명령. "▶ 다음 세션" 의 최신 핸드오프 링크를 새 핸드오프로.
- `docs/decisions.md`: `2026-09-26 | 주입 탐침을 채점자만 · 더하기 · 끝 붙이기로 설계 | 변수를 하나로 묶으려고 | 생성 모델 동시 측정 · 바꿔 끼우기 · 맨 앞 끼우기` + 결과 한 줄.
- `docs/BACKLOG.md` §5: 이 항목을 결과로 닫고, 다음 후보(생성 모델 탐침. 이번 붕괴 지점 근처만 잰다)를 남긴다.
- `docs/superpowers/handoff-2026-09-26.md`: 앞 핸드오프와 같은 틀(어디까지 왔나 · 결론 · 방법론 · 다음 · 함정 · 안 한 것).

- [ ] **Step 6: 로컬 검사 후 커밋 · 푸시 · PR**

```bash
cd ai-service && .venv/bin/python -m app.inject_probe_check && .venv/bin/python -m app.judge_agreement_check
cd .. && git add -A ai-service/testdata/inject_probe_results.jsonl AGENTS.md docs/decisions.md docs/BACKLOG.md docs/superpowers/handoff-2026-09-26.md
git commit -m "docs: 주입 탐침 결과를 기록한다"
git push -u origin feat/inject-probe
gh pr create --title "feat: 무관한 청크 주입 탐침으로 채점자가 무엇에 약한지 잰다" --body-file "$TMPDIR/pr-body.md"
```
PR 본문은 `.github/PULL_REQUEST_TEMPLATE.md` 를 채워 `$TMPDIR/pr-body.md` 에 먼저 쓴다. **한계 & 트레이드오프** 와 **검토한 대안** 칸이 핵심이다. PR 을 연 뒤 CI 는 기다리지 않는다.
