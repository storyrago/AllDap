# 1차 방어선 되살리기 — 판정과 컷의 분리 · 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `max_distance` 가 겸하던 두 일을 나눠, 벡터 최근접 거리로 "근거가 있는가" 를 따로 판정해 근거가 없으면 LLM 을 아예 부르지 않는다.

**Architecture:** `retriever.search()` 초입(하이브리드 재정렬 **전**)에서 `rows[0]` 의 벡터 거리를 새 설정 `answerable_max_distance` 와 비교해, 멀면 빈 리스트를 반환한다. 빈 리스트는 `generator.generate()` 가 이미 LLM 미호출 fallback 으로 처리한다(`generator.py:120`) — 새 상태도 새 경로도 만들지 않는다.

**Tech Stack:** Python 3 / FastAPI / psycopg / pgvector / Cloudflare Workers AI (`@cf/baai/bge-m3`)

## Global Constraints

- **`max_distance = 0.55` 는 건드리지 않는다.** 6회 일관 측정으로 확정된 값이고, 이 슬라이스는 거기 손대지 않는 것이 전제다.
- **`api/`(Spring) · `web/` · `widget/` 은 한 줄도 안 고친다.** 판정 결과는 기존 `is_fallback` 경로를 그대로 탄다.
- **테스트는 pytest 가 아니라 `app/*_check.py` 자체 점검 패턴이다.** `assert` + `main()` + `if __name__ == "__main__"`. 이 저장소에 pytest 는 없다.
- **주석과 출력 문구는 한국어.**
- **평가 측정은 설정당 3회 이상.** 편차가 0.032 라 1회로는 방향도 크기도 말할 수 없다.
- **봇 ID**: `628d2785-a128-486c-a1ac-556f19f06de3` (코퍼스 50문서 · 306청크)
- **로컬 실행**: `docker compose up -d` 로 DB 를 띄운 뒤 `cd ai-service && .venv/bin/python -m app.<모듈>`. 임베딩 호출에 `CF_ACCOUNT_ID` · `CF_API_TOKEN` 이 필요하다(`.env`).

---

## File Structure

| 파일 | 책임 | 변경 |
|---|---|---|
| `ai-service/app/answerable_check.py` | 거리 분포 측정 · 임계값 트레이드오프 표 · 홀드아웃 검증 | **신규** |
| `ai-service/app/fallback_e2e_check.py` | `guard()` 를 다른 질문 목록에도 쓸 수 있게 파라미터화 | 수정 (한 함수) |
| `ai-service/app/config.py` | `answerable_max_distance` 설정 추가 | 수정 |
| `ai-service/app/retriever.py` | `search()` 에 판정 게이트 | 수정 |
| `docs/decisions.md` · `AGENTS.md` · `ai-service/app/config.py` 주석 | 측정 결과와 결정 기록 | 수정 |

---

## Task 1: 측정 스크립트 — 순수 함수와 자체 점검

**Files:**
- Create: `ai-service/app/answerable_check.py`
- Modify: `ai-service/app/fallback_e2e_check.py` (`guard()` 파라미터화)

**Interfaces:**
- Consumes: `app.fallback_e2e_check.UNGROUNDED` (`list[tuple[str, tuple[str, ...]]]`), `app.fallback_e2e_check.guard`, `app.retriever.embed_one`, `app.db.cursor`
- Produces:
  - `_tradeoff(grounded: list[float], ungrounded: list[float], threshold: float) -> tuple[int, int]`
  - `_tradeoff_table(grounded: list[float], ungrounded: list[float]) -> list[tuple[float, int, int]]`
  - `d1(bot_id: UUID, question: str) -> float | None`
  - `HOLDOUT: list[tuple[str, tuple[str, ...]]]` (Task 2 에서 채운다)

- [ ] **Step 1: `guard()` 를 파라미터화한다**

`ai-service/app/fallback_e2e_check.py` 의 `guard()` 를 아래로 교체. 기본 인자라 기존 호출부(`main()` 의 `if not guard():`)는 안 고쳐도 된다.

```python
def guard(questions: list[tuple[str, tuple[str, ...]]] | None = None) -> bool:
    """감시 낱말이 코퍼스에 나타났는지 본다. 하나라도 나오면 측정을 막는다.

    questions 를 받는 이유: 같은 가드를 <홀드아웃 질문 목록>에도 써야 하는데
    (`answerable_check`), 로직을 복사하면 한쪽만 고쳐지는 사고가 구조적으로 가능해진다.
    기본값이 UNGROUNDED 라 기존 호출부는 그대로 둔다.
    """
    questions = UNGROUNDED if questions is None else questions
    ok = True
    with cursor() as cur:
        for question, sentinels in questions:
            for word in sentinels:
                cur.execute(
                    """SELECT count(*), min(d.filename)
                         FROM chunks c JOIN documents d ON d.id = c.document_id
                        WHERE c.bot_id = %s AND c.content LIKE %s""",
                    (BOT_ID, f"%{word}%"),
                )
                n, filename = cur.fetchone()
                if n:
                    ok = False
                    print(f"⚠️  '{word}' 가 코퍼스에 {n}건 있습니다 ({filename})")
                    print(f"    → \"{question}\" 은 이제 답이 있을 수 있습니다. 질문을 바꾸세요.")
    return ok
```

- [ ] **Step 2: 순수 함수와 자체 점검을 담은 스크립트를 만든다**

`ai-service/app/answerable_check.py` 를 아래 내용으로 생성. 이 단계에서는 **DB 를 부르는 부분(`d1`·`main`)을 아직 넣지 않는다** — 순수 함수만 먼저 검증한다.

