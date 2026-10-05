"""tools.judgeft_export 의 점검. DB 도 외부 API 도 쓰지 않는다.

실행:  cd ai-service && python -m tools.judgeft_export_check
"""
from __future__ import annotations

from .judge5 import RULES_V2, parse_result
from .judge5v2_export import apply_review
from .judge5 import build_messages
from .judgeft_export import (
    build_train, forbidden_problems, leak_problems, merge_reviews, overlap_problems, pending_rows, split_val,
    train_short,
)
from .judgeft_files import PAIRS, TRAIN_QUOTA
from .judgeft_rationale import load_templates

SRC = [{"chunk_id": 1, "filename": "plan.md", "content": "베이직 요금제는 데이터를 월 10GB 준다. 프리미엄 요금제는 데이터를 월 30GB 준다."},
       {"chunk_id": 2, "filename": "etc.md", "content": "요금제 변경은 한 달에 한 번 할 수 있다."}]
CONTRAST = {"asked": {"target": "베이직", "value": "월 10GB"}, "other": {"target": "프리미엄", "value": "월 30GB"},
            "chunk_ids": [1]}


def _fixture() -> tuple[list[dict], list[dict], dict, list[dict]]:
    """학습용 질문 넷: ⑧ 둘(하나는 짝), ⑥ 하나, ① 하나. ⑧ 하나(t-002)는 인용이 근거와 달라 빠져야 한다."""
    qs, rs, vs = [], [], []
    for i in range(1, 5):
        qid = f"travel-{i:03d}"
        qs.append({"qid": qid, "domain": "travel", "question": f"베이직 요금제의 데이터는 얼마인가요 {i}",
                   "two_part": False, "answer": "베이직 요금제는 데이터를 월 10GB 줍니다.", "claims": 1,
                   "contrast": CONTRAST})
        rs.append({"qid": qid, "domain": "travel", "status": "ok", "drop_reason": None, "settings": {},
                   "sources": SRC})
    ev = [{"source": 1, "quote": "월 10GB"}]
    other = {"target": "프리미엄", "source": 1, "quote": "월 30GB"}
    vs.append({"qid": "travel-001", "type": 8, "answer": "베이직 요금제는 데이터를 월 30GB 줍니다.", "target": "베이직",
               "evidence": ev, "other": other})
    vs.append({"qid": "travel-002", "type": 8, "answer": "베이직 요금제는 데이터를 월 30GB 줍니다. 참고", "target": "베이직",
               "evidence": [{"source": 1, "quote": "월 70GB"}], "other": other})
    vs.append({"qid": "travel-003", "type": 6, "answer": "베이직 요금제는 데이터를 월 20GB 줍니다.", "target": "베이직",
               "evidence": ev, "new_value": "월 20GB", "old_value": "월 10GB"})
    vs.append({"qid": "travel-004", "type": 1, "answer": "베이직 요금제는 데이터를 월 10GB 줍니다.", "target": "베이직",
               "evidence": ev})
    assignment = {"seed": 1, "rounds": [{"round": 0, "sheet": "train", "pool": [],
                                         "types": {"travel-001": 8, "travel-002": 8, "travel-003": 6, "travel-004": 1},
                                         "pairs": ["travel-001", "travel-002"], "contrast_five": [], "unused": []}]}
    return qs, rs, assignment, vs


def check_build_train_drops_only_broken_items_and_their_pairs() -> None:
    qs, rs, a, vs = _fixture()
    items, dropped = build_train(qs, rs, a, vs, load_templates())
    assert sorted((i["qid"], i["kind"]) for i in items) == [
        ("travel-001", "main"), ("travel-001", "pair"), ("travel-003", "main"), ("travel-004", "main")]
    assert set(dropped["main"]) == {"travel-002"} and set(dropped["pair"]) == {"travel-002"}
    for i in items:
        assert parse_result(i["target"], "stop", rules=RULES_V2) == (i["score"], "ok")
        assert i["messages"][0]["role"] == "system" and i["messages"][1]["role"] == "user"
    pair = next(i for i in items if i["kind"] == "pair")
    assert pair["score"] == 5 and "월 30GB" not in pair["messages"][1]["content"].split("###Response to evaluate:")[1]


def check_split_val_keeps_question_together_and_is_stable() -> None:
    qs, rs, a, vs = _fixture()
    items, _ = build_train(qs, rs, a, vs, load_templates())
    many = [dict(i, qid=f"{i['qid']}-{k}", id=f"{i['id']}{k}") for k in range(10) for i in items]
    train, val = split_val(many)
    assert len(train) + len(val) == len(many)
    assert {i["qid"] for i in train}.isdisjoint({i["qid"] for i in val})       # 같은 질문은 한쪽에만
    assert len({i["qid"] for i in val}) == round(0.1 * len({i["qid"] for i in many}))
    assert split_val(many) == (train, val)


def check_leak_problems_find_overlaps() -> None:
    qs, rs, a, vs = _fixture()
    items, _ = build_train(qs, rs, a, vs, load_templates())
    assert leak_problems(items, qs, rs, ["전혀 다른 시험지 글"]) == []
    assert leak_problems(items, qs, rs, ["... " + SRC[0]["content"] + " ..."])       # 근거 청크가 겹침
    assert leak_problems(items, qs, rs, [qs[0]["question"]])                       # 질문이 겹침
    assert leak_problems(items, qs, rs, [items[0]["target"]])                      # 모범 답안이 겹침


