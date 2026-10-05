"""tools.judgeft_gate, tools.judgeft_determinism 의 점검. DB 도 외부 API 도 쓰지 않는다.

실행:  cd ai-service && python -m tools.judgeft_gate_check
"""
from __future__ import annotations

from .judgeft_determinism import compare_runs, decide_pre_from, env_diff, runs_for
from .judgeft_files import V2_RESULTS_DIR, result_path
from .judgeft_gate import gate_a, review_conditions


def _cases(n8: int = 60, n5: int = 20, two: int = 12) -> dict[str, dict]:
    c = {f"e{i}": {"type": 8, "score": 1, "two_targets": True} for i in range(n8)}
    c |= {f"f{i}": {"type": 1 + i % 2, "score": 5, "two_targets": i < two} for i in range(n5)}
    return c


def _run(severe: int, unread: int, n8: int = 60) -> list[dict]:
    rows = []
    for i in range(n8):
        out = "x [RESULT] 5" if i < severe else ("양식 없음" if i < severe + unread else "x [RESULT] 1")
        rows.append({"case_id": f"e{i}", "output": out, "finish": "stop"})
    return rows


def check_review_conditions_pass_and_fail() -> None:
    assert all(c.ok for c in review_conditions(_cases()))
    assert {c.no for c in review_conditions(_cases(n8=53, n5=14, two=9)) if not c.ok} == {1, 2, 3}


def check_gate_a_threshold_and_unread_denominator() -> None:
    cases = _cases()
    assert gate_a([_run(6, 0)], cases)["pass"]                      # 6/60 = 10%
    assert not gate_a([_run(5, 0)], cases)["pass"]                  # 5/60
    r = gate_a([_run(6, 4)], cases)["runs"][0]                      # 못 읽음 4개는 분모에서 빠진다: 6/56
    assert r["unread"] == 4 and abs(r["ratio"] - 6 / 56) < 1e-9
    assert not gate_a([_run(9, 0), _run(5, 0), _run(9, 0)], cases)["pass"]   # 비율이 가장 낮은 실행으로 판정
    over = dict(cases, e0={"type": 8, "score": 3, "two_targets": True})      # 사용자가 3점으로 바꾼 ⑧ 은 세지 않는다
    assert gate_a([_run(6, 0)], over)["runs"][0]["eighth"] == 59


def check_compare_runs_and_env() -> None:
    a = [{"case_id": "c1", "output": "x [RESULT] 5", "finish": "stop"}]
    assert compare_runs(a, [dict(a[0])])["diff"] == 0
    assert compare_runs(a, [dict(a[0], output="y [RESULT] 5")])["diff"] == 1     # 점수가 같아도 본문이 다르면 다르다
    assert env_diff({"torch": "2.11.0+cu130", "transformers": "4.57.6", "bitsandbytes": "0.50.2"},
                    {"torch": "2.11.0+cu130", "transformers": "4.57.6", "bitsandbytes": "0.50.2"}) == {}
    assert set(env_diff({"torch": "2.12.0"}, {"torch": "2.11.0"})) >= {"torch"}
    assert "gpu" in env_diff({"gpu": "NVIDIA L4"}, {"gpu": "Tesla T4"})


def check_decide_pre_separates_causes() -> None:
    """판이 같아도 v2 와 다르면 새 환경의 run2 를 요구하고, run1 과 run2 로 실행 수를 정한다."""
    a = [{"case_id": "c1", "output": "x [RESULT] 5", "finish": "stop"}]
    b = [dict(a[0], output="y [RESULT] 5")]
    r = decide_pre_from(a, a, None, {})
    assert r["use_v2"] and r["runs"] == 1
    try:
        decide_pre_from(a, b, None, {})
    except SystemExit as e:
        assert "run2" in str(e)
    else:
        raise AssertionError("판이 같은데 v2 와 다르면 run2 를 요구해야 한다")
    r = decide_pre_from(a, b, a, {})                 # 새 환경의 두 실행은 같다: v2 와의 차이는 코드나 환경 쪽
    assert not r["use_v2"] and r["runs"] == 1 and r["vs_v2"]["diff"] == 1
    r = decide_pre_from(a, b, b, {})                 # 새 환경의 두 실행도 다르다: 생성이 실행마다 다르다
    assert not r["use_v2"] and r["runs"] == 3
    r = decide_pre_from(a, a, a, {"torch": {"v2": "2.11.0", "now": "2.12.0"}})   # 판이 다르면 v2 와 대조하지 않는다
    assert not r["use_v2"] and "vs_v2" not in r


def check_runs_for_follows_spec_table() -> None:
    v2 = V2_RESULTS_DIR / "M3_run1.jsonl"
    same1 = {"pre": {"use_v2": True, "runs": 1}, "post": {"runs": 1}}
    assert runs_for("M3pre", "frozen", same1) == [v2]
    assert runs_for("M3pre", "frozen", {"pre": {"use_v2": True, "runs": 3}}) == [
        v2, result_path("frozen", "M3pre", 1), result_path("frozen", "M3pre", 2)]
    assert runs_for("M3pre", "frozen", {"pre": {"use_v2": False, "runs": 1}}) == [result_path("frozen", "M3pre", 1)]
    assert runs_for("M1", "new", same1) == [result_path("new", "M1", n) for n in (1, 2, 3)]
    assert runs_for("M1", "frozen", same1) == [V2_RESULTS_DIR / "M1_run1.jsonl"]
    assert runs_for("M3ft", "frozen", {"post": {"runs": 3}})[2] == result_path("frozen", "M3ft", 3)


CHECKS = [check_review_conditions_pass_and_fail, check_gate_a_threshold_and_unread_denominator,
          check_compare_runs_and_env, check_runs_for_follows_spec_table, check_decide_pre_separates_causes]


def main() -> None:
    for fn in CHECKS:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(CHECKS)}가지 전부 통과.")


if __name__ == "__main__":
    main()
