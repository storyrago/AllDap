"""채점자 대조 도구의 순수 함수 자체 점검. DB 도 외부 API 도 쓰지 않는다.

왜 이 검사가 있나
─────────────────────────────────────────────────────────────────────────────
이 도구가 내는 결론은 "채점자가 <어느 방향으로> 틀리는가" 다.
🔴 후함과 박함의 부호가 한 번 뒤집히면 결론이 정반대가 된다:
   "전체충실성이 실제보다 높게 나온다" ↔ "낮게 나온다".
숫자는 그럴듯하게 나오고 아무도 눈치채지 못한다. 그래서 부호를 검사로 못박는다.

그리고 근거 <순서>가 채점자 판단을 바꾼다는 것이 2026-09-18 에 실측됐다
(무관한 청크가 4번째에 끼자 3번째 자리의 정답을 못 봤다).
그래서 케이스를 묶는 해시가 순서를 지우면 안 된다. 그것도 검사한다.
"""
from __future__ import annotations

from .eval_cases import Case, SourceRef, case_key, chunk_ids_of
from .judge_agreement import (
    build_payload, confusion, direction_counts, linear_weighted_kappa, overall_faithfulness,
)


def check_chunk_ids_are_parsed_as_int() -> None:
    """🔴 저장된 chunk_id 는 문자열이다. int 로 안 바꾸면 chunks 조회가 통째로 빈다.

    그러면 사람이 <근거 없이> 라벨을 매기게 되고, 그 라벨은 거짓이 된다.
    """
    raw = [{"score": 0.6, "chunk_id": "270", "filename": "a.md"},
           {"score": 0.5, "chunk_id": "319", "filename": "b.md"}]
    assert chunk_ids_of(raw) == [270, 319]


def check_chunk_ids_keep_order() -> None:
    """순서를 유지한다. 정렬하면 서로 다른 입력이 한 칸으로 뭉개진다."""
    raw = [{"chunk_id": "9"}, {"chunk_id": "2"}, {"chunk_id": "7"}]
    assert chunk_ids_of(raw) == [9, 2, 7]


def check_case_key_distinguishes_source_order() -> None:
    """근거 순서가 다르면 다른 케이스다.

    2026-09-18 실측: 같은 답변 · 같은 청크 집합인데 무관한 청크가 끼는 <자리>가
    달라지자 충실성이 1.0 에서 0.0 으로 갈렸다. 순서를 지우면 그 사실이 사라진다.
    """
    a = case_key(58, "같은 답", [1, 2, 3])
    b = case_key(58, "같은 답", [3, 2, 1])
    assert a != b


def check_case_key_is_stable() -> None:
    """같은 입력은 언제 불러도 같은 값이다. 라벨을 이어받는 근거가 이것이다."""
    assert case_key(58, "답", [1, 2]) == case_key(58, "답", [1, 2])


def _fake_case(case_id: str, faith: float) -> Case:
    return Case(
        case_id=case_id,
        question_id=58,
        question="질문",
        ground_truth="정답",
        generated_answer="답변",
        sources=(SourceRef(chunk_id=1, document_id=2, filename="a.md", content="본문"),),
        seen_in_runs=(11, 12),
        judge_faithfulness=faith,
        judge_relevancy=1.0,
    )


def check_dump_hides_judge_scores() -> None:
    """🔴 이 도구의 존재 이유다. 채점자 점수를 보고 매기면 앵커링되어 대조가 성립하지 않는다.

    `answerable_check` 가 홀드아웃을 기본 모드에서 <읽지도 않게> 만들어둔 것과 같은 규칙이다.

    🔴 본문에서 낱말을 찾는 방식으로 검사하지 않는다. 그렇게 하면 두 가지로 거짓이 된다:
       근거 청크 본문에 우연히 "judge" 가 섞이면 <블라인드가 멀쩡한데도> 실패하고
       (이 저장소의 "정상을 실패로 부르는 검사" 부류다), 반대로 점수가 다른 이름의
       칸으로 새어 나가면 낱말 검사를 그냥 지나간다.
       그래서 <허용된 칸 목록>을 고정하고 그 밖의 칸이 생기면 실패시킨다.
    """
    allowed = {
        "case_id", "question_id", "question", "ground_truth",
        "generated_answer", "sources", "seen_in_runs", "label", "note",
    }
    payload = build_payload([_fake_case("aaa", 0.0)], carried={})
    case = payload["cases"][0]
    extra = set(case) - allowed
    assert not extra, f"라벨 파일에 허용되지 않은 칸이 생겼습니다: {sorted(extra)}"
    assert set(case["sources"][0]) == {"chunk_id", "filename", "content"}
    assert case["label"] is None


def check_dump_carries_existing_labels() -> None:
    """다시 dump 해도 사람이 채운 칸을 잃지 않는다. 1.5~2시간짜리 일이라 이어 할 수 있어야 한다."""
    carried = {"aaa": {"label": 0.5, "note": "절반만 근거에 있다"}}
    payload = build_payload([_fake_case("aaa", 1.0)], carried=carried)
    assert payload["cases"][0]["label"] == 0.5
    assert payload["cases"][0]["note"] == "절반만 근거에 있다"


