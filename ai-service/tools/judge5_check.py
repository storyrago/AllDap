"""채점 모델 비교 실험(2026-10-02)의 자체 점검. DB 도 외부 API 도 쓰지 않는다. CI 에서 돈다.

실행:  cd ai-service && .venv/bin/python -m tools.judge5_check

왜 이 검사가 있나
─────────────────────────────────────────────────────────────────────────────
이 실험의 결론은 "어느 채점 모델이 사람에 더 가까운가, 어느 방향으로 틀리는가" 다.
점수를 읽는 규칙, 후함과 박함의 부호, 부호 검정의 p 값 중 하나만 틀려도 결론이 바뀐다.
숫자는 그럴듯하게 나오므로 눈으로는 잡히지 않는다. 그래서 검사로 고정한다.
"""
from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

from .judge5 import (
    CRITERIA, MAX_NEW_TOKENS, MODELS, RUBRIC, SCALE,
    build_messages, compare, linear_weighted_kappa, parse_result, pick_best,
    replacement_failures, sign_test_p, summarize, to_three,
)
from .judge5_cloudflare import done_ids, result_line
from .judge5_export import CASES_SHA, NEW_LABELS, ROOT, labels_ready, make_cases, make_label_file
from .judge_label_server import LabelRejected, apply_label

_SOURCES = [
    {"chunk_id": 1, "filename": "a.md", "content": "연차는 15일이다."},
    {"chunk_id": 2, "filename": "b.md", "content": "재택은 주 1회다."},
]

_OLD = {
    "_readme": "옛 안내",
    "run_ids": [11],
    "cases": [
        {"case_id": "bb", "question_id": "2", "question": "q2", "ground_truth": "정답2",
         "generated_answer": "a2", "sources": _SOURCES, "seen_in_runs": [11], "label": 1, "note": "옛 메모"},
        {"case_id": "aa", "question_id": "1", "question": "q1", "ground_truth": "정답1",
         "generated_answer": "a1", "sources": _SOURCES, "seen_in_runs": [11], "label": 0.5, "note": ""},
    ],
}


def check_new_label_file_hides_old_label_and_reference() -> None:
    """🔴 새 라벨은 블라인드로 매긴다. 옛 라벨, 옛 메모, 기대 답변이 파일에 없어야 화면에도 못 샌다."""
    new = make_label_file(_OLD)
    for c in new["cases"]:
        assert c["label"] is None and c["note"] == ""
        assert "ground_truth" not in c
        assert "seen_in_runs" not in c
    assert "옛 메모" not in str(new)
    assert "정답1" not in str(new)


_CASE_KEYS = {"case_id", "question", "generated_answer", "sources", "label", "note"}


def check_new_label_file_keeps_cases_and_only_safe_keys() -> None:
    """사례 키가 정확히 여섯이어야 한다. question_id 같은 단서가 하나라도 붙으면 여기서 걸린다."""
    new = make_label_file(_OLD)
    assert {c["case_id"] for c in new["cases"]} == {"aa", "bb"}
    assert all(set(c) == _CASE_KEYS for c in new["cases"])
    assert all(c["sources"] == _SOURCES for c in new["cases"])
    assert new["scale"] == 5


def check_new_label_file_order_is_shuffled_but_fixed() -> None:
    """옛 화면(case_id 순서)과 다른 순서로 보이되, 다시 만들어도 같은 순서여야 한다."""
    old = dict(_OLD, cases=[dict(_OLD["cases"][0], case_id=f"c{i:02d}") for i in range(20)])
    a = [c["case_id"] for c in make_label_file(old)["cases"]]
    b = [c["case_id"] for c in make_label_file(dict(old, cases=old["cases"][::-1]))["cases"]]
    assert a == b                 # 입력 순서와 무관하고 실행마다 같다
    assert a != sorted(a)         # 옛 화면 순서가 아니다


