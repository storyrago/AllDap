"""채점 모델 비교 v2 의 변별력 관문(스펙 7-2절). 모델을 돌리기 전에 다섯 조건을 모두 넘는지 본다.

실행:  cd ai-service && $PY -m tools.judge5v2_gate
산출:  testdata/judge5v2/gate.md. 하나라도 통과하지 못하면 종료 코드가 1 이다.

관문은 검수(스펙 4절)를 반영한 정답 점수로 계산한다. 그래서 review.jsonl 에 사용자 판단이 빠진
불일치 문항이 있으면 계산하지 않고 멈춘다.
"""
from __future__ import annotations

import sys
from collections import Counter
from dataclasses import dataclass

from .judge5 import SCALE
from .judge5v2_files import DOMAINS, GATE, REVIEW, read_jsonl

MIN_TOTAL = 200
FIVE_LOW, FIVE_HIGH = 0.25, 0.35
LOW_SCORES = (4, 3, 2, 1)
MIN_PER_LOW_SCORE = 20
MIN_PER_DOMAIN = 40
MIN_TYPE8 = 15
MAX_FAKE = 0.65


@dataclass(frozen=True)
class Condition:
    no: int
    ok: bool
    text: str


def fake_within1(scores: list[int]) -> dict[int, float]:
    """가짜 모델(늘 k점)의 거리 1 이하 비율. 문항이 없으면 0.0 이다."""
    n = len(scores)
    return {k: (sum(1 for s in scores if abs(s - k) <= 1) / n if n else 0.0) for k in SCALE}


def check_gate(cases: list[dict]) -> list[Condition]:
    n = len(cases)
    scores = [c["score"] for c in cases]
    by_score = Counter(scores)
    by_domain = Counter(c["domain"] for c in cases)
    n8 = sum(1 for c in cases if c["type"] == 8)
    five = by_score[5] / n if n else 0.0
    fakes = fake_within1(scores)
    best = max(fakes.values()) if n else 1.0     # 문항이 없으면 통과시키지 않으려고 1.0 으로 둔다
    return [
        Condition(1, n >= MIN_TOTAL, f"남은 문항 {n}개(기준 {MIN_TOTAL}개 이상)"),
        Condition(2, n > 0 and FIVE_LOW <= five <= FIVE_HIGH, f"정답 점수 5 의 비율 {five:.1%}(기준 25~35%)"),
        Condition(3, all(by_score[s] >= MIN_PER_LOW_SCORE for s in LOW_SCORES),
                  "정답 점수별 " + ", ".join(f"{s}점 {by_score[s]}개" for s in LOW_SCORES) + "(기준 각 20개 이상)"),
        Condition(4, all(by_domain[d] >= MIN_PER_DOMAIN for d in DOMAINS) and n8 >= MIN_TYPE8,
                  "분야별 " + ", ".join(f"{d} {by_domain[d]}개" for d in DOMAINS)
                  + f", ⑧ {n8}개(기준 분야마다 40개 이상, ⑧ 15개 이상)"),
        Condition(5, best <= MAX_FAKE,
                  "가짜 모델의 거리 1 이하 비율 " + ", ".join(f"늘 {k}점 {v:.1%}" for k, v in sorted(fakes.items(), reverse=True))
                  + "(기준 가장 높은 값 65% 이하)"),
    ]


def render(conds: list[Condition]) -> str:
    lines = ["# 변별력 관문 (스펙 7-2절)", "", "| 번호 | 통과 | 내용 |", "|---|---|---|"]
    lines += [f"| {c.no} | {'통과' if c.ok else '실패'} | {c.text} |" for c in conds]
    lines += ["", "모두 통과" if all(c.ok for c in conds) else "통과하지 못한 조건이 있다. 모델을 돌리지 않는다."]
    return "\n".join(lines) + "\n"


def main() -> int:
    # 여기서 늦게 불러오는 이유: 관문 계산(check_gate)만 점검할 때는 내보내기 도구가 없어도 되게 한다.
    # 두 파일을 서로 다른 세션이 동시에 만든다.
    from .judge5v2_export import apply_review, load_and_build

    _, key = load_and_build()
    kept, _, problems = apply_review(key, read_jsonl(REVIEW))
    if problems:
        print("관문을 계산하지 않았습니다. 검수가 끝나지 않았습니다.")
        for p in problems[:20]:
            print(f"  - {p}")
        return 1
    conds = check_gate(list(kept.values()))
    text = render(conds)
    GATE.write_text(text, encoding="utf-8")
    print(text)
    return 0 if all(c.ok for c in conds) else 1


if __name__ == "__main__":
    sys.exit(main())