```python
"""판정 임계값(`answerable_max_distance`)을 고르기 위한 <거리 분포> 측정.

실행:
    cd ai-service && .venv/bin/python -m app.answerable_check            # 임계값을 고를 때
    cd ai-service && .venv/bin/python -m app.answerable_check --holdout  # 고른 뒤 검증할 때
    cd ai-service && .venv/bin/python -m app.answerable_check --self     # DB 없이 순수 함수만

`fallback_e2e_check` 와 무엇이 다른가
─────────────────────────────────────────────────────────────────────────────
  fallback_e2e_check   LLM 까지 태워 <fallback 이 나오는가>를 본다. 생성 호출 23회.
  answerable_check     임베딩만 써서 <거리 분포와 임계값 트레이드오프>를 본다. (이 파일)
                       평가 1회의 임베딩 총량이 16질문에 0.4 뉴런이므로 질문당 ≈0.025,
                       36질문이면 ≈1 뉴런이다. 사실상 공짜라 몇 번이든 돌릴 수 있다.

🔴 이 파일이 생긴 이유 — AGENTS.md 의 `d1` 표를 <재현할 수 없었다>
─────────────────────────────────────────────────────────────────────────────
"d1 임계 0.3777 이면 근거없음 10/10 을 막으면서 정답 청크 15/16 을 지킨다"는 표가
AGENTS.md 에 있는데, **그걸 돌린 스크립트가 저장소에 없다.** 수동 측정이었다.

`fallback_e2e_check` 가 생긴 이유가 정확히 같은 문제였다 —
W1 완료 조건 3번이 통과했다고 기록돼 있는데 그 질문 10개가 어디에도 없었다.
**측정은 재현할 수 없으면 측정이 아니다.** 같은 일을 반복하지 않는다.

🔴 홀드아웃을 <같은 표에 띄우지 않는> 이유
─────────────────────────────────────────────────────────────────────────────
홀드아웃은 "이 임계값이 테스트셋에 과적합된 게 아니다"를 보이는 데 쓴다.
그런데 임계값을 고르는 표에 함께 띄우면 **보면서 고르게 되고, 그 순간 홀드아웃이 아니다.**
그래서 모드를 나눴다. 기본 모드는 홀드아웃을 <읽지도 않는다.>
"""
from __future__ import annotations

import sys
from uuid import UUID

from .db import close_pool, cursor
from .fallback_e2e_check import BOT_ID, UNGROUNDED, guard
from .retriever import embed_one

# ── 홀드아웃: 임계값을 고른 <뒤에만> 보는 근거없음 질문 ────────────────
# Task 2 에서 채운다.
HOLDOUT: list[tuple[str, tuple[str, ...]]] = []


def _tradeoff(grounded: list[float], ungrounded: list[float], threshold: float) -> tuple[int, int]:
    """(정답 유지 수, 근거없음 차단 수).

    유지 = `d1 <= threshold` → 판정 통과 → 답변 경로로 간다.
    차단 = `d1 >  threshold` → 판정 실패 → LLM 미호출 fallback.

    ⚠️ 경계(`==`)는 <유지>다. `retriever.search()` 의 게이트가 `rows[0][4] > answerable`
       이므로 부등호 방향이 반드시 같아야 한다. 여기서 `<` 를 쓰면 표와 실제 동작이
       경계값에서 어긋나고, 하필 고른 임계값이 경계면 측정이 통째로 거짓이 된다.
    """
    kept = sum(1 for d in grounded if d <= threshold)
    blocked = sum(1 for d in ungrounded if d > threshold)
    return kept, blocked


def _tradeoff_table(
    grounded: list[float], ungrounded: list[float], lo: int = 30, hi: int = 55
) -> list[tuple[float, int, int]]:
    """임계값을 0.01 간격으로 훑되 <결과가 바뀌는 지점만> 남긴다.

    26줄을 다 보여줘도 되지만, 같은 (유지·차단) 이 반복되면 눈이 미끄러진다.
    바뀌는 지점만 남기면 표가 곧 <경계 목록>이 되어 고를 곳이 바로 보인다.

    lo·hi 가 int(백분율)인 이유: float 를 누적하면 0.1+0.2 문제로 임계값이
    0.44000000000000006 이 된다. 정수로 돌고 나눈다.
    """
    rows: list[tuple[float, int, int]] = []
    prev: tuple[int, int] | None = None
    for i in range(lo, hi + 1):
        t = i / 100
        r = _tradeoff(grounded, ungrounded, t)
        if r != prev:
            rows.append((t, *r))
            prev = r
    return rows


def _self_check() -> None:
    """DB 없이 도는 순수 함수 검사."""
    g = [0.20, 0.30, 0.40]   # 정답 문항의 d1 (가깝다)
    u = [0.45, 0.50, 0.55]   # 근거없음 문항의 d1 (멀다)

    # ① 완전히 갈리는 임계값 — 정답 전부 유지, 근거없음 전부 차단.
    assert _tradeoff(g, u, 0.40) == (3, 3), _tradeoff(g, u, 0.40)

    # ② 너무 낮으면 정답을 자른다.
    assert _tradeoff(g, u, 0.25) == (1, 3), _tradeoff(g, u, 0.25)

    # ③ 너무 높으면 아무것도 못 막는다 = 지금 상태(게이트 없음)와 같다.
    assert _tradeoff(g, u, 0.60) == (3, 0), _tradeoff(g, u, 0.60)

    # ④ 🔴 경계는 <유지>다. search() 의 `> answerable` 과 부등호가 같아야 한다.
    #    여기가 어긋나면 표와 실제 동작이 경계값에서 갈린다.
    assert _tradeoff([0.40], [], 0.40) == (1, 0), "경계값이 유지가 아니다"
    assert _tradeoff([], [0.40], 0.40) == (0, 0), "경계값이 차단으로 세어졌다"

    # ⑤ 표는 <바뀌는 지점만> 남는다. 위 g·u 는 0.30~0.55 에서 경계가 몇 개뿐이다.
    table = _tradeoff_table(g, u)
    assert len(table) < 26, f"표가 안 접혔다: {len(table)}줄"
    assert all(
        table[i][1:] != table[i + 1][1:] for i in range(len(table) - 1)
    ), f"연속한 두 줄의 결과가 같다: {table}"

    # ⑥ 표의 첫 줄은 lo(0.30) 에서 시작한다 — 훑은 구간의 왼쪽 끝을 알 수 있어야 한다.
    assert table[0][0] == 0.30, table[0]

    print("OK — 트레이드오프 계산 6가지 통과")


def main() -> None:
    if "--self" in sys.argv:
        _self_check()
        return
    raise SystemExit("측정 모드는 Task 2 에서 구현한다")


if __name__ == "__main__":
    try:
        main()
    finally:
        close_pool()
```

