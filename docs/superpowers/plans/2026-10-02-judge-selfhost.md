# 채점 모델 비교 실험 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> 이 저장소에서는 실행을 idle 세션에 나눠 맡긴다. 구현 세션과 검토 세션은 다른 세션으로 둔다.

**Goal:** 지금 Cloudflare 에서 쓰는 채점 모델(M1)과 코랩에서 돌리는 공개 모델 셋(M2, M3, M4)을 사람이 다시 매긴 1~5 충실성 라벨 44건과 대조해, 스펙이 고정한 판정 규칙대로 결과를 낸다.

**Architecture:** 채점표, 공통 지시문, 점수 읽기, 대조 수치를 `tools/judge5.py` 한 파일에 모은다. 사람 라벨링 화면, 시험지 내보내기, Cloudflare 채점, 대조 보고가 모두 이 파일을 쓴다. 코랩 노트북은 시험지 파일에 이미 완성된 지시문(messages)을 받아 원문만 저장한다. 점수는 로컬에서 `judge5.parse_result` 하나로 읽는다. 따라서 지시문과 점수 읽기 규칙이 두 벌로 갈라질 자리가 없다.

**Tech Stack:** Python 3.13 표준 라이브러리(도구), `app.cf`(Cloudflare 호출), 코랩의 transformers, bitsandbytes 4비트, Google Drive.

**설계 문서:** [`docs/superpowers/specs/2026-10-02-judge-selfhost-design.md`](../specs/2026-10-02-judge-selfhost-design.md). 아래에서 "스펙 §n" 은 이 문서의 절이다.

## Global Constraints

- 서비스 코드(`ai-service/app/`)는 고치지 않는다. 새 도구는 `ai-service/tools/` 에 둔다. `app` 은 `tools` 를 import 하지 않는다(`tools.import_boundary_check` 가 CI 에서 막는다).
- 테스트는 이 저장소 관례대로 `python -m tools.<이름>_check` 다(pytest 아님). 모든 명령은 `ai-service/` 에서 `.venv/bin/python` 으로 돌린다.
- 채점표 다섯 줄, 공통 지시문, 모델 이름은 `tools/judge5.py` 에만 적는다. 다른 파일은 import 하거나 시험지 파일에서 읽는다.
- **순서 규칙(스펙 §4-1):** 사람의 새 라벨 44건이 커밋되기 전에는 44건 중 어떤 사례도 모델에 넣지 않는다. 그 전의 동작 확인은 코드 안의 가짜 사례(`--smoke`)로만 한다.
- 옛 라벨 파일 `testdata/judge_labels.json` 은 고치지 않는다.
- 최대 출력 토큰 512, 탐욕적 디코딩(Cloudflare 는 `temperature = 0`).
- "못 읽음" 은 0점이나 틀림으로 세지 않는다. 읽지 못한 이유(`missing`, `out_of_range`, `conflict`)도 하나로 뭉개지 않는다.
- 문서, 주석, 커밋 메시지에 em dash 를 쓰지 않는다. 커밋 메시지는 `<타입>: <한국어 요약>` 이고 끝에 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` 를 붙인다.
- 파이썬 코드에는 왜 그렇게 썼는지(문법, 관용구 포함) 짧은 주석을 단다. 개발자가 파이썬에 약하다.

## 파일 구조

| 파일 | 새로/수정 | 책임 | 태스크 |
|---|---|---|---|
| `AGENTS.md` (작업 규칙 7번) | 수정 | 채점 모델 추론을 실험 용도로 연다 | 1 |
| `ai-service/tools/judge5.py` | 새로 | 채점표, 공통 지시문, 점수 읽기, 대조 수치 | 1 |
| `ai-service/tools/judge5_check.py` | 새로 | 위 모듈과 라벨 서버, 내보내기, 노트북의 자체 점검(CI) | 1, 2, 4, 5 |
| `.github/workflows/ci.yml` | 수정 | `tools.judge5_check` 등록 | 1 |
| `ai-service/tools/judge_label_server.py` | 수정 | 다섯 칸 모드 | 2 |
| `ai-service/tools/judge5_export.py` | 새로 | 빈 새 라벨 파일 만들기, 시험지 파일 만들기 | 2, 4 |
| `ai-service/testdata/judge_labels_5pt.json` | 새로 | 새 라벨 | 2(빈 파일), 3(채움) |
| `ai-service/tools/judge5_cloudflare.py` | 새로 | M1 채점 | 4 |
| `ai-service/notebooks/judge5_colab.ipynb` | 새로 | M2, M3, M4 채점 | 5 |
| `ai-service/tools/judge5_report.py` | 새로 | 스펙 §4 의 수치와 판정 | 6 |
| `ai-service/testdata/judge5/` | 새로 | 시험지, 결과, 보고 | 7 |
| `docs/superpowers/plans/2026-10-02-judge-selfhost-results.md` | 새로 | 결과 문서 | 7 |

시험지 파일 한 줄의 모양(태스크 4가 만들고 태스크 4, 5, 6이 읽는다):

```json
{"case_id": "03e71eb80d67", "messages": [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]}
```

결과 파일 한 줄의 모양(태스크 4, 5가 쓰고 태스크 6이 읽는다). 파일 이름은 `results/{모델}_run{실행 번호}.jsonl`:

```json
{"case_id": "...", "model": "M3", "repo": "Unbabel/M-Prometheus-14B", "revision": "커밋 해시 또는 cloudflare", "run": 1, "output": "Feedback: ... [RESULT] 5", "finish": "stop", "cases_sha256": "..."}
```

모델을 돌리지 못했을 때는 `results/{모델}_skipped.json` 하나를 쓴다: `{"model": "M2", "reason": "..."}`.

---

### Task 1: 공통 채점 모듈과 규칙 7번

**Files:**
- Modify: `AGENTS.md:255-261`
- Create: `ai-service/tools/judge5.py`
- Create: `ai-service/tools/judge5_check.py`
- Modify: `.github/workflows/ci.yml` (`python -m tools.import_boundary_check` 다음 줄)

**Interfaces:**
- Produces (뒤 태스크가 쓰는 이름):
  - `SCALE: tuple[int, ...] = (1, 2, 3, 4, 5)`
  - `MODELS: dict[str, str]` (키 `"M1"`~`"M4"`)
  - `MAX_NEW_TOKENS: int = 512`
  - `CRITERIA: str`, `RUBRIC: dict[int, str]`
  - `build_messages(question: str, sources: list[dict], answer: str) -> list[dict[str, str]]` (sources 원소는 `filename`, `content` 키를 가진 dict)
  - `parse_result(text: str | None) -> tuple[int | None, str]` (상태는 `"ok"`, `"missing"`, `"out_of_range"`, `"conflict"`)
  - `Summary`, `summarize(pairs: list[tuple[int, int | None]]) -> Summary`
  - `Comparison`, `compare(human: dict[str, int], a: dict[str, int | None], b: dict[str, int | None]) -> Comparison`
  - `sign_test_p(k: int, n: int) -> float`
  - `linear_weighted_kappa(pairs: list[tuple[int, int]]) -> float | None`
  - `pick_best(summaries: dict[str, Summary]) -> str | None`
  - `replacement_failures(cand: Summary, m1: Summary, vs_m1: Comparison) -> list[str]`
  - `to_three(v: int) -> float`
  - `sha256_file(path: str | Path) -> str`

- [ ] **Step 1: 워크트리를 만든다**

```bash
cd /Users/cheonjamin/projects/AllDap
git fetch origin
git worktree add ../AllDap-judge -b feat/judge-selfhost origin/main
cd ../AllDap-judge/ai-service
ln -s ../../AllDap/ai-service/.venv .venv   # 가상환경은 메인 폴더 것을 같이 쓴다
ln -s ../../AllDap/ai-service/.env .env      # Cloudflare 키를 읽으려면 필요하다(태스크 4)
git status --short   # 아무것도 안 나와야 한다(.venv, .env 링크는 공통 exclude 에 이미 있다)
.venv/bin/python -m tools.import_boundary_check
```

Expected: `git status --short` 출력 없음. 마지막 명령이 통과 메시지로 끝난다. `.env` 링크가 `git status` 에 보이면 `printf 'ai-service/.env\n' >> "$(git rev-parse --git-common-dir)/info/exclude"` 를 한 번 실행한다.

- [ ] **Step 2: 실패하는 점검을 쓴다** (`ai-service/tools/judge5_check.py`)

```python
"""채점 모델 비교 실험(2026-10-02)의 자체 점검. DB 도 외부 API 도 쓰지 않는다. CI 에서 돈다.

실행:  cd ai-service && .venv/bin/python -m tools.judge5_check

왜 이 검사가 있나
─────────────────────────────────────────────────────────────────────────────
이 실험의 결론은 "어느 채점 모델이 사람에 더 가까운가, 어느 방향으로 틀리는가" 다.
점수를 읽는 규칙, 후함과 박함의 부호, 부호 검정의 p 값 중 하나만 틀려도 결론이 바뀐다.
숫자는 그럴듯하게 나오므로 눈으로는 잡히지 않는다. 그래서 검사로 고정한다.
"""
from __future__ import annotations

from .judge5 import (
    CRITERIA, RUBRIC, SCALE,
    build_messages, compare, linear_weighted_kappa, parse_result, pick_best,
    replacement_failures, sign_test_p, summarize, to_three,
)

_SOURCES = [
    {"chunk_id": 1, "filename": "a.md", "content": "연차는 15일이다."},
    {"chunk_id": 2, "filename": "b.md", "content": "재택은 주 1회다."},
]


def check_parse_reads_single_result() -> None:
    assert parse_result("Feedback: 근거와 같다. [RESULT] 5") == (5, "ok")
    # 괄호를 씌우거나 공백이 없어도 읽는다. 모델마다 버릇이 다르다.
    assert parse_result("Feedback: x [RESULT](4)") == (4, "ok")


def check_parse_keeps_failure_reasons_apart() -> None:
    """못 읽은 이유 셋을 하나로 뭉개지 않는다(이 저장소가 낸 버그 부류)."""
    assert parse_result("Feedback: 점수를 안 썼다") == (None, "missing")
    assert parse_result("") == (None, "missing")
    assert parse_result(None) == (None, "missing")
    assert parse_result("[RESULT] 7") == (None, "out_of_range")
    assert parse_result("[RESULT] 0") == (None, "out_of_range")
    assert parse_result("[RESULT] 3 ... [RESULT] 5") == (None, "conflict")
    # 같은 점수를 두 번 쓴 것은 모순이 아니다.
    assert parse_result("[RESULT] 4 [RESULT] 4") == (4, "ok")


def check_messages_carry_every_source_in_order() -> None:
    msgs = build_messages("연차는?", _SOURCES, "15일입니다.")
    assert [m["role"] for m in msgs] == ["system", "user"]
    user = msgs[1]["content"]
    # 근거 순서가 채점을 바꾼다는 것이 실측돼 있다(2026-09-18). 순서를 지키는지 본다.
    assert user.index("[근거 1] (출처: a.md)") < user.index("[근거 2] (출처: b.md)")
    assert "연차는 15일이다." in user and "재택은 주 1회다." in user
    assert "15일입니다." in user and "연차는?" in user


def check_messages_carry_the_whole_rubric() -> None:
    user = build_messages("q", _SOURCES, "a")[1]["content"]
    assert CRITERIA in user
    for k in SCALE:
        assert f"Score {k}: {RUBRIC[k]}" in user


def check_messages_do_not_leak_reference_answer() -> None:
    """스펙 §3-2: 공통 지시문에 기대 답변을 넣지 않는다. 자리 자체가 없어야 한다."""
    user = build_messages("q", _SOURCES, "a")[1]["content"]
    assert "Reference Answer" not in user
    assert "기대 답변" not in user


