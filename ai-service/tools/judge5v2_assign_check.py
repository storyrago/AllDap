"""tools.judge5v2_assign 의 점검. DB 도 외부 API 도 쓰지 않는다.

실행:  cd ai-service && python -m tools.judge5v2_assign_check

배정이 틀리면 정답 점수 분포가 스펙 7-1절과 달라지거나, 자격이 없는 질문에 ③, ④가 붙어
정답 점수가 하나로 정해지지 않는 문항이 생긴다(스펙 3-2절). 어느 쪽도 결과 숫자로는 드러나지 않는다.
"""
from __future__ import annotations

import random
from collections import Counter

from .judge5v2_assign import (
    Shortfall, assign_domain, assigned_types, pool_for, replay_round, run_round, supplement_needs, valid_contrast,
)
from .judge5v2_files import DOMAINS, QUOTA

_CONTRAST = {"asked": {"target": "골드", "value": "10,000원"}, "other": {"target": "실버", "value": "20,000원"},
             "chunk_ids": [1]}


def _pool(domain: str = "shop", n: int = 75, even: int = 20, odd3: int = 15, contrast_every: int = 7) -> list[dict]:
    """주장 2개 even 개, 주장 3개 odd3 개, 나머지는 주장 1개. 주장 2개짜리만 답이 두 가지인 질문(two_part)이다.
    답이 하나인 질문 중 contrast_every 번째마다 ⑧ 조건을 만족한다(⑧ 은 답이 하나인 질문에만 붙는다)."""
    out = []
    for i in range(n):
        claims = 2 if i < even else 3 if i < even + odd3 else 1
        two_part = i < even
        out.append({"qid": f"{domain}-{i:03d}", "domain": domain, "question": f"질문 {i}", "answer": f"답 {i}",
                    "claims": claims, "two_part": two_part,
                    "contrast": _CONTRAST if not two_part and i % contrast_every == 0 else None})
    return out


def check_assign_meets_quota_and_eligibility() -> None:
    res, short = assign_domain(_pool(), dict(QUOTA), random.Random("s"))
    assert short == {}
    assert Counter(res["types"].values()) == Counter(QUOTA)
    claims = {q["qid"]: q for q in _pool()}
    for qid, t in res["types"].items():
        c = claims[qid]["claims"]
        if t == 4:
            assert c >= 2 and c % 2 == 0, qid
        if t == 3:
            assert c >= 2, qid
        if t == 8:
            assert claims[qid]["contrast"] is not None, qid
        if t in (6, 8):
            assert not claims[qid]["two_part"], qid
    assert len(res["unused"]) == 75 - 60 and res["eighth_to_sixth"] == 0


def check_assign_is_reproducible_and_order_free() -> None:
    """같은 입력과 같은 시드면 같은 배정이다(스펙 3-3절). 입력 순서는 결과를 바꾸지 않는다."""
    a, _ = assign_domain(_pool(), dict(QUOTA), random.Random("s"))
    b, _ = assign_domain(_pool()[::-1], dict(QUOTA), random.Random("s"))
    c, _ = assign_domain(_pool(), dict(QUOTA), random.Random("다른 시드"))
    assert a == b and a != c


def check_assign_moves_missing_eighth_to_sixth() -> None:
    """⑧ 조건을 만족하는 질문이 모자라면 ⑥ 으로 채운다(스펙 3-3절 5). 둘 다 정답 점수가 1이다."""
    pool = _pool(contrast_every=10**6)           # ⑧ 조건을 만족하는 질문이 없다(0번은 답이 두 가지라 붙지 않는다)
    pool[60]["contrast"] = _CONTRAST             # 주장 1개라 ④, ③ 에 뽑히지 않는 답이 하나인 질문에 하나만 붙인다
    res, short = assign_domain(pool, dict(QUOTA), random.Random("s"))
    counts = Counter(res["types"].values())
    assert short == {} and counts[8] == 1 and counts[6] == QUOTA[6] + QUOTA[8] - 1
    assert res["eighth_to_sixth"] == QUOTA[8] - 1


def check_assign_sixth_and_eighth_need_single_answer() -> None:
    """⑥, ⑧ 은 답이 하나인 질문에만 붙는다(스펙 3-2절). 그런 질문이 모자라면 ⑥ 이 모자란다고 알린다(스펙 3-3절 5)."""
    pool = _pool()
    for i, q in enumerate(pool):
        q["two_part"], q["contrast"] = i < 65, None  # 답이 하나인 질문은 마지막 10개(65~74번, 주장 1개)뿐이다
    pool[0]["contrast"] = _CONTRAST                  # 답이 두 가지인 질문의 contrast 는 ⑧ 자격이 아니다
    res, short = assign_domain(pool, dict(QUOTA), random.Random("s"))
    counts = Counter(res["types"].values())
    assert counts[8] == 0 and res["eighth_to_sixth"] == QUOTA[8]
    assert counts[6] == 10 and short == {6: QUOTA[6] + QUOTA[8] - 10}
    assert all(int(qid[-3:]) >= 65 for qid, t in res["types"].items() if t == 6)