- [ ] **Step 3: 자체 점검이 통과하는지 확인**

```bash
cd ai-service && .venv/bin/python -m app.answerable_check --self
```

Expected: `OK — 트레이드오프 계산 6가지 통과`

- [ ] **Step 4: 부등호를 일부러 뒤집어 검사가 실제로 잡는지 확인**

`_tradeoff` 의 `if d <= threshold` 를 `if d < threshold` 로 잠깐 바꾸고 다시 실행.

```bash
cd ai-service && .venv/bin/python -m app.answerable_check --self
```

Expected: `AssertionError: 경계값이 유지가 아니다`

확인했으면 **`<=` 로 되돌린다.** 되돌린 뒤 Step 3 을 다시 돌려 `OK` 를 확인한다.

> 왜 이 단계가 있나: 통과하는 assert 는 <검사가 있다>는 것만 보여주고 <잡는다>는 것은
> 보여주지 않는다. 이 저장소는 회귀 테스트가 실제로는 아무것도 안 잡고 있던 것을
> 한 번 발견한 적이 있다(2026-09-05, `usage_events` 의 `occurred_at`).

- [ ] **Step 5: 커밋**

```bash
git add ai-service/app/answerable_check.py ai-service/app/fallback_e2e_check.py
git commit -m "$(cat <<'EOF'
feat: 판정 임계값 측정 스크립트 — 순수 함수와 자체 점검

트레이드오프 계산(_tradeoff·_tradeoff_table)과 검사 6가지.
경계(d1 == threshold)를 <유지>로 두는 것이 핵심이다 — search() 의
게이트가 `> answerable` 이라 부등호 방향이 어긋나면 표와 실제 동작이
경계값에서 갈린다. 부등호를 뒤집어 검사가 실제로 잡는 것도 확인했다.

guard() 는 기본 인자로 파라미터화했다. 홀드아웃 목록에도 같은 가드를
써야 하는데 복사하면 한쪽만 고쳐지는 사고가 구조적으로 가능해진다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: 홀드아웃 질문 10개 + 측정 모드

**Files:**
- Modify: `ai-service/app/answerable_check.py`

**Interfaces:**
- Consumes: Task 1 의 `_tradeoff_table`, `guard`, `UNGROUNDED`, `BOT_ID`, `embed_one`
- Produces: `d1(bot_id, question) -> float | None`, 채워진 `HOLDOUT`, 동작하는 `main()`

- [ ] **Step 1: 홀드아웃 질문 10개를 채운다**

`answerable_check.py` 의 `HOLDOUT = []` 를 아래로 교체.

```python
# ── 홀드아웃: 임계값을 고른 <뒤에만> 보는 근거없음 질문 ────────────────
#
# 기존 UNGROUNDED 10개와 <주제가 겹치지 않게> 골랐다. 겹치면 같은 문서가
# top1 으로 올라와 사실상 같은 측정을 두 번 하는 셈이 된다.
#
# 감시 낱말 규칙은 UNGROUNDED 와 같다 — 코퍼스에 그 낱말이 생기면
# 이 질문은 더 이상 "근거 없는 질문"이 아니다. guard() 가 막는다.
HOLDOUT: list[tuple[str, tuple[str, ...]]] = [
    ("사내 동호회 지원금이 있나요?", ("동호회", "동아리")),
    ("기숙사나 사택을 제공하나요?", ("기숙사", "사택")),
    ("통근버스가 운행하나요?", ("통근버스", "셔틀")),
    ("헌혈하면 휴가를 주나요?", ("헌혈",)),
    ("사내 벤처 제도가 있나요?", ("사내벤처",)),
    ("사내 도서관을 이용할 수 있나요?", ("도서관",)),
    ("주차장을 무료로 쓸 수 있나요?", ("주차",)),
    ("창립기념일에 쉬나요?", ("창립",)),
    ("사내 심리상담을 받을 수 있나요?", ("심리상담", "상담실")),
    ("회사 콘도를 예약할 수 있나요?", ("콘도", "리조트")),
]
```

- [ ] **Step 2: 가드를 먼저 돌려 질문이 쓸 수 있는지 확인**

아직 `main()` 이 없으므로 한 줄로 확인한다.

```bash
cd ai-service && .venv/bin/python -c "
from app.answerable_check import HOLDOUT
from app.fallback_e2e_check import guard
from app.db import close_pool
print('OK' if guard(HOLDOUT) else '🔴 걸림')
close_pool()"
```

Expected: `OK`

**걸린 질문이 있으면** 그 질문을 아래 대체 후보로 바꾸고 다시 돌린다 (10개를 유지할 것):

```
("사내 마사지실이 있나요?", ("마사지",))
("자녀 입학 축하금을 주나요?", ("입학",))
("업무용 자전거를 대여할 수 있나요?", ("자전거",))
("사내 세탁 서비스가 있나요?", ("세탁",))
("반차를 오전·오후 중 고를 수 있나요?", ("반차",))
```

> ⚠️ 대체 후보도 걸릴 수 있다. 걸리면 코퍼스에 없는 주제를 직접 찾아 만든다 —
> `SELECT count(*) FROM chunks WHERE bot_id='628d2785-a128-486c-a1ac-556f19f06de3' AND content LIKE '%낱말%'`
> 이 0 인 낱말이면 된다.

- [ ] **Step 3: 측정 코드를 넣는다**

`answerable_check.py` 의 `def main()` 을 아래로 교체하고, 그 **앞에** `d1` 과 `_measure` 를 추가한다.

```python
def d1(bot_id: UUID, question: str) -> float | None:
    """질문의 <벡터 최근접 거리>. 근거가 하나도 없으면 None.

    ⚠️ `retriever.search()` 의 첫 SQL 과 <같은 거리>를 재야 한다.
       거기서는 `ORDER BY distance LIMIT %s` 로 여러 건을 가져오고 그중 첫 행이
       최근접인데, 여기서는 그 첫 행 하나만 필요하므로 `LIMIT 1` 이다.
       JOIN documents 를 하지 않는 이유: 파일명이 필요 없고, 조인이 없으면
       documents 행이 없는 청크에서도 같은 값이 나온다(거리는 chunks 만의 성질이다).
    """
    qvec = embed_one(question)
    with cursor() as cur:
        cur.execute(
            """SELECT c.embedding <=> %s::vector AS distance
                 FROM chunks c
                WHERE c.bot_id = %s AND c.embedding IS NOT NULL
                ORDER BY distance
                LIMIT 1""",
            (qvec, bot_id),
        )
        row = cur.fetchone()
    return float(row[0]) if row else None


