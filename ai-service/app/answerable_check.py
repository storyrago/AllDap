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