def check_summary_direction() -> None:
    """🔴 후함 = 모델이 사람보다 높다. 부호가 뒤집히면 결론이 정반대가 된다."""
    s = summarize([(3, 5), (5, 4), (4, 4), (2, None)])
    assert (s.generous, s.harsh) == (1, 1)
    assert (s.total, s.unread, s.exact, s.within1) == (4, 1, 1, 2)
    assert s.mean_distance == (2 + 1 + 0) / 3
    assert s.confusion[(3, 5)] == 1 and s.confusion[(5, 4)] == 1


def check_summary_all_unread_has_no_mean() -> None:
    """전부 못 읽었으면 평균 거리는 0 이 아니라 없음이다."""
    assert summarize([(5, None)]).mean_distance is None


def check_sign_test_known_values() -> None:
    assert sign_test_p(0, 0) == 1.0
    assert abs(sign_test_p(0, 10) - 2 / 1024) < 1e-12
    assert abs(sign_test_p(10, 10) - 2 / 1024) < 1e-12
    assert abs(sign_test_p(1, 5) - 2 * (1 + 5) / 32) < 1e-12
    assert sign_test_p(3, 6) == 1.0


def check_compare_excludes_unread_and_ties() -> None:
    human = {"a": 5, "b": 5, "c": 3, "d": 4}
    x = {"a": 5, "b": 4, "c": None, "d": 4}
    y = {"a": 4, "b": 4, "c": 3, "d": 4}
    c = compare(human, x, y)
    assert (c.excluded, c.a_closer, c.b_closer, c.ties) == (1, 1, 0, 2)
    assert c.verdict("x", "y") == "구별되지 않음"


def check_compare_verdict_names_the_closer_model() -> None:
    human = {str(i): 5 for i in range(10)}
    good = {str(i): 5 for i in range(10)}
    bad = {str(i): 1 for i in range(10)}
    assert compare(human, good, bad).verdict("좋은", "나쁜") == "좋은 가 사람에 더 가깝다"
    assert compare(human, bad, good).verdict("나쁜", "좋은") == "좋은 가 사람에 더 가깝다"


def check_kappa() -> None:
    # 부동소수 계산이라 정확히 1.0 이 아닐 수 있다. 아주 작은 오차는 허용한다.
    assert abs(linear_weighted_kappa([(1, 1), (3, 3), (5, 5)]) - 1.0) < 1e-12
    # 한 칸에만 몰리면 정의되지 않는다. 0 으로 뭉개지 않고 없음으로 돌려준다.
    assert linear_weighted_kappa([(5, 5), (5, 5)]) is None
    assert linear_weighted_kappa([]) is None


def check_to_three_follows_old_label_definition() -> None:
    """근거에 없는 주장이 하나라도 있으면 1.0 이 아니다(옛 라벨 정의)."""
    assert [to_three(v) for v in SCALE] == [0.0, 0.5, 0.5, 0.5, 1.0]


def check_pick_best_tie_breaks() -> None:
    a = summarize([(5, 5), (5, 4), (5, 1)])        # 거리 1 이하 2건, 평균 5/3
    b = summarize([(5, 5), (5, 4), (5, 1)])        # a 와 모든 값이 같다
    c = summarize([(5, 5), (5, 4), (5, 3)])        # 거리 1 이하 2건, 평균 1
    assert pick_best({"M2": a, "M3": c}) == "M3"   # 평균 거리가 작은 쪽
    assert pick_best({"M3": a, "M2": b}) == "M2"   # 모든 값이 같으면 이름 순서
    assert pick_best({}) is None


def check_replacement_rule() -> None:
    m1 = summarize([(5, 5), (5, 5), (4, 4)])
    good = summarize([(5, 5), (5, 5), (4, 4)])
    unread = summarize([(5, 5), (5, None), (4, 4)])
    human = {"a": 5, "b": 5, "c": 4}
    tie = compare(human, {"a": 5, "b": 5, "c": 4}, {"a": 5, "b": 5, "c": 4})
    assert replacement_failures(good, m1, tie) == []
    assert any("못 읽음" in r for r in replacement_failures(unread, m1, tie))


CHECKS = [
    check_parse_reads_single_result,
    check_parse_keeps_failure_reasons_apart,
    check_messages_carry_every_source_in_order,
    check_messages_carry_the_whole_rubric,
    check_messages_do_not_leak_reference_answer,
    check_summary_direction,
    check_summary_all_unread_has_no_mean,
    check_sign_test_known_values,
    check_compare_excludes_unread_and_ties,
    check_compare_verdict_names_the_closer_model,
    check_kappa,
    check_to_three_follows_old_label_definition,
    check_pick_best_tie_breaks,
    check_replacement_rule,
]


def main() -> None:
    for fn in CHECKS:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(CHECKS)}가지 전부 통과.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 실패하는지 본다**

Run: `.venv/bin/python -m tools.judge5_check`
Expected: `ModuleNotFoundError: No module named 'tools.judge5'`

- [ ] **Step 4: 모듈을 쓴다** (`ai-service/tools/judge5.py`)

```python
"""채점 모델 비교 실험(2026-10-02)의 공통 채점 모듈.

설계: docs/superpowers/specs/2026-10-02-judge-selfhost-design.md

이 파일 하나가 쥐고 있는 것
─────────────────────────────────────────────────────────────────────────────
1. 채점표(1~5 각 점수의 뜻). 사람 라벨링 화면과 네 모델의 지시문이 모두 여기서 읽는다.
2. 공통 지시문. 네 모델이 글자 하나까지 같은 입력을 받게 하려고 한 곳에서만 만든다.
3. 모델 출력에서 점수를 읽는 함수. 코랩 노트북은 원문만 저장하고 점수는 여기서 읽는다.
   읽는 규칙이 노트북과 로컬에 두 벌 있으면 언젠가 갈라진다.
4. 대조 수치(거리, 후함 박함, 부호 검정, 교체 후보 기준). 스펙 §4 를 그대로 옮겼다.

외부 API 도 DB 도 부르지 않는다. 그래서 CI 의 tools.judge5_check 로 전부 검사한다.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path

SCALE: tuple[int, ...] = (1, 2, 3, 4, 5)

# 스펙 §2 의 네 모델. 결과 파일과 보고서가 이 키(M1~M4)로 모델을 부른다.
MODELS: dict[str, str] = {
    "M1": "@cf/mistralai/mistral-small-3.1-24b-instruct",
    "M2": "mistralai/Mistral-Small-3.1-24B-Instruct-2503",
    "M3": "Unbabel/M-Prometheus-14B",
    "M4": "Qwen/Qwen2.5-14B-Instruct",
}

# 이유를 먼저 쓰고 끝에 점수를 쓰는 양식이라 짧으면 점수가 잘린다(스펙 §3-3).
MAX_NEW_TOKENS = 512

CRITERIA = (
    "충실성: 답변의 모든 주장이 근거에 실제로 적혀 있는가. "
    "답변이 세상의 상식에 맞는지는 보지 않는다. 사실이더라도 근거에 없으면 점수를 낮춘다."
)

# 스펙 §3-1 의 채점표. dict 의 키가 점수, 값이 그 점수의 뜻이다.
RUBRIC: dict[int, str] = {
    1: "답변이 근거와 관계없는 내용을 지어냈거나, 근거와 반대되는 내용을 말한다",
    2: "답변의 주장 대부분이 근거에 없다",
    3: "근거에 있는 주장과 근거에 없는 주장이 비슷한 정도로 섞여 있다",
    4: "답변의 핵심 답은 근거와 일치한다. 다만 근거에 없는 사소한 주장이 하나 있다",
    5: "답변의 모든 주장이 근거에 적혀 있다",
}

# M3(M-Prometheus)가 학습한 절대 평가 양식이다(Prometheus 2 의 기대 답변 없는 판).
# 틀은 영어 그대로 두고 내용(근거, 질문, 답변, 채점표)만 한국어로 넣는다(스펙 §3-2).
SYSTEM_PROMPT = (
    "You are a fair judge assistant tasked with providing clear, objective feedback based on "
    "a specific criteria, ensuring each assessment reflects the absolute standards set for performance."
)

_USER_TEMPLATE = """###Task Description:
An instruction (might include an Input inside it), a response to evaluate, and a score rubric representing a evaluation criteria are given.
1. Write a detailed feedback that assess the quality of the response strictly based on the given score rubric, not evaluating in general.
2. After writing a feedback, write a score that is an integer between 1 and 5. You should refer to the score rubric.
3. The output format should look as follows: "Feedback: (write a feedback for criteria) [RESULT] (an integer number between 1 and 5)"
4. Please do not generate any other opening, closing, and explanations.

###The instruction to evaluate:
{instruction}

###Response to evaluate:
{response}

###Score Rubrics:
[{criteria}]
Score 1: {s1}
Score 2: {s2}
Score 3: {s3}
Score 4: {s4}
Score 5: {s5}

###Feedback: """


def build_instruction(question: str, sources: list[dict]) -> str:
    """채점 대상이 받은 과제를 다시 쓴다: 근거 전문과 질문.

    근거 머리표 `[근거 i] (출처: 파일명)` 는 생성 모델이 받은 모양
    (`app/generator.py` 의 `_build_context`)과 같게 둔다. 채점 모델은 생성 모델이 본 것과
    같은 것을 봐야 한다(`app/judge.py` 의 2026-08-02 버그 주석).
    """
    # enumerate(xs, 1) 은 번호를 1 부터 매긴다. "\n\n".join 은 블록 사이에 빈 줄을 하나 둔다.
    blocks = "\n\n".join(
        f"[근거 {i}] (출처: {s['filename']})\n{s['content']}" for i, s in enumerate(sources, 1)
    )
    return f"아래 근거만 사용해서 질문에 답하세요.\n\n<근거>\n{blocks}\n</근거>\n\n<질문>\n{question}"


def build_messages(question: str, sources: list[dict], answer: str) -> list[dict[str, str]]:
    """네 모델에 똑같이 줄 대화(messages)를 만든다. 기대 답변은 받지도 않는다."""
    # **{...} 는 dict 를 키워드 인자로 펼친다. s1=RUBRIC[1], ..., s5=RUBRIC[5] 와 같다.
    user = _USER_TEMPLATE.format(
        instruction=build_instruction(question, sources),
        response=answer,
        criteria=CRITERIA,
        **{f"s{k}": v for k, v in RUBRIC.items()},
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


# [RESULT] 뒤의 정수. 괄호를 씌우는 모델이 있어 \(? 로 선택적으로 받는다.
_RESULT_RE = re.compile(r"\[RESULT\]\s*\(?\s*(\d+)")


def parse_result(text: str | None) -> tuple[int | None, str]:
    """모델 출력에서 점수를 읽는다. (점수, 상태) 를 돌려준다.

    상태는 넷이다. 앞의 하나만 점수가 있고 나머지 셋은 서로 다른 실패다.
      ok            점수 하나를 읽었다
      missing       [RESULT] 가 없다(출력이 잘렸거나 양식을 안 지켰다)
      out_of_range  1~5 밖의 수를 썼다
      conflict      [RESULT] 를 여러 번 쓰고 값이 서로 다르다
    셋을 "못 읽음" 하나로 뭉개지 않는 이유: 원인이 다르면 고칠 곳도 다르다.
    """
    if not text:
        return None, "missing"
    found = [int(x) for x in _RESULT_RE.findall(text)]
    if not found:
        return None, "missing"
    if any(v not in SCALE for v in found):
        return None, "out_of_range"
    if len(set(found)) > 1:
        return None, "conflict"
    return found[0], "ok"


@dataclass(frozen=True)  # frozen=True: 만든 뒤 값을 못 바꾼다. 집계 결과가 도중에 변하지 않게 한다.
class Summary:
    total: int
    unread: int
    exact: int
    within1: int
    mean_distance: float | None   # 읽은 사례가 0건이면 None (0.0 이 아니다)
    generous: int                 # 모델 점수 > 사람 점수
    harsh: int                    # 모델 점수 < 사람 점수
    confusion: dict[tuple[int, int], int]  # 키는 (사람, 모델) 순서


def summarize(pairs: list[tuple[int, int | None]]) -> Summary:
    """(사람 점수, 모델 점수 또는 None) 목록을 스펙 §4-2 의 수치로 정리한다."""
    read = [(h, m) for h, m in pairs if m is not None]
    dists = [abs(h - m) for h, m in read]
    conf = {(h, m): 0 for h in SCALE for m in SCALE}
    for h, m in read:
        conf[(h, m)] += 1
    return Summary(
        total=len(pairs),
        unread=len(pairs) - len(read),
        exact=sum(1 for d in dists if d == 0),
        within1=sum(1 for d in dists if d <= 1),
        mean_distance=(sum(dists) / len(dists)) if dists else None,
        generous=sum(1 for h, m in read if m > h),
        harsh=sum(1 for h, m in read if m < h),
        confusion=conf,
    )


def sign_test_p(k: int, n: int) -> float:
    """양측 부호 검정의 정확한 p 값. n 번 중 한쪽이 k 번 이겼을 때.

    공정한 동전을 n 번 던져 k 번 이하(또는 n-k 번 이상)가 나올 확률의 두 배다.
    math.comb(n, i) 는 n 개 중 i 개를 고르는 경우의 수다.
    """
    if n == 0:
        return 1.0
    tail = min(k, n - k)
    p = 2 * sum(math.comb(n, i) for i in range(tail + 1)) / 2**n
    return min(1.0, p)


@dataclass(frozen=True)
class Comparison:
    excluded: int   # 둘 중 하나라도 못 읽어 뺀 사례 수
    a_closer: int
    b_closer: int
    ties: int
    p_value: float

    def verdict(self, a: str, b: str) -> str:
        """스펙 §4-3 의 판정 문장. p < 0.05 일 때만 더 가까운 쪽을 말한다."""
        if self.p_value < 0.05 and self.a_closer != self.b_closer:
            closer = a if self.a_closer > self.b_closer else b
            return f"{closer} 가 사람에 더 가깝다"
        return "구별되지 않음"


def compare(human: dict[str, int], a: dict[str, int | None], b: dict[str, int | None]) -> Comparison:
    """두 모델 중 사례마다 누가 사람에 더 가까운지 세고 부호 검정을 한다(스펙 §4-3)."""
    excluded = a_closer = b_closer = ties = 0
    for cid, h in human.items():
        x, y = a.get(cid), b.get(cid)
        if x is None or y is None:
            excluded += 1
            continue
        dx, dy = abs(x - h), abs(y - h)
        if dx < dy:
            a_closer += 1
        elif dy < dx:
            b_closer += 1
        else:
            ties += 1
    return Comparison(excluded, a_closer, b_closer, ties, sign_test_p(a_closer, a_closer + b_closer))


def linear_weighted_kappa(pairs: list[tuple[int, int]]) -> float | None:
    """선형 가중 카파(보조 지표). 정의되지 않으면 None.

    한 칸에 사례가 몰리면 우연 일치가 1 에 가까워져 분모가 0 이 된다. 그때 0.0 을 돌려주면
    "일치하지 않는다" 로 읽히므로, 계산할 수 없다는 뜻으로 None 을 돌려준다.
    """
    n = len(pairs)
    if n == 0:
        return None
    k = len(SCALE)
    idx = {v: i for i, v in enumerate(SCALE)}

    def w(a: int, b: int) -> float:
        return 1.0 - abs(a - b) / (k - 1)

    obs = sum(w(idx[h], idx[m]) for h, m in pairs) / n
    hc = [sum(1 for h, _ in pairs if h == v) / n for v in SCALE]
    mc = [sum(1 for _, m in pairs if m == v) / n for v in SCALE]
    exp = sum(w(a, b) * hc[a] * mc[b] for a in range(k) for b in range(k))
    if abs(1.0 - exp) < 1e-12:
        return None
    return (obs - exp) / (1.0 - exp)


def pick_best(summaries: dict[str, Summary]) -> str | None:
    """M2~M4 중 가장 나은 후보(스펙 §4-3). 거리 1 이하가 많은 순, 같으면 평균 거리가 작은 순,
    그래도 같으면 못 읽음이 적은 순, 그래도 같으면 이름 순서."""
    if not summaries:
        return None

    def key(name: str) -> tuple:
        s = summaries[name]
        mean = s.mean_distance if s.mean_distance is not None else math.inf
        # sorted 는 작은 값이 앞이므로 "많을수록 좋은" 값에는 음수를 붙인다.
        return (-s.within1, mean, s.unread, name)

    return sorted(summaries, key=key)[0]


def replacement_failures(cand: Summary, m1: Summary, vs_m1: Comparison) -> list[str]:
    """교체 후보 기준(스펙 §4-4)에서 어긋난 항목을 돌려준다. 빈 목록이면 교체 후보다.

    vs_m1 은 compare(사람, 후보, M1) 의 결과여야 한다(a 가 후보, b 가 M1).
    """
    out = []
    if cand.within1 < m1.within1:
        out.append(f"거리 1 이하 사례가 M1 보다 적다({cand.within1} < {m1.within1})")
    if cand.unread > 0:
        out.append(f"못 읽음 사례가 {cand.unread}건 있다")
    if vs_m1.p_value < 0.05 and vs_m1.b_closer > vs_m1.a_closer:
        out.append(f"부호 검정에서 M1 이 사람에 더 가깝다(p = {vs_m1.p_value:.4f})")
    return out


def to_three(v: int) -> float:
    """새 라벨을 옛 세 칸으로 옮긴다(스펙 §4-6). 5 만 1.0, 1 만 0.0, 나머지는 0.5."""
    return 1.0 if v == 5 else 0.0 if v == 1 else 0.5


def sha256_file(path: str | Path) -> str:
    """파일 내용의 SHA-256. 코랩과 로컬이 같은 시험지를 읽었는지 확인하는 데 쓴다."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
```

