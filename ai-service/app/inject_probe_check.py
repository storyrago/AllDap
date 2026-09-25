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

from dataclasses import replace

from .eval_cases import Case, SourceRef
from .judge import Scores
from .inject_probe import (
    CONDITIONS, REVIEW_VALUES, Candidate, bad_reviews, bucket, build_conditions,
    distribution, done_keys, drops, first_drop, inconsistent_cases, latest, make_record, missing_conditions, missing_gold,
    position_pairs, review_counts, pick_far,
    pick_near, select_targets, unstable_bases,
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
        # 못 잰 줄은 떨어진 건이 아니다. drops 에 섞이면 사람이 review 를 적을 대상이 부풀려진다
        ("b", "near+2", None, None),
        ("c", "base", None, None),
    ])
    skip = set(unstable_bases(lm))
    assert skip == {"a", "c"}
    assert [(r["case_id"], r["condition"]) for r in drops(lm, skip)] == [("b", "near+1")]


def check_first_drop_is_the_earliest_step() -> None:
    lm = _lm([("a", "near+1", 1.0, None), ("a", "near+2", 0.5, None), ("a", "near+4", 0.0, None),
              ("a", "far+1", 1.0, None), ("a", "far+2", None, None), ("a", "far+4", 1.0, None)])
    assert first_drop(lm, "a", "near") == "near+2"
    # far+2 를 못 쟀으니 far+4 가 1.0 이어도 "끝까지 버텼다" 고 말할 수 없다
    assert first_drop(lm, "a", "far") == "?", "못 잰 자리가 먼저 오면 판정 불가다"


def check_first_drop_none_only_when_all_measured() -> None:
    lm = _lm([("a", "near+1", 1.0, None), ("a", "near+2", 1.0, None), ("a", "near+4", 1.0, None),
              ("b", "near+1", None, None), ("b", "near+2", 0.0, None),
              ("c", "near+1", 1.0, None), ("c", "near+2", 0.0, None), ("c", "near+4", None, None)])
    assert first_drop(lm, "a", "near") is None, "전부 재서 전부 1.0 이면 무너지지 않은 것이다"
    assert first_drop(lm, "b", "near") == "?", "+1 을 못 쟀으면 +2 가 처음 무너진 자리인지 모른다"
    assert first_drop(lm, "c", "near") == "near+2", "무너진 <뒤의> 못 잼은 판정을 바꾸지 않는다"
    # 후보가 모자라 +4 를 <만들지 않은> 것은 못 잼이 아니다
    lm = _lm([("d", "far+1", 1.0, None), ("d", "far+2", 1.0, None)])
    assert first_drop(lm, "d", "far") is None


def check_review_values_are_restricted() -> None:
    recs = [{"case_id": "a", "condition": "near+1", "review": "무관"},
            {"case_id": "b", "condition": "near+1", "review": None},
            {"case_id": "c", "condition": "near+2", "review": "관련있음"}]
    bad = bad_reviews(recs)
    assert len(bad) == 1 and "관련있음" in bad[0]
    assert REVIEW_VALUES == ("무관", "모순", "뒷받침")


def check_missing_gold_document_is_reported() -> None:
    """정답 문서를 모르면 그 문서의 형제 청크를 못 뺀다. 그러면 near 가 답을 뒷받침해
    점수가 안 떨어지고, 결과가 조용히 "near 에 강하다" 쪽으로 기운다. 그래서 멈춰야 한다."""
    # replace: frozen 데이터클래스는 필드를 못 바꾸므로, 한 필드만 다른 <새 객체>를 만든다
    targets = [_case("a", 1.0), replace(_case("b", 1.0), question_id=7)]
    assert missing_gold(targets, {3: 30}) == [7]
    assert missing_gold(targets, {3: 30, 7: 70}) == []
    # 같은 문항이 여러 케이스에 있어도 한 번만 찍는다
    assert missing_gold([_case("a", 1.0), _case("c", 1.0)], {}) == [3]


def _lm_injected(rows: list[tuple[str, str, list[int]]]) -> dict:
    """(case_id, 조건, 주입한 chunk_id 목록) 으로 결과 줄을 만든다. 점수는 전부 1.0."""
    return latest([
        {"case_id": c, "condition": k, "faithfulness": 1.0, "review": None, "reason": "",
         "injected": [{"chunk_id": i, "filename": f"{i}.md", "distance": 0.3} for i in ids]}
        for c, k, ids in rows
    ])


