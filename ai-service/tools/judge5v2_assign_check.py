"""tools.judge5v2_assign 의 점검. DB 도 외부 API 도 쓰지 않는다.

실행:  cd ai-service && python -m tools.judge5v2_assign_check

배정이 틀리면 정답 점수 분포가 스펙 7-1절과 달라지거나, 자격이 없는 질문에 ③, ④가 붙어
정답 점수가 하나로 정해지지 않는 문항이 생긴다(스펙 3-2절). 어느 쪽도 결과 숫자로는 드러나지 않는다.
"""
from __future__ import annotations

import contextlib
import io
import random
import tempfile
from collections import Counter
from pathlib import Path
from unittest import mock

from . import judge5v2_assign
from .judge5v2_assign import (
    Shortfall, assign_domain, assigned_types, pool_for, replay_round, run_round, supplement_needs, supplement_pools,
    valid_contrast,
)
from .judge5v2_files import DOMAINS, QUOTA, write_jsonl

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
    # 답이 두 가지인 질문의 contrast 는 ⑧ 자격이 아니다. 주장 1개인 질문(50번)에 붙인다. 주장 2개인 질문에 붙이면
    # ④ 가 먼저 가져갈 수 있어서, ⑧ 이 two_part 를 거절하지 않아도 이 점검이 통과해 버린다.
    pool[50]["contrast"] = _CONTRAST
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
    for bad in (dict(q, two_part=True),                                      # 답이 두 가지인 질문의 contrast
                dict(q, contrast=None, claims=True)):                        # true 는 int 이기도 하지만 주장 수가 아니다
        try:
            pool_for([bad], tried)
        except ValueError:
            continue
        raise AssertionError(bad)


def check_assign_order_fourth_eighth_third_sixth() -> None:
    """뽑는 순서 ④ → ⑧ → ③ → ⑥ 을 고정한다(스펙 3-3절 3).

    ⑧ 자격 질문 6개가 모두 주장 3개다. ③ 이 ⑧ 보다 먼저 뽑으면 그중 일부를 ③ 으로 가져가 ⑧ 이 모자라고,
    ⑥ 이 ⑧ 보다 먼저 뽑으면 답이 하나인 질문 중에서 ⑧ 자격 질문을 가져간다. 어느 쪽이든 eighth_to_sixth 가 0 이 아니게 된다.
    """
    out = []
    for i in range(75):
        # 0~8: 주장 2, 답 두 가지(④ 몫) / 9~23: 주장 3, 답 하나(9~14 가 ⑧ 자격) / 24~30: 주장 1, 답 하나(⑥ 몫) / 나머지: 주장 1, 답 두 가지
        claims, two_part = (2, True) if i < 9 else (3, False) if i < 24 else (1, False) if i < 31 else (1, True)
        out.append({"qid": f"shop-{i:03d}", "domain": "shop", "answer": "답", "claims": claims, "two_part": two_part,
                    "contrast": _CONTRAST if 9 <= i < 15 else None})
    res, short = assign_domain(out, dict(QUOTA), random.Random("s"))
    assert short == {} and res["eighth_to_sixth"] == 0
    assert {q for q, t in res["types"].items() if t == 8} == {f"shop-{i:03d}" for i in range(9, 15)}
    assert {q for q, t in res["types"].items() if t == 6} == {f"shop-{i:03d}" for i in range(24, 31)}


def check_supplement_needs_with_eighth_moved_to_sixth() -> None:
    """⑧ 을 ⑥ 으로 돌린 회차 뒤의 보충은 돌린 ⑧ 을 다시 요구하지 않는다(스펙 3-3절 5, 7-2절 끝의 경우 2)."""
    pool = _pool(contrast_every=10**6)
    pool[60]["contrast"] = _CONTRAST                     # ⑧ 자격이 하나뿐이라 5개가 ⑥ 으로 간다
    res, _ = assign_domain(pool, dict(QUOTA), random.Random("s"))
    assert res["eighth_to_sixth"] == QUOTA[8] - 1
    empty = {"types": {}, "unused": [], "eighth_to_sixth": 0}
    assignment = {"seed": 1, "rounds": [{"domains": {"shop": res, "hr": empty, "manual": empty, "finance": empty}}]}
    domain_of = {q: "shop" for q in res["types"]}
    zero = {t: 0 for t in QUOTA}
    assert supplement_needs(assignment, set(), domain_of)["shop"] == zero
    sixth = sorted(q for q, t in res["types"].items() if t == 6)[0]
    eighth = next(q for q, t in res["types"].items() if t == 8)
    assert supplement_needs(assignment, {sixth}, domain_of)["shop"] == {**zero, 6: 1}
    assert supplement_needs(assignment, {eighth}, domain_of)["shop"] == {**zero, 8: 1}


def check_supplement_pools_skip_used_keep_unused() -> None:
    """보충 후보는 앞 회차에서 유형을 받은 질문을 빼고, 받지 않은 질문과 새 질문은 남긴다(스펙 7-2절)."""
    pool = _pool()
    res, _ = assign_domain(pool, dict(QUOTA), random.Random("s"))
    empty = {"types": {}, "unused": [], "eighth_to_sixth": 0}
    assignment = {"seed": 1, "rounds": [{"domains": {"shop": res, "hr": empty, "manual": empty, "finance": empty}}]}
    new = dict(pool[0], qid="shop-075")
    got = supplement_pools({"shop": pool + [new], "hr": []}, assignment)
    assert sorted(q["qid"] for q in got["shop"]) == sorted(res["unused"] + ["shop-075"])
    assert got["hr"] == []


def check_first_stops_with_code_2_when_eighth_moved() -> None:
    """⑧ 을 ⑥ 으로 돌린 분야가 있으면 first 는 파일을 남기고 종료 코드 2 로 멈춘다(계획 E5).
    질문 파일에 잘못된 줄이 있으면 traceback 이 아니라 한국어 안내와 종료 코드 1 이다."""
    src = [{"chunk_id": 1, "content": "골드 10,000원 / 실버 20,000원"}]

    def run(questions: list[dict]) -> tuple[int, bool]:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            paths = {"ASSIGNMENT": d / "a.json", "QUESTIONS": d / "q.jsonl", "RETRIEVED": d / "r.jsonl"}
            write_jsonl(paths["QUESTIONS"], questions)
            write_jsonl(paths["RETRIEVED"], [{"qid": q["qid"], "status": "ok", "sources": src} for q in questions])
            # mock.patch.multiple: 모듈 전역(경로 상수)을 with 블록 안에서만 바꾸고 끝나면 되돌린다.
            with mock.patch.multiple(judge5v2_assign, **paths), contextlib.redirect_stdout(io.StringIO()):
                code = judge5v2_assign.cmd_first()
            return code, paths["ASSIGNMENT"].exists()

    assert run([q for d in DOMAINS for q in _pool(d)]) == (0, True)
    moved = [q for d in DOMAINS for q in _pool(d, contrast_every=10**6)]
    moved[60]["contrast"] = _CONTRAST
    assert run(moved) == (2, True)
    assert run([dict(q, claims=True) for d in DOMAINS for q in _pool(d)]) == (1, False)


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
    check_assign_order_fourth_eighth_third_sixth,
    check_supplement_needs_with_eighth_moved_to_sixth,
    check_supplement_pools_skip_used_keep_unused,
    check_first_stops_with_code_2_when_eighth_moved,
]


def main() -> None:
    for fn in CHECKS:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(CHECKS)}가지 전부 통과.")


if __name__ == "__main__":
    main()