- [ ] **Step 5: 통과하는지 본다**

Run: `.venv/bin/python -m tools.judge5_check`
Expected: 14줄의 `✅` 와 `14가지 전부 통과.`

- [ ] **Step 6: 변이 시험을 한다** (검사가 실제로 잡는지)

`summarize` 의 `generous=sum(1 for h, m in read if m > h)` 를 `m < h` 로 잠깐 바꾸고 점검을 돌린다. `check_summary_direction` 에서 `AssertionError` 가 나야 한다. 확인하면 되돌린다. `parse_result` 의 `conflict` 분기를 지워도 `check_parse_keeps_failure_reasons_apart` 가 실패해야 한다. 확인하면 되돌린다.

- [ ] **Step 7: CI 에 등록한다** (`.github/workflows/ci.yml`)

`python -m tools.import_boundary_check` 줄 바로 다음에 같은 들여쓰기로 한 줄을 더한다.

```yaml
          python -m tools.judge5_check
```

그리고 같은 파일의 주석 목록(`✅ tools.import_boundary_check ...` 문단) 다음에 한 줄을 더한다.

```yaml
      #    ✅ tools.judge5_check 는 채점 모델 비교 실험의 순수 함수(점수 읽기, 대조 수치, 부호 검정)만 본다.
```

- [ ] **Step 8: 작업 규칙 7번을 고친다** (`AGENTS.md` 255~261행을 아래로 바꾼다)

```markdown
7. **범위를 넓히지 말 것 (2026-09-16 에 <리랭커 추론에 한해> 열었고, 2026-10-02 에 <채점 모델 추론을 실험 용도로> 열었다).**
   ⬜ **여전히 범위 밖:** 생성 모델(llama-3.3-70b) 셀프호스팅 · 경량화, 임베딩 모델 셀프호스팅,
   온디바이스 추론 일반. 원래 기각 사유가 그대로 유효하다(t3.micro 1GB 로 불가능하다).
   ✅ **연 것은 둘이다.**
   ① 리랭커(`bge-reranker-base`, 2억 7천만 파라미터) 추론을 로컬에서 돌리고 양자화하는 것.
   근거는 `docs/superpowers/specs/2026-09-16-reranker-local-quantization-design.md` 와
   `docs/decisions.md` 2026-09-16 항목.
   ② 채점 모델의 추론을 **실험 용도로** 직접 돌리는 것(로컬 또는 코랩). 서비스의 채점은
   Cloudflare 를 그대로 쓴다. 근거는 `docs/superpowers/specs/2026-10-02-judge-selfhost-design.md`.
```

`AGENTS.md` 620행 근처의 "알려진 한계" 한 줄도 맞춘다.

```markdown
- 임베딩·답변 생성·채점은 외부 API(Cloudflare)다. 직접 돌리는 것은 리랭커 추론과 실험용 채점 모델 추론뿐이다(작업 규칙 7번).
```

- [ ] **Step 9: 커밋한다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge
git add AGENTS.md .github/workflows/ci.yml ai-service/tools/judge5.py ai-service/tools/judge5_check.py
git commit -m "feat: 채점 모델 비교 실험의 공통 채점 모듈과 점검을 더하고 작업 규칙 7번을 연다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: 다섯 칸 라벨링 화면과 빈 새 라벨 파일

**Files:**
- Modify: `ai-service/tools/judge_label_server.py`
- Create: `ai-service/tools/judge5_export.py` (이 태스크에서는 `labels` 하위 명령만)
- Create: `ai-service/testdata/judge_labels_5pt.json`
- Modify: `ai-service/tools/judge5_check.py`

**Interfaces:**
- Consumes: `judge5.SCALE`, `judge5.CRITERIA`, `judge5.RUBRIC`
- Produces:
  - `judge5_export.OLD_LABELS = "testdata/judge_labels.json"`, `judge5_export.NEW_LABELS = "testdata/judge_labels_5pt.json"` (둘 다 `ai-service/` 기준 상대 경로를 `ROOT` 로 절대 경로화한 `Path`)
  - `judge5_export.make_label_file(old: dict) -> dict`
  - 새 라벨 파일 모양: `{"_readme": str, "scale": 5, "rubric": {"criteria": str, "levels": {"1": str, ..., "5": str}}, "source_file": "testdata/judge_labels.json", "cases": [{"case_id", "question", "generated_answer", "sources", "label", "note"}]}`
  - `judge_label_server.apply_label` 이 `data["scale"] == 5` 이면 1~5 정수만 받는다

- [ ] **Step 1: 실패하는 점검을 더한다** (`ai-service/tools/judge5_check.py`)

import 줄 아래에 더한다.

