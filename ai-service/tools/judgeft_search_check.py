"""tools.judgeft_search 의 점검. DB 도 외부 API 도 쓰지 않는다.

실행:  cd ai-service && python -m tools.judgeft_search_check

검색 한 건의 동작은 v2 의 judge5v2_search_check 가 이미 본다. 여기서는 이 실험에서 달라진 것만 본다.
"""
from __future__ import annotations

from .judgeft_search import parse_bots


def _refused(fn) -> bool:
    try:
        fn()
    except SystemExit:
        return True
    return False


def check_parse_bots_accepts_open_fields() -> None:
    assert parse_bots(["travel=13", "school=15"], ["school", "travel"], frozenset({1})) == {"travel": 13, "school": 15}


def check_parse_bots_refuses_protected_and_unknown() -> None:
    fields, prot = ["school", "travel"], frozenset({1, 7, 8, 9})
    assert _refused(lambda: parse_bots(["travel=9"], fields, prot))       # v2 의 봇
    assert _refused(lambda: parse_bots(["hospital=13"], fields, prot))    # 열지 않은 분야(예비)
    assert _refused(lambda: parse_bots(["travel=13", "school=13"], fields, prot))
    assert _refused(lambda: parse_bots(["travel=x"], fields, prot))


CHECKS = [check_parse_bots_accepts_open_fields, check_parse_bots_refuses_protected_and_unknown]


def main() -> None:
    for fn in CHECKS:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(CHECKS)}가지 전부 통과.")


if __name__ == "__main__":
    main()