def _measure(label: str, questions: list[str]) -> list[float]:
    """질문 목록의 d1 을 재서 출력하고 돌려준다."""
    print(f"── {label} ({len(questions)}문항) ──")
    out: list[float] = []
    for q in questions:
        d = d1(BOT_ID, q)
        if d is None:
            print(f"  ⚠️  근거 청크가 하나도 없습니다: {q}")
            continue
        out.append(d)
        print(f"  {d:.4f}  {q[:44]}")
    if out:
        print(f"  → 최소 {min(out):.4f} · 중앙 {sorted(out)[len(out) // 2]:.4f} · 최대 {max(out):.4f}\n")
    return out


def _eval_questions() -> list[str]:
    """평가 테스트셋(16문항). evalrun._execute 와 <같은 조건>으로 읽는다."""
    with cursor() as cur:
        cur.execute(
            """SELECT question FROM eval_questions
                WHERE bot_id=%s AND is_active
                ORDER BY created_at""",
            (BOT_ID,),
        )
        return [r[0] for r in cur.fetchall()]


def main() -> None:
    if "--self" in sys.argv:
        _self_check()
        return

    _self_check()  # 측정 전에 계산 로직부터 검증한다

    if "--holdout" in sys.argv:
        # 🔴 홀드아웃 모드 — 임계값을 <이미 고른 뒤에> 돌린다.
        print("── 홀드아웃 질문 점검 (감시 낱말이 코퍼스에 없는가) ──")
        if not guard(HOLDOUT):
            print("\n🔴 중단합니다. 답이 있을 수 있는 질문으로 재면 <거짓 차단률>이 나옵니다.")
            sys.exit(1)
        print(f"OK — 홀드아웃 {len(HOLDOUT)}개 전부 코퍼스에 흔적 없음\n")

        held = _measure("홀드아웃 · 근거없음", [q for q, _ in HOLDOUT])
        print("── 임계값별 홀드아웃 차단률 ──")
        for t, _, blocked in _tradeoff_table([], held):
            print(f"  {t:.2f}  차단 {blocked:2d}/{len(held)}")
        return

    # ── 기본 모드: 임계값을 고르기 위한 표 ──
    # 🔴 홀드아웃은 <읽지도 않는다.> 보면서 고르면 홀드아웃이 아니게 된다.
    print("── 근거없음 질문 점검 (감시 낱말이 코퍼스에 없는가) ──")
    if not guard():
        print("\n🔴 중단합니다.")
        sys.exit(1)
    print(f"OK — 근거없음 {len(UNGROUNDED)}개 전부 코퍼스에 흔적 없음\n")

    grounded = _measure("평가 테스트셋 · 근거있음", _eval_questions())
    ungrounded = _measure("근거없음", [q for q, _ in UNGROUNDED])

    print("── 임계값 트레이드오프 (결과가 바뀌는 지점만) ──")
    print(f"  {'임계':>6}  {'정답유지':>8}  {'근거없음차단':>12}")
    for t, kept, blocked in _tradeoff_table(grounded, ungrounded):
        print(f"  {t:6.2f}  {kept:5d}/{len(grounded):<2d}  {blocked:8d}/{len(ungrounded):<2d}")
    print("\n⚠️  경계값에 딱 붙여 고르지 말 것 — 분포가 조금만 흔들려도 뚫린다.")
    print("    고른 뒤 `--holdout` 으로 검증할 것.")