```python
from .judge5_export import make_label_file
from .judge_label_server import LabelRejected, apply_label

_OLD = {
    "_readme": "옛 안내",
    "run_ids": [11],
    "cases": [
        {"case_id": "bb", "question_id": "2", "question": "q2", "ground_truth": "정답2",
         "generated_answer": "a2", "sources": _SOURCES, "seen_in_runs": [11], "label": 1, "note": "옛 메모"},
        {"case_id": "aa", "question_id": "1", "question": "q1", "ground_truth": "정답1",
         "generated_answer": "a1", "sources": _SOURCES, "seen_in_runs": [11], "label": 0.5, "note": ""},
    ],
}


def check_new_label_file_hides_old_label_and_reference() -> None:
    """🔴 새 라벨은 블라인드로 매긴다. 옛 라벨, 옛 메모, 기대 답변이 파일에 없어야 화면에도 못 샌다."""
    new = make_label_file(_OLD)
    for c in new["cases"]:
        assert c["label"] is None and c["note"] == ""
        assert "ground_truth" not in c
        assert "seen_in_runs" not in c
    assert "옛 메모" not in str(new)
    assert "정답1" not in str(new)


def check_new_label_file_keeps_cases_and_sorts_by_id() -> None:
    new = make_label_file(_OLD)
    assert [c["case_id"] for c in new["cases"]] == ["aa", "bb"]
    assert new["cases"][0]["sources"] == _SOURCES
    assert new["scale"] == 5


def check_new_label_file_rubric_is_the_model_rubric() -> None:
    """사람이 보는 채점표와 모델이 받는 채점표가 같은 글자여야 한다."""
    new = make_label_file(_OLD)
    assert new["rubric"]["criteria"] == CRITERIA
    assert new["rubric"]["levels"] == {str(k): v for k, v in RUBRIC.items()}


def check_apply_label_five_point_mode() -> None:
    data = make_label_file(_OLD)
    out = apply_label(data, "aa", 4, "")
    assert [c["label"] for c in out["cases"]] == [4, None]
    for bad in (0, 0.5, 6):
        try:
            apply_label(data, "aa", bad, "")
        except LabelRejected:
            continue
        raise AssertionError(f"{bad} 를 받으면 안 된다")


def check_apply_label_old_mode_unchanged() -> None:
    """scale 이 없는 옛 파일은 예전처럼 0, 0.5, 1 만 받는다."""
    out = apply_label(_OLD, "aa", 0.5, "")
    assert out["cases"][1]["label"] == 0.5
    try:
        apply_label(_OLD, "aa", 4, "")
    except LabelRejected:
        return
    raise AssertionError("옛 파일에 4 를 받으면 안 된다")
```

`CHECKS` 목록 끝에 다섯 이름을 더한다.

```python
    check_new_label_file_hides_old_label_and_reference,
    check_new_label_file_keeps_cases_and_sorts_by_id,
    check_new_label_file_rubric_is_the_model_rubric,
    check_apply_label_five_point_mode,
    check_apply_label_old_mode_unchanged,
```

- [ ] **Step 2: 실패하는지 본다**

Run: `.venv/bin/python -m tools.judge5_check`
Expected: `ModuleNotFoundError: No module named 'tools.judge5_export'`

- [ ] **Step 3: 내보내기 도구의 `labels` 를 쓴다** (`ai-service/tools/judge5_export.py`)

```python
"""채점 모델 비교 실험(2026-10-02)의 파일 만들기.

실행:
    cd ai-service
    .venv/bin/python -m tools.judge5_export labels   # 빈 새 라벨 파일(1~5)을 만든다
    .venv/bin/python -m tools.judge5_export cases    # 시험지 파일을 만든다(태스크 4)

DB 를 쓰지 않는다. 사례 44건은 옛 라벨 파일에 이미 전부 들어 있다(스펙 §1-2).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .judge5 import CRITERIA, RUBRIC

# __file__ 은 ai-service/tools/judge5_export.py 다. 두 번 올라가면 ai-service/ 다.
# 실행 위치와 무관하게 같은 파일을 가리키려고 __file__ 기준으로 잡는다.
ROOT = Path(__file__).resolve().parent.parent
OLD_LABELS = ROOT / "testdata" / "judge_labels.json"
NEW_LABELS = ROOT / "testdata" / "judge_labels_5pt.json"

_README5 = (
    "label 칸에 1~5 정수만 적는다. 화면(python -m tools.judge_label_server --path testdata/judge_labels_5pt.json)으로 "
    "매기는 것을 권한다. 옛 라벨, 기대 답변, 모델 점수는 일부러 들어 있지 않다. 보고 매기면 끌려가 대조가 성립하지 않는다. "
    "기준은 rubric 칸이고, 네 채점 모델이 받는 채점표와 같은 글자다."
)


def make_label_file(old: dict) -> dict:
    """옛 라벨 파일에서 사례만 옮겨 빈 새 라벨 파일을 만든다.

    옮기지 않는 것: label, note(옛 라벨), ground_truth(스펙 §3-2: 충실성은 근거만 본다),
    question_id, seen_in_runs(문항 번호가 단서가 되지 않게).
    """
    cases = [
        {
            "case_id": c["case_id"],
            "question": c["question"],
            "generated_answer": c["generated_answer"],
            "sources": c["sources"],
            "label": None,
            "note": "",
        }
        # sorted(..., key=...) 는 case_id(해시) 순서로 줄 세운다. 옛 파일과 같은 순서다.
        for c in sorted(old["cases"], key=lambda c: c["case_id"])
    ]
    return {
        "_readme": _README5,
        "scale": 5,
        "rubric": {"criteria": CRITERIA, "levels": {str(k): v for k, v in RUBRIC.items()}},
        "source_file": "testdata/judge_labels.json",
        "cases": cases,
    }


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cmd_labels() -> int:
    if NEW_LABELS.exists():
        # 이미 매긴 라벨을 빈 파일로 덮으면 사람이 들인 시간이 사라진다. 그래서 거절만 한다.
        print(f"{NEW_LABELS.relative_to(ROOT)} 가 이미 있습니다. 덮어쓰지 않습니다. 다시 만들려면 파일을 직접 지우세요.")
        return 1
    old = json.loads(OLD_LABELS.read_text(encoding="utf-8"))
    new = make_label_file(old)
    _write_json(NEW_LABELS, new)
    print(f"{NEW_LABELS.relative_to(ROOT)} 에 {len(new['cases'])}건을 비운 채로 썼습니다.")
    print("라벨링: .venv/bin/python -m tools.judge_label_server --path testdata/judge_labels_5pt.json")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="채점 모델 비교 실험의 파일을 만든다")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("labels", help="빈 새 라벨 파일(1~5)을 만든다")
    args = p.parse_args(argv)
    if args.cmd == "labels":
        return cmd_labels()
    return 2


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 라벨 서버의 `apply_label` 을 고친다** (`ai-service/tools/judge_label_server.py`)

import 줄에 더한다.

```python
from .judge5 import SCALE
```

`apply_label` 의 첫 검사를 아래로 바꾼다.

```python
    # 파일에 scale: 5 가 있으면 다섯 칸 라벨 파일이다(tools.judge5_export labels 가 만든다).
    # 없으면 2026-09-25 의 옛 파일이므로 예전 세 칸 규칙을 그대로 쓴다.
    allowed = SCALE if data.get("scale") == 5 else LABELS
    if label is not None and label not in allowed:
        raise LabelRejected(f"라벨은 {', '.join(str(v) for v in allowed)} 중 하나여야 합니다: {label!r}")
```

주의: 파이썬에서 `0.5 in (1, 2, 3, 4, 5)` 는 `False`, `4.0 in (1, 2, 3, 4, 5)` 는 `True` 다. 화면이 보내는 `4` 와 `4.0` 은 둘 다 받고 `0.5` 는 거절한다.

- [ ] **Step 5: 점검이 통과하는지 본다**

Run: `.venv/bin/python -m tools.judge5_check && .venv/bin/python -m tools.judge_agreement_check`
Expected: 둘 다 `전부 통과.` (`judge_agreement_check` 는 옛 세 칸 동작이 그대로인지 본다)

- [ ] **Step 6: 화면에 다섯 칸 모드를 더한다** (`PAGE` 문자열 안)

(가) "기준" 카드의 세 칸 표와 0.5 예시를 `<div id="rule3">` 로 감싸고, 그 아래에 다섯 칸 표 자리를 둔다. 기존 `<table class="rule">...</table>` 부터 `0.5 는 언제 나오나` `<details>` 끝까지를 아래처럼 감싼다.

```html
    <div id="rule3">
      (기존 세 칸 표와 "0.5 는 언제 나오나" details 그대로)
    </div>
    <div id="rule5" hidden>
      <p class="hint" id="criteria5" style="margin:0 0 8px"></p>
      <table class="rule" id="table5"></table>
    </div>
```

(나) "충실성" 카드의 버튼 묶음 `<div class="btns">` 에 `id="btns3"` 를 붙이고, 바로 아래에 빈 묶음을 둔다.

```html
    <div class="btns" id="btns5" hidden></div>
```

(다) 스크립트의 `boot()` 를 아래로 바꾼다. 다섯 칸 파일이면 표와 버튼을 파일의 `rubric` 에서 그린다. 화면에 따로 적지 않는 이유는 모델이 받는 채점표와 글자가 어긋나지 않게 하려는 것이다.

```javascript
let scale = 3;   // 3 = 옛 파일(0, 0.5, 1), 5 = 새 파일(1~5)

async function boot() {
  data = await (await fetch('/api/data')).json();
  $('readme').textContent = data._readme;
  if (data.scale === 5) {
    scale = 5;
    $('rule3').hidden = true;
    $('btns3').hidden = true;
    $('rule5').hidden = false;
    $('btns5').hidden = false;
    $('criteria5').textContent = data.rubric.criteria;
    // 5 부터 1 까지 내림차순으로 그린다. 옛 화면도 1.0 을 맨 위에 두었다.
    for (let v = 5; v >= 1; v--) {
      const tr = document.createElement('tr');
      const a = document.createElement('td'); a.innerHTML = '<strong>' + v + '</strong>';
      const b = document.createElement('td'); b.textContent = data.rubric.levels[String(v)];
      tr.append(a, b);
      $('table5').append(tr);
      const btn = document.createElement('button');
      btn.dataset.v = String(v);
      btn.innerHTML = v + ' <span class="hint">(' + v + ')</span>';
      $('btns5').append(btn);
    }
    const clear = document.createElement('button');
    clear.dataset.v = '';
    clear.innerHTML = '지우기 <span class="hint">(0)</span>';
    $('btns5').append(clear);
  }
  // 버튼은 boot 안에서 만들어지므로 클릭 연결도 boot 안에서 한다(다섯 칸 버튼이 이 시점에 생긴다).
  document.querySelectorAll('[data-v]').forEach(btn => {
    btn.onclick = () => setLabel(btn.dataset.v === '' ? null : parseFloat(btn.dataset.v), true);
  });
  i = firstUnlabeled();
  render();
}
```

(라) 스크립트 아래쪽의 전역 클릭 연결 블록(`document.querySelectorAll('[data-v]').forEach(btn => { btn.onclick = ... });`)은 `boot()` 안으로 옮겼으므로 지운다.

(마) `render()` 의 기대 답변 줄을 바꾼다. 다섯 칸 파일에는 `ground_truth` 가 없다.

```javascript
  $('gt').textContent = c.ground_truth ? '참고로 둔 정답(질문 생성 때 만든 것): ' + c.ground_truth : '';
```

(바) 키보드 처리의 `map` 을 바꾼다.

```javascript
  const map = scale === 5
    ? { '1': 1, '2': 2, '3': 3, '4': 4, '5': 5, '0': null }
    : { '1': 1, '2': 0.5, '3': 0, '0': null };
```

(사) `serve()` 의 마지막 안내 줄을 파일에 따라 바꾼다.

```python
    nxt = ("python -m tools.judge5_export cases" if data.get("scale") == 5
           else "python -m tools.judge_agreement report --reasons")
    print(f"끝나면 Ctrl+C 로 서버를 끄고 `{nxt}` 를 돌리세요.")
```

- [ ] **Step 7: 빈 새 라벨 파일을 만들고 화면을 눈으로 확인한다**

```bash
.venv/bin/python -m tools.judge5_export labels
.venv/bin/python -m tools.judge_label_server --path testdata/judge_labels_5pt.json --no-open --port 8766 &
sleep 1; curl -s localhost:8766/api/data | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['scale'], len(d['cases']), sum(c['label'] is None for c in d['cases']))"
kill %1
```

Expected: `testdata/judge_labels_5pt.json 에 44건을 비운 채로 썼습니다.` 와 `5 44 44`.

브라우저(또는 claude-in-chrome)로 `http://127.0.0.1:8766` 을 열어 확인한다: 다섯 칸 표 다섯 줄, 버튼 1~5 와 지우기, 기대 답변 줄이 비어 있음. 버튼 4 를 한 번 누르고 파일에 `"label": 4` 가 생긴 것을 확인한 뒤 지우기(0)로 되돌린다. 옛 파일(`--path` 없이)도 한 번 열어 세 칸 화면이 그대로인지 본다. 끝나면 `git diff testdata/judge_labels.json` 이 비어 있어야 한다.

