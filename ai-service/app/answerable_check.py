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

from .db import close_pool, cursor
from .fallback_e2e_check import BOT_ID, UNGROUNDED, guard
from .retriever import embed_one
from .schemas import Id

# ── 홀드아웃: 임계값을 고른 <뒤에만> 보는 근거없음 질문 ────────────────
#
# 기존 UNGROUNDED 10개와 <주제가 겹치지 않게> 골랐다. 겹치면 같은 문서가
# top1 으로 올라와 사실상 같은 측정을 두 번 하는 셈이 된다.
#
# 감시 낱말 규칙은 UNGROUNDED 와 같다 — 코퍼스에 그 낱말이 생기면
# 이 질문은 더 이상 "근거 없는 질문"이 아니다. guard() 가 막는다.
# 🔴 처음 고른 10개 중 <6개가 가드에 걸렸다.> 코퍼스에 실제로 그 문서가 있었다:
#    동호회(24_사내동호회) · 기숙사/사택(39) · 통근버스(38) · 주차(22) · 창립(41_장기근속).
#    사람이 "이건 없겠지" 하고 고른 것의 절반이 틀렸다는 뜻이다 —
#    가드가 없었다면 <근거가 있는 질문으로 차단률을 재고> 그 숫자를 믿을 뻔했다.
HOLDOUT: list[tuple[str, tuple[str, ...]]] = [
    ("헌혈하면 휴가를 주나요?", ("헌혈",)),
    ("사내 벤처 제도가 있나요?", ("사내벤처",)),
    ("사내 도서관을 이용할 수 있나요?", ("도서관",)),
    ("사내 심리상담을 받을 수 있나요?", ("심리상담", "상담실")),
    ("회사 콘도를 예약할 수 있나요?", ("콘도", "리조트")),
    ("사내에 수면실이 있나요?", ("수면실", "낮잠")),
    ("사내 마사지 서비스를 받을 수 있나요?", ("마사지",)),
    ("회사에서 세탁 서비스를 제공하나요?", ("세탁",)),
    ("자전거로 출퇴근하면 거치대가 있나요?", ("자전거",)),
    ("개인 택배를 회사로 받아도 되나요?", ("택배",)),
]


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


def d1(bot_id: Id, question: str) -> float | None:
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


if __name__ == "__main__":
    try:
        main()
    finally:
        close_pool()
