"""tools.judgeft_report 의 점검. DB 도 외부 API 도 쓰지 않는다.

실행:  cd ai-service && python -m tools.judgeft_report_check
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import mock

from . import judgeft_files, judgeft_report
from .judgeft_files import V2_RESULTS_DIR, read_jsonl, write_json, write_jsonl
from .judgeft_report import Metrics, criteria, eighth_change, metrics, pipeline_lines, training_summary, unread_kinds

KEY = {"e1": {"type": 8, "score": 1, "two_targets": True}, "e2": {"type": 8, "score": 1, "two_targets": True},
       "a1": {"type": 1, "score": 5, "two_targets": True}, "a2": {"type": 2, "score": 5, "two_targets": False},
       "t3": {"type": 4, "score": 3, "two_targets": False}}


def _m(**kw) -> Metrics:
    base = dict(within1=0, exact=0, mean_distance=None, unread=0, miss=0, false_alarm=0, severe=0, severe8=0,
                within1_ex8=10, fa_two=1, fa_one=1)
    return Metrics(**(base | kw))


def check_metrics_split_eighth_and_false_alarms() -> None:
    x = metrics(KEY, {"e1": 5, "e2": 1, "a1": 4, "a2": 5, "t3": 1})
    assert (x.severe, x.severe8, x.false_alarm, x.fa_two, x.fa_one) == (1, 1, 1, 1, 0)
    assert x.within1_ex8 == 2                         # a1(4), a2(5) 는 거리 1 이하, t3(1) 은 아니다. ⑧ 은 세지 않는다
    assert metrics(KEY, {"e1": None, "e2": 1, "a1": 5, "a2": 5, "t3": 3}).unread == 1


def check_criteria_use_worst_post_and_best_comparator() -> None:
    def table(post_sev_new: list[int], m1_sev_new: list[int]) -> dict:
        return {"M3ft": {"new": [_m(severe=s) for s in post_sev_new], "frozen": [_m(severe=1)]},
                "M3pre": {"new": [_m()], "frozen": [_m()]},
                "M1": {"new": [_m(severe=s) for s in m1_sev_new], "frozen": [_m(severe=1)]}}
    assert all(ok for _, ok, _ in criteria(table([2], [2, 3, 4])))           # 2 <= 가장 좋은 M1 2
    assert not criteria(table([1, 3], [2, 2, 2]))[0][1]                      # 학습 후 가장 나쁜 실행 3 > 2
    t = table([1], [2])
    t["M3ft"]["frozen"] = [_m(severe=1, fa_two=2)]                           # 대상이 둘인 질문의 헛경보가 늘었다
    assert not criteria(t)[2][1]
    t = table([1], [2])
    t["M3ft"]["new"] = [_m(severe=1, within1_ex8=9)]                         # ⑧ 뺀 거리 1 이하가 줄었다
    assert not criteria(t)[2][1]
    t = table([1], [2])
    t["M3ft"]["new"] = [_m(severe=1, unread=1)]                              # 못 읽음이 M1 보다 많다
    assert not criteria(t)[3][1]


def check_eighth_change_counts_fixed_and_new_misses() -> None:
    c = eighth_change(KEY, {"e1": 5, "e2": 1, "a1": 5, "a2": 5, "t3": 3}, {"e1": 1, "e2": 1, "a1": 5, "a2": 5, "t3": 3})
    assert (c.a_closer, c.b_closer, c.ties) == (1, 0, 1)
    six = {f"e{i}": {"type": 8, "score": 1, "two_targets": True} for i in range(6)}
    c6 = eighth_change(six, {k: 5 for k in six}, {k: 1 for k in six})
    assert abs(c6.p_value - 0.03125) < 1e-9                                  # 스펙 7-1절의 근거: 6개 모두 고쳐지면 약 0.03


def check_pipeline_lines_count_supplements_and_drops() -> None:
    a = {"rounds": [{"sheet": "test", "types": {"a": 1}, "pairs": []}, {"sheet": "test", "types": {"b": 8, "c": 1}, "pairs": []},
                    {"sheet": "train", "types": {"d": 8}, "pairs": ["d"]}]}
    out = pipeline_lines(a, {"main": {"x": ["인용이 없다"], "y": ["인용이 없다"]}, "pair": {"x": ["짝의 ⑧ 이 빠졌다"]}})
    assert out[0] == "- test: 배정 회차 2개, 보충 회차에서 채운 문항 2개"
    assert out[1] == "- train: 배정 회차 1개, 보충 회차에서 채운 문항 0개"
    assert "본 문항 2개, 짝 1개" in out[2] and "  - 인용이 없다: 2" in out


def check_unread_kinds_and_training_log_last_line() -> None:
    rows = [{"output": "x [RESULT] 5", "finish": "stop"}, {"output": "잘림", "finish": "length"},
            {"output": "[RESULT] 3 [RESULT] 4", "finish": "stop"}, {"output": "[RESULT] 9", "finish": "stop"}]
    assert unread_kinds(rows) == {"missing": 1, "conflict": 1, "out_of_range": 1, "length": 1}
    log = [{"session_start": 1, "mode": "train"}, {"step": 1, "train_loss": 2.0, "scale": 65536.0, "skipped": True},
           {"step": 2, "train_loss": 1.9, "scale": 32768.0, "skipped": False},
           {"session_start": 2, "mode": "train"}, {"resumed_from": 1}, {"step": 2, "train_loss": 1.5, "scale": 32768.0,
                                                                         "skipped": False, "val_loss": 1.4}]
    out = "\n".join(training_summary(log))
    assert "학습 단계 2개" in out and "학습 세션 2번" in out and "[1]" in out
    assert "마지막 단계 1.5000" in out and "2단계 1.4000" in out and "건너뛴 단계 1개 [1]" in out   # 단계마다 마지막 줄


def _write_fixture(d: Path, gate_pass: bool) -> dict:
    """새 시험지 4문항(⑧ 둘), 학습 전 M3 의 새 시험지 결과, 관문 기록. 동결 시험지는 v2 의 실제 파일을 쓴다."""
    cases = {f"e{i}": {"type": 8, "score": 1, "two_targets": True, "decision": "match"} for i in range(2)}
    cases |= {"a0": {"type": 1, "score": 5, "two_targets": True, "decision": "keep"},
              "b0": {"type": 4, "score": 3, "two_targets": False, "decision": "override"}}
    paths = {"ANSWER_KEY": d / "answer_key.json", "ASSIGNMENT": d / "assignment.json", "GATE_A": d / "gate_a.json",
             "GATE_B": d / "gate_b.json", "TRAIN_DONE": d / "train_done.json", "TRAINING_LOG": d / "training_log.jsonl",
             "TRAIN_DROPPED": d / "train_dropped.json", "DETERMINISM": d / "determinism.json"}
    write_json(paths["ANSWER_KEY"], {"stage": "final", "cases": cases,
                                     "dropped": {"x0": {"type": 6, "reason": "검수 메모"}}})
    write_json(paths["ASSIGNMENT"], {"rounds": [{"sheet": "test", "types": {}, "pairs": []}]})
    write_json(paths["GATE_A"], {"threshold": 0.1, "pass": gate_pass,
                                 "runs": [{"run": 1, "eighth": 2, "unread": 0, "severe": 1 if gate_pass else 0,
                                           "ratio": 0.5 if gate_pass else 0.0}]})
    write_json(paths["DETERMINISM"], {"pre": {"use_v2": True, "runs": 1}})
    out = [{"case_id": c, "output": "x [RESULT] 1", "finish": "stop"} for c in cases]
    write_jsonl(d / "results" / "new" / "M3pre_run1.jsonl", out)
    return paths


def check_report_builds_when_ended_at_gate_a() -> None:
    """관문 (a) 에서 끝나도 보고서가 나오고, 하지 않은 것은 하지 않음으로 적힌다."""
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        paths = _write_fixture(d, gate_pass=False)
        patches = [mock.patch.object(judgeft_report, k, v) for k, v in paths.items()]
        patches.append(mock.patch.object(judgeft_files, "RESULTS_DIR", d / "results"))
        for x in patches:
            x.start()
        try:
            text = judgeft_report.build()
            assert "판정: 통과하지 못함" in text and "관문 (b)" in text and "하지 않음(gate_b.json 이 없다" in text
            assert "버린 문항 1개: ⑥" in text and "사용자가 정답 점수 유지 1" in text and "검수 뒤 조건 1: 실패" in text
            assert "| 학습 후 M3 | 하지 않음(관문에서 끝났거나 채점하지 않았다. 없는 것: determinism.json 의 post) |" in text
            assert "new/M1_run1.jsonl, new/M1_run2.jsonl, new/M1_run3.jsonl" in text and "판정하지 않음" in text
            assert "#### 학습 전 M3 (첫 실행)" in text and "### 유형별 (시험지 new" in text   # 혼동행렬과 유형별 표
            assert "| 늘 1점 |" in text
            # 관문을 통과했는데 학습이 끝나지 않았으면 만들지 않는다(스펙 6-5절)
            write_json(paths["GATE_A"], {**json.loads(paths["GATE_A"].read_text()), "pass": True})
            try:
                judgeft_report.build()
            except SystemExit as e:
                assert "학습이 끝나지 않았습니다" in str(e)
            else:
                raise AssertionError("학습 전에 새 시험지 결과로 보고서를 만들었다")
        finally:
            for x in patches:
                x.stop()


def check_report_builds_full_with_criteria() -> None:
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        paths = _write_fixture(d, gate_pass=True)
        write_json(paths["GATE_B"], {"longest_id": "r1", "longest_tokens": 900, "peak_gb": 12.1, "step_seconds": 60.0,
                                     "total_steps": 135, "est_hours": 2.2, "save_every": 30, "finite": True,
                                     "losses": [1.2, 1.1]})
        write_json(paths["TRAIN_DONE"], {"adapter_sha256": "ab" * 32})
        write_jsonl(paths["TRAINING_LOG"], [{"session_start": 1, "mode": "train"},
                                            {"step": 1, "train_loss": 1.0, "scale": 65536.0, "skipped": False}])
        write_json(paths["DETERMINISM"], {"pre": {"use_v2": True, "runs": 1}, "post": {"runs": 1}})
        new_rows = read_jsonl(d / "results" / "new" / "M3pre_run1.jsonl")
        for n in (1, 2, 3):
            write_jsonl(d / "results" / "new" / f"M1_run{n}.jsonl", new_rows)
        write_jsonl(d / "results" / "new" / "M3ft_run1.jsonl", new_rows)
        write_jsonl(d / "results" / "frozen" / "M3ft_run1.jsonl", read_jsonl(V2_RESULTS_DIR / "M1_run1.jsonl"))
        patches = [mock.patch.object(judgeft_report, k, v) for k, v in paths.items()]
        patches.append(mock.patch.object(judgeft_files, "RESULTS_DIR", d / "results"))
        for x in patches:
            x.start()
        try:
            text = judgeft_report.build()
        finally:
            for x in patches:
                x.stop()
        assert "가장 긴 문항 r1(900토큰)" in text and "어댑터 SHA-256 abab" in text
        assert "- 기준 1:" in text and "- 기준 4:" in text and "⑧ 만의 짝 부호 검정(보고 항목)" in text
        # 세 실행 중 하나만 빠지면 그 파일 이름이 표에 나오고 기준은 판정하지 않는다
        (d / "results" / "new" / "M1_run2.jsonl").unlink()
        for x in patches:
            x.start()
        try:
            text = judgeft_report.build()
        finally:
            for x in patches:
                x.stop()
        assert "없는 것: new/M1_run2.jsonl) |" in text and "판정하지 않음" in text


CHECKS = [check_metrics_split_eighth_and_false_alarms, check_pipeline_lines_count_supplements_and_drops, check_criteria_use_worst_post_and_best_comparator,
          check_eighth_change_counts_fixed_and_new_misses, check_unread_kinds_and_training_log_last_line,
          check_report_builds_when_ended_at_gate_a, check_report_builds_full_with_criteria]


def main() -> None:
    for fn in CHECKS:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(CHECKS)}가지 전부 통과.")


if __name__ == "__main__":
    main()