- [ ] **Step 8: 커밋한다**

```bash
git add ai-service/tools/judge_label_server.py ai-service/tools/judge5_export.py \
        ai-service/tools/judge5_check.py ai-service/testdata/judge_labels_5pt.json
git commit -m "feat: 라벨링 화면에 1~5 다섯 칸 모드를 더하고 빈 새 라벨 파일을 만든다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push -u origin feat/judge-selfhost
```

---

### Task 3: 사람이 새 라벨 44건을 매긴다 (사용자 작업)

**Files:**
- Modify: `ai-service/testdata/judge_labels_5pt.json`

이 태스크는 사람이 한다. 구현 세션은 안내와 커밋만 한다. 태스크 4~6의 구현은 이 태스크와 동시에 진행해도 된다. 다만 44건을 모델에 넣는 것은 이 태스크의 커밋 뒤다(Global Constraints 의 순서 규칙).

- [ ] **Step 1: 화면을 띄운다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge/ai-service
.venv/bin/python -m tools.judge_label_server --path testdata/judge_labels_5pt.json
```

- [ ] **Step 2: 사용자가 44건을 매긴다**

안내할 것: 근거만 보고 매긴다. 옛 라벨이나 지난번 판단을 떠올리지 않으려고 노력한다(완전히 지울 수는 없으므로 스펙 §8 의 한계로 적어 두었다). 애매한 건은 메모 칸에 이유를 한 줄 적는다.

- [ ] **Step 3: 다 채웠는지 확인하고 커밋한다**

```bash
python3 -c "import json; d=json.load(open('testdata/judge_labels_5pt.json')); print(sum(c['label'] is None for c in d['cases']), sorted({c['label'] for c in d['cases']}))"
```

Expected: 첫 값 `0`, 둘째 값은 1~5 의 부분집합.

```bash
git add ai-service/testdata/judge_labels_5pt.json
git commit -m "feat: 채점 모델 비교 실험의 새 사람 라벨 44건(1~5)을 매긴다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

---

### Task 4: 시험지 파일과 M1 채점 도구

**Files:**
- Modify: `ai-service/tools/judge5_export.py` (`cases` 하위 명령)
- Create: `ai-service/tools/judge5_cloudflare.py`
- Modify: `ai-service/tools/judge5_check.py`

**Interfaces:**
- Consumes: `judge5.build_messages`, `judge5.MODELS`, `judge5.MAX_NEW_TOKENS`, `judge5.sha256_file`, `judge5_export.NEW_LABELS`, `app.cf.run`, `app.cf.text_of`, `app.cf.finish_reason`, `app.cf.neurons_used`
- Produces:
  - `judge5_export.JUDGE5_DIR = ROOT / "testdata" / "judge5"`, `CASES = JUDGE5_DIR / "cases.jsonl"`, `CASES_SHA = JUDGE5_DIR / "cases.sha256"`, `RESULTS_DIR = JUDGE5_DIR / "results"`
  - `judge5_export.make_cases(labels: dict) -> list[dict]` (원소 키는 `case_id`, `messages` 둘뿐)
  - `judge5_export.labels_ready(labels: dict) -> list[str]` (문제 목록. 빈 목록이면 준비됨)
  - `judge5_cloudflare.result_line(case_id: str, model: str, repo: str, revision: str, run: int, output: str, finish: str | None, cases_sha256: str) -> dict`
  - `judge5_cloudflare.done_ids(path: Path) -> set[str]`

- [ ] **Step 1: 실패하는 점검을 더한다** (`ai-service/tools/judge5_check.py`)

import 를 고치고 더한다.

```python
from .judge5_export import labels_ready, make_cases, make_label_file
from .judge5_cloudflare import done_ids, result_line
import json
import tempfile
from pathlib import Path
```

```python
def _filled(labels: dict, v: int = 5) -> dict:
    return dict(labels, cases=[dict(c, label=v) for c in labels["cases"]])


def check_cases_carry_no_label() -> None:
    """🔴 시험지에 사람 라벨이 들어가면 코랩 모델이 정답을 보고 채점한다."""
    cases = make_cases(_filled(make_label_file(_OLD), 3))
    assert [sorted(c) for c in cases] == [["case_id", "messages"]] * 2
    assert all('"label"' not in json.dumps(c, ensure_ascii=False) for c in cases)


def check_cases_use_the_common_messages() -> None:
    labels = _filled(make_label_file(_OLD))
    first = labels["cases"][0]
    assert make_cases(labels)[0]["messages"] == build_messages(
        first["question"], first["sources"], first["generated_answer"])


def check_labels_ready_refuses_incomplete() -> None:
    """라벨이 하나라도 비면 시험지를 만들지 않는다(스펙 §4-1 순서)."""
    assert labels_ready(make_label_file(_OLD))   # 비어 있으면 문제 목록이 나온다
    assert labels_ready(_filled(make_label_file(_OLD))) == []


def check_result_line_shape() -> None:
    line = result_line("aa", "M1", "@cf/x", "cloudflare", 1, "Feedback: [RESULT] 5", "stop", "abc")
    assert sorted(line) == sorted(
        ["case_id", "model", "repo", "revision", "run", "output", "finish", "cases_sha256"])


def check_done_ids_reads_existing_lines() -> None:
    """이어 하기: 이미 쓴 사례는 다시 부르지 않는다(뉴런 절약, 코랩 끊김 대비)."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "M1_run1.jsonl"
        assert done_ids(p) == set()
        p.write_text(json.dumps({"case_id": "aa"}) + "\n" + json.dumps({"case_id": "bb"}) + "\n")
        assert done_ids(p) == {"aa", "bb"}
```

`CHECKS` 끝에 더한다.

```python
    check_cases_carry_no_label,
    check_cases_use_the_common_messages,
    check_labels_ready_refuses_incomplete,
    check_result_line_shape,
    check_done_ids_reads_existing_lines,
```

- [ ] **Step 2: 실패하는지 본다**

Run: `.venv/bin/python -m tools.judge5_check`
Expected: `ImportError: cannot import name 'labels_ready'`

- [ ] **Step 3: `cases` 하위 명령을 쓴다** (`ai-service/tools/judge5_export.py`)

import 를 고친다.

```python
import subprocess

from .judge5 import CRITERIA, RUBRIC, SCALE, build_messages, sha256_file
```

경로 상수 아래에 더한다.

```python
JUDGE5_DIR = ROOT / "testdata" / "judge5"
CASES = JUDGE5_DIR / "cases.jsonl"
CASES_SHA = JUDGE5_DIR / "cases.sha256"
RESULTS_DIR = JUDGE5_DIR / "results"
```

함수를 더한다.

```python
def labels_ready(labels: dict) -> list[str]:
    """새 라벨이 시험지를 만들어도 될 상태인지 본다. 문제를 문장으로 돌려준다."""
    problems = []
    empty = [c["case_id"] for c in labels["cases"] if c["label"] is None]
    if empty:
        problems.append(f"라벨이 빈 사례가 {len(empty)}건 있습니다(예: {empty[0]})")
    bad = [c["case_id"] for c in labels["cases"] if c["label"] is not None and c["label"] not in SCALE]
    if bad:
        problems.append(f"1~5 가 아닌 라벨이 {len(bad)}건 있습니다(예: {bad[0]})")
    return problems


def _committed(path: Path) -> list[str]:
    """파일이 git 에 커밋돼 있고 고친 흔적이 없는지 본다.

    커밋을 요구하는 이유: 모델 결과를 본 뒤 라벨을 고치면 대조가 성립하지 않는다.
    커밋 시점이 "모델을 돌리기 전에 라벨이 이랬다" 는 기록이 된다(스펙 §4-1).
    """
    rel = str(path.relative_to(ROOT))
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=ROOT, capture_output=True)
    if tracked.returncode != 0:
        return [f"{rel} 이 아직 커밋되지 않았습니다. 라벨을 커밋한 뒤 다시 실행하세요."]
    dirty = subprocess.run(["git", "status", "--porcelain", "--", rel], cwd=ROOT, capture_output=True, text=True)
    if dirty.stdout.strip():
        return [f"{rel} 에 커밋하지 않은 변경이 있습니다. 커밋한 뒤 다시 실행하세요."]
    return []


def make_cases(labels: dict) -> list[dict]:
    """시험지 파일의 줄들. 사례 번호와 완성된 지시문(messages)만 담는다. 라벨은 넣지 않는다."""
    return [
        {"case_id": c["case_id"], "messages": build_messages(c["question"], c["sources"], c["generated_answer"])}
        for c in labels["cases"]
    ]


def cmd_cases() -> int:
    labels = json.loads(NEW_LABELS.read_text(encoding="utf-8"))
    problems = labels_ready(labels) + _committed(NEW_LABELS)
    if problems:
        print("시험지를 만들지 않았습니다.")
        for p in problems:
            print(f"  - {p}")
        return 1
    JUDGE5_DIR.mkdir(parents=True, exist_ok=True)
    rows = make_cases(labels)
    # sort_keys=True: 키 순서를 고정해 같은 내용이면 같은 해시가 나오게 한다.
    CASES.write_text(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    sha = sha256_file(CASES)
    CASES_SHA.write_text(f"{sha}  cases.jsonl\n", encoding="utf-8")
    print(f"{CASES.relative_to(ROOT)} 에 {len(rows)}건을 썼습니다.")
    print(f"SHA-256: {sha}")
    print("코랩 노트북의 EXPECTED_SHA256 에 이 값을 넣으세요(계획 태스크 7).")
    return 0
```

`main` 에 하위 명령을 더한다.

```python
    sub.add_parser("cases", help="시험지 파일을 만든다(새 라벨이 다 차고 커밋돼 있어야 한다)")
```

```python
    if args.cmd == "cases":
        return cmd_cases()
```

- [ ] **Step 4: M1 채점 도구를 쓴다** (`ai-service/tools/judge5_cloudflare.py`)

