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


def check_build_counts_no_finish_and_nondefault() -> None:
    """못 읽음 중 512 잘림, finish 기록 없음, 그 밖의 finish 값을 따로 센다. 검색 줄의 nondefault 수와 시험지의
    검색 설정 종류를 적는다."""
    with tempfile.TemporaryDirectory() as tmp:
        paths = _write_inputs(Path(tmp))
        m4 = paths["results_dir"] / "M4_run1.jsonl"
        rows = [json.loads(l) for l in m4.read_text().splitlines()]
        for i, r in enumerate(rows):
            # 대괄호 끝은 stop 일 때만 읽는다. content_filter 는 stop, length, 기록 없음이 아닌 그 밖의 값의 예다.
            r["finish"] = None if i < 3 else "length" if i < 5 else "content_filter" if i == 5 else "stop"
        m4.write_text("".join(json.dumps(r) + "\n" for r in rows))
        with paths["retrieved"].open("a") as f:   # q0 를 다른 설정으로 다시 검색한 줄
            f.write(json.dumps({"qid": "q0", "domain": "shop", "status": "ok", "drop_reason": None,
                                "settings": {"top_k": 8}, "nondefault": {"top_k": {"default": 5, "actual": 8}}}) + "\n")
            # 시험지에 없는 질문(qy)의 줄은 시험지의 설정 종류에 세지 않는다.
            f.write(json.dumps({"qid": "qy", "domain": "hr", "status": "dropped", "drop_reason": "max_distance",
                                "settings": {"top_k": 3}}) + "\n")
        text = build(**paths)
    assert "(missing 6, 그중 2개는 512 토큰에서 잘림, 3개는 finish 기록 없음, 1개는 finish 가 그 밖의 값)" in text, text
    assert "검색 줄(nondefault) 1개, 최종 시험지의 검색 설정 2가지" in text


def check_settings_kinds_use_last_search_line() -> None:
    """시험지 문항의 앞 검색 줄이 다른 설정이어도 마지막 줄이 기본이면 설정은 1가지다. 시험지는 마지막 줄의
    settings 를 옮기므로(judge5v2_export), 앞 줄까지 세면 시험지에 없는 설정을 섞였다고 잘못 적는다."""
    with tempfile.TemporaryDirectory() as tmp:
        paths = _write_inputs(Path(tmp))
        base = paths["retrieved"].read_text()
        earlier = json.dumps({"qid": "q1", "domain": "shop", "status": "dropped", "drop_reason": "rerank_failed",
                              "settings": {"top_k": 8}}) + "\n"
        paths["retrieved"].write_text(earlier + base)   # q1 의 앞 줄은 다른 설정, 마지막 줄은 다른 문항과 같은 설정
        text = build(**paths)
    assert "최종 시험지의 검색 설정 1가지" in text, text


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


CHECKS = [check_error_counts_follow_spec, check_build_compares_in_the_right_direction, check_build_counts_no_finish_and_nondefault,
          check_settings_kinds_use_last_search_line, check_build_refuses_draft_key]


def main() -> None:
    for fn in CHECKS:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(CHECKS)}가지 전부 통과.")


if __name__ == "__main__":
    main()