def check_committed_new_label_file_is_blind() -> None:
    """커밋된 새 라벨 파일 자체를 본다. 손으로 고치거나 다른 도구가 덮어써 단서가 들어가도 CI 가 잡는다.
    Task 3 뒤에는 이 파일이 실험의 자이므로 라벨 값의 범위도 함께 본다."""
    data = json.loads(NEW_LABELS.read_text(encoding="utf-8"))
    assert data["scale"] == 5
    assert data["rubric"]["criteria"] == CRITERIA
    assert data["rubric"]["levels"] == {str(k): v for k, v in RUBRIC.items()}
    assert len(data["cases"]) == 44
    for c in data["cases"]:
        assert set(c) == _CASE_KEYS, c["case_id"]
        assert c["label"] is None or c["label"] in SCALE, c["case_id"]


def check_new_label_file_rubric_is_the_model_rubric() -> None:
    """사람이 보는 채점표와 모델이 받는 채점표가 같은 글자여야 한다."""
    new = make_label_file(_OLD)
    assert new["rubric"]["criteria"] == CRITERIA
    assert new["rubric"]["levels"] == {str(k): v for k, v in RUBRIC.items()}


def check_apply_label_five_point_mode() -> None:
    data = make_label_file(_OLD)
    out = apply_label(data, "aa", 4, "")
    # 순서를 섞으므로 위치가 아니라 case_id 로 본다.
    assert {c["case_id"]: c["label"] for c in out["cases"]} == {"aa": 4, "bb": None}
    for bad in (0, 0.5, 6):
        try:
            apply_label(data, "aa", bad, "")
        except LabelRejected:
            continue
        raise AssertionError(f"{bad} 를 받으면 안 된다")


def check_apply_label_old_mode_unchanged() -> None:
    """scale 이 없는 옛 파일은 예전처럼 0, 0.5, 1 만 받는다."""
    out = apply_label(_OLD, "aa", 0.5, "")
    assert out["cases"][1]["label"] == 0.5
    try:
        apply_label(_OLD, "aa", 4, "")
    except LabelRejected:
        return
    raise AssertionError("옛 파일에 4 를 받으면 안 된다")


def check_parse_reads_single_result() -> None:
    assert parse_result("Feedback: 근거와 같다. [RESULT] 5") == (5, "ok")
    # 괄호를 씌우거나 공백이 없어도 읽는다. 모델마다 버릇이 다르다.
    assert parse_result("Feedback: x [RESULT](4)") == (4, "ok")


def check_parse_keeps_failure_reasons_apart() -> None:
    """못 읽은 이유 셋을 하나로 뭉개지 않는다(이 저장소가 낸 버그 부류)."""
    assert parse_result("Feedback: 점수를 안 썼다") == (None, "missing")
    assert parse_result("") == (None, "missing")
    assert parse_result(None) == (None, "missing")
    assert parse_result("[RESULT] 7") == (None, "out_of_range")
    assert parse_result("[RESULT] 0") == (None, "out_of_range")
    assert parse_result("[RESULT] 3 ... [RESULT] 5") == (None, "conflict")
    # 같은 점수를 두 번 쓴 것은 모순이 아니다.
    assert parse_result("[RESULT] 4 [RESULT] 4") == (4, "ok")


def check_messages_carry_every_source_in_order() -> None:
    msgs = build_messages("연차는?", _SOURCES, "15일입니다.")
    assert [m["role"] for m in msgs] == ["system", "user"]
    user = msgs[1]["content"]
    # 근거 순서가 채점을 바꾼다는 것이 실측돼 있다(2026-09-18). 순서를 지키는지 본다.
    assert user.index("[근거 1] (출처: a.md)") < user.index("[근거 2] (출처: b.md)")
    assert "연차는 15일이다." in user and "재택은 주 1회다." in user
    assert "15일입니다." in user and "연차는?" in user


def check_messages_carry_the_whole_rubric() -> None:
    user = build_messages("q", _SOURCES, "a")[1]["content"]
    assert CRITERIA in user
    for k in SCALE:
        assert f"Score {k}: {RUBRIC[k]}" in user