def _consistent_rows(case_id: str) -> list[tuple[str, str, list[int]]]:
    return [
        (case_id, "base", []),
        (case_id, "near+1", [11]), (case_id, "near+2", [11, 12]), (case_id, "near+4", [11, 12, 13, 14]),
        (case_id, "far+1", [21]), (case_id, "far+2", [21, 22]), (case_id, "far+4", [21, 22, 23, 24]),
        (case_id, "near+1@front", [11]),
    ]


def check_consistent_injection_passes() -> None:
    assert inconsistent_cases(_lm_injected(_consistent_rows("a"))) == []
    # 후보가 모자라 +4 가 없는 것은 어긋남이 아니다
    rows = [r for r in _consistent_rows("a") if r[1] != "near+4"]
    assert inconsistent_cases(_lm_injected(rows)) == []


def check_broken_nesting_is_caught() -> None:
    """이어 돌리다 날짜가 바뀌면 near 를 새로 고른다. 그러면 +1 ⊂ +2 가 조용히 깨진다."""
    rows = _consistent_rows("a")
    # near+1 은 [11] 인데 near+2 앞자리가 99. near+4 는 새 near+2 를 따라가게 둬서
    # 어긋난 자리가 정확히 한 곳(near+1 → near+2)이 되게 한다
    rows[2] = ("a", "near+2", [99, 12])
    rows[3] = ("a", "near+4", [99, 12, 13, 14])
    bad = inconsistent_cases(_lm_injected(rows))
    assert len(bad) == 1 and "a" in bad[0] and "near+2" in bad[0], bad
    rows = _consistent_rows("b")
    rows[6] = ("b", "far+4", [21, 77, 23, 24])  # far+2 는 [21, 22]
    bad = inconsistent_cases(_lm_injected(rows))
    assert len(bad) == 1 and "far+4" in bad[0], bad


def check_front_mismatch_is_caught() -> None:
    """맨 앞 조건이 다른 청크를 넣었으면 "자리" 가 아니라 "청크" 를 비교한 셈이다."""
    rows = _consistent_rows("a")
    rows[7] = ("a", "near+1@front", [55])
    bad = inconsistent_cases(_lm_injected(rows))
    assert len(bad) == 1 and "near+1@front" in bad[0], bad


def check_position_pairs_drop_unmeasured() -> None:
    """자리 비교에서 한쪽이라도 못 잼이면 <같은 칸/갈림> 어느 쪽에도 넣으면 안 된다."""
    lm = _lm([("a", "near+1", 1.0, None), ("a", "near+1@front", 0.0, None),
              ("b", "near+1", None, None), ("b", "near+1@front", 1.0, None),
              ("c", "near+1", 1.0, None), ("c", "near+1@front", None, None),
              ("d", "near+1", 1.0, None)])
    both, unmeasured = position_pairs(lm, ["a", "b", "c", "d"])
    assert both == ["a"] and unmeasured == 2


def check_missing_conditions_are_listed() -> None:
    """[1] 의 행마다 합계가 다른 이유가 표에 보여야 한다."""
    lm = _lm([(c_, k, 1.0, None) for c_ in ("a", "b") for k in CONDITIONS if not (c_ == "b" and k.startswith("far"))])
    lm.pop(("a", "near+4"))
    got = missing_conditions(lm, ["a", "b"])
    assert got == {"a": ["near+4"], "b": ["far+1", "far+2", "far+4"]}, got


def check_review_counts_are_separate() -> None:
    """무관 · 모순 · 뒷받침은 따로 센다. 채점자의 약점은 <무관한데 떨어진> 것뿐이다."""
    dropped = [{"condition": "near+1", "review": "무관"}, {"condition": "near+1", "review": "모순"},
               {"condition": "near+1", "review": "무관"}, {"condition": "near+1", "review": None},
               {"condition": "far+1", "review": "뒷받침"}]
    assert review_counts(dropped, "near+1") == {"무관": 2, "모순": 1, "뒷받침": 0}
    assert review_counts(dropped, "far+1") == {"무관": 0, "모순": 0, "뒷받침": 1}


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
        check_failed_scoring_is_null_not_zero,
        check_resume_skips_only_successful_keys,
        check_latest_line_wins,
        check_distribution_counts_null_separately,
        check_unstable_base_is_excluded_from_drops,
        check_first_drop_is_the_earliest_step,
        check_review_values_are_restricted,
        check_missing_gold_document_is_reported,
        check_consistent_injection_passes,
        check_broken_nesting_is_caught,
        check_front_mismatch_is_caught,
        check_first_drop_none_only_when_all_measured,
        check_position_pairs_drop_unmeasured,
        check_missing_conditions_are_listed,
        check_review_counts_are_separate,
    ]
    for fn in checks:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(checks)}가지 전부 통과.")


if __name__ == "__main__":
    main()
