"""tools.judge5v2_gate 의 점검. DB 도 외부 API 도 쓰지 않는다.

실행:  cd ai-service && python -m tools.judge5v2_gate_check

관문 계산이 틀리면 변별력이 없는 시험 문제로 모델을 돌리게 된다. 앞 실험이 그렇게 끝났다(스펙 1-1절).
"""
from __future__ import annotations

from .judge5v2_files import DOMAINS, QUOTA, TABLE_SCORE
from .judge5v2_gate import check_gate, fake_within1


def _full() -> list[dict]:
    return [{"domain": d, "type": t, "score": TABLE_SCORE[t]} for d in DOMAINS for t, n in QUOTA.items() for _ in range(n)]


def check_fake_ratios_match_spec() -> None:
    """스펙 7-1절의 가짜 모델 수치: 늘 5점 45%, 늘 4점 60%, 늘 3점 40%, 늘 2점 55%, 늘 1점 40%."""
    got = {k: round(v, 4) for k, v in fake_within1([c["score"] for c in _full()]).items()}
    assert got == {1: 0.40, 2: 0.55, 3: 0.40, 4: 0.60, 5: 0.45}, got


def check_gate_passes_on_full_quota() -> None:
    assert all(c.ok for c in check_gate(_full()))


def check_gate_fails_each_condition() -> None:
    def failed(cases: list[dict]) -> set[int]:
        return {c.no for c in check_gate(cases) if not c.ok}

    full = _full()
    assert 1 in failed(full[:199])
    assert {2, 3, 5} <= failed([dict(c, score=5) for c in full])          # 모두 5점
    no_hr = [c for c in full if c["domain"] != "hr"] + [c for c in full if c["domain"] == "hr"][:39]
    assert 4 in failed(no_hr)                                              # hr 이 39문항
    eighth = [c for c in full if c["type"] == 8]
    assert 4 in failed([c for c in full if c["type"] != 8] + eighth[:14])  # ⑧ 이 14문항
    assert failed([]) >= {1, 2, 3, 4, 5}                                   # 빈 시험은 모두 실패


CHECKS = [check_fake_ratios_match_spec, check_gate_passes_on_full_quota, check_gate_fails_each_condition]


def main() -> None:
    for fn in CHECKS:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(CHECKS)}가지 전부 통과.")


if __name__ == "__main__":
    main()