def check_messages_do_not_leak_reference_answer() -> None:
    """스펙 §3-2: 공통 지시문에 기대 답변을 넣지 않는다. 자리 자체가 없어야 한다."""
    user = build_messages("q", _SOURCES, "a")[1]["content"]
    assert "Reference Answer" not in user
    assert "기대 답변" not in user


def check_summary_direction() -> None:
    """🔴 후함 = 모델이 사람보다 높다. 부호가 뒤집히면 결론이 정반대가 된다."""
    # 후함 2건, 박함 1건으로 일부러 비대칭이다. 1 대 1 이면 부호를 뒤집어도 같은 값이 나와
    # 검사가 아무것도 잡지 못한다(계획의 원래 데이터가 그랬다. 변이 시험으로 확인했다).
    s = summarize([(3, 5), (2, 4), (5, 4), (4, 4), (2, None)])
    assert (s.generous, s.harsh) == (2, 1)
    assert (s.total, s.unread, s.exact, s.within1) == (5, 1, 1, 2)
    assert s.mean_distance == (2 + 2 + 1 + 0) / 4
    assert s.confusion[(3, 5)] == 1 and s.confusion[(5, 4)] == 1


def check_summary_all_unread_has_no_mean() -> None:
    """전부 못 읽었으면 평균 거리는 0 이 아니라 없음이다."""
    assert summarize([(5, None)]).mean_distance is None


def check_sign_test_known_values() -> None:
    assert sign_test_p(0, 0) == 1.0
    assert abs(sign_test_p(0, 10) - 2 / 1024) < 1e-12
    assert abs(sign_test_p(10, 10) - 2 / 1024) < 1e-12
    assert abs(sign_test_p(1, 5) - 2 * (1 + 5) / 32) < 1e-12
    assert sign_test_p(3, 6) == 1.0


def check_compare_excludes_unread_and_ties() -> None:
    human = {"a": 5, "b": 5, "c": 3, "d": 4}
    x = {"a": 5, "b": 4, "c": None, "d": 4}
    y = {"a": 4, "b": 4, "c": 3, "d": 4}
    c = compare(human, x, y)
    assert (c.excluded, c.a_closer, c.b_closer, c.ties) == (1, 1, 0, 2)
    assert c.verdict("x", "y") == "구별되지 않음"


def check_compare_verdict_names_the_closer_model() -> None:
    human = {str(i): 5 for i in range(10)}
    good = {str(i): 5 for i in range(10)}
    bad = {str(i): 1 for i in range(10)}
    assert compare(human, good, bad).verdict("좋은", "나쁜") == "좋은 가 사람에 더 가깝다"
    assert compare(human, bad, good).verdict("나쁜", "좋은") == "좋은 가 사람에 더 가깝다"


def check_kappa() -> None:
    # 부동소수 계산이라 정확히 1.0 이 아닐 수 있다. 아주 작은 오차는 허용한다.
    assert abs(linear_weighted_kappa([(1, 1), (3, 3), (5, 5)]) - 1.0) < 1e-12
    # 한 칸에만 몰리면 정의되지 않는다. 0 으로 뭉개지 않고 없음으로 돌려준다.
    assert linear_weighted_kappa([(5, 5), (5, 5)]) is None
    assert linear_weighted_kappa([]) is None


def check_to_three_follows_old_label_definition() -> None:
    """근거에 없는 주장이 하나라도 있으면 1.0 이 아니다(옛 라벨 정의)."""
    assert [to_three(v) for v in SCALE] == [0.0, 0.5, 0.5, 0.5, 1.0]


