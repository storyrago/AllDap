"""tools.judgeft_assign 의 점검. DB 도 외부 API 도 쓰지 않는다.

실행:  cd ai-service && python -m tools.judgeft_assign_check
"""
from __future__ import annotations

import random

from .judge5v2_assign import eligible3, eligible4, eligible6, eligible8
from .judgeft_assign import (
    Shortfall, assign_test, assign_train, dry_run, pools_by_sheet, qualified_counts, replay, run_round, supplement_needs,
)
from .judgeft_files import CONTRAST_FIVE, PAIRS, SEED, TEST_QUOTA, TRAIN_QUOTA

DOC = {"test": ["school"], "train": ["travel", "telecom"], "reserve": ["hospital"]}


def _q(field: str, i: int, *, two: bool, claims: int, contrast: bool) -> tuple[dict, dict]:
    """(질문 줄, 검색 줄) 한 쌍. contrast 이면 근거 청크에 값이 다른 두 대상이 함께 있다."""
    qid = f"{field}-{i:03d}"
    text = "일반석 20,000원, 비즈니스석 50,000원" if contrast else "수수료는 3,000원"
    c = ({"asked": {"target": "일반석", "value": "20,000원"}, "other": {"target": "비즈니스석", "value": "50,000원"},
          "chunk_ids": [i]} if contrast else None)
    q = {"qid": qid, "domain": field, "question": f"질문 {qid}", "two_part": two, "answer": f"답 {qid}",
         "claims": claims, "contrast": c}
    r = {"qid": qid, "domain": field, "status": "ok", "drop_reason": None,
         "sources": [{"chunk_id": i, "filename": "a.md", "content": text}]}
    return q, r