```

- [ ] **Step 4: 자체 점검이 여전히 통과하는지 확인**

```bash
cd ai-service && .venv/bin/python -m app.answerable_check --self
```

Expected: `OK — 트레이드오프 계산 6가지 통과`

- [ ] **Step 5: 커밋** (측정은 Task 3 에서 돌린다 — 코드와 측정을 나눠 커밋해야 "코드가 이래서 이 숫자가 나왔다"가 읽힌다)

```bash
git add ai-service/app/answerable_check.py
git commit -m "$(cat <<'EOF'
feat: 판정 임계값 측정 — 홀드아웃 질문 10개와 측정 모드

기본 모드는 평가 16문항 + 근거없음 10문항의 d1 을 재고 트레이드오프 표를 낸다.
--holdout 은 고른 뒤에만 돌린다 — 같은 표에 띄우면 보면서 고르게 되고
그 순간 홀드아웃이 아니게 된다.

홀드아웃 질문은 기존 UNGROUNDED 와 주제가 겹치지 않게 골랐다.
겹치면 같은 문서가 top1 으로 올라와 같은 측정을 두 번 하는 셈이다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: 측정 실행 → 임계값 선택

코드를 안 고친다. **측정하고 고르는 단계다.**

- [ ] **Step 1: DB 가 떠 있는지 확인**

```bash
docker compose ps
```

Expected: `alldap-db` 가 `Up ... (healthy)`. 아니면 `docker compose up -d`.

- [ ] **Step 2: 기본 모드로 측정한다**

```bash
cd ai-service && .venv/bin/python -m app.answerable_check
```

Expected: 가드 통과 → 평가 16문항 d1 → 근거없음 10문항 d1 → 트레이드오프 표.

**출력을 그대로 저장한다** (다음 단계와 문서에 붙인다):

```bash
cd ai-service && .venv/bin/python -m app.answerable_check | tee /tmp/answerable-baseline.txt
```

- [ ] **Step 3: 임계값을 고른다**

표를 보고 고른다. **기준 두 개:**

1. **정답 유지가 최대한 높을 것.** 정답을 자르면 fallback 이 늘고 응답률이 떨어진다.
2. **경계에 붙이지 말 것.** `0.3777` 이 근거없음 최솟값(`0.3839`)에 딱 붙은 값이라
   분포가 조금만 흔들려도 뚫린다. 근거없음 최솟값과 정답 최댓값 사이에 **여유 구간**이
   있으면 그 안에서 **정답 쪽에 가깝게**(= 더 낮게) 잡는다.

> 🔴 **AGENTS.md 의 0.3777 을 그대로 쓰지 말 것.** 그 값이 재현되는지부터가 이 측정의 목적이다.
> 코퍼스·임베딩이 그때와 같아 비슷하게 나오는 것이 정상이지만, **다르게 나오면 다른 쪽이 맞다** —
> 지금 측정이 재현 가능한 쪽이다.

**🔴 두 분포가 겹치면 (= 정답 유지 16/16 과 근거없음 차단 10/10 을 동시에 만족하는 임계값이 없으면)**

겹치는 것이 정상이다. 그때는 **정답 유지를 우선하되, 잘리는 문항이 <어느 것인지>를 본다.**

```bash
cd ai-service && .venv/bin/python -c "
from app.answerable_check import d1, _eval_questions
from app.fallback_e2e_check import BOT_ID
from app.db import close_pool
T = <고른 값>
for q in _eval_questions():
    d = d1(BOT_ID, q)
    if d is not None and d > T:
        print(f'잘림 {d:.4f}  {q}')
close_pool()"
```

- 잘리는 문항이 **원래도 fallback 이던 것**(재택 주 2회 · 기간제 연차)이면 **손해가 없다** —
  이미 못 답하던 질문이 답변 경로 대신 판정에서 걸리는 것뿐이라 전체충실성이 안 움직인다.
- 잘리는 문항이 **원래 1.000 이던 것**이면 그만큼 전체충실성이 떨어진다.
  16문항 중 1개면 `-0.063` 이고 이는 편차(0.032)의 2배라 필수 기준(`0.843` 이상)을 위협한다.
  → 그 경우 임계값을 **더 높게** 잡아 그 문항을 살리고, 차단률이 5/10 아래로 떨어지면
  **이 기능을 켜지 않는다**(Task 6 에서 `None` 유지 + 반증 기록).

- [ ] **Step 4: 고른 값으로 홀드아웃을 검증한다**

```bash
cd ai-service && .venv/bin/python -m app.answerable_check --holdout | tee /tmp/answerable-holdout.txt
```

기본 모드에서 고른 임계값의 **홀드아웃 차단률**을 본다.

**판정:**
- 기존 10문항 차단률과 **비슷하면** 통과 — 과적합이 아니라는 근거가 된다.
- **크게 낮으면** 과적합 신호다. 임계값을 더 보수적으로(낮게) 다시 고르고 이 단계를 반복한다.

- [ ] **Step 5: 측정 결과를 결정 로그에 남긴다**

`docs/decisions.md` 맨 아래에 한 줄 추가. `<고른 값>` · `<수치>` 는 실제 측정값으로 채운다.