def check_pick_best_tie_breaks() -> None:
    a = summarize([(5, 5), (5, 4), (5, 1)])        # 거리 1 이하 2건, 평균 5/3
    b = summarize([(5, 5), (5, 4), (5, 1)])        # a 와 모든 값이 같다
    c = summarize([(5, 5), (5, 4), (5, 3)])        # 거리 1 이하 2건, 평균 1
    assert pick_best({"M2": a, "M3": c}) == "M3"   # 평균 거리가 작은 쪽
    assert pick_best({"M3": a, "M2": b}) == "M2"   # 모든 값이 같으면 이름 순서
    assert pick_best({}) is None
    # 못 읽음만 다른 두 요약: 못 읽음이 적은 쪽(리뷰 지적, 이 분기가 점검에 안 걸려 있었다).
    with_unread = summarize([(5, 5), (5, 5), (5, None)])   # 거리 1 이하 2건, 평균 0, 못 읽음 1
    no_unread = summarize([(5, 5), (5, 5)])                 # 거리 1 이하 2건, 평균 0, 못 읽음 0
    assert pick_best({"M2": with_unread, "M3": no_unread}) == "M3"
    # 평균 거리가 못 읽음보다 먼저 본다. 순서가 뒤집히면 M2 가 뽑힌다.
    worse_mean = summarize([(5, 5), (5, 4)])                # 거리 1 이하 2건, 평균 0.5, 못 읽음 0
    assert pick_best({"M2": worse_mean, "M3": with_unread}) == "M3"


def check_replacement_rule() -> None:
    m1 = summarize([(5, 5), (5, 5), (4, 4)])
    good = summarize([(5, 5), (5, 5), (4, 4)])
    unread = summarize([(5, 5), (5, None), (4, 4)])
    human = {"a": 5, "b": 5, "c": 4}
    tie = compare(human, {"a": 5, "b": 5, "c": 4}, {"a": 5, "b": 5, "c": 4})
    assert replacement_failures(good, m1, tie) == []
    assert any("못 읽음" in r for r in replacement_failures(unread, m1, tie))

    # 기준 1: 거리 1 이하가 M1 보다 하나라도 적으면 탈락한다.
    one_less = summarize([(5, 5), (5, 3), (4, 4)])
    assert any("거리 1 이하" in r for r in replacement_failures(one_less, m1, tie))

    # 기준 3 의 방향. compare 의 인자 순서는 (사람, 후보, M1) 이다. 10:0 으로 갈리면 p = 2/1024 < 0.05.
    # 두 경우 모두 거리 1 이하 수가 같아서(전부 거리 0 또는 1) 기준 1 은 걸리지 않는다. 기준 3 만 따로 본다.
    human10 = {str(i): 5 for i in range(10)}
    fives = {str(i): 5 for i in range(10)}
    fours = {str(i): 4 for i in range(10)}
    s5, s4 = summarize([(5, 5)] * 10), summarize([(5, 4)] * 10)
    # 가) M1 이 사람에 더 가깝다 → 실패 사유가 나와야 한다.
    assert any("M1 이 사람에 더 가깝다" in r
               for r in replacement_failures(s4, s5, compare(human10, fours, fives)))
    # 나) 후보가 사람에 더 가깝다 → 실패 사유가 없어야 한다(방향이 뒤집히면 여기서 걸린다).
    assert replacement_failures(s5, s4, compare(human10, fives, fours)) == []


def _filled(labels: dict, v: int = 5) -> dict:
    return dict(labels, cases=[dict(c, label=v) for c in labels["cases"]])


def check_cases_carry_no_label() -> None:
    """🔴 시험지에 사람 라벨이 들어가면 코랩 모델이 정답을 보고 채점한다."""
    cases = make_cases(_filled(make_label_file(_OLD), 3))
    assert [sorted(c) for c in cases] == [["case_id", "messages"]] * 2
    assert all('"label"' not in json.dumps(c, ensure_ascii=False) for c in cases)


def check_cases_use_the_common_messages() -> None:
    labels = _filled(make_label_file(_OLD))
    first = labels["cases"][0]
    assert make_cases(labels)[0]["messages"] == build_messages(
        first["question"], first["sources"], first["generated_answer"])


