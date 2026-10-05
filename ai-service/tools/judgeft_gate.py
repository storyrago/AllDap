"""새 시험지의 검수 뒤 조건(스펙 4-4절)과 학습 전 관문 (a)(스펙 7-1절).

실행:
    cd ai-service
    $PY -m tools.judgeft_gate review     # 최종 새 시험지의 세 조건과 가짜 모델 수치. gate.md 를 쓴다
    $PY -m tools.judgeft_gate a          # 학습 전 M3 의 새 시험지 결과로 관문 (a). gate_a.json 을 쓴다

관문 (a) 는 ⑧ 의 심각한 놓침 수, ⑧ 의 못 읽음 수, 통과 여부만 낸다. 문항별 점수나 출력은 찍지 않는다.
학습이 끝날 때까지 새 시험지의 문항별 결과를 보지 않기 위해서다(스펙 6-5절).
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from .judge5 import RULES_V2, parse_result
from .judge5v2_gate import fake_within1
from .judgeft_determinism import runs_for
from .judgeft_files import (
    ANSWER_KEY, DETERMINISM, GATE, GATE_A, GATE_A_RATIO, MIN_CONTRAST_FIVE_AFTER_REVIEW, MIN_EIGHTH_AFTER_REVIEW,
    MIN_FIVE_AFTER_REVIEW, read_json, read_jsonl, write_json,
)


# @dataclass(frozen=True): 필드만 적으면 __init__ 과 비교(==)를 만들어 주는 장식이다. frozen=True 는 만든 뒤
# 값을 바꿀 수 없게 한다. 한 번 센 수치가 뒤에서 몰래 바뀌지 않게 하려는 것이다(Java 의 record 와 비슷하다).
@dataclass(frozen=True)
class Condition:
    no: int
    ok: bool
    text: str


def review_conditions(cases: dict[str, dict]) -> list[Condition]:
    """검수 뒤 세 조건. cases 는 정답 파일의 cases(문항 id 마다 type, score, two_targets)."""
    n8 = sum(1 for k in cases.values() if k["type"] == 8)
    five = [k for k in cases.values() if k["type"] in (1, 2)]
    two = sum(1 for k in five if k["two_targets"])
    return [
        Condition(1, n8 >= MIN_EIGHTH_AFTER_REVIEW, f"⑧ {n8}문항(기준 {MIN_EIGHTH_AFTER_REVIEW} 이상)"),
        Condition(2, len(five) >= MIN_FIVE_AFTER_REVIEW, f"①과 ② {len(five)}문항(기준 {MIN_FIVE_AFTER_REVIEW} 이상)"),
        Condition(3, two >= MIN_CONTRAST_FIVE_AFTER_REVIEW,
                  f"대상이 둘인 질문의 ①과 ② {two}문항(기준 {MIN_CONTRAST_FIVE_AFTER_REVIEW} 이상)"),
    ]


def gate_a(runs: list[list[dict]], cases: dict[str, dict]) -> dict:
    """관문 (a). runs 는 학습 전 M3 의 새 시험지 결과(실행마다 줄 목록). 실행마다 분모는 ⑧ 수에서 못 읽음을 뺀 수다.
    통과는 비율이 가장 낮은 실행으로 판정한다(스펙 7-1절: 속는다고 말하려면 매번 속아야 한다. 못 읽음이 실행마다
    달라 분모가 다를 수 있으므로 수가 아니라 비율로 고른다).

    ⑧ 은 정답 점수가 1 인 문항만 센다. 검수에서 사용자가 점수를 바꾼(override) ⑧ 은 심각한 놓침의 정의(정답 1,
    모델 4 이상)가 맞지 않는다. 보고서의 severe8 과 같은 범위다."""
    eighth = {cid for cid, k in cases.items() if k["type"] == 8 and k["score"] == 1}
    out = []
    for i, rows in enumerate(runs, 1):
        got = {r["case_id"]: parse_result(r["output"], r.get("finish"), rules=RULES_V2)[0] for r in rows}
        # := 는 값을 이름에 담으면서 그 값으로 바로 if 를 판단한다(파이썬 3.8 의 대입식). 계산을 한 번만 하고 결과를 아래에서 다시 쓴다.
        if missing := eighth - set(got):
            raise SystemExit(f"실행 {i} 에 ⑧ 문항 {len(missing)}개의 결과가 없습니다. 마저 채점한 뒤 다시 하세요.")
        unread = sum(1 for c in eighth if got[c] is None)
        severe = sum(1 for c in eighth if got[c] is not None and got[c] >= 4)
        denom = len(eighth) - unread
        out.append({"run": i, "eighth": len(eighth), "unread": unread, "severe": severe,
                    "ratio": severe / denom if denom else 0.0})
    return {"threshold": GATE_A_RATIO, "runs": out, "pass": bool(out) and min(r["ratio"] for r in out) >= GATE_A_RATIO}


def _final_cases() -> dict[str, dict]:
    ak = read_json(ANSWER_KEY)
    if ak.get("stage") != "final":
        raise SystemExit("새 시험지 최종본이 아닙니다. `judgeft_export test final` 을 먼저 하세요.")
    return ak["cases"]


def cmd_review() -> int:
    cases = _final_cases()
    conds = review_conditions(cases)
    fakes = fake_within1([k["score"] for k in cases.values()])
    n4 = sum(1 for k in cases.values() if k["type"] == 4)
    lines = ["# 새 시험지의 검수 뒤 조건", ""] + [f"- 조건 {c.no}: {'통과' if c.ok else '실패'}. {c.text}" for c in conds]
    lines += ["", f"- ④ 는 보충하지 않는다(스펙 4-4절). 남은 ④ {n4}문항",
              "- 가짜 모델의 거리 1 이하 비율: " + ", ".join(f"늘 {k}점 {v:.1%}" for k, v in sorted(fakes.items(), reverse=True))]
    GATE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0 if all(c.ok for c in conds) else 2


def cmd_a() -> int:
    cases = _final_cases()
    det = read_json(DETERMINISM)
    res = gate_a([read_jsonl(p) for p in runs_for("M3pre", "new", det)], cases)
    write_json(GATE_A, res)
    for r in res["runs"]:
        print(f"실행 {r['run']}: ⑧ {r['eighth']}문항, 못 읽음 {r['unread']}, 심각한 놓침 {r['severe']}, 비율 {r['ratio']:.1%}")
    print(f"관문 (a): {'통과' if res['pass'] else '통과하지 못함'}(기준 {GATE_A_RATIO:.0%} 이상, 비율이 가장 낮은 실행으로 판정)")
    return 0 if res["pass"] else 2


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="검수 뒤 조건과 학습 전 관문 (a)")
    p.add_argument("which", choices=("review", "a"))
    return cmd_review() if p.parse_args(argv).which == "review" else cmd_a()


if __name__ == "__main__":
    sys.exit(main())
