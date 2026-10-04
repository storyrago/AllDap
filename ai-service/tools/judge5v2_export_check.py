"""tools.judge5v2_export 의 점검. DB 도 외부 API 도 쓰지 않는다.

실행:  cd ai-service && python -m tools.judge5v2_export_check

시험지에 변형 유형이나 정답 점수가 새어 들어가면 채점 모델과 검수 세션이 답을 보고 매기게 된다.
검수 결과를 잘못 반영하면 정답 점수가 바뀐다. 둘 다 결과 숫자로는 드러나지 않는다.
"""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
from pathlib import Path
from unittest import mock

from . import judge5v2_export
from .judge5 import build_messages
from .judge5v2_export import CASE_KEYS, ExportProblem, apply_review, build_cases, case_id_of, fence_for

_SRC = [{"chunk_id": 1, "filename": "a.md",
         "content": "골드 10,000원 / 실버 20,000원 / 브론즈 30,000원. 이 문장은 200자보다 길 수 있다."}]
_SETTINGS = {"top_k": 5}


def _inputs():
    questions = [
        {"qid": "shop-001", "domain": "shop", "question": "골드 무료 기준은?", "answer": "골드는 10,000원 이상이면 무료입니다.",
         "claims": 1, "two_part": False, "contrast": {"asked": {"target": "골드", "value": "10,000원"},
                                                      "other": {"target": "실버", "value": "20,000원"}, "chunk_ids": [1]}},
        {"qid": "shop-002", "domain": "shop", "question": "실버 무료 기준은?", "answer": "실버는 20,000원 이상이면 무료입니다.",
         "claims": 1, "two_part": False, "contrast": None},
        {"qid": "shop-003", "domain": "shop", "question": "브론즈 무료 기준은?", "answer": "브론즈는 30,000원 이상이면 무료입니다.",
         "claims": 1, "two_part": False, "contrast": None},
    ]
    retrieved = [{"qid": q["qid"], "status": "ok", "settings": _SETTINGS, "sources": _SRC} for q in questions]
    types = {"shop-001": 8, "shop-002": 1, "shop-003": 6}
    variants = [{"qid": "shop-001", "type": 8, "answer": "골드는 20,000원 이상이면 무료입니다.", "note": ""},
                {"qid": "shop-002", "type": 1, "answer": "실버는 20,000원 이상이면 무료입니다.", "note": ""},
                {"qid": "shop-003", "type": 6, "answer": "브론즈는 35,000원 이상이면 무료입니다.", "note": "",
                 "new_value": "35,000원", "old_value": "30,000원"}]
    return questions, retrieved, types, variants


def check_cases_hide_type_and_score() -> None:
    rows, key = build_cases(*_inputs())
    assert all(set(r) == CASE_KEYS for r in rows)
    text = json.dumps(rows, ensure_ascii=False)
    assert "table_score" not in text and "shop-001" not in text   # qid 도 단서가 되지 않게 넣지 않는다
    assert {k["table_score"] for k in key.values()} == {1, 5}


def check_messages_carry_full_sources_and_variant() -> None:
    rows, key = build_cases(*_inputs())
    by_qid = {k["qid"]: cid for cid, k in key.items()}
    row = next(r for r in rows if r["case_id"] == by_qid["shop-001"])
    assert row["messages"] == build_messages("골드 무료 기준은?", [{"filename": "a.md", "content": _SRC[0]["content"]}],
                                             "골드는 20,000원 이상이면 무료입니다.")
    assert row["search_settings"] == _SETTINGS


def check_case_id_uses_no_type() -> None:
    assert case_id_of("shop", "q", "a") == case_id_of("shop", "q", "a")
    assert len(case_id_of("shop", "q", "a")) == 12 and case_id_of("shop", "q", "a") != case_id_of("shop", "q", "b")


def check_rows_are_shuffled_but_fixed() -> None:
    q, r, t, v = _inputs()
    a, _ = build_cases(q, r, t, v)
    b, _ = build_cases(q[::-1], r[::-1], t, v[::-1])
    assert a == b