def check_assign_reports_fourth_and_third_shortfall() -> None:
    """④, ③ 자격 질문이 모자라면 다른 유형으로 채우지 않고 모자란 수를 알린다(스펙 3-3절 4)."""
    _, short = assign_domain(_pool(even=5, odd3=0), dict(QUOTA), random.Random("s"))
    assert short[4] == QUOTA[4] - 5 and short[3] == QUOTA[3]
    try:
        run_round({d: _pool(d, even=5, odd3=0) for d in DOMAINS},
                  {d: dict(QUOTA) for d in DOMAINS}, 1, 0)
    except Shortfall as e:
        assert set(e.short) == set(DOMAINS)
        return
    raise AssertionError("모자라면 Shortfall 이어야 한다")


def check_replay_reproduces_round() -> None:
    pools = {d: _pool(d) for d in DOMAINS}
    needs = {d: dict(QUOTA) for d in DOMAINS}
    domains = run_round(pools, needs, 20261005, 0)
    rnd = {"pool": {d: [q["qid"] for q in pools[d]] for d in DOMAINS},
           "needs": {d: {str(t): n for t, n in QUOTA.items()} for d in DOMAINS}, "domains": domains}
    by_id = {q["qid"]: q for d in DOMAINS for q in pools[d]}
    assert replay_round(rnd, by_id, 20261005, 0) == domains


def check_supplement_needs_counts_only_drops() -> None:
    res, _ = assign_domain(_pool(), dict(QUOTA), random.Random("s"))
    empty = {"types": {}, "unused": [], "eighth_to_sixth": 0}
    assignment = {"seed": 1, "rounds": [{"domains": {"shop": res, "hr": empty, "manual": empty, "finance": empty}}]}
    fourth = sorted(q for q, t in res["types"].items() if t == 4)[:2]
    domain_of = {q: "shop" for q in res["types"]}
    needs = supplement_needs(assignment, set(fourth), domain_of)
    assert needs["shop"] == {t: (2 if t == 4 else 0) for t in QUOTA}
    assert needs["hr"] == QUOTA
    assert assigned_types(assignment) == res["types"]


def check_valid_contrast() -> None:
    """⑧ 조건은 두 값이 근거 청크에 글자 그대로 있고 서로 다를 때만이다(스펙 3-2절)."""
    src = [{"chunk_id": 1, "content": "골드 10,000원 / 실버 20,000원"}, {"chunk_id": 2, "content": "다른 내용"}]
    assert valid_contrast(_CONTRAST, src) is None
    same = {**_CONTRAST, "other": {"target": "실버", "value": "10,000원"}}
    assert valid_contrast(same, src) is not None                       # 값이 같다
    assert valid_contrast({**_CONTRAST, "chunk_ids": [2]}, src) is not None   # 그 청크에 값이 없다
    assert valid_contrast({**_CONTRAST, "chunk_ids": [9]}, src) is not None   # 근거 청크가 아니다
    near = [{"chunk_id": 1, "content": "골드 110,000원 / 실버 20,000원"}]
    assert valid_contrast(_CONTRAST, near) is not None   # 10,000원 은 110,000원 의 일부일 뿐이다(값 경계)


def check_pool_for_uses_last_search_and_refuses_two_part_contrast() -> None:
    """검색 줄은 질문마다 마지막 줄이 판정이다(계획 형식 2). 답이 두 가지인 질문의 contrast 는 잘못 적은 것이다."""
    src = [{"chunk_id": 1, "content": "골드 10,000원 / 실버 20,000원"}]
    q = {"qid": "shop-001", "domain": "shop", "answer": "답", "claims": 1, "two_part": False, "contrast": _CONTRAST}
    tried = [{"qid": "shop-001", "status": "dropped", "drop_reason": "rerank_failed", "sources": src},
             {"qid": "shop-001", "status": "ok", "drop_reason": None, "sources": src}]
    assert [x["qid"] for x in pool_for([q], tried)["shop"]] == ["shop-001"]   # 다시 검색해 성공했다
    assert pool_for([q], tried[::-1])["shop"] == []                          # 마지막 시도가 호출 실패다
    try:
        pool_for([dict(q, two_part=True)], tried)
    except ValueError:
        return
    raise AssertionError("답이 두 가지인 질문의 contrast 는 거절해야 한다")


CHECKS = [
    check_assign_meets_quota_and_eligibility,
    check_assign_is_reproducible_and_order_free,
    check_assign_moves_missing_eighth_to_sixth,
    check_assign_sixth_and_eighth_need_single_answer,
    check_assign_reports_fourth_and_third_shortfall,
    check_replay_reproduces_round,
    check_supplement_needs_counts_only_drops,
    check_valid_contrast,
    check_pool_for_uses_last_search_and_refuses_two_part_contrast,
]


def main() -> None:
    for fn in CHECKS:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(CHECKS)}가지 전부 통과.")


if __name__ == "__main__":
    main()
