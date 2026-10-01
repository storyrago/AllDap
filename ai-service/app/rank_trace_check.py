"""rank_trace 비교 모드의 순수 함수 점검. DB 도 모델도 쓰지 않는다. CI 에서 돈다.

실행:  cd ai-service && .venv/bin/python -m app.rank_trace_check

판정 규칙의 숫자는 스펙(2026-10-01-reranker-finetune-design.md §5-3)에 적힌 예와 같아야 한다.
  좋아짐 12, 나빠짐 2 → p 약 0.013 → 효과 있음
  좋아짐 6, 나빠짐 4 → p 약 0.75 → 구별되지 않음
  6:0 → 약 0.031, 5:0 → 0.0625 (갈린 문제가 5개 이하면 결과와 관계없이 구별되지 않음)
"""
from __future__ import annotations

from .rank_trace import chunks_not_ready, gate_count, judge, paired, sign_test_p, summarize


def _r(qid: int, status: str, **ranks: int) -> dict:
    # **ranks 는 키워드 인자를 딕셔너리로 모은다. _r(1, "fixable", local=3) → ranks={"local": 3}
    return {"qid": qid, "question": f"질문{qid}", "status": status, "ranks": dict(ranks)}


def check_sign_test_matches_spec_examples() -> None:
    assert abs(sign_test_p(12, 2) - 0.01294) < 1e-4, sign_test_p(12, 2)
    assert abs(sign_test_p(6, 4) - 0.75391) < 1e-4, sign_test_p(6, 4)
    assert abs(sign_test_p(6, 0) - 0.03125) < 1e-9
    assert abs(sign_test_p(5, 0) - 0.0625) < 1e-9
    assert sign_test_p(2, 12) == sign_test_p(12, 2), "양측 검정은 방향에 대칭이다"
    assert sign_test_p(0, 0) == 1.0
    assert sign_test_p(6, 6) == 1.0, "1 을 넘으면 1 로 자른다"


def check_judge() -> None:
    assert judge(12, 2) == "효과 있음"
    assert judge(2, 12) == "악화"
    assert judge(6, 4) == "구별되지 않음"
    assert judge(5, 0) == "구별되지 않음"
    assert judge(6, 0) == "효과 있음"


def check_summarize_counts_unfixable_in_denominator() -> None:
    results = [
        _r(1, "fixable", local=1),
        _r(2, "fixable", local=7),
        _r(3, "gate"),
        _r(4, "outside"),
    ]
    s = summarize(results, "local", top_k=5)
    assert s["n"] == 4 and s["fixable"] == 2 and s["hit"] == 1, s
    assert s["top_rate"] == 0.25, "분모는 시험 문제 전체다(스펙 §5-3)"
    assert s["fixable_rate"] == 0.5
    assert s["mean_rank"] == 4.0
    assert s["status_counts"] == {"fixable": 2, "gate": 1, "cut": 0, "outside": 1}, s


def check_paired_ignores_ties_and_unfixable() -> None:
    results = [
        _r(1, "fixable", local=7, local_ft=2),   # 좋아짐
        _r(2, "fixable", local=3, local_ft=9),   # 나빠짐
        _r(3, "fixable", local=2, local_ft=4),   # 둘 다 5위 안: 동점
        _r(4, "fixable", local=8, local_ft=6),   # 둘 다 5위 밖: 동점
        _r(5, "cut"),
    ]
    up, down = paired(results, "local", "local_ft", top_k=5)
    assert [r["qid"] for r in up] == [1], up
    assert [r["qid"] for r in down] == [2], down


def check_gate_count_uses_all_questions() -> None:
    results = [_r(1, "fixable", local=6), _r(2, "fixable", local=1), _r(3, "gate"), _r(4, "outside")]
    assert gate_count(results, "local", top_k=5) == (1, 4)


def check_chunks_not_ready() -> None:
    assert chunks_not_ready(3, 120, 0) is None
    empty_bot = chunks_not_ready(3, 0, 0)
    assert empty_bot and "청크 0개" in empty_bot, empty_bot
    half = chunks_not_ready(3, 120, 1)
    assert half and "120개" in half and "1개" in half, half


def main() -> None:
    checks = [
        check_sign_test_matches_spec_examples,
        check_judge,
        check_summarize_counts_unfixable_in_denominator,
        check_paired_ignores_ties_and_unfixable,
        check_gate_count_uses_all_questions,
        check_chunks_not_ready,
    ]
    for fn in checks:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(checks)}가지 전부 통과.")


if __name__ == "__main__":
    main()
