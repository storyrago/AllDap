"""tools.judgeft_files, tools.judgeft_fields 의 점검. DB 도 외부 API 도 쓰지 않는다.

실행:  cd ai-service && python -m tools.judgeft_fields_check
"""
from __future__ import annotations

from .judgeft_fields import initial_order, open_field
from .judgeft_files import (
    CONTRAST_FIVE, FIELD_CANDIDATES, PAIRS, TEST_MIN_QUALIFIED, TEST_QUOTA, TRAIN_MIN_QUALIFIED, TRAIN_QUOTA,
)


def check_quotas_match_spec() -> None:
    """스펙 4-4절의 표: 학습 600(⑧ 240, 짝 120), 새 시험지 120(⑧ 60), 대상이 둘인 ①② 12, 확장 기준 72와 240."""
    assert sum(TRAIN_QUOTA.values()) + PAIRS == 600 and TRAIN_QUOTA[8] == 240 and PAIRS == 120
    assert sum(TEST_QUOTA.values()) == 120 and TEST_QUOTA[8] == 60
    assert sum(CONTRAST_FIVE.values()) == 12 and all(CONTRAST_FIVE[t] <= TEST_QUOTA[t] for t in CONTRAST_FIVE)
    assert TEST_MIN_QUALIFIED == 72 and TRAIN_MIN_QUALIFIED == 240


def check_order_is_seeded_and_complete() -> None:
    a, b = initial_order(), initial_order()
    assert a == b                                            # 같은 시드면 같은 순서
    assert sorted(a["order"]) == sorted(FIELD_CANDIDATES)
    assert a["test"] + a["train"] + a["reserve"] == a["order"] and len(a["train"]) == 2
    assert initial_order(seed=1)["order"] != a["order"] or initial_order(seed=2)["order"] != a["order"]


def check_open_follows_rules() -> None:
    doc = initial_order()
    t = open_field(doc, "test")
    assert len(t["test"]) == 2 and t["reserve"] == [] and doc["reserve"]   # 원래 doc 은 그대로
    for bad in (lambda: open_field(t, "test"),                 # 시험용 셋째는 없다
                lambda: open_field(t, "train"),                # 예비가 없으면 --new 가 필요하다
                lambda: open_field(t, "train", "hr"),          # v2 의 분야는 쓰지 않는다
                lambda: open_field(t, "train", "Pharmacy"),    # 영어 소문자만
                lambda: open_field(doc, "train", "pharmacy")):  # 예비가 남았으면 예비를 쓴다
        try:
            bad()
        except ValueError:
            continue
        raise AssertionError("규칙을 어긴 분야 열기가 통과했다")
    tr = open_field(t, "train", "pharmacy")
    assert tr["train"][-1] == "pharmacy" and tr["opened"][-1] == {"sheet": "train", "field": "pharmacy"}
    try:
        open_field(tr, "train", "insurance")                   # 학습용 넷째는 없다
    except ValueError:
        return
    raise AssertionError("학습용 넷째 분야가 열렸다")


CHECKS = [check_quotas_match_spec, check_order_is_seeded_and_complete, check_open_follows_rules]


def main() -> None:
    for fn in CHECKS:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(CHECKS)}가지 전부 통과.")


if __name__ == "__main__":
    main()