def check_build_refuses_bad_variants() -> None:
    q, r, t, v = _inputs()
    sixth_in_source = dict(v[2], answer="브론즈는 20,000원 이상이면 무료입니다.", new_value="20,000원")
    bad_cases = [
        [dict(v[0], type=6), v[1], v[2]],                                       # 배정과 유형이 다르다
        [v[0], dict(v[1], answer="실버는 2만 원 이상이면 무료입니다."), v[2]],     # ①이 원본과 다르다
        [dict(v[0], answer=q[0]["answer"]), v[1], v[2]],                          # ⑧ 이 원본과 같다
        [dict(v[0], answer="골드는 무료입니다."), v[1], v[2]],                     # ⑧ 이 다른 대상의 값을 쓰지 않았다
        [v[1], v[2]],                                                              # 변형 답변이 빠졌다
        [v[0], v[1], sixth_in_source],                                             # ⑥ 의 값이 근거에 있다
        [v[0], v[1], {k: x for k, x in v[2].items() if k != "new_value"}],         # ⑥ 에 new_value 가 없다
        [v[0], v[1], dict(v[2], new_value="40,000원")],                           # ⑥ 의 new_value 가 답변에 없다
        [v[0], v[1], dict(v[2], answer="브론즈는 35,000원 이상이면 무료입니다. 기존 기준은 30,000원입니다.")],  # ⑥ 에 옛 값이 남았다
        [v[0], v[1], {k: x for k, x in v[2].items() if k != "old_value"}],         # ⑥ 에 old_value 가 없다
        [v[0], v[1], dict(v[2], old_value="25,000원")],                           # ⑥ 의 old_value 가 멀쩡한 답변에 없다
        [dict(v[0], answer="골드는 10,000원, 실버는 20,000원입니다."), v[1], v[2]],  # ⑧ 이 두 대상의 값을 다 썼다
    ]
    for variants in bad_cases:
        try:
            build_cases(q, r, t, variants)
        except ExportProblem:
            continue
        raise AssertionError(variants)
    two_part = [dict(x, two_part=True) if x["qid"] == "shop-003" else x for x in q]
    try:
        build_cases(two_part, r, t, v)                                     # ⑥ 이 답이 두 가지인 질문에 붙었다
    except ExportProblem:
        return
    raise AssertionError("답이 두 가지인 질문의 ⑥ 은 거절해야 한다")


def check_values_are_matched_with_boundaries() -> None:
    """값은 다른 값의 일부로 찾지 않는다(계획 형식 1). 묻는 값 2,000원 이 답변의 12,000원 안에 있다고 보면
    멀쩡한 ⑧ 을 거절한다. ⑥ 의 새 값 35,000원 이 근거의 135,000원 안에 있다고 보면 멀쩡한 ⑥ 을 거절한다."""
    src = [{"chunk_id": 1, "filename": "a.md", "content": "일반 2,000원, 프리미엄 12,000원, 법인 135,000원"}]
    q = [{"qid": "fin-001", "domain": "finance", "question": "일반 수수료는?", "answer": "2,000원입니다.", "claims": 1,
          "two_part": False, "contrast": {"asked": {"target": "일반", "value": "2,000원"},
                                          "other": {"target": "프리미엄", "value": "12,000원"}, "chunk_ids": [1]}},
         {"qid": "fin-002", "domain": "finance", "question": "법인 수수료는?", "answer": "135,000원입니다.", "claims": 1,
          "two_part": False, "contrast": None}]
    r = [{"qid": x["qid"], "status": "ok", "settings": _SETTINGS, "sources": src} for x in q]
    v = [{"qid": "fin-001", "type": 8, "answer": "12,000원입니다.", "note": ""},
         {"qid": "fin-002", "type": 6, "answer": "35,000원입니다.", "note": "", "new_value": "35,000원",
          "old_value": "135,000원"}]    # 옛 값 135,000원 은 변형 답변의 35,000원 안에 있지 않다(값 경계)
    rows, _ = build_cases(q, r, {"fin-001": 8, "fin-002": 6}, v)
    assert len(rows) == 2