```python
"""M1(지금 서비스의 채점 모델, Cloudflare)으로 시험지를 채점한다.

실행:
    cd ai-service
    .venv/bin/python -m tools.judge5_cloudflare --smoke   # 가짜 사례 하나로 연결만 확인(44건을 쓰지 않는다)
    .venv/bin/python -m tools.judge5_cloudflare           # 시험지 44건 채점 → testdata/judge5/results/M1_run1.jsonl

점수는 여기서 읽지 않는다. 출력 원문만 저장하고 점수는 tools.judge5_report 가
judge5.parse_result 하나로 읽는다. 코랩 결과와 같은 규칙으로 읽기 위해서다.

이어 하기: 이미 결과 파일에 있는 사례는 건너뛴다. 호출이 실패한 사례는 결과 파일에 쓰지 않으므로
다시 실행하면 그 사례만 다시 부른다. 실패를 결과 줄로 남기지 않는 이유: "호출 실패" 와
"모델이 양식을 안 지켜 못 읽음" 은 다른 사실이다. 앞의 것은 다시 부르면 풀리고, 뒤의 것은 결과다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app import cf

from .judge5 import MAX_NEW_TOKENS, MODELS, build_messages, parse_result, sha256_file
from .judge5_export import CASES, CASES_SHA, RESULTS_DIR

MODEL_KEY = "M1"
RUN = 1


def result_line(case_id: str, model: str, repo: str, revision: str, run: int,
                output: str, finish: str | None, cases_sha256: str) -> dict:
    """결과 파일 한 줄. 코랩 노트북도 같은 키로 쓴다(계획 파일 구조 절)."""
    return {"case_id": case_id, "model": model, "repo": repo, "revision": revision, "run": run,
            "output": output, "finish": finish, "cases_sha256": cases_sha256}


def done_ids(path: Path) -> set[str]:
    """결과 파일에 이미 있는 사례 번호. 파일이 없으면 빈 집합."""
    if not path.exists():
        return set()
    return {json.loads(line)["case_id"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def _call(messages: list[dict]) -> tuple[str, str | None]:
    result = cf.run(MODELS[MODEL_KEY], {
        "messages": messages,
        "max_tokens": MAX_NEW_TOKENS,
        "temperature": 0,   # 채점은 같은 입력에 같은 점수여야 한다(스펙 §3-3)
    })
    return cf.text_of(result), cf.finish_reason(result)


def smoke() -> int:
    """44건이 아닌 가짜 사례로 연결과 양식만 본다. 순서 규칙(스펙 §4-1) 때문에 따로 둔다."""
    msgs = build_messages(
        "연차는 며칠인가요?",
        [{"filename": "가짜.md", "content": "정규직 직원의 연차는 15일이다."}],
        "연차는 15일이고, 회사 창립기념일에는 하루 더 쉽니다.",
    )
    text, finish = _call(msgs)
    print(text)
    print(f"\nfinish={finish}  읽은 결과={parse_result(text)}  뉴런={cf.neurons_used()}")
    return 0


def run_all(limit: int | None) -> int:
    expected = CASES_SHA.read_text(encoding="utf-8").split()[0]
    actual = sha256_file(CASES)
    if actual != expected:
        print(f"시험지 해시가 다릅니다: 파일 {actual} / 기록 {expected}. tools.judge5_export cases 를 다시 실행하세요.")
        return 1
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"{MODEL_KEY}_run{RUN}.jsonl"
    done = done_ids(out)
    rows = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]
    todo = [r for r in rows if r["case_id"] not in done][:limit]
    failed = 0
    for r in todo:
        try:
            text, finish = _call(r["messages"])
        except Exception as e:  # noqa: BLE001 - 한 건의 호출 실패가 나머지를 막지 않게 한다
            failed += 1
            print(f"호출 실패 {r['case_id']}: {type(e).__name__}: {e}")
            continue
        line = result_line(r["case_id"], MODEL_KEY, MODELS[MODEL_KEY], "cloudflare", RUN, text, finish, actual)
        # "a" 는 이어 쓰기 모드다. 한 줄씩 바로 써 두면 중간에 멈춰도 그때까지의 결과가 남는다.
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    total = len(done_ids(out))
    print(f"{out.name}: {total}/{len(rows)}건. 이번 호출 실패 {failed}건. 뉴런 {cf.neurons_used()}")
    if total < len(rows):
        print("빠진 사례가 있습니다. 같은 명령을 다시 실행하면 빠진 사례만 부릅니다.")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="M1(Cloudflare)으로 시험지를 채점한다")
    p.add_argument("--smoke", action="store_true", help="가짜 사례 하나로 연결만 확인한다")
    p.add_argument("--limit", type=int, default=None, help="이번 실행에서 부를 최대 사례 수")
    args = p.parse_args(argv)
    return smoke() if args.smoke else run_all(args.limit)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: 점검이 통과하는지 본다**

Run: `.venv/bin/python -m tools.judge5_check && .venv/bin/python -m tools.import_boundary_check`
Expected: 둘 다 통과.

- [ ] **Step 6: 가짜 사례로 연결을 확인한다** (44건은 쓰지 않는다)

Run: `.venv/bin/python -m tools.judge5_cloudflare --smoke`
Expected: `Feedback: ... [RESULT] n` 모양의 출력, `읽은 결과=(n, 'ok')`. 가짜 답변에는 근거에 없는 주장(창립기념일)이 하나 있으므로 4 가 나오면 양식과 채점표가 통한 것이다. 다른 점수가 나와도 실패는 아니다. 출력과 뉴런 수를 PR 본문 재료로 남긴다. `읽은 결과` 가 `missing` 이면 출력 원문을 보고 원인을 보고한다(양식을 바꾸기 전에 오케스트레이터 alldap-f8 에게 알린다. 공통 지시문은 스펙이 고정한 것이다).

- [ ] **Step 7: 커밋한다**

```bash
git add ai-service/tools/judge5_export.py ai-service/tools/judge5_cloudflare.py ai-service/tools/judge5_check.py
git commit -m "feat: 채점 모델 비교 실험의 시험지 내보내기와 M1(Cloudflare) 채점 도구를 더한다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

---

### Task 5: 코랩 노트북

**Files:**
- Create: `ai-service/notebooks/judge5_colab.ipynb`
- Modify: `ai-service/tools/judge5_check.py`

**Interfaces:**
- Consumes: 시험지 파일 모양, 결과 파일 모양(계획 파일 구조 절), `judge5.MODELS`, `judge5.MAX_NEW_TOKENS`
- Produces: 노트북 코드 칸에 `EXPECTED_SHA256 = "..."`, `MAX_NEW_TOKENS = 512`, `REPOS = {...}` 세 줄이 문자 그대로 있다(점검이 정규식으로 읽는다)

노트북은 결과를 Google Drive 의 `MyDrive/alldap_judge5/` 에 한 줄씩 쓴다. 코랩 연결이 끊겨도 다시 실행하면 이어서 한다(스펙 §6). 실행 순서는 M3, M4, M2 다. 실험의 핵심 비교(M3 와 M4)를 먼저 끝내고, 메모리가 가장 위험한 M2 를 마지막에 둔다.

- [ ] **Step 1: 실패하는 점검을 더한다** (`ai-service/tools/judge5_check.py`)

```python
import re

from .judge5 import MAX_NEW_TOKENS, MODELS
from .judge5_export import CASES_SHA, ROOT

NOTEBOOK = ROOT / "notebooks" / "judge5_colab.ipynb"


def _notebook_code() -> str:
    nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    # ipynb 의 source 는 문자열일 수도, 줄 목록일 수도 있다. 둘 다 이어 붙인다.
    parts = []
    for cell in nb["cells"]:
        if cell["cell_type"] == "code":
            src = cell["source"]
            parts.append(src if isinstance(src, str) else "".join(src))
    return "\n".join(parts)


def check_notebook_matches_the_module() -> None:
    """노트북은 judge5 를 import 하지 못한다(코랩에는 이 저장소가 없다). 그래서 값을 복사해 두고
    여기서 글자가 같은지 본다. 갈라지면 코랩 모델만 다른 조건으로 채점한다."""
    code = _notebook_code()
    assert f"MAX_NEW_TOKENS = {MAX_NEW_TOKENS}" in code
    for key in ("M2", "M3", "M4"):
        assert f'"{key}": "{MODELS[key]}"' in code, key
    assert "do_sample=False" in code


def check_notebook_hash_matches_cases_file() -> None:
    """시험지 파일이 있으면 노트북의 기대 해시가 그 파일의 해시와 같아야 한다."""
    m = re.search(r'EXPECTED_SHA256\s*=\s*"([0-9a-f]{64}|)"', _notebook_code())
    assert m, "노트북에 EXPECTED_SHA256 줄이 없다"
    if CASES_SHA.exists():
        assert m.group(1) == CASES_SHA.read_text(encoding="utf-8").split()[0], "노트북 해시를 갱신하라(태스크 7)"
```

`CHECKS` 끝에 두 이름을 더한다.

- [ ] **Step 2: 실패하는지 본다**

Run: `.venv/bin/python -m tools.judge5_check`
Expected: `FileNotFoundError` (노트북이 없다)

- [ ] **Step 3: 노트북을 만든다**

아래 스크립트를 스크래치패드에 저장해 한 번 실행한다(저장소에는 넣지 않는다). 칸마다 (종류, 내용) 이다.

```python
import json
from pathlib import Path

CELLS = [
("markdown", """# AllDap 채점 모델 비교 (M2, M3, M4)

설계: `docs/superpowers/specs/2026-10-02-judge-selfhost-design.md`

**실행 방법**
1. 런타임 > 런타임 유형 변경 > **T4 GPU**
2. 왼쪽 열쇠 아이콘(비밀값)에 `HF_TOKEN` 을 넣는다(Hugging Face 토큰, 읽기 권한). 노트북 접근을 허용한다.
3. Google Drive 의 `MyDrive/alldap_judge5/` 폴더에 `cases.jsonl` 을 올린다.
4. 런타임 > **모두 실행**. Drive 연결 허용 창이 뜨면 허용한다.
5. 끊기면 같은 순서로 다시 **모두 실행** 한다. 이미 채점한 사례는 건너뛴다.
6. 끝나면 마지막 칸이 `alldap_judge5_results.zip` 을 내려받는다.

모델 하나가 메모리에 안 올라가면 그 모델은 건너뛰고 이유를 `{모델}_skipped.json` 에 남긴다. 다른 모델로 바꿔 끼우지 않는다."""),
("code", """!pip install -q -U "transformers>=4.50" accelerate bitsandbytes huggingface_hub"""),
("code", """import hashlib, json, os, platform, shutil, traceback
import torch, transformers, bitsandbytes
from google.colab import drive, userdata, files
from huggingface_hub import model_info
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig

drive.mount('/content/drive')
DIR = '/content/drive/MyDrive/alldap_judge5'
CASES = f'{DIR}/cases.jsonl'
OUT = f'{DIR}/results'
os.makedirs(OUT, exist_ok=True)
HF_TOKEN = userdata.get('HF_TOKEN')

EXPECTED_SHA256 = ""
MAX_NEW_TOKENS = 512
REPOS = {
    "M3": "Unbabel/M-Prometheus-14B",
    "M4": "Qwen/Qwen2.5-14B-Instruct",
    "M2": "mistralai/Mistral-Small-3.1-24B-Instruct-2503",
}

sha = hashlib.sha256(open(CASES, 'rb').read()).hexdigest()
assert sha == EXPECTED_SHA256, f'시험지 해시가 다릅니다: {sha}. 올린 파일이 맞는지 확인하세요.'
CASE_ROWS = [json.loads(l) for l in open(CASES, encoding='utf-8') if l.strip()]
print(len(CASE_ROWS), '건, 해시 확인 완료')

env = {'gpu': torch.cuda.get_device_name(0), 'torch': torch.__version__,
       'transformers': transformers.__version__, 'bitsandbytes': bitsandbytes.__version__,
       'python': platform.python_version()}
json.dump(env, open(f'{OUT}/env.json', 'w'), ensure_ascii=False, indent=2)
print(env)"""),
("code", """QUANT = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type='nf4',
                           bnb_4bit_compute_dtype=torch.float16)  # T4 는 bf16 을 지원하지 않는다

def load(repo):
    tok = AutoTokenizer.from_pretrained(repo, token=HF_TOKEN)
    try:
        model = AutoModelForCausalLM.from_pretrained(repo, quantization_config=QUANT, device_map='auto', token=HF_TOKEN)
    except ValueError:
        # Mistral-Small-3.1 은 이미지도 받는 모델이라 CausalLM 으로 안 열릴 수 있다. 글만 넣어 쓴다.
        from transformers import AutoModelForImageTextToText
        model = AutoModelForImageTextToText.from_pretrained(repo, quantization_config=QUANT, device_map='auto', token=HF_TOKEN)
    model.eval()
    return tok, model

def generate(tok, model, messages):
    ids = tok.apply_chat_template(messages, add_generation_prompt=True, return_tensors='pt').to(model.device)
    with torch.no_grad():
        out = model.generate(ids, max_new_tokens=MAX_NEW_TOKENS, do_sample=False,
                             temperature=None, top_p=None, top_k=None,
                             pad_token_id=tok.pad_token_id or tok.eos_token_id)
    new = out[0, ids.shape[1]:]
    finish = 'length' if new.shape[0] >= MAX_NEW_TOKENS else 'stop'
    return tok.decode(new, skip_special_tokens=True), finish

def done_ids(path):
    if not os.path.exists(path):
        return set()
    return {json.loads(l)['case_id'] for l in open(path, encoding='utf-8') if l.strip()}

def run_model(key):
    repo = REPOS[key]
    skip = f'{OUT}/{key}_skipped.json'
    paths = [f'{OUT}/{key}_run{r}.jsonl' for r in (1, 2)]
    if all(len(done_ids(p)) == len(CASE_ROWS) for p in paths):
        print(key, '이미 끝남'); return
    try:
        revision = model_info(repo, token=HF_TOKEN).sha
        tok, model = load(repo)
        for run, path in zip((1, 2), paths):
            done = done_ids(path)
            for i, row in enumerate(CASE_ROWS):
                if row['case_id'] in done:
                    continue
                text, finish = generate(tok, model, row['messages'])
                line = {'case_id': row['case_id'], 'model': key, 'repo': repo, 'revision': revision,
                        'run': run, 'output': text, 'finish': finish, 'cases_sha256': sha}
                with open(path, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(line, ensure_ascii=False) + '\\n')
                print(key, f'run{run}', i + 1, '/', len(CASE_ROWS), finish)
        if os.path.exists(skip):
            os.remove(skip)
    except torch.cuda.OutOfMemoryError as e:
        json.dump({'model': key, 'reason': f'GPU 메모리 부족: {e}'}, open(skip, 'w'), ensure_ascii=False)
        print(key, '메모리 부족으로 건너뜀')"""),
("code", """import gc
for key in ('M3', 'M4', 'M2'):
    try:
        run_model(key)
    except Exception:
        # 메모리 부족 말고 다른 이유로 실패하면 멈춘다. 다른 모델로 넘어가 결과를 섞지 않는다.
        traceback.print_exc()
        raise
    finally:
        # run_model 이 돌아오면 그 안의 지역 변수(model, tok)가 사라진다.
        # 그 뒤에 쓰레기 수거와 GPU 캐시 비우기를 해야 다음 모델이 올라갈 자리가 생긴다.
        gc.collect()
        torch.cuda.empty_cache()"""),
("code", """shutil.make_archive('/content/alldap_judge5_results', 'zip', OUT)
files.download('/content/alldap_judge5_results.zip')"""),
]

nb = {
    "nbformat": 4, "nbformat_minor": 5,
    "metadata": {"accelerator": "GPU", "colab": {"gpuType": "T4"},
                 "kernelspec": {"name": "python3", "display_name": "Python 3"}},
    "cells": [
        ({"cell_type": "markdown", "metadata": {}, "source": src} if kind == "markdown" else
         {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": src})
        for kind, src in CELLS
    ],
}
Path("/Users/cheonjamin/projects/AllDap-judge/ai-service/notebooks").mkdir(exist_ok=True)
Path("/Users/cheonjamin/projects/AllDap-judge/ai-service/notebooks/judge5_colab.ipynb").write_text(
    json.dumps(nb, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
```