```
2026-09-06 | 판정 임계값(answerable_max_distance)을 <고른 값> 으로 정했다 | 트레이드오프 표에서 정답 유지 <N>/16 · 근거없음 차단 <M>/10 이고, 홀드아웃 10문항에서도 <K>/10 이 차단돼 이 테스트셋에 과적합된 값이 아님을 확인했다. 경계에 붙이지 않은 이유: AGENTS.md 의 0.3777 은 근거없음 최솟값(0.3839)에 딱 붙은 값이라 분포가 조금만 흔들려도 뚫린다 | ① 0.3777 그대로: 경계값이라 취약하다 ② 더 높게: 차단률이 떨어져 비용 절감 경로가 안 열린다 ③ 더 낮게: 정답을 자르기 시작한다
```

```bash
git add docs/decisions.md
git commit -m "$(cat <<'EOF'
docs: 판정 임계값 측정 결과와 선택 근거

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: 판정 게이트 구현

**Files:**
- Modify: `ai-service/app/config.py` (`max_distance` 정의 **바로 아래**)
- Modify: `ai-service/app/retriever.py` (`search()` 안, `rows` 를 가져온 직후)

**Interfaces:**
- Consumes: Task 3 에서 고른 임계값
- Produces: `Settings.answerable_max_distance: float | None`

- [ ] **Step 1: 설정을 추가한다**

`ai-service/app/config.py` 에서 `max_distance: float = 0.55` 줄 **바로 아래**에 추가.
`<고른 값>` 은 Task 3 의 결과로 채운다. **Task 6 까지는 `None`(꺼짐)으로 둔다** —
검증 전에 켜면 "켜고 나서 쟀다"가 되어 before/after 가 성립하지 않는다.

```python
    # ── 판정: 근거가 <있는가> (위 컷과 별개다) ────────────────────────
    #
    # 🔴 max_distance 하나가 <두 일>을 겸하고 있었다. 둘은 반대 방향을 원한다:
    #      ① 어떤 청크를 근거로 쓸지 (개수)  — 높아야 한다. 낮추면 근거가 줄어 답이 틀린다
    #      ② 근거가 있는지 없는지 판정      — 낮아야 한다. 높으면 아무 질문에나 근거가 붙는다
    #    그래서 어느 쪽으로 움직여도 다른 쪽이 나빠졌다(위 0.45·0.43 측정).
    #    이 값이 ②만 맡는다. 컷은 0.55 그대로다.
    #
    # None = 게이트 없음(2026-09-06 이전 동작). 값이 있으면 <벡터 최근접 거리>가
    #        이보다 먼 질문은 근거를 통째로 버려 LLM 을 아예 부르지 않는다.
    #
    # 왜 이게 필요한가 — 논거 셋, 무게 순서:
    #   ① 🔴 2차 방어선(NO_ANSWER)은 <봇 지침 한 줄로 뚫린다>(bot_prompt_check 실측).
    #      "모르는 것도 아는 척 답해" 를 넣으면 근거 없는 질문에 is_fallback=False 로 답한다.
    #      1차 방어선은 프롬프트로 못 뚫는다 — 코드이기 때문이다.
    #   ② 비용: 평가 1회 804 뉴런 중 생성이 380.3(47.3%)이다.
    #   ③ 지연: 검색컷에 걸리면 119~170ms, 생성까지 가면 1.5초대다.
    #
    # ⚠️ 이 값은 <코퍼스와 임베딩 모델에 딸려 있다.> 둘 중 하나라도 바뀌면 무효다.
    #    `python -m app.answerable_check` 로 다시 재고 고를 것.
    #    (임베딩을 bge-m3 로 바꿨을 때 1차 방어선이 0/10 → 4/10 으로 살아난 전례가 있다)
    answerable_max_distance: float | None = None
```

- [ ] **Step 2: 판정 게이트를 넣는다**

`ai-service/app/retriever.py` 의 `search()` 안에서, `rows = list(cur.fetchall())` 바로 **다음 줄**,
`if hybrid:` 블록 **앞**에 삽입한다.

```python
    # ── 판정: 근거가 <있는가> (max_distance 컷과 별개다) ──────────────
    #
    # ⚠️ rows[0] 은 <벡터 최근접>이고, 하이브리드 재정렬 <전에> 봐야 한다:
    #      · rows 는 ORDER BY distance 로 왔으므로 rows[0] 이 최근접이다.
    #      · 하이브리드가 덧붙이는 키워드 행은 벡터 top-N <밖>이라 항상 이보다 멀다.
    #      · 리랭커는 순서만 바꾸고 거리를 안 건드린다.
    #    → 리랭커·하이브리드를 어떻게 켜든 판정값이 안 흔들린다.
    #      편의가 아니라 <비교가 성립하기 위한 조건>이다. 판정이 설정에 따라 흔들리면
    #      무엇 때문에 점수가 변했는지 알 수 없다(같은 이유로 아래 컷도 벡터 거리를 쓴다).
    #
    # 빈 목록을 돌려주면 generator.generate 가 LLM 을 안 부르고 fallback 한다.
    # 새 상태도 새 경로도 만들지 않는다.
    answerable = s.answerable_max_distance
    if answerable is not None and (not rows or rows[0][4] > answerable):
        return []