def check_apply_review_paths() -> None:
    """스펙 4절: 같으면 통과, 다르면 사용자 판단(keep, override, drop). 판단이 없으면 멈춘다."""
    key = {c: {"qid": c, "domain": "shop", "type": 3, "table_score": 4} for c in ("a", "b", "c", "d", "e")}
    reviews = [
        {"case_id": "a", "review_score": 4},
        {"case_id": "b", "review_score": 3, "user_decision": "keep", "reason": "대응표가 맞다"},
        {"case_id": "c", "review_score": 3, "user_decision": "override", "override_score": 3, "reason": "주장이 둘이 아니다"},
        {"case_id": "d", "review_score": 2, "user_decision": "drop", "reason": "애매하다"},
        {"case_id": "e", "review_score": 2},
    ]
    kept, dropped, problems = apply_review(key, reviews)
    assert kept["a"]["score"] == 4 and kept["a"]["decision"] == "match"
    assert kept["b"]["score"] == 4 and kept["b"]["decision"] == "keep"
    assert kept["c"]["score"] == 3 and kept["c"]["decision"] == "override"
    assert set(dropped) == {"d"} and "e" not in kept
    assert len(problems) == 1 and problems[0].startswith("e:")
    _, _, p2 = apply_review(key, reviews[:4])
    assert any(x.startswith("e:") for x in p2)                     # 검수 점수가 없는 문항
    _, _, p3 = apply_review(key, [dict(reviews[2], reason="")] + reviews[:2] + reviews[3:4] + [reviews[0] | {"case_id": "e"}])
    assert any(x.startswith("c:") for x in p3)                     # 고친 점수에 이유가 없다
    ok = reviews[:4] + [reviews[0] | {"case_id": "e"}]               # 문제가 없는 검수 줄 다섯
    _, _, p4 = apply_review(key, [dict(ok[1], reason="  ")] + ok[:1] + ok[2:])
    assert [x[:2] for x in p4] == ["b:"]                           # 대응표대로 둔다는 판단에도 이유가 있어야 한다
    _, _, p5 = apply_review(key, ok + [{"case_id": "z", "review_score": 3}])
    assert [x[:2] for x in p5] == ["z:"]                           # 시험지에 없는 문항의 검수 줄


def check_build_uses_last_search_line() -> None:
    """검색 줄은 질문마다 마지막 줄이 판정이다(계획 형식 2). 첫 줄을 쓰면 버린 시도의 근거로 시험지를 만든다."""
    q, r, t, v = _inputs()
    old = dict(r[1], settings={"top_k": 3}, sources=[{"chunk_id": 9, "filename": "old.md", "content": "옛 시도"}])
    rows, key = build_cases(q, [old] + r, t, v)
    cid = next(c for c, k in key.items() if k["qid"] == "shop-002")
    row = next(x for x in rows if x["case_id"] == cid)
    assert row["search_settings"] == _SETTINGS and "옛 시도" not in json.dumps(row, ensure_ascii=False)
    failed_last = dict(r[1], status="dropped", drop_reason="rerank_failed")
    try:
        build_cases(q, r + [failed_last], t, v)                    # 첫 줄은 ok 지만 마지막 시도가 실패했다
    except ExportProblem:
        return
    raise AssertionError("마지막 검색 줄이 실패면 그 질문으로 시험지를 만들지 않아야 한다")


def check_mismatch_fence_outlasts_inner_backticks() -> None:
    """근거 청크 안의 백틱 셋이 mismatches.md 의 코드 블록을 일찍 닫지 않게 울타리를 더 길게 만든다."""
    tick = "`"
    assert fence_for("평범한 글") == tick * 3
    body = "앞\n" + tick * 3 + "python\nx = 1\n" + tick * 3 + "\n뒤 " + tick * 5
    assert fence_for(body) == tick * 6


def check_draft_refuses_to_overwrite_final() -> None:
    """동결된 최종 정답 파일을 draft 로 덮지 않는다. 덮으면 M1 채점이 검수 전 시험지로 돈다."""
    with tempfile.TemporaryDirectory() as tmp:
        ak = Path(tmp) / "answer_key.json"
        ak.write_text(json.dumps({"stage": "final", "cases": {}}), encoding="utf-8")
        before = ak.read_text(encoding="utf-8")

        def must_not_build():
            raise AssertionError("final 이 있으면 시험지를 다시 만들기 전에 멈춰야 한다")

        with mock.patch.multiple(judge5v2_export, ANSWER_KEY=ak, load_and_build=must_not_build), \
                contextlib.redirect_stdout(io.StringIO()):
            assert judge5v2_export.cmd_draft() == 1
        assert ak.read_text(encoding="utf-8") == before


CHECKS = [
    check_cases_hide_type_and_score,
    check_messages_carry_full_sources_and_variant,
    check_case_id_uses_no_type,
    check_rows_are_shuffled_but_fixed,
    check_build_refuses_bad_variants,
    check_values_are_matched_with_boundaries,
    check_apply_review_paths,
    check_build_uses_last_search_line,
    check_mismatch_fence_outlasts_inner_backticks,
    check_draft_refuses_to_overwrite_final,
]


def main() -> None:
    for fn in CHECKS:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(CHECKS)}가지 전부 통과.")


if __name__ == "__main__":
    main()
