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
