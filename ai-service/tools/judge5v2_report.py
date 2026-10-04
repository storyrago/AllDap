"""채점 모델 비교 v2 의 보고서. v2 스펙 6절을 계산한다.

실행:  cd ai-service && $PY -m tools.judge5v2_report
산출:  testdata/judge5v2/report.md (화면에도 같은 내용을 찍는다)

판정 규칙은 스펙 6절에 측정 전에 고정돼 있다. 이 도구는 그 규칙을 계산할 뿐이고, 결과를 보고 규칙을
바꾸는 자리가 아니다. 앞 실험과 다른 점: 정답이 사람 라벨이 아니라 대응표이고(판정 문구의 basis),
점수는 v2 규칙으로 읽고, 교체 후보 기준에 심각한 놓침이 더해졌다.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .judge5 import MODELS, RULES_V2, SCALE, Summary, compare, parse_result, replacement_failures, summarize
from .judge5_report import ReportProblem, load_finishes, load_run
from .judge5v2_assign import assigned_types
from .judge5v2_files import (
    ANSWER_KEY, ASSIGNMENT, CASES_SHA, DOMAINS, REPORT, RESULTS_DIR, RETRIEVED, TYPE_NAMES, latest_by_qid, read_json,
    read_jsonl,
)
from .judge5v2_gate import check_gate, fake_within1

MODEL_KEYS = ("M1", "M3", "M4")
BASIS = "대응표"
PAIRS = (("M3", "M1", "서비스의 채점 모델을 M3 로 바꿔도 되는가"),
         ("M3", "M4", "같은 바탕 모델에 채점 학습을 더한 효과가 있는가"))


@dataclass(frozen=True)
class Errors:
    miss: int          # 정답 점수 4 이하에 5점
    false_alarm: int   # 정답 점수 5 에 4점 이하
    severe_miss: int   # 정답 점수 1 에 4점 이상


def error_counts(pairs: list[tuple[int, int | None]]) -> Errors:
    """(정답 점수, 모델 점수 또는 None) 목록에서 스펙 6-1절의 세 수를 센다. 못 읽음은 세지 않는다."""
    read = [(k, m) for k, m in pairs if m is not None]
    return Errors(
        miss=sum(1 for k, m in read if k <= 4 and m == 5),
        false_alarm=sum(1 for k, m in read if k == 5 and m <= 4),
        severe_miss=sum(1 for k, m in read if k == 1 and m >= 4),
    )


def read_scores(outputs: dict[str, str], finishes: dict[str, str | None]) -> tuple[dict[str, int | None], dict[str, int]]:
    scores: dict[str, int | None] = {}
    kinds: Counter = Counter()
    for cid, text in outputs.items():
        v, status = parse_result(text, finishes.get(cid), rules=RULES_V2)
        scores[cid] = v
        kinds[status] += 1
    return scores, dict(kinds)


def _fmt(x: float | None) -> str:
    return "계산 불가" if x is None else f"{round(x, 3):.3f}"


def _row(name: str, s: Summary, e: Errors, note: str = "") -> str:
    return (f"| {name} | {s.within1}/{s.total} | {e.miss} | {e.false_alarm} | {e.severe_miss} | {s.exact} "
            f"| {_fmt(s.mean_distance)} | {s.unread}{note} |")


def _pipeline(ak: dict, retrieved: list[dict], assignment: dict) -> list[str]:
    # 검색 도구의 --allow-nondefault 로 돌린 줄은 nondefault 키를 가진다. 시도 기록까지 모두 센다(마지막 줄만이 아니다).
    nondefault = sum(1 for r in retrieved if "nondefault" in r)
    # 호출 실패로 다시 검색한 질문은 줄이 여럿이다. 질문마다 마지막 줄이 판정이다(계획 형식 2).
    retrieved = latest_by_qid(retrieved)
    # 시험지의 search_settings 는 그 질문의 마지막 검색 줄의 settings 를 그대로 옮긴 것이다(judge5v2_export).
    # 그래서 시험지 파일을 따로 읽지 않고 여기서 센다. dict 는 집합에 못 넣어서 키를 고정한 JSON 글자로 바꾼다.
    in_cases = {c["qid"] for c in ak["cases"].values()}
    kinds = {json.dumps(r.get("settings"), ensure_ascii=False, sort_keys=True) for r in retrieved if r["qid"] in in_cases}
    out = ["## 문항이 줄어든 경위", "",
           f"검색 설정: 기본값과 다른 설정으로 돌린 검색 줄(nondefault) {nondefault}개, "
           f"최종 시험지의 검색 설정 {len(kinds)}가지(스펙 2-3절은 모두 기본 설정 한 가지다)", "",
           "검색에서 버린 질문(스펙 2-3절, 다시 검색한 뒤의 판정):", ""]
    for d in DOMAINS:
        rows = [r for r in retrieved if r["domain"] == d]
        drops = Counter(r["drop_reason"] for r in rows if r["status"] != "ok")
        parts = ", ".join(f"{reason} {n}" for reason, n in sorted(drops.items())) or "없음"
        out.append(f"- {d}: 검색한 질문 {len(rows)}개 중 버림 {parts}")
    # 검색은 통과했지만 정답이 근거 청크 밖이라 배정 후보에서 뺀 질문(스펙 2-3절). 회차마다 그때의 excluded.json
    # 전체를 기록하므로(judge5v2_assign 의 _round_doc) 회차의 excluded_counts 를 더하면 같은 질문을 회차 수만큼
    # 센다. 그래서 회차들의 excluded({qid: 원인})를 합친 뒤 한 번씩 센다. 분야는 검색 줄에서 읽는다.
    excluded: dict[str, str] = {}
    for rnd in assignment["rounds"]:
        excluded.update(rnd.get("excluded") or {})
    # 앞 회차가 제외했다가 뒤 회차에서 제외가 풀려 배정된 질문은 합집합에 남아 있다. 그대로 두면 아래 "배정" 에서
    # 쓴 질문으로도 세고 여기서 제외로도 세어 두 번 들어간다. 마지막 상태는 배정이므로 제외에서 뺀다.
    for qid in assigned_types(assignment):
        excluded.pop(qid, None)
    domain_of = {r["qid"]: r["domain"] for r in retrieved}
    out += ["", "검색은 통과했지만 정답이 근거 청크 밖이라 배정 후보에서 뺀 질문(스펙 2-3절, excluded.json):", ""]
    for d in DOMAINS:
        reasons = Counter(why for q, why in excluded.items() if domain_of.get(q) == d)
        parts = ", ".join(f"{reason} {n}" for reason, n in sorted(reasons.items())) or "없음"
        out.append(f"- {d}: {parts}")
    assigned: dict[str, int] = {}
    moved: Counter = Counter()
    for rnd in assignment["rounds"]:
        for d, res in rnd["domains"].items():
            assigned.update(res["types"])
            moved[d] += res["eighth_to_sixth"]
    out += ["", "배정(스펙 3-3절):", ""]
    for d in DOMAINS:
        # 제외한 질문은 위에서 따로 셌으므로 여기서는 빼고 센다. 빼지 않으면 "쓰지 않은 질문" 에 한 번 더 들어간다.
        ok = [r["qid"] for r in retrieved if r["domain"] == d and r["status"] == "ok" and r["qid"] not in excluded]
        unused = sum(1 for q in ok if q not in assigned)
        # 보충 회차는 앞 회차에서 쓰지 않은 질문도 다시 뽑는다(스펙 3-3절 6). 그래서 모든 회차를 거친 뒤의 수를 적는다.
        out.append(f"- {d}: 검색을 통과하고 제외되지 않은 질문 {len(ok)}개 중 모든 회차 뒤에도 쓰지 않은 질문 {unused}개, "
                   f"⑧ 이 모자라 ⑥ 으로 돌린 문항 {moved[d]}개")
    dec = Counter(c["decision"] for c in ak["cases"].values())
    out += ["", "검수(스펙 4절):", "",
            f"- 검수 점수가 정답 점수와 같았던 문항 {dec['match']}개, 달랐지만 대응표대로 둔 문항 {dec['keep']}개, "
            f"사용자가 정답 점수를 고친 문항 {dec['override']}개, 버린 문항 {len(ak['dropped'])}개"]
    for cid, c in sorted(ak["cases"].items()):
        if c["decision"] == "override":
            out.append(f"  - 고침 {cid} ({TYPE_NAMES[c['type']]}): 대응표 {c['table_score']}점에서 {c['score']}점으로. 이유: {c['reason']}")
    for cid, c in sorted(ak["dropped"].items()):
        out.append(f"  - 버림 {cid} ({TYPE_NAMES[c['type']]}): {c['reason']}")
    by_type = Counter(TYPE_NAMES[c["type"]] for c in ak["dropped"].values())
    if by_type:
        out.append("- 버린 문항의 유형별 수: " + ", ".join(f"{t} {n}" for t, n in sorted(by_type.items())))
    return out


def _breakdown(title: str, groups: dict[str, list[str]], key: dict[str, int],
               scores: dict[str, dict[str, int | None]]) -> list[str]:
    out = [f"### {title}", "", "| 묶음 | 모델 | 문항 | 거리 1 이하 | 놓침 | 헛경보 | 심각한 놓침 | 못 읽음 |",
           "|---|---|---|---|---|---|---|---|"]
    for g, ids in groups.items():
        for m, sc in scores.items():
            pairs = [(key[c], sc[c]) for c in ids]
            s, e = summarize(pairs), error_counts(pairs)
            out.append(f"| {g} | {m} | {len(ids)} | {s.within1} | {e.miss} | {e.false_alarm} | {e.severe_miss} | {s.unread} |")
    return out + [""]


def build(answer_key: Path = ANSWER_KEY, cases_sha: Path = CASES_SHA, results_dir: Path = RESULTS_DIR,
          retrieved: Path = RETRIEVED, assignment: Path = ASSIGNMENT) -> str:
    ak = read_json(answer_key)
    if ak.get("stage") != "final":
        raise ReportProblem("정답 파일이 최종본이 아닙니다. tools.judge5v2_export final 을 먼저 실행하세요.")
    sha = cases_sha.read_text(encoding="utf-8").split()[0]
    if sha != ak["cases_sha256"]:
        raise ReportProblem("정답 파일과 시험지 해시 파일의 해시가 다릅니다. 같은 final 실행의 산출물인지 확인하세요.")
    key = {cid: c["score"] for cid, c in ak["cases"].items()}
    ids = sorted(key)

    scores: dict[str, dict[str, int | None]] = {}
    kinds: dict[str, dict[str, int]] = {}
    cuts: dict[str, int] = {}
    no_finish: dict[str, int] = {}
    other_finish: dict[str, int] = {}
    skipped: dict[str, str] = {}
    for m in MODEL_KEYS:
        run1, skip = results_dir / f"{m}_run1.jsonl", results_dir / f"{m}_skipped.json"
        if skip.exists():
            skipped[m] = json.loads(skip.read_text(encoding="utf-8"))["reason"]
            continue
        if not run1.exists():
            skipped[m] = "결과 파일 없음"
            continue
        outputs = load_run(run1, set(ids), sha)   # 빠진 문항이나 다른 시험지 줄이 있으면 멈춘다(스펙 6-5절)
        finishes = load_finishes(run1)
        scores[m], kinds[m] = read_scores(outputs, finishes)
        cuts[m] = sum(1 for c in ids if scores[m][c] is None and finishes.get(c) == "length")
        # finish 기록이 없는 못 읽음. v2 규칙은 finish 가 stop 이 아니면 대괄호 끝을 읽지 않으므로(스펙 6-4절 세부 규칙 2)
        # 잘림과 따로 센다. 이 수가 크면 모델이 못한 것이 아니라 결과 파일에 finish 를 적지 않은 것일 수 있다.
        no_finish[m] = sum(1 for c in ids if scores[m][c] is None and finishes.get(c) is None)
        # stop, length, 기록 없음이 아닌 값(예: 제공자의 내용 거름). 스펙 6-4절 세부 규칙 2 에 따라 이것도 대괄호 끝을
        # 읽지 않는다. 셋 중 어디에도 안 세면 못 읽음의 원인 일부가 표에서 사라진다.
        other_finish[m] = sum(1 for c in ids if scores[m][c] is None and finishes.get(c) not in (None, "stop", "length"))

    sums = {m: summarize([(key[c], scores[m][c]) for c in ids]) for m in scores}
    errs = {m: error_counts([(key[c], scores[m][c]) for c in ids]) for m in scores}

    out = ["# 채점 모델 비교 v2 결과", "",
           f"문항 {len(ids)}개. 정답 점수 분포: " + ", ".join(f"{v}점 {sum(1 for k in key.values() if k == v)}개" for v in SCALE),
           "분야 분포: " + ", ".join(f"{d} {sum(1 for c in ak['cases'].values() if c['domain'] == d)}개" for d in DOMAINS), ""]
    out += _pipeline(ak, read_jsonl(retrieved), read_json(assignment))
    out += ["", "## 변별력 관문 (스펙 7-2절)", ""]
    out += [f"- {c.no}. {'통과' if c.ok else '실패'}: {c.text}" for c in check_gate(list(ak["cases"].values()))]

    out += ["", "## 모델마다의 수치 (스펙 6-1절)", "",
            "| 모델 | 거리 1 이하 | 놓침 | 헛경보 | 심각한 놓침 | 정확히 같음 | 평균 거리 | 못 읽음 |",
            "|---|---|---|---|---|---|---|---|"]
    for m in scores:
        detail = ", ".join(f"{k} {v}" for k, v in sorted(kinds[m].items()) if k != "ok")
        why = [f"{n}개는 {label}" for n, label in ((cuts[m], "512 토큰에서 잘림"), (no_finish[m], "finish 기록 없음"),
                                                   (other_finish[m], "finish 가 그 밖의 값")) if n]
        note = (f" ({detail}" + (", 그중 " + ", ".join(why) if why else "") + ")") if detail else ""
        out.append(_row(m, sums[m], errs[m], note))
    for m, why in skipped.items():
        out.append(f"| {m} | 제외: {why} | | | | | | |")
    fakes = fake_within1([key[c] for c in ids])
    for k in sorted(SCALE, reverse=True):
        pairs = [(key[c], k) for c in ids]
        out.append(_row(f"늘 {k}점", summarize(pairs), error_counts(pairs)))
    out += ["", "가짜 모델의 거리 1 이하 비율: " + ", ".join(f"늘 {k}점 {v:.1%}" for k, v in sorted(fakes.items(), reverse=True))]

    out += ["", "## 혼동행렬 (행은 정답 점수, 열은 모델 점수)", ""]
    for m in sums:
        out += [f"### {m} ({MODELS[m]})", "", f"| 정답 점수 \\ {m} | " + " | ".join(str(v) for v in SCALE) + " |",
                "|---" * (len(SCALE) + 1) + "|"]
        out += [f"| {h} | " + " | ".join(str(sums[m].confusion[(h, v)]) for v in SCALE) + " |" for h in SCALE]
        out.append("")

    out += ["## 두 모델 비교 (스펙 6-2절)", ""]
    for a, b, what in PAIRS:
        if a not in scores or b not in scores:
            out.append(f"- {a} 와 {b} ({what}): 하지 않음. 결과가 없는 모델이 있다")
            continue
        c = compare(key, scores[a], scores[b])
        out.append(f"- {a} 와 {b} ({what}): {a} 가 더 가까움 {c.a_closer}, {b} 가 더 가까움 {c.b_closer}, "
                   f"같음 {c.ties}, 제외 {c.excluded}, p = {c.p_value:.4f}, 판정: **{c.verdict(a, b, basis=BASIS)}**")

    out += ["", "## 교체 후보 (스펙 6-3절)", ""]
    for k in ("M3", "M4"):
        if k not in sums or "M1" not in sums:
            out.append(f"- {k}: 판단하지 않음. 결과가 없는 모델이 있다")
            continue
        fails = replacement_failures(sums[k], sums["M1"], compare(key, scores[k], scores["M1"]),
                                     basis=BASIS, severe=(errs[k].severe_miss, errs["M1"].severe_miss))
        out.append(f"- {k}: " + ("**교체 후보**" if not fails else "아님. " + "; ".join(fails)))
    if "M1" in sums:
        out.append(f"- 참고: M1 의 못 읽음 {sums['M1'].unread}개. M1 에 못 읽음이 있으면 기준 1은 후보에게 유리해지고 "
                   f"기준 4는 후보에게 불리해진다(스펙 9절)")

    out += ["", "## 나눠 본 표 (판정에 쓰지 않는다)", ""]
    meta = ak["cases"]
    by_type = {TYPE_NAMES[t]: [c for c in ids if meta[c]["type"] == t] for t in sorted({m["type"] for m in meta.values()})}
    by_domain = {d: [c for c in ids if meta[c]["domain"] == d] for d in DOMAINS}
    out += _breakdown("유형별", by_type, key, scores)
    out += _breakdown("분야별", by_domain, key, scores)
    return "\n".join(out) + "\n"


def main() -> int:
    try:
        text = build()
    except ReportProblem as e:
        print(f"보고서를 만들지 않았습니다: {e}")
        return 1
    REPORT.write_text(text, encoding="utf-8")
    print(text)
    print(f"보고서: {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
