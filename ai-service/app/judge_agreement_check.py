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
from .judge_agreement import build_payload


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
    """
    payload = build_payload([_fake_case("aaa", 0.0)], carried={})
    blob = __import__("json").dumps(payload, ensure_ascii=False)
    assert "faithfulness" not in blob
    assert "judge" not in blob
    assert payload["cases"][0]["label"] is None


def check_dump_carries_existing_labels() -> None:
    """다시 dump 해도 사람이 채운 칸을 잃지 않는다. 1.5~2시간짜리 일이라 이어 할 수 있어야 한다."""
    carried = {"aaa": {"label": 0.5, "note": "절반만 근거에 있다"}}
    payload = build_payload([_fake_case("aaa", 1.0)], carried=carried)
    assert payload["cases"][0]["label"] == 0.5
    assert payload["cases"][0]["note"] == "절반만 근거에 있다"


def main() -> None:
    checks = [
        check_chunk_ids_are_parsed_as_int,
        check_chunk_ids_keep_order,
        check_case_key_distinguishes_source_order,
        check_case_key_is_stable,
        check_dump_hides_judge_scores,
        check_dump_carries_existing_labels,
    ]
    for fn in checks:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(checks)}가지 전부 통과.")


if __name__ == "__main__":
    main()
