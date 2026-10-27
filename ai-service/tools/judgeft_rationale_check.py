"""tools.judgeft_rationale 의 점검. DB 도 외부 API 도 쓰지 않는다.

실행:  cd ai-service && python -m tools.judgeft_rationale_check
"""
from __future__ import annotations

from .judge5 import RULES_V2, parse_result
from .judgeft_files import TABLE_SCORE
from .judgeft_rationale import load_templates, record_problems, render, template_problems

SOURCES = [{"filename": "a.md", "content": "베이직 요금제는 데이터를 월 10GB 준다."},
           {"filename": "b.md", "content": "프리미엄 요금제는 데이터를 월 30GB 준다."}]
QUESTION = {"qid": "x-001", "contrast": {"asked": {"target": "베이직", "value": "월 10GB"},
                                         "other": {"target": "프리미엄", "value": "월 30GB"}, "chunk_ids": [1, 2]}}
REC8 = {"target": "베이직", "evidence": [{"source": 1, "quote": "월 10GB"}],
        "other": {"target": "프리미엄", "source": 2, "quote": "월 30GB"}}
RECS = {
    1: {"target": "베이직", "evidence": [{"source": 1, "quote": "월 10GB"}]},
    2: {"target": None, "evidence": [{"source": 1, "quote": "월 10GB"}]},
    3: {"evidence": [{"source": 1, "quote": "월 10GB"}], "added": ["남은 데이터는 이월됩니다"]},
    4: {"evidence": [{"source": 1, "quote": "월 10GB"}], "added": ["대리점에서만 바꿀 수 있습니다"]},
    5: {"evidence": [{"source": 1, "quote": "월 10GB"}], "added": ["가입비가 없습니다", "해외에서도 쓸 수 있습니다"]},
    6: {"target": "베이직", "evidence": [{"source": 1, "quote": "월 10GB"}], "new_value": "월 20GB",
        "old_value": "월 10GB"},
    7: {"gist": "매장 방문 예약 절차"},
    8: REC8,
}


def check_committed_templates_follow_rules() -> None:
    """커밋된 틀 파일: 묶음 아홉, 묶음마다 셋 이상, 빈칸 규칙, 한글 없음, 끝맺음 없음."""
    assert template_problems(load_templates()) == []


def check_template_problems_catch_broken_files() -> None:
    good = load_templates()
    assert template_problems({k: v for k, v in good.items() if k != "eight"})                   # 묶음 하나 빠짐
    assert template_problems({**good, "seven": good["seven"][:2]})                              # 둘뿐
    assert template_problems({**good, "seven": good["seven"] + ["The response says \"베이직\" 요금 {gist}."]})  # 한글
    assert template_problems({**good, "four": good["four"] + ["{evidence} only."]})             # added 빠짐
    assert template_problems({**good, "two": good["two"] + ["{evidence} {added} [RESULT] 2"]})   # 끝맺음


def check_every_type_renders_and_parses_to_table_score() -> None:
    """모범 답안을 v2 의 읽는 규칙으로 읽으면 정답 점수가 나온다(스펙 5-2절 확인 4)."""
    tpl = load_templates()
    for t, rec in RECS.items():
        assert record_problems(t, rec, QUESTION, SOURCES) == [], (t, record_problems(t, rec, QUESTION, SOURCES))
        out = render(t, rec, QUESTION, f"id-{t}", tpl)
        assert parse_result(out, "stop", rules=RULES_V2) == (TABLE_SCORE[t], "ok"), (t, out)
        assert out.count("[RESULT]") == 1 and "{" not in out
    eight = render(8, REC8, QUESTION, "id-8", tpl)
    assert "\"베이직\"" in eight and "\"프리미엄\"" in eight and "월 30GB" in eight and "[근거 2]" in eight


def check_render_is_seeded_by_item_id() -> None:
    tpl = load_templates()
    a = {render(8, REC8, QUESTION, f"id-{i}", tpl) for i in range(30)}
    assert len(a) == 3                                                       # 세 틀이 모두 쓰인다
    assert render(8, REC8, QUESTION, "id-1", tpl) == render(8, REC8, QUESTION, "id-1", tpl)


def check_record_problems_catch_bad_quotes_and_targets() -> None:
    assert record_problems(1, {"target": "베이직", "evidence": [{"source": 1, "quote": "월 70GB"}]}, QUESTION, SOURCES)
    assert record_problems(1, {"target": "베이직", "evidence": [{"source": 3, "quote": "월 10GB"}]}, QUESTION, SOURCES)
    assert record_problems(8, {**REC8, "target": "프리미엄"}, QUESTION, SOURCES)
    assert record_problems(8, {**REC8, "other": {"target": "프리미엄", "source": 1, "quote": "월 30GB"}},
                           QUESTION, SOURCES)
    assert record_problems(3, {"evidence": [{"source": 1, "quote": "월 10GB"}]}, QUESTION, SOURCES)
    assert record_problems(7, {}, QUESTION, SOURCES)
    swapped = {**REC8, "evidence": [{"source": 2, "quote": "월 30GB"}]}            # 첫째 인용이 다른 대상의 값
    assert any("첫째" in p for p in record_problems(8, swapped, QUESTION, SOURCES))
    two = dict(QUESTION, claims=2)                                                # 주장이 둘인데 인용이 하나
    assert any("2개 적는다" in p for p in record_problems(8, REC8, two, SOURCES))
    assert record_problems(8, {**REC8, "evidence": REC8["evidence"] + [{"source": 1, "quote": "데이터를"}]}, two,
                           SOURCES) == []


def check_eighth_cites_asked_value_and_pair_cites_all() -> None:
    """⑧ 의 모범 답안은 첫째 인용(질문 대상의 값)만, 짝 문항은 모든 인용을 쓴다."""
    tpl = load_templates()
    rec = {**REC8, "evidence": REC8["evidence"] + [{"source": 1, "quote": "데이터를"}]}
    eight = render(8, rec, QUESTION, "id-8", tpl)
    pair = render(1, {"target": rec["target"], "evidence": rec["evidence"]}, QUESTION, "id-p", tpl)
    assert "\"데이터를\"" not in eight and "\"데이터를\"" in pair and "\"월 10GB\"" in pair


CHECKS = [check_committed_templates_follow_rules, check_template_problems_catch_broken_files,
          check_every_type_renders_and_parses_to_table_score, check_render_is_seeded_by_item_id,
          check_record_problems_catch_bad_quotes_and_targets, check_eighth_cites_asked_value_and_pair_cites_all]


def main() -> None:
    for fn in CHECKS:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(CHECKS)}가지 전부 통과.")


if __name__ == "__main__":
    main()