def check_sentence_overlap_both_ways_and_forbidden_values() -> None:
    """문장 하나만 겹쳐도 두 방향 모두에서 찾는다. 공통 지시문의 문장은 겹쳐도 세지 않는다."""
    template = "\n".join(m["content"] for m in build_messages("", [], ""))
    shared = "프리미엄 요금제는 해외 로밍 데이터를 하루 1GB 까지 무료로 준다."
    train = {"학습 문서 a": "첫 문장은 학습 쪽에만 있는 충분히 긴 문장이다. " + shared}
    test = {"시험 문서 b": "시험 쪽 문서의 첫 문장은 여기에만 있는 긴 문장이다.\n" + shared + " 뒤에 더 붙은 말"}
    found = overlap_problems(train, test, template)
    assert len(found) == 2 and any(f.startswith("학습 쪽") for f in found) and any(f.startswith("시험 쪽") for f in found)
    common = {"x": template + "\n학습 쪽 고유의 문장은 이렇게 충분히 길게 쓴다."}
    assert overlap_problems(common, {"y": template + "\n시험 쪽 고유의 문장도 이렇게 충분히 길게 쓴다."}, template) == []
    assert forbidden_problems({"문장 틀": "The response gives {asked_value}."}) == []
    assert forbidden_problems({"학습 문항 1": "이체 한도는 \"1일 5억 원\" 이다"}) == ["학습 문항 1: 금지 값 '1일 5억 원' 가 있다(스펙 4-5절)"]


def check_train_refuses_duplicate_variants_and_counts_quota() -> None:
    """같은 질문의 변형 줄이 둘이면 멈추고, 할당량 모자람은 남은 문항으로 센다."""
    qs, rs, a, vs = _fixture()
    try:
        build_train(qs, rs, a, vs + [dict(vs[2], answer="다른 답")], load_templates())
    except ValueError as e:
        assert "travel-003" in str(e)
    else:
        raise AssertionError("변형 줄이 둘인데 조용히 하나를 골랐다")
    full = [{"kind": "main", "type": t} for t, n in TRAIN_QUOTA.items() for _ in range(n)]
    full += [{"kind": "pair", "type": 1}] * PAIRS
    assert train_short(full) == {}                                           # 앞에서 빠졌어도 채웠으면 0
    assert train_short(full[1:-1]) == {"1": 1, "pairs": 1}


def check_pair_needs_asked_value_in_clean_answer() -> None:
    qs, rs, a, vs = _fixture()
    qs[0] = dict(qs[0], answer="베이직 요금제는 데이터를 넉넉하게 줍니다.")    # travel-001 의 멀쩡한 답변에 값이 없다
    items, dropped = build_train(qs, rs, a, vs, load_templates())
    assert ("travel-001", "pair") not in {(i["qid"], i["kind"]) for i in items}
    assert "값" in dropped["pair"]["travel-001"][0]


def check_supplement_review_flow_reviews_only_new_cases() -> None:
    """보충 뒤의 순서(계획 E9 Step 4): 검수하지 않은 문항만 뽑고, 그 결과를 덧붙이면 apply_review 가 멈추지 않는다.
    이미 검수한 문항을 다시 덧붙이면 merge_reviews 가 먼저 막는다(apply_review 의 "검수 줄이 두 개다" 를 피한다)."""
    key = {f"c{i}": {"qid": f"q{i}", "table_score": 1} for i in range(5)}
    rows = [{"case_id": c} for c in key]
    first = [{"case_id": f"c{i}", "review_score": 1} for i in range(3)]          # 첫 검수는 c0~c2
    todo = pending_rows(rows, first)
    assert [r["case_id"] for r in todo] == ["c3", "c4"]
    new = [{"case_id": "c3", "review_score": 1}, {"case_id": "c4", "review_score": 1}]
    merged, problems = merge_reviews(first, new, {r["case_id"] for r in todo})
    assert problems == [] and len(merged) == 5
    kept, dropped, bad = apply_review(key, merged)
    assert bad == [] and len(kept) == 5
    _, problems = merge_reviews(first, new + [{"case_id": "c0", "review_score": 1}], {"c3", "c4"})
    assert any("c0" in p for p in problems)                                          # 이미 검수한 문항
    _, problems = merge_reviews(first, new[:1], {"c3", "c4"})
    assert any("없는 문항 1개" in p for p in problems)                              # 검수가 빠진 문항


CHECKS = [check_build_train_drops_only_broken_items_and_their_pairs, check_split_val_keeps_question_together_and_is_stable,
          check_leak_problems_find_overlaps, check_supplement_review_flow_reviews_only_new_cases,
          check_sentence_overlap_both_ways_and_forbidden_values, check_train_refuses_duplicate_variants_and_counts_quota,
          check_pair_needs_asked_value_in_clean_answer]


def main() -> None:
    for fn in CHECKS:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(CHECKS)}가지 전부 통과.")


if __name__ == "__main__":
    main()
