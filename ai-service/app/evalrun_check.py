"""evalrun 의 실행 상태 판정 자체 점검. DB·모델을 부르지 않는다.

왜 이 검사가 있나
─────────────────────────────────────────────────────────────────────────────
`eval_runs.status` 는 <이 실행을 다른 설정과 비교해도 되는가> 를 말한다.
그런데 판정이 틀리면 화면에 "완료" 로 보이는 실행의 숫자가 거짓이 되고,
그 숫자로 W4 의 before/after 결론을 내리게 된다. 실제로 그렇게 틀린 결론을
한 번 냈다(2026-08-13, 리랭커 융합 — AGENTS.md 참고).

🔴 특히 <채점 실패> 를 잡는지 본다. 채점 실패는 fallback 과 완전히 다른 사실인데,
   `scored_count` 에서 빠지는 결과만 같아 뭉개지기 쉽다. 그리고 Spring 의
   전체 충실성이 `avg × scored / total` 이라 <충실성 0점으로 환산된다.>
"""
from __future__ import annotations

from .evalrun import _run_status


def check_all_processed_and_scored_is_completed() -> None:
    """전부 처리하고 전부 채점했으면 completed. 비교에 쓸 수 있다."""
    assert _run_status(processed=16, total=16, judge_failed=0) == "completed"


def check_nothing_processed_is_failed() -> None:
    """한 문항도 처리하지 못했으면 측정 자체가 없다.

    2026-08-12 에 16문항이 전부 429 로 죽었는데 completed 로 남아,
    지표가 NULL 인 그 실행을 유효한 측정으로 착각한 적이 있다."""
    assert _run_status(processed=0, total=16, judge_failed=0) == "failed"


def check_partial_processing_is_partial() -> None:
    """일부만 처리했으면 <분모가 달라> 다른 설정과 비교할 수 없다."""
    assert _run_status(processed=13, total=16, judge_failed=0) == "partial"


def check_judge_failure_is_partial() -> None:
    """🔴 이 검사가 이 파일의 존재 이유다.

    검색·생성은 전부 됐는데 채점만 실패한 경우. 예전에는 completed 였다.
    그러면 Spring 의 전체 충실성(avg × scored / total)이 그 문항을
    <충실성 0점> 으로 환산하는데, 화면에는 "완료" 로 보인다.

    실제 시나리오: 16문항 전부 정답(실제 1.000)인데 judge 가 2건에서
    코드펜스 없는 잡소리를 뱉어 _extract_json 이 None 을 반환
    → avg=1.000, scored=14, total=16 → 대시보드 0.875.
    그 값을 다른 설정의 0.875 와 나란히 놓고 "차이 없음" 이라고 결론낸다."""
    assert _run_status(processed=16, total=16, judge_failed=2) == "partial"


def check_judge_failure_does_not_mask_failed() -> None:
    """전멸은 채점 실패가 있어도 여전히 failed 다. failed 가 더 강한 사실이다."""
    assert _run_status(processed=0, total=16, judge_failed=0) == "failed"


def main() -> None:
    checks = [
        check_all_processed_and_scored_is_completed,
        check_nothing_processed_is_failed,
        check_partial_processing_is_partial,
        check_judge_failure_is_partial,
        check_judge_failure_does_not_mask_failed,
    ]
    for fn in checks:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(checks)}가지 전부 통과.")


if __name__ == "__main__":
    main()