```

- [ ] **Step 3: 게이트가 실제로 도는지 확인한다** (설정을 임시로 켜서)

`<고른 값>` 은 Task 3 의 결과.

```bash
cd ai-service && ANSWERABLE_MAX_DISTANCE=<고른 값> .venv/bin/python -c "
from uuid import UUID
from app.retriever import search
from app.db import close_pool
BOT = UUID('628d2785-a128-486c-a1ac-556f19f06de3')
print('근거없음(사내 헬스장):', len(search(BOT, '사내 헬스장 이용 시간은 어떻게 되나요?')), '건')
print('근거있음(인턴 식대)  :', len(search(BOT, '인턴 사원의 식대는 월 얼마인가요?')), '건')
close_pool()"
```

Expected: 근거없음 **0건** · 근거있음 **1건 이상**.

> 근거없음이 0건이 아니면 게이트가 안 도는 것이다. 환경변수 이름(`ANSWERABLE_MAX_DISTANCE`)과
> `config.py` 의 필드명이 맞는지, 삽입 위치가 `rows` 획득 **뒤**인지 확인한다.

- [ ] **Step 4: 게이트를 끈 상태(기본값 None)에서 기존 동작이 그대로인지 확인한다**

```bash
cd ai-service && .venv/bin/python -c "
from uuid import UUID
from app.retriever import search
from app.db import close_pool
BOT = UUID('628d2785-a128-486c-a1ac-556f19f06de3')
print('근거없음(사내 헬스장):', len(search(BOT, '사내 헬스장 이용 시간은 어떻게 되나요?')), '건')
close_pool()"
```

Expected: **5건** (게이트가 꺼져 있으므로 기존 동작 — 근거가 붙어서 통과한다).

- [ ] **Step 5: 커밋**

```bash
git add ai-service/app/config.py ai-service/app/retriever.py
git commit -m "$(cat <<'EOF'
feat: 판정 게이트 — 근거가 없으면 LLM 을 부르지 않는다

max_distance 가 겸하던 두 일 중 <판정>을 answerable_max_distance 로 분리한다.
컷(0.55)은 그대로 두어 근거 개수를 유지하고, 벡터 최근접 거리로만 판정한다.

rows[0] 을 하이브리드 재정렬 전에 보는 것이 핵심이다 — 키워드 행은 벡터 top-N
밖이라 항상 더 멀고 리랭커는 거리를 안 건드리므로, 두 설정을 어떻게 켜든
판정값이 안 흔들린다. 비교가 성립하기 위한 조건이다.

기본값은 아직 None(꺼짐)이다. Task 5 검증 전에 켜면 before/after 가 성립하지 않는다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: 검증 — 필수 기준 3개

코드를 안 고친다. **켠 상태로 재는 단계다.** `<고른 값>` 은 Task 3 의 결과.

- [ ] **Step 1: `fallback_e2e_check` — 게이트를 켠 상태**

```bash
cd ai-service && ANSWERABLE_MAX_DISTANCE=<고른 값> .venv/bin/python -m app.fallback_e2e_check | tee /tmp/answerable-fallback-on.txt
```

**필수 기준:**
- `fallback 10/10` (기준 8)
- `대조군 3/3`

**목표 기준:**
- `그중 검색컷` 이 **5건 이상** (지금은 1건)

> 하나라도 깨지면 Task 3 으로 돌아가 임계값을 다시 고른다.

- [ ] **Step 2: 평가 실행 3회 — 게이트를 켠 상태**

Python 서비스를 켠 채로 띄우고 평가를 3회 돌린다.

```bash
cd ai-service && ANSWERABLE_MAX_DISTANCE=<고른 값> .venv/bin/uvicorn app.main:app --port 8001
```

다른 터미널에서 **3회** (한 번에 하나씩, 끝난 뒤 다음):

```bash
curl -X POST localhost:8001/internal/bots/628d2785-a128-486c-a1ac-556f19f06de3/eval/runs
```

- [ ] **Step 3: 3회 결과를 읽는다**

```bash
cd /Users/cheonjamin/projects/AllDap && docker compose exec -T db psql -U alldap -d alldap -c "
SELECT status, created_at::time(0) AS 시각,
       avg_faithfulness AS 충실성, avg_relevancy AS 관련성, answered_rate AS 응답률,
       scored_count || '/' || question_count AS 채점,
       round(avg_faithfulness * scored_count / NULLIF(question_count,0), 3) AS 전체충실성
  FROM eval_runs
 WHERE bot_id = '628d2785-a128-486c-a1ac-556f19f06de3'
 ORDER BY created_at DESC LIMIT 3;"
```

> 컬럼명 주의: **`avg_relevancy`**(relevance 아님) · **`question_count`**(total_count 아님).
> 전체충실성 계산식은 `evalrun.py:34` 의 정의 그대로다 —
> `avg_faithfulness × scored_count / question_count`.

**필수 기준: 전체충실성 `0.875` 유지** (편차 0.032 안 = `0.843` 이상).

> 🔴 **`status` 가 `completed` 인지 반드시 볼 것.** `failed` 는 전부 실패한 실행이고,
> 일부만 실패한 실행은 `completed` 로 남는다. 지표가 NULL 이면 그 실행은 측정이 아니다.
> 오염 판정은 `scored_count` 가 아니라 **`generated_answer IS NULL` 행의 존재**로 한다 —
> `scored_count` 는 fallback 이 많으면 자연히 작아지는 정상값이다(2026-08-13 에 여기서 한 번 틀렸다).

- [ ] **Step 4: 홀드아웃 최종 확인**

```bash
cd ai-service && .venv/bin/python -m app.answerable_check --holdout
```

고른 임계값의 차단률이 Task 3 Step 4 와 같은지 본다. 다르면 코퍼스가 바뀐 것이다.

- [ ] **Step 5: 결과를 임시 파일에 정리한다** (Task 6 에서 문서로 옮긴다)

