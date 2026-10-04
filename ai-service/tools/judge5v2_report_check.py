"""tools.judge5v2_report 의 점검. DB 도 외부 API 도 쓰지 않는다.

실행:  cd ai-service && python -m tools.judge5v2_report_check

비교 쌍의 순서, 놓침과 헛경보의 방향, 대괄호 끝 규칙의 적용 중 하나만 틀려도 결론이 바뀐다.
숫자는 그럴듯하게 나오므로 눈으로는 잡히지 않는다.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from .judge5v2_report import build, error_counts

_KEY = [5, 5, 5, 4, 3, 2, 1, 1, 1, 1]
_TYPE_OF = {5: 1, 4: 3, 3: 4, 2: 5, 1: 6}


def check_error_counts_follow_spec() -> None:
    """놓침, 헛경보, 심각한 놓침은 정답 점수로 정의한다(스펙 6-1절). 못 읽음은 세지 않는다."""
    e = error_counts([(4, 5), (1, 5), (1, 4), (5, 4), (5, 5), (1, None), (3, 3)])
    assert (e.miss, e.false_alarm, e.severe_miss) == (2, 1, 2)


def _write_inputs(d: Path) -> dict:
    ids = [f"c{i:02d}" for i in range(len(_KEY))]
    cases = {cid: {"qid": f"q{i}", "domain": "shop", "type": _TYPE_OF[k], "table_score": k, "score": k,
                   "review_score": k, "decision": "match"} for i, (cid, k) in enumerate(zip(ids, _KEY))}
    (d / "key.json").write_text(json.dumps({"stage": "final", "cases_sha256": "s", "cases": cases, "dropped": {}}))
    (d / "sha").write_text("s  cases.jsonl\n")
    (d / "retrieved.jsonl").write_text("".join(
        json.dumps({"qid": f"q{i}", "domain": "shop", "status": "ok", "drop_reason": None}) + "\n" for i in range(10))
        + json.dumps({"qid": "qx", "domain": "hr", "status": "dropped", "drop_reason": "answerable"}) + "\n")
    (d / "assignment.json").write_text(json.dumps({"seed": 1, "rounds": [{"domains": {
        "shop": {"types": {f"q{i}": _TYPE_OF[k] for i, k in enumerate(_KEY)}, "unused": [], "eighth_to_sixth": 0}}}]}))
    res = d / "results"
    res.mkdir()

    def write(name: str, outs: list[str]) -> None:
        (res / name).write_text("".join(
            json.dumps({"case_id": c, "output": o, "finish": "stop", "cases_sha256": "s"}) + "\n" for c, o in zip(ids, outs)))

    write("M1_run1.jsonl", ["[RESULT] 4"] * 10)
    write("M3_run1.jsonl", ["[RESULT] 5"] * 10)
    write("M4_run1.jsonl", [f"이유를 적었다. [{k}]" for k in _KEY])   # 대괄호 끝 규칙으로만 읽힌다
    return {"answer_key": d / "key.json", "cases_sha": d / "sha", "results_dir": res,
            "retrieved": d / "retrieved.jsonl", "assignment": d / "assignment.json"}


def check_build_compares_in_the_right_direction() -> None:
    """M1 은 전부 4, M3 는 전부 5, M4 는 대응표와 같다(대괄호 끝으로 적었다).
    M3 와 M1: M3 가 더 가까움 3, M1 이 더 가까움 7. M3 와 M4: 0 대 7 로 M4. M4 만 교체 후보다."""
    with tempfile.TemporaryDirectory() as tmp:
        text = build(**_write_inputs(Path(tmp)))
    assert "| M4 | 10/10 | 0 | 0 | 0 | 10 |" in text                     # v2 규칙으로 모두 읽혔다
    assert "| M3 | 4/10 | 7 | 0 | 4 |" in text                            # 놓침 7, 헛경보 0, 심각한 놓침 4
    assert "- M3 와 M1 (서비스의 채점 모델을 M3 로 바꿔도 되는가): M3 가 더 가까움 3, M1 가 더 가까움 7" in text
    assert "M3 가 더 가까움 0, M4 가 더 가까움 7" in text and "판정: **M4 가 대응표에 더 가깝다**" in text
    assert "- M4: **교체 후보**" in text
    assert "- M3: 아님. 거리 1 이하 사례가 M1 보다 적다(4 < 5)" in text
    assert "hr: 검색한 질문 1개 중 버림 answerable 1" in text
    assert "| 늘 4점 |" in text                                          # 가짜 모델 행


def check_build_refuses_draft_key() -> None:
    from .judge5_report import ReportProblem
    with tempfile.TemporaryDirectory() as tmp:
        paths = _write_inputs(Path(tmp))
        doc = json.loads(paths["answer_key"].read_text())
        paths["answer_key"].write_text(json.dumps({**doc, "stage": "draft"}))
        try:
            build(**paths)
        except ReportProblem:
            return
    raise AssertionError("검수 전 정답 파일로는 보고서를 만들지 않는다")


CHECKS = [check_error_counts_follow_spec, check_build_compares_in_the_right_direction, check_build_refuses_draft_key]


def main() -> None:
    for fn in CHECKS:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(CHECKS)}가지 전부 통과.")


if __name__ == "__main__":
    main()