def check_labels_ready_refuses_incomplete() -> None:
    """라벨이 하나라도 비면 시험지를 만들지 않는다(스펙 §4-1 순서)."""
    assert labels_ready(make_label_file(_OLD))   # 비어 있으면 문제 목록이 나온다
    assert labels_ready(_filled(make_label_file(_OLD))) == []


def check_result_line_shape() -> None:
    line = result_line("aa", "M1", "@cf/x", "cloudflare", 1, "Feedback: [RESULT] 5", "stop", "abc")
    assert sorted(line) == sorted(
        ["case_id", "model", "repo", "revision", "run", "output", "finish", "cases_sha256"])


def check_done_ids_reads_existing_lines() -> None:
    """이어 하기: 이미 쓴 사례는 다시 부르지 않는다(뉴런 절약, 코랩 끊김 대비)."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "M1_run1.jsonl"
        assert done_ids(p) == set()
        p.write_text(json.dumps({"case_id": "aa"}) + "\n" + json.dumps({"case_id": "bb"}) + "\n")
        assert done_ids(p) == {"aa", "bb"}


NOTEBOOK = ROOT / "notebooks" / "judge5_colab.ipynb"


def _notebook_code() -> str:
    nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    # ipynb 의 source 는 문자열일 수도, 줄 목록일 수도 있다. 둘 다 이어 붙인다.
    parts = []
    for cell in nb["cells"]:
        if cell["cell_type"] == "code":
            src = cell["source"]
            parts.append(src if isinstance(src, str) else "".join(src))
    return "\n".join(parts)


def check_notebook_matches_the_module() -> None:
    """노트북은 judge5 를 import 하지 못한다(코랩에는 이 저장소가 없다). 그래서 값을 복사해 두고
    여기서 글자가 같은지 본다. 갈라지면 코랩 모델만 다른 조건으로 채점한다."""
    code = _notebook_code()
    assert f"MAX_NEW_TOKENS = {MAX_NEW_TOKENS}" in code
    for key in ("M2", "M3", "M4"):
        assert f'"{key}": "{MODELS[key]}"' in code, key
    assert "do_sample=False" in code


def check_notebook_hash_matches_cases_file() -> None:
    """시험지 파일이 있으면 노트북의 기대 해시가 그 파일의 해시와 같아야 한다."""
    m = re.search(r'EXPECTED_SHA256\s*=\s*"([0-9a-f]{64}|)"', _notebook_code())
    assert m, "노트북에 EXPECTED_SHA256 줄이 없다"
    if CASES_SHA.exists():
        assert m.group(1) == CASES_SHA.read_text(encoding="utf-8").split()[0], "노트북 해시를 갱신하라(태스크 7)"


CHECKS = [
    check_parse_reads_single_result,
    check_parse_keeps_failure_reasons_apart,
    check_messages_carry_every_source_in_order,
    check_messages_carry_the_whole_rubric,
    check_messages_do_not_leak_reference_answer,
    check_summary_direction,
    check_summary_all_unread_has_no_mean,
    check_sign_test_known_values,
    check_compare_excludes_unread_and_ties,
    check_compare_verdict_names_the_closer_model,
    check_kappa,
    check_to_three_follows_old_label_definition,
    check_pick_best_tie_breaks,
    check_replacement_rule,
    check_new_label_file_hides_old_label_and_reference,
    check_new_label_file_keeps_cases_and_only_safe_keys,
    check_new_label_file_order_is_shuffled_but_fixed,
    check_committed_new_label_file_is_blind,
    check_new_label_file_rubric_is_the_model_rubric,
    check_apply_label_five_point_mode,
    check_apply_label_old_mode_unchanged,
    check_cases_carry_no_label,
    check_cases_use_the_common_messages,
    check_labels_ready_refuses_incomplete,
    check_result_line_shape,
    check_done_ids_reads_existing_lines,
    check_notebook_matches_the_module,
    check_notebook_hash_matches_cases_file,
]


def main() -> None:
    for fn in CHECKS:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(CHECKS)}가지 전부 통과.")


if __name__ == "__main__":
    main()