def check_direction_generous_means_judge_is_higher() -> None:
    """🔴 부호가 뒤집히면 결론이 정반대가 된다. 이 검사가 이 파일의 존재 이유다.

    (사람, 채점자) = (0.0, 1.0) 은 <채점자가 후하다>. 사람이 0점을 줄 답에 1점을 줬다.
    그러면 전체충실성이 실제보다 <높게> 나온다.
    """
    generous, harsh, same = direction_counts([(0.0, 1.0)])
    assert (generous, harsh, same) == (1, 0, 0)


def check_direction_harsh_means_judge_is_lower() -> None:
    """(사람, 채점자) = (1.0, 0.0) 은 <채점자가 박하다>. q3 가 이 모양이었다.

    그러면 전체충실성이 실제보다 <낮게> 나온다.
    """
    generous, harsh, same = direction_counts([(1.0, 0.0)])
    assert (generous, harsh, same) == (0, 1, 0)


def check_confusion_counts_by_human_then_judge() -> None:
    """혼동행렬의 키는 (사람, 채점자) 순서다. 뒤집으면 표를 거꾸로 읽게 된다."""
    m = confusion([(1.0, 1.0), (1.0, 1.0), (1.0, 0.5), (0.5, 1.0)])
    assert m[(1.0, 1.0)] == 2
    assert m[(1.0, 0.5)] == 1
    assert m[(0.5, 1.0)] == 1
    assert m[(0.0, 0.0)] == 0


def check_overall_faithfulness_matches_the_repo_formula() -> None:
    """전체충실성 = avg × scored / total. 정리하면 sum / total 이다.

    이 저장소가 쓰는 식 그대로여야 채점자 기준 수치와 나란히 놓을 수 있다.
    fallback 이 많아 scored 가 작아지는 것은 정상이고, 오염 지표는 따로 있다
    (generated_answer IS NULL = 처리 실패).
    """
    # 26문항 중 24건만 채점됐고 그 평균이 1.0 이면 24/26
    assert abs(overall_faithfulness([1.0] * 24, 26) - 24 / 26) < 1e-9
    # 채점된 것이 하나도 없으면 0.0 이다(0으로 나누지 않는다)
    assert overall_faithfulness([], 26) == 0.0


def check_kappa_is_one_on_perfect_agreement() -> None:
    """완전 일치면 1.0. 다만 이 값은 참고용이다(분포 치우침 주석이 출력에 붙는다)."""
    pairs = [(1.0, 1.0)] * 8 + [(0.5, 0.5)] * 2
    assert abs(linear_weighted_kappa(pairs) - 1.0) < 1e-9


def check_kappa_paradox_is_real_on_this_distribution() -> None:
    """🔴 카파 역설을 <실행 가능한 형태로> 못박는다. 출력의 주석이 말뿐이 아니게 한다.

    지금 DB 의 채점자 분포는 44건 중 충실성 1.0 이 40건이다. 사람이 그 44건을 전부
    1.0 으로 본다면(채점자가 박하게만 틀렸다면 그렇게 된다) 이런 일이 벌어진다:

        일치율 90.9%  ·  선형가중 카파 0.0000

    한쪽 평정자가 한 값에 고정되면 우연 일치 기대치가 관측 일치와 같아져 분자가
    정확히 0 이 된다. **채점자가 44건 중 40건을 맞혔는데도 카파는 "우연 수준" 이다.**

    이 검사가 있는 이유는 <미래의 누군가>가 출력의 주석을 지우고 카파만 인용하는 것을
    막기 위해서다. 이 저장소가 반복해 낸 부류다: 숫자 하나가 서로 다른 사실을 뭉갠다.
    """
    pairs = [(1.0, 1.0)] * 40 + [(1.0, 0.5)] * 3 + [(1.0, 0.0)]
    agreement = sum(1 for h, j in pairs if h == j) / len(pairs)
    assert abs(agreement - 40 / 44) < 1e-9
    assert abs(linear_weighted_kappa(pairs)) < 1e-9
    # 그리고 방향은 전부 <박함> 이다. 채점자가 낮게 줬으므로 전체충실성은 실제보다 낮다.
    assert direction_counts(pairs) == (0, 4, 40)


def main() -> None:
    checks = [
        check_chunk_ids_are_parsed_as_int,
        check_chunk_ids_keep_order,
        check_case_key_distinguishes_source_order,
        check_case_key_is_stable,
        check_dump_hides_judge_scores,
        check_dump_carries_existing_labels,
        check_direction_generous_means_judge_is_higher,
        check_direction_harsh_means_judge_is_lower,
        check_confusion_counts_by_human_then_judge,
        check_overall_faithfulness_matches_the_repo_formula,
        check_kappa_is_one_on_perfect_agreement,
        check_kappa_paradox_is_real_on_this_distribution,
    ]
    for fn in checks:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(checks)}가지 전부 통과.")


if __name__ == "__main__":
    main()