def _data(n_test: int = 150, n_train: int = 620) -> tuple[list[dict], list[dict]]:
    """시험용 150, 학습용 620 질문. 셋 중 하나는 답이 두 가지(주장 2), 나머지는 답이 하나이고 ⑧ 조건을 만족한다."""
    qs, rs = [], []
    for field, n, base in (("school", n_test, 0), ("travel", n_train // 2, 10_000), ("telecom", n_train // 2, 20_000)):
        for i in range(n):
            two = i % 3 == 0
            q, r = _q(field, base + i, two=two, claims=2 if two or i % 3 == 1 else 1,
                      contrast=not two)
            qs.append(q)
            rs.append(r)
    return qs, rs


def check_pools_split_by_sheet_and_skip_reserve() -> None:
    qs, rs = _data()
    extra_q, extra_r = _q("hospital", 99_999, two=False, claims=1, contrast=False)   # 예비 분야의 질문
    pools = pools_by_sheet(qs + [extra_q], rs + [extra_r], {}, DOC)
    assert {q["domain"] for q in pools["test"]} == {"school"}
    assert {q["domain"] for q in pools["train"]} == {"travel", "telecom"}
    assert all(q["domain"] != "hospital" for p in pools.values() for q in p)
    counts = qualified_counts(pools)
    assert counts["school"]["qualified"] == sum(1 for q in pools["test"] if eligible8(q))


def check_test_assignment_meets_quota_and_eligibility() -> None:
    qs, rs = _data()
    pool = pools_by_sheet(qs, rs, {}, DOC)["test"]
    res = assign_test(pool, TEST_QUOTA, CONTRAST_FIVE, random.Random(f"{SEED}:test:0"))
    got = {t: sum(1 for v in res["types"].values() if v == t) for t in TEST_QUOTA}
    assert got == TEST_QUOTA, got
    by = {q["qid"]: q for q in pool}
    rules = {4: eligible4, 8: eligible8, 3: eligible3, 6: eligible6}
    assert all(rules[t](by[q]) for q, t in res["types"].items() if t in rules)
    assert len(res["contrast_five"]) == 12 and all(eligible8(by[q]) and res["types"][q] in (1, 2)
                                                   for q in res["contrast_five"])


def check_train_assignment_has_pairs_from_eighth() -> None:
    qs, rs = _data()
    pool = pools_by_sheet(qs, rs, {}, DOC)["train"]
    res = assign_train(pool, TRAIN_QUOTA, PAIRS, [], random.Random(f"{SEED}:train:0"))
    got = {t: sum(1 for v in res["types"].values() if v == t) for t in TRAIN_QUOTA}
    assert got == TRAIN_QUOTA, got
    assert len(res["pairs"]) == PAIRS and all(res["types"][q] == 8 for q in res["pairs"])


def check_shortfall_stops_instead_of_moving() -> None:
    """⑧ 이 모자라면 v2 처럼 ⑥ 으로 돌리지 않고 멈춘다(스펙 3-3절은 분야를 늘린다)."""
    qs, rs = _data(n_test=60)
    pool = pools_by_sheet(qs, rs, {}, DOC)["test"]
    try:
        assign_test(pool, TEST_QUOTA, CONTRAST_FIVE, random.Random(0))
    except Shortfall as e:
        assert "8" in e.short or "contrast1" in e.short
        return
    raise AssertionError("⑧ 이 모자란데 배정이 통과했다")


def check_replay_reproduces_and_catches_tampering() -> None:
    qs, rs = _data()
    pools = pools_by_sheet(qs, rs, {}, DOC)
    rounds = []
    for sheet, quota, extra in (("test", TEST_QUOTA, {"contrast_needs": {str(t): n for t, n in CONTRAST_FIVE.items()}}),
                                ("train", TRAIN_QUOTA, {"pair_needs": PAIRS, "pair_from": []})):
        rnd = {"round": 0, "sheet": sheet, "pool": sorted(q["qid"] for q in pools[sheet]),
               "needs": {str(t): n for t, n in quota.items()}, **extra}
        rnd.update(run_round(sheet, pools[sheet], rnd, SEED))
        rounds.append(rnd)
    by = {q["qid"]: q for q in qs}
    assert replay({"seed": SEED, "rounds": rounds}, by) == []
    first = next(iter(rounds[0]["types"]))
    rounds[0]["types"][first] = 7 if rounds[0]["types"][first] != 7 else 5
    assert replay({"seed": SEED, "rounds": rounds}, by) == ["test 회차 0"]


def check_supplement_needs_refill_to_quota() -> None:
    kept = {f"t{i}": t for i, t in enumerate([8] * 50 + [1] * 8 + [2] * 10)}
    five = {f"t{i}" for i in range(50, 54)}        # 대상이 둘인 ① 넷만 남았다
    plan = supplement_needs("test", {}, kept, set(), five)
    assert plan["needs"][8] == 10 and plan["contrast_needs"] == {"1": 2, "2": 6}
    assert plan["needs"][1] == 2 and plan["needs"][2] == 6 and 4 not in plan["needs"]   # ④ 는 보충하지 않는다
    train_kept = {f"r{i}": 8 for i in range(238)}
    tp = supplement_needs("train", {}, train_kept, {f"r{i}" for i in range(118)}, set())
    assert tp["needs"][8] == 2 and tp["pair_needs"] == 2 and len(tp["pair_from"]) == 120


def check_count_runs_first_assignment_not_just_qualified_total() -> None:
    """⑧ 자격이 기준(72)과 같아도, 주장 2 인 ⑧ 자격을 ④ 가 먼저 가져가면 첫 배정은 모자란다.
    count 의 판정(dry_run)은 첫 배정을 그대로 돌려 보므로 이 모자람을 미리 낸다. 결과는 first 와 같아야 한다."""
    qs, rs = [], []
    for i in range(150):
        if i < 72:                                   # ⑧ 자격 72, 그중 24 는 주장 2 라 ④ 의 자격도 있다
            q, r = _q("school", i, two=False, claims=2 if i < 24 else 1, contrast=True)
        elif i < 112:                                # 답이 두 가지(④, ③ 후보)
            q, r = _q("school", i, two=True, claims=2, contrast=False)
        else:                                        # 답이 하나, ⑧ 조건 없음(⑥ 후보)
            q, r = _q("school", i, two=False, claims=1, contrast=False)
        qs.append(q)
        rs.append(r)
    pool = pools_by_sheet(qs, rs, {}, DOC)["test"]
    assert sum(1 for q in pool if eligible8(q)) == 72
    d = dry_run("test", pool, SEED)
    assert d["eighth_left"] < 72 and set(d["short"]) & {"8", "contrast1", "contrast2"}, d
    try:
        assign_test(pool, TEST_QUOTA, CONTRAST_FIVE, random.Random(f"{SEED}:test:0"))
    except Shortfall as e:
        assert e.short == d["short"], (e.short, d["short"])
    else:
        raise AssertionError("dry_run 은 모자란다고 했는데 첫 배정이 통과했다")
    qs2, rs2 = _data()                               # 넉넉한 입력에서는 모자람이 없다
    assert dry_run("test", pools_by_sheet(qs2, rs2, {}, DOC)["test"], SEED)["short"] == {}


CHECKS = [check_pools_split_by_sheet_and_skip_reserve, check_test_assignment_meets_quota_and_eligibility,
          check_train_assignment_has_pairs_from_eighth, check_shortfall_stops_instead_of_moving,
          check_replay_reproduces_and_catches_tampering, check_supplement_needs_refill_to_quota,
          check_count_runs_first_assignment_not_just_qualified_total]


def main() -> None:
    for fn in CHECKS:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(CHECKS)}가지 전부 통과.")


if __name__ == "__main__":
    main()
