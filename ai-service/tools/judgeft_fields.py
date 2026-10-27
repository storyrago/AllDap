"""분야 순서를 시드로 정하고, 필요할 때 분야를 연다(스펙 3-2절, 3-3절).

실행:
    cd ai-service
    $PY -m tools.judgeft_fields order               # 처음 한 번. fields.json 이 없어야 한다
    $PY -m tools.judgeft_fields open test           # 예비 분야를 두 번째 시험용 분야로 연다(스펙 3-3절 1)
    $PY -m tools.judgeft_fields open train          # 세 번째 학습용 분야를 연다. 예비 분야가 남아 있으면 그것
    $PY -m tools.judgeft_fields open train --new pharmacy   # 예비 분야가 이미 쓰였으면 새 분야 이름을 준다

어느 분야가 시험용인지를 시드로 정하는 이유: 출제 세션이 ⑧ 을 만들기 쉬운 분야를 시험용으로 고르면
시험이 학습 데이터와 비슷한 쪽으로 치우칠 수 있다(스펙 3-2절).
"""
from __future__ import annotations

import argparse
import random
import re
import sys

from .judgeft_files import (
    FIELD_CANDIDATES, FIELDS, MAX_TEST_FIELDS, MAX_TRAIN_FIELDS, SEED, read_json, write_json,
)
from .judge5v2_files import DOMAINS as V2_DOMAINS


def initial_order(seed: int = SEED) -> dict:
    """네 후보를 시드로 섞는다. 첫째가 시험용, 둘째와 셋째가 학습용, 넷째가 예비 분야다.

    sorted 로 먼저 줄 세우는 이유: FIELD_CANDIDATES 의 적힌 순서가 바뀌어도 같은 시드에서 같은 결과가 나오게 한다.
    """
    order = sorted(FIELD_CANDIDATES)
    random.Random(f"{seed}:fields").shuffle(order)
    return {"seed": seed, "order": order, "test": [order[0]], "train": order[1:3], "reserve": [order[3]],
            "opened": []}


def open_field(doc: dict, sheet: str, new: str | None = None) -> dict:
    """분야 하나를 연다. 원래 doc 은 고치지 않고 새 dict 를 돌려준다. 규칙을 어기면 ValueError."""
    doc = {k: (list(v) if isinstance(v, list) else v) for k, v in doc.items()}
    used = set(doc["test"]) | set(doc["train"])
    if sheet == "test":
        if new is not None:
            raise ValueError("시험용 분야는 예비 분야만 연다(스펙 3-3절 1). --new 를 주지 않는다")
        if len(doc["test"]) >= MAX_TEST_FIELDS:
            raise ValueError(f"시험용 분야는 {MAX_TEST_FIELDS}개까지다(스펙 3-3절 3). 멈추고 사용자에게 보인다")
        if not doc["reserve"]:
            raise ValueError("예비 분야가 이미 쓰였다. 멈추고 사용자에게 보인다")
        field = doc["reserve"].pop()
        doc["test"].append(field)
    elif sheet == "train":
        if len(doc["train"]) >= MAX_TRAIN_FIELDS:
            raise ValueError(f"학습용 분야는 {MAX_TRAIN_FIELDS}개까지다(스펙 3-3절 3). 멈추고 사용자에게 보인다")
        if doc["reserve"]:
            if new is not None:
                raise ValueError("예비 분야가 남아 있으면 예비 분야를 쓴다(스펙 3-3절 2). --new 를 주지 않는다")
            field = doc["reserve"].pop()
        else:
            # 새 분야 이름은 폴더 이름과 qid 앞머리가 되므로 영어 소문자만 받는다.
            if not new or not re.fullmatch(r"[a-z]+", new):
                raise ValueError("예비 분야가 이미 쓰였다. --new 로 새 분야 이름(영어 소문자)을 준다")
            if new in used or new in FIELD_CANDIDATES or new in V2_DOMAINS:
                raise ValueError(f"{new} 는 이미 쓴 분야이거나 v2 의 분야다(스펙 3-3절 2)")
            field = new
        doc["train"].append(field)
    else:
        raise ValueError("sheet 는 test 또는 train 이다")
    doc["opened"].append({"sheet": sheet, "field": field})
    return doc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="분야 순서를 정하고 분야를 연다")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("order")
    o = sub.add_parser("open")
    o.add_argument("sheet", choices=("test", "train"))
    o.add_argument("--new", default=None)
    args = p.parse_args(argv)
    if args.cmd == "order":
        if FIELDS.exists():
            print("fields.json 이 이미 있습니다. 순서는 한 번만 정합니다.")
            return 1
        doc = initial_order()
    else:
        try:
            doc = open_field(read_json(FIELDS), args.sheet, args.new)
        except ValueError as e:
            print(f"분야를 열지 않았습니다: {e}")
            return 1
    write_json(FIELDS, doc)
    print(f"시험용 {doc['test']}, 학습용 {doc['train']}, 예비 {doc['reserve']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