주의: 결과 줄의 `'\\n'` 은 스크립트의 세 따옴표 문자열 안이라 역슬래시를 두 번 쓴 것이다. 만들어진 노트북 칸에는 `'\n'` 으로 들어가야 한다. 만든 뒤 노트북을 열어 그 줄을 눈으로 확인한다.

- [ ] **Step 4: 점검이 통과하는지 본다**

Run: `.venv/bin/python -m tools.judge5_check`
Expected: `전부 통과.` (`EXPECTED_SHA256 = ""` 는 시험지 파일이 아직 없으므로 통과한다)

그리고 노트북의 코드 칸이 문법 오류 없이 읽히는지 본다(실행은 하지 않는다).

```bash
.venv/bin/python - <<'EOF'
import ast, json
nb = json.load(open("notebooks/judge5_colab.ipynb"))
for c in nb["cells"]:
    if c["cell_type"] == "code":
        src = c["source"] if isinstance(c["source"], str) else "".join(c["source"])
        # '!' 로 시작하는 줄은 코랩 셸 명령이라 파이썬 문법이 아니다. 빼고 검사한다.
        ast.parse("\n".join(l for l in src.splitlines() if not l.startswith("!")))
print("문법 OK")
EOF
```

- [ ] **Step 5: 커밋한다**

```bash
git add ai-service/notebooks/judge5_colab.ipynb ai-service/tools/judge5_check.py
git commit -m "feat: 채점 모델 비교 실험의 코랩 노트북(M2, M3, M4)을 더한다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

---

### Task 6: 대조 보고 도구

**Files:**
- Create: `ai-service/tools/judge5_report.py`
- Modify: `ai-service/tools/judge5_check.py`

**Interfaces:**
- Consumes: `judge5.summarize`, `compare`, `pick_best`, `replacement_failures`, `linear_weighted_kappa`, `parse_result`, `to_three`, `MODELS`, `judge5_export.NEW_LABELS`, `OLD_LABELS`, `CASES_SHA`, `RESULTS_DIR`
- Produces:
  - `load_run(path: Path, case_ids: set[str], cases_sha: str) -> dict[str, str]` (사례 번호 → 출력 원문. 사례가 모자라거나 남거나 해시가 다르면 `ReportProblem`)
  - `scores_of(outputs: dict[str, str]) -> tuple[dict[str, int | None], dict[str, int]]` (점수, 상태별 개수)
  - `render(...) -> str` (마크다운)
  - 산출물 `testdata/judge5/report.md`

- [ ] **Step 1: 실패하는 점검을 더한다** (`ai-service/tools/judge5_check.py`)

```python
from .judge5_report import ReportProblem, load_run, scores_of


def check_load_run_refuses_partial_or_foreign_files() -> None:
    """🔴 부분 결과로 표를 내지 않는다. 한 번 찍힌 숫자는 꼬리표 없이 인용된다."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "M3_run1.jsonl"
        p.write_text(json.dumps({"case_id": "aa", "output": "[RESULT] 5", "cases_sha256": "s"}) + "\n")
        for ids, sha in (({"aa", "bb"}, "s"), ({"aa"}, "다른해시")):
            try:
                load_run(p, ids, sha)
            except ReportProblem:
                continue
            raise AssertionError("받으면 안 된다")
        assert load_run(p, {"aa"}, "s") == {"aa": "[RESULT] 5"}


def check_scores_of_counts_each_failure_kind() -> None:
    scores, kinds = scores_of({"a": "[RESULT] 5", "b": "점수 없음", "c": "[RESULT] 9", "d": "[RESULT] 2 [RESULT] 3"})
    assert scores == {"a": 5, "b": None, "c": None, "d": None}
    assert kinds == {"ok": 1, "missing": 1, "out_of_range": 1, "conflict": 1}
```

`CHECKS` 끝에 두 이름을 더한다.

- [ ] **Step 2: 실패하는지 본다**

Run: `.venv/bin/python -m tools.judge5_check`
Expected: `ModuleNotFoundError: No module named 'tools.judge5_report'`

- [ ] **Step 3: 보고 도구를 쓴다** (`ai-service/tools/judge5_report.py`)

```python
"""채점 모델 비교 실험(2026-10-02)의 대조 보고. 스펙 §4 를 그대로 계산한다.

실행:  cd ai-service && .venv/bin/python -m tools.judge5_report
산출:  testdata/judge5/report.md (화면에도 같은 내용을 찍는다)

판정 규칙은 스펙 §4 에 측정 전에 고정돼 있다. 이 도구는 그 규칙을 계산할 뿐이고,
결과를 보고 규칙을 바꾸는 자리가 아니다.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from .judge5 import (
    SCALE, MODELS, Summary, compare, linear_weighted_kappa, parse_result, pick_best,
    replacement_failures, summarize, to_three,
)
from .judge5_export import CASES_SHA, NEW_LABELS, OLD_LABELS, RESULTS_DIR, labels_ready

REPORT = RESULTS_DIR.parent / "report.md"


class ReportProblem(RuntimeError):
    """입력 파일이 완전하지 않다. 부분 집계를 내지 않는다."""


def load_run(path: Path, case_ids: set[str], cases_sha: str) -> dict[str, str]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    got = {r["case_id"] for r in rows}
    if got != case_ids:
        raise ReportProblem(f"{path.name}: 사례가 맞지 않습니다(빠짐 {len(case_ids - got)}, 남음 {len(got - case_ids)})")
    if len(rows) != len(got):
        raise ReportProblem(f"{path.name}: 같은 사례가 두 번 있습니다")
    if any(r["cases_sha256"] != cases_sha for r in rows):
        raise ReportProblem(f"{path.name}: 다른 시험지로 채점한 줄이 있습니다")
    return {r["case_id"]: r["output"] for r in rows}


def scores_of(outputs: dict[str, str]) -> tuple[dict[str, int | None], dict[str, int]]:
    scores: dict[str, int | None] = {}
    kinds: Counter = Counter()   # Counter 는 없는 키를 0 으로 치는 dict 다
    for cid, text in outputs.items():
        v, status = parse_result(text)
        scores[cid] = v
        kinds[status] += 1
    return scores, dict(kinds)


def _fmt(x: float | None, nd: int = 3) -> str:
    return "계산 불가" if x is None else f"{x:.{nd}f}"


def _summary_rows(name: str, s: Summary, kinds: dict[str, int], kappa: float | None) -> str:
    unread = ", ".join(f"{k} {v}" for k, v in sorted(kinds.items()) if k != "ok") or "없음"
    return (f"| {name} | {s.exact} | {s.within1} | {_fmt(s.mean_distance)} | {s.generous} | {s.harsh} "
            f"| {s.unread} ({unread}) | {_fmt(kappa)} |")


def _confusion(name: str, s: Summary) -> str:
    head = "| 사람 \\ " + name + " | " + " | ".join(str(m) for m in SCALE) + " |"
    sep = "|---" * (len(SCALE) + 1) + "|"
    body = [f"| {h} | " + " | ".join(str(s.confusion[(h, m)]) for m in SCALE) + " |" for h in SCALE]
    return "\n".join([head, sep, *body])