```bash
cat /tmp/answerable-baseline.txt /tmp/answerable-holdout.txt /tmp/answerable-fallback-on.txt > /tmp/answerable-all.txt && wc -l /tmp/answerable-all.txt
```

---

## Task 6: 기본값 결정 + 문서

**Files:**
- Modify: `ai-service/app/config.py` (기본값)
- Modify: `AGENTS.md` (진행 상황 · 알려진 한계)
- Modify: `docs/decisions.md` (결정 한 줄)

- [ ] **Step 1: 기본값을 정한다**

Task 5 의 필수 기준 3개가 **전부** 통과했으면 `config.py` 의 기본값을 `None` → `<고른 값>` 으로 바꾼다.

```python
    answerable_max_distance: float | None = <고른 값>
```

**하나라도 깨졌으면 `None` 으로 둔다.** 그 경우 아래 문서에 "왜 안 켰는가" 를 적는다 —
이 저장소는 반증된 시도를 지우지 않는다.

- [ ] **Step 2: `config.py` 주석에 측정 결과를 박는다**

Step 1 에서 넣은 주석 블록 **끝**에 실측 표를 추가. `<수치>` 는 Task 5 의 실제 값.

```python
    # ── 2026-09-06 측정 (설정당 3회) ──────────────────────────────────
    #
    #   설정         전체충실성   fallback   그중 검색컷   대조군
    #   None(꺼짐)   0.875        10/10      1/10          3/3
    #   <고른 값>    <수치>       <수치>     <수치>        <수치>
    #
    # 홀드아웃 10문항(임계값 결정에 쓰지 않은 질문) 차단 <K>/10 —
    # 기존 10문항의 <M>/10 과 비슷해 이 테스트셋에 과적합된 값이 아니다.
```

- [ ] **Step 3: `AGENTS.md` 를 갱신한다**

**세 곳:**

1. "🔴 W4 는 끝났다. 다음 후보" 절의 **1번 항목**(1차 방어선 되살리기)을 결과로 교체.
   켰으면 `✅`, 안 켰으면 반증 기록으로.
2. "알려진 한계" 의 **1차 방어선 항목** — "되살릴 수 없다" 는 서술을 실제 결과와 맞춘다.
3. "남은 구멍" 에서 이 항목이 있으면 뺀다.

> ⚠️ **`AGENTS.md` 의 `d1` 표(0.3777 · 15/16 · 10/10)에 재현 방법을 붙인다.**
> 그 표를 돌린 스크립트가 없던 것이 이 슬라이스가 시작된 이유 중 하나다:
> `→ 재현: cd ai-service && .venv/bin/python -m app.answerable_check`

- [ ] **Step 4: 결정 로그에 최종 한 줄**

`docs/decisions.md` 맨 아래에 추가. 켠 경우:

```
2026-09-06 | 판정(answerable_max_distance)과 컷(max_distance)을 분리해 1차 방어선을 되살렸다 | 한 값이 반대 방향을 원하는 두 일을 겸하고 있었다 — 근거 선별은 값이 높아야 하고(낮추면 근거가 줄어 답이 틀린다, 0.45·0.43 실측) 근거 유무 판정은 낮아야 한다(높으면 아무 질문에나 근거가 붙는다). 컷을 0.55 로 둔 채 벡터 최근접 거리로만 판정하니 검색컷이 1/10 → <N>/10 이 되면서 전체충실성 <수치> 를 유지했다. 판정을 rows[0](하이브리드 재정렬 전)에서 하는 것이 핵심인데, 그래야 리랭커·하이브리드를 어떻게 켜든 판정값이 안 흔들려 비교가 성립한다. 가장 무거운 논거는 비용도 지연도 아니다 — 2차 방어선(NO_ANSWER)은 봇 지침 한 줄로 뚫리는 것이 실측돼 있고(bot_prompt_check), 1차 방어선은 코드라 프롬프트로 못 뚫는다 | ① max_distance 를 낮추기: 2026-08-17 에 기각됐다(응답률 +0.063 의 대가가 오답 2건) ② 점수 격차(d5-d1·d2-d1): 2026-08-17 에 반증됐다(차단 3/10·0/10) ③ 봇별 상대 임계값: 봇이 하나뿐이고 분포를 잴 데이터도 없는데 매 질문 계산이 붙는다 ④ 두 신호 조합(거리+근거 개수): 표본 26문항에서 파라미터를 늘리는 것은 과적합을 키우는 정확한 방법이고, "값 하나가 두 일을 겸한다"를 고치려다 값 셋으로 가는 셈이다
```

- [ ] **Step 5: 커밋하고 PR 을 연다**

```bash
git add ai-service/app/config.py AGENTS.md docs/decisions.md
git commit -m "$(cat <<'EOF'
feat: 판정 게이트 기본값과 측정 결과 문서화

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
git push -u origin feat/answerability-gate
gh pr create --fill
```

PR 본문은 `.github/PULL_REQUEST_TEMPLATE.md` 를 채운다. **두 칸이 핵심이다:**

- **한계 & 트레이드오프** — 표본 36문항의 한계, 코퍼스·임베딩이 바뀌면 무효라는 것,
  홀드아웃이 과적합을 배제하지 않고 **줄일 뿐**이라는 것.
- **검토한 대안과 선택 이유** — 위 결정 로그의 ①~④.

**어떻게 해결했나요** 칸에는 "돌려봤다" 가 아니라 **실제 실행 결과**를 붙인다
(`/tmp/answerable-all.txt` 의 표).
