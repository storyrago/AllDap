"""채점 모델 비교 실험(2026-10-02)의 대조 보고. 스펙 §4 를 그대로 계산한다.

실행:  cd ai-service && .venv/bin/python -m tools.judge5_report
산출:  testdata/judge5/report.md (화면에도 같은 내용을 찍는다)

판정 규칙은 스펙 §4 에 측정 전에 고정돼 있다. 이 도구는 그 규칙을 계산할 뿐이고,
결과를 보고 규칙을 바꾸는 자리가 아니다.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from .judge5 import (
    SCALE, MODELS, Summary, compare, linear_weighted_kappa, parse_result, pick_best,
    replacement_failures, summarize, to_three,
)
from .judge5_export import CASES_SHA, NEW_LABELS, OLD_LABELS, RESULTS_DIR, labels_ready

REPORT = RESULTS_DIR.parent / "report.md"


class ReportProblem(RuntimeError):
    """입력 파일이 완전하지 않다. 부분 집계를 내지 않는다."""


def load_run(path: Path, case_ids: set[str], cases_sha: str) -> dict[str, str]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    got = {r["case_id"] for r in rows}
    if got != case_ids:
        raise ReportProblem(f"{path.name}: 사례가 맞지 않습니다(빠짐 {len(case_ids - got)}, 남음 {len(got - case_ids)})")
    if len(rows) != len(got):
        raise ReportProblem(f"{path.name}: 같은 사례가 두 번 있습니다")
    if any(r["cases_sha256"] != cases_sha for r in rows):
        raise ReportProblem(f"{path.name}: 다른 시험지로 채점한 줄이 있습니다")
    return {r["case_id"]: r["output"] for r in rows}


def load_ids(path: Path) -> set[str]:
    """결과 파일에 있는 사례 번호. 건너뛴 모델이 몇 건까지 했는지 적는 데만 쓴다."""
    return {json.loads(line)["case_id"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def scores_of(outputs: dict[str, str]) -> tuple[dict[str, int | None], dict[str, int]]:
    scores: dict[str, int | None] = {}
    kinds: Counter = Counter()   # Counter 는 없는 키를 0 으로 치는 dict 다
    for cid, text in outputs.items():
        v, status = parse_result(text)
        scores[cid] = v
        kinds[status] += 1
    return scores, dict(kinds)


def _fmt(x: float | None, nd: int = 3) -> str:
    if x is None:
        return "계산 불가"
    # 부동소수 오차로 -0.0000001 같은 값이 나오면 "-0.000" 으로 찍힌다. 반올림한 값이 0 이면 0.0 으로 둔다.
    v = round(x, nd)
    return f"{0.0 if v == 0 else v:.{nd}f}"


def _summary_rows(name: str, s: Summary, kinds: dict[str, int], kappa: float | None) -> str:
    unread = ", ".join(f"{k} {v}" for k, v in sorted(kinds.items()) if k != "ok") or "없음"
    return (f"| {name} | {s.exact} | {s.within1} | {_fmt(s.mean_distance)} | {s.generous} | {s.harsh} "
            f"| {s.unread} ({unread}) | {_fmt(kappa)} |")


def _confusion(name: str, s: Summary) -> str:
    head = "| 사람 \\ " + name + " | " + " | ".join(str(m) for m in SCALE) + " |"
    sep = "|---" * (len(SCALE) + 1) + "|"
    body = [f"| {h} | " + " | ".join(str(s.confusion[(h, m)]) for m in SCALE) + " |" for h in SCALE]
    return "\n".join([head, sep, *body])


def build() -> str:
    labels = json.loads(NEW_LABELS.read_text(encoding="utf-8"))
    problems = labels_ready(labels)
    if problems:
        raise ReportProblem("새 라벨이 다 차지 않았습니다: " + "; ".join(problems))
    human = {c["case_id"]: int(c["label"]) for c in labels["cases"]}
    ids = set(human)
    cases_sha = CASES_SHA.read_text(encoding="utf-8").split()[0]

    scores: dict[str, dict[str, int | None]] = {}
    kinds: dict[str, dict[str, int]] = {}
    skipped: dict[str, str] = {}
    repeat: dict[str, str] = {}
    failures: dict[str, int] = {}
    for key in MODELS:
        run1 = RESULTS_DIR / f"{key}_run1.jsonl"
        skip = RESULTS_DIR / f"{key}_skipped.json"
        fail_log = RESULTS_DIR / f"{key}_failures.jsonl"
        # 호출 실패 기록(지금은 M1 만 쓴다). 결과가 아니라 "몇 번 다시 불렀나" 의 기록이라 따로 센다.
        failures[key] = (sum(1 for line in fail_log.read_text(encoding="utf-8").splitlines() if line.strip())
                         if fail_log.exists() else 0)
        # 건너뜀 기록을 결과 파일보다 먼저 본다. 코랩에서 채점 도중에 메모리가 모자라면 부분 결과 파일과
        # 건너뜀 기록이 함께 남는다. 부분 파일을 먼저 읽으면 보고서 전체가 멈춘다(계획 코드가 그랬다).
        if skip.exists():
            reason = json.loads(skip.read_text(encoding="utf-8"))["reason"]
            partial = len(load_ids(run1)) if run1.exists() else 0
            skipped[key] = reason + (f" (건너뛰기 전에 실행 1 을 {partial}건 채점했다. 표에는 넣지 않는다)" if partial else "")
            continue
        if not run1.exists():
            skipped[key] = "결과 파일 없음"
            continue
        scores[key], kinds[key] = scores_of(load_run(run1, ids, cases_sha))
        run2 = RESULTS_DIR / f"{key}_run2.jsonl"
        if run2.exists():
            # 실행 2 는 재현 확인에만 쓰고 판정에는 쓰지 않는다. 그래서 불완전하면 보고서를 멈추지 않고
            # "불완전" 이라고만 적는다. 부분 결과로 다른 사례 수를 세지는 않는다(숫자가 꼬리표 없이 인용된다).
            try:
                s2, _ = scores_of(load_run(run2, ids, cases_sha))
                repeat[key] = f"{sum(1 for cid in ids if s2[cid] != scores[key][cid])}건"
            except ReportProblem as e:
                repeat[key] = f"계산하지 않음. {e}"

    sums = {k: summarize([(human[c], v[c]) for c in sorted(ids)]) for k, v in scores.items()}
    kappas = {k: linear_weighted_kappa([(human[c], v[c]) for c in sorted(ids) if v[c] is not None])
              for k, v in scores.items()}

    out = ["# 채점 모델 비교 결과", "",
           f"사례 {len(ids)}건. 새 라벨 분포: "
           + ", ".join(f"{v}점 {sum(1 for h in human.values() if h == v)}건" for v in SCALE), "",
           "## 모델마다의 수치 (스펙 §4-2, 실행 1 기준)", "",
           "| 모델 | 정확히 같음 | 거리 1 이하 | 평균 거리 | 후함 | 박함 | 못 읽음 | 선형 가중 카파(보조) | 호출 실패 기록 |",
           "|---|---|---|---|---|---|---|---|---|"]
    out += [_summary_rows(k, sums[k], kinds[k], kappas[k]) + f" {failures[k]} |" for k in sums]
    for k, why in skipped.items():
        out.append(f"| {k} | 제외: {why} | | | | | | | {failures[k]} |")
    out += ["", "호출 실패 기록은 다시 불러서 받은 사례도 포함한 실패 횟수다. 못 읽음과 다르다"
                "(못 읽음은 모델이 답했지만 점수를 읽지 못한 것이다). 끝내 받지 못한 사례가 있으면 보고서가 만들어지지 않는다."]

    out += ["", "## 혼동행렬 (행은 새 라벨, 열은 모델 점수)", ""]
    for k in sums:
        out += [f"### {k} ({MODELS[k]})", "", _confusion(k, sums[k]), ""]

    out += ["## 두 모델 비교 (스펙 §4-3)", ""]
    pairs = [("M1", "M2", "돌리는 곳과 4비트"), ("M4", "M3", "같은 바탕 모델에 더한 채점 학습")]
    best = pick_best({k: s for k, s in sums.items() if k != "M1"})
    if best:
        pairs.append((best, "M1", f"가장 나은 후보({best})와 지금 채점 모델"))
    for a, b, what in pairs:
        if a not in scores or b not in scores:
            out.append(f"- {a} 와 {b} ({what}): 하지 않음. 결과가 없는 모델이 있다")
            continue
        c = compare(human, scores[a], scores[b])
        out.append(f"- {a} 와 {b} ({what}): {a} 가 더 가까움 {c.a_closer}, {b} 가 더 가까움 {c.b_closer}, "
                   f"같음 {c.ties}, 제외 {c.excluded}, p = {c.p_value:.4f} → **{c.verdict(a, b)}**")

    out += ["", "## 교체 후보 (스펙 §4-4)", ""]
    if "M1" in sums:
        for k in (m for m in sums if m != "M1"):
            fails = replacement_failures(sums[k], sums["M1"], compare(human, scores[k], scores["M1"]))
            out.append(f"- {k}: " + ("**교체 후보**" if not fails else "아님. " + "; ".join(fails)))
    else:
        out.append("- M1 결과가 없어 판단하지 않음")

    out += ["", "## 재현 (실행 1 과 실행 2 의 점수가 다른 사례 수)", ""]
    out += [f"- {k}: {n}" for k, n in repeat.items()] or ["- 실행 2 결과 없음"]

    old = {c["case_id"]: float(c["label"]) for c in json.loads(OLD_LABELS.read_text(encoding="utf-8"))["cases"]}
    same = sum(1 for cid in ids if to_three(human[cid]) == old[cid])
    out += ["", "## 보조: 사람 라벨의 일관성 (스펙 §4-6, 판정에 쓰지 않는다)", "",
            f"새 라벨을 세 칸으로 옮겼을 때 옛 라벨과 같은 사례: {same} / {len(ids)}"]
    return "\n".join(out) + "\n"


def main() -> int:
    try:
        text = build()
    except ReportProblem as e:
        print(f"보고서를 만들지 않았습니다: {e}")
        return 1
    REPORT.write_text(text, encoding="utf-8")
    print(text)
    print(f"→ {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