def build() -> str:
    labels = json.loads(NEW_LABELS.read_text(encoding="utf-8"))
    problems = labels_ready(labels)
    if problems:
        raise ReportProblem("새 라벨이 다 차지 않았습니다: " + "; ".join(problems))
    human = {c["case_id"]: int(c["label"]) for c in labels["cases"]}
    ids = set(human)
    cases_sha = CASES_SHA.read_text(encoding="utf-8").split()[0]

    scores: dict[str, dict[str, int | None]] = {}
    kinds: dict[str, dict[str, int]] = {}
    skipped: dict[str, str] = {}
    repeat: dict[str, int] = {}
    for key in MODELS:
        run1 = RESULTS_DIR / f"{key}_run1.jsonl"
        skip = RESULTS_DIR / f"{key}_skipped.json"
        if not run1.exists():
            skipped[key] = json.loads(skip.read_text(encoding="utf-8"))["reason"] if skip.exists() else "결과 파일 없음"
            continue
        scores[key], kinds[key] = scores_of(load_run(run1, ids, cases_sha))
        run2 = RESULTS_DIR / f"{key}_run2.jsonl"
        if run2.exists():
            s2, _ = scores_of(load_run(run2, ids, cases_sha))
            repeat[key] = sum(1 for cid in ids if s2[cid] != scores[key][cid])

    sums = {k: summarize([(human[c], v[c]) for c in sorted(ids)]) for k, v in scores.items()}
    kappas = {k: linear_weighted_kappa([(human[c], v[c]) for c in sorted(ids) if v[c] is not None])
              for k, v in scores.items()}

    out = ["# 채점 모델 비교 결과", "",
           f"사례 {len(ids)}건. 새 라벨 분포: "
           + ", ".join(f"{v}점 {sum(1 for h in human.values() if h == v)}건" for v in SCALE), "",
           "## 모델마다의 수치 (스펙 §4-2, 실행 1 기준)", "",
           "| 모델 | 정확히 같음 | 거리 1 이하 | 평균 거리 | 후함 | 박함 | 못 읽음 | 선형 가중 카파(보조) |",
           "|---|---|---|---|---|---|---|---|"]
    out += [_summary_rows(k, sums[k], kinds[k], kappas[k]) for k in sums]
    for k, why in skipped.items():
        out.append(f"| {k} | 제외: {why} | | | | | | |")

    out += ["", "## 혼동행렬 (행은 새 라벨, 열은 모델 점수)", ""]
    for k in sums:
        out += [f"### {k} ({MODELS[k]})", "", _confusion(k, sums[k]), ""]

    out += ["## 두 모델 비교 (스펙 §4-3)", ""]
    pairs = [("M1", "M2", "돌리는 곳과 4비트"), ("M4", "M3", "같은 바탕 모델에 더한 채점 학습")]
    best = pick_best({k: s for k, s in sums.items() if k != "M1"})
    if best:
        pairs.append((best, "M1", f"가장 나은 후보({best})와 지금 채점 모델"))
    for a, b, what in pairs:
        if a not in scores or b not in scores:
            out.append(f"- {a} 와 {b} ({what}): 하지 않음. 결과가 없는 모델이 있다")
            continue
        c = compare(human, scores[a], scores[b])
        out.append(f"- {a} 와 {b} ({what}): {a} 가 더 가까움 {c.a_closer}, {b} 가 더 가까움 {c.b_closer}, "
                   f"같음 {c.ties}, 제외 {c.excluded}, p = {c.p_value:.4f} → **{c.verdict(a, b)}**")

    out += ["", "## 교체 후보 (스펙 §4-4)", ""]
    if "M1" in sums:
        for k in (m for m in sums if m != "M1"):
            fails = replacement_failures(sums[k], sums["M1"], compare(human, scores[k], scores["M1"]))
            out.append(f"- {k}: " + ("**교체 후보**" if not fails else "아님. " + "; ".join(fails)))
    else:
        out.append("- M1 결과가 없어 판단하지 않음")

    out += ["", "## 재현 (실행 1 과 실행 2 의 점수가 다른 사례 수)", ""]
    out += [f"- {k}: {n}건" for k, n in repeat.items()] or ["- 실행 2 결과 없음"]

    old = {c["case_id"]: float(c["label"]) for c in json.loads(OLD_LABELS.read_text(encoding="utf-8"))["cases"]}
    same = sum(1 for cid in ids if to_three(human[cid]) == old[cid])
    out += ["", "## 보조: 사람 라벨의 일관성 (스펙 §4-6, 판정에 쓰지 않는다)", "",
            f"새 라벨을 세 칸으로 옮겼을 때 옛 라벨과 같은 사례: {same} / {len(ids)}"]
    return "\n".join(out) + "\n"


def main() -> int:
    try:
        text = build()
    except ReportProblem as e:
        print(f"보고서를 만들지 않았습니다: {e}")
        return 1
    REPORT.write_text(text, encoding="utf-8")
    print(text)
    print(f"→ {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 점검이 통과하는지 본다**

Run: `.venv/bin/python -m tools.judge5_check && .venv/bin/python -m tools.import_boundary_check`
Expected: 둘 다 통과.

- [ ] **Step 5: 가짜 결과로 보고서 모양을 확인한다**

스크래치패드에 가짜 라벨, 가짜 결과를 만들어 `build()` 를 돌려 본다(저장소의 testdata 를 건드리지 않는다). 가장 쉬운 방법은 `judge5_export` 와 `judge5_report` 의 경로 상수를 스크립트 안에서 덮어쓰는 것이다.

```bash
.venv/bin/python - <<'EOF'
import json, tempfile
from pathlib import Path
from tools import judge5_export as ex, judge5_report as rp

d = Path(tempfile.mkdtemp())
ids = [f"c{i:02d}" for i in range(10)]
labels = {"scale": 5, "cases": [{"case_id": c, "label": 5 if i < 8 else 3} for i, c in enumerate(ids)]}
old = {"cases": [{"case_id": c, "label": 1.0 if i < 8 else 0.5} for i, c in enumerate(ids)]}
(d / "new.json").write_text(json.dumps(labels)); (d / "old.json").write_text(json.dumps(old))
(d / "sha").write_text("s  cases.jsonl\n"); (d / "results").mkdir()
for key, vals in {"M1": [5]*9 + [4], "M3": [5]*10, "M4": [4]*10}.items():
    for run in (1, 2):
        (d / "results" / f"{key}_run{run}.jsonl").write_text("".join(
            json.dumps({"case_id": c, "output": f"[RESULT] {v}", "cases_sha256": "s"}) + "\n" for c, v in zip(ids, vals)))
(d / "results" / "M2_skipped.json").write_text(json.dumps({"model": "M2", "reason": "GPU 메모리 부족: 가짜"}))
rp.NEW_LABELS, rp.OLD_LABELS, rp.CASES_SHA, rp.RESULTS_DIR = d / "new.json", d / "old.json", d / "sha", d / "results"
print(rp.build())
EOF
```

Expected: 표에 M1, M3, M4 세 줄과 `M2 | 제외: GPU 메모리 부족: 가짜`, 비교 셋 중 M1 과 M2 는 `하지 않음`, M4 와 M3 는 판정 문장, 교체 후보 절, 재현 `0건` 셋, 일관성 `10 / 10`. 숫자를 손으로 하나 검산한다: M4 는 전부 4 이므로 사람 5 인 8건에서 박함, 사람 3 인 2건에서 후함이다.

- [ ] **Step 6: 커밋한다**

```bash
git add ai-service/tools/judge5_report.py ai-service/tools/judge5_check.py
git commit -m "feat: 채점 모델 비교 실험의 대조 보고 도구를 더한다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

---

### Task 7: 실행, 기록, PR

**Files:**
- Create: `ai-service/testdata/judge5/cases.jsonl`, `cases.sha256`, `results/*`, `report.md`
- Modify: `ai-service/notebooks/judge5_colab.ipynb` (`EXPECTED_SHA256`)
- Create: `docs/superpowers/plans/2026-10-02-judge-selfhost-results.md`
- Modify: `docs/decisions.md`, `docs/BACKLOG.md`
- Create: `docs/superpowers/handoff-2026-10-0X.md` (실행한 날짜)
- Modify: `AGENTS.md` ("다음 세션은 여기서 시작한다" 의 최신 핸드오프 링크만)

이 태스크는 태스크 3(라벨 커밋)이 끝난 뒤에만 시작한다.

- [ ] **Step 1: 시험지를 만들고 노트북에 해시를 넣는다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge/ai-service
.venv/bin/python -m tools.judge5_export cases
```

Expected: `44건을 썼습니다` 와 `SHA-256: <64자리>`. 노트북의 `EXPECTED_SHA256 = ""` 를 그 값으로 바꾼다(노트북을 JSON 으로 읽어 해당 칸 문자열을 바꾸고 다시 쓴다). 그다음 `.venv/bin/python -m tools.judge5_check` 가 통과해야 한다.

```bash
git add ai-service/testdata/judge5/cases.jsonl ai-service/testdata/judge5/cases.sha256 ai-service/notebooks/judge5_colab.ipynb
git commit -m "feat: 채점 모델 비교 실험의 시험지를 만들고 노트북에 해시를 적는다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

- [ ] **Step 2: M1 을 채점한다**

Run: `.venv/bin/python -m tools.judge5_cloudflare`
Expected: `44/44건`. 빠진 사례가 있으면 같은 명령을 다시 실행한다. 뉴런 수를 기록한다(스펙 §6 의 추정치 약 1,100 과 비교).

- [ ] **Step 3: 사용자가 코랩을 실행한다**

사용자에게 안내한다: `cases.jsonl` 을 Drive 의 `MyDrive/alldap_judge5/` 에 올리고, `ai-service/notebooks/judge5_colab.ipynb` 를 코랩에서 열어(파일 > 노트북 업로드) T4 와 `HF_TOKEN` 을 설정한 뒤 모두 실행한다. M2 저장소가 약관 동의를 요구하면 Hugging Face 에서 동의한다. 끝나면 zip 을 받아 `testdata/judge5/results/` 에 푼다.

실패하면 오류 원문을 받아 오케스트레이터(alldap-f8)에게 넘긴다. 노트북을 고쳐야 하면 고친 이유를 커밋 메시지에 적는다. 고칠 수 있는 것은 실행 환경 문제뿐이다. 모델, 지시문, 생성 설정은 스펙이 고정한 것이라 바꾸지 않는다. M2 가 메모리 부족으로 빠지는 것은 실패가 아니라 스펙 §6 이 정한 결과다.

- [ ] **Step 4: 보고서를 만든다**

Run: `.venv/bin/python -m tools.judge5_report`
Expected: `testdata/judge5/report.md`. 커밋한다.

```bash
git add ai-service/testdata/judge5/results ai-service/testdata/judge5/report.md
git commit -m "feat: 채점 모델 비교 실험의 결과와 보고서를 남긴다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

- [ ] **Step 5: 결과 문서를 쓴다** (`docs/superpowers/plans/2026-10-02-judge-selfhost-results.md`)

스펙의 용어를 그대로 쓴다. 절은 이 순서다: 무엇을 했나(사례 수, 모델 리비전, 코랩 환경 `env.json`, M1 뉴런), 보고서 표 전문, 스펙 §4-5 의 미리 적은 해석 중 어느 경우에 해당하는가, 못 읽음 사례의 원문 예시, 점수는 맞았는데 이유가 근거와 다른 사례(있으면), 한계(스펙 §8 그대로 + 실행에서 새로 생긴 것), 다음 단계(스펙 §7 로 갈지, 사람 라벨을 늘릴지). 결과에 맞춰 규칙을 다시 해석하지 않는다.

- [ ] **Step 6: 기록을 남긴다**

- `docs/decisions.md` 에 한 줄: `2026-10-02 | 채점 모델 후보를 1~5 사람 라벨 44건과 대조 | (결과 한 구절) | M-Prometheus 단독, 0/0.5/1 유지, 서비스 채점 방식 동시 변경`
- `docs/BACKLOG.md` §5 표에 이 실험의 행을 더하고 결과 문서를 링크한다. §6 의 "채점자 사유가 저장되지 않는다" 행에는 이번 실험이 이유를 저장했다는 사실만 한 줄 덧붙인다(서비스는 여전히 버린다).
- 핸드오프 `docs/superpowers/handoff-2026-10-0X.md` 를 쓰고 `AGENTS.md` 의 최신 핸드오프 링크를 바꾼다. **AGENTS.md 에 결과를 적지 않는다.**

- [ ] **Step 7: PR 을 연다**

```bash
cd /Users/cheonjamin/projects/AllDap-judge
cd ai-service && .venv/bin/python -m tools.judge5_check && .venv/bin/python -m tools.import_boundary_check && cd ..
git add docs AGENTS.md && git commit -m "docs: 채점 모델 비교 실험의 결과, 결정, 핸드오프를 남긴다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
gh pr create --title "feat: 공개 채점 모델 셋을 코랩에서 돌려 사람 라벨 44건(1~5)과 대조한다" --body-file <PR 본문 파일>
```

PR 본문은 `.github/PULL_REQUEST_TEMPLATE.md` 를 채운다. "어떻게 해결했나요" 에 보고서 표와 실행 명령의 실제 출력을 붙인다. "한계 & 트레이드오프" 에 스펙 §8 과 실행에서 생긴 것을 적는다. 본문 끝에 `🤖 Generated with [Claude Code](https://claude.com/claude-code)` 를 붙인다. CI 는 기다리지 않는다.
