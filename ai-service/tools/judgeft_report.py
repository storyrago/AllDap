"""스펙 7절의 관문 결과, 8절의 수치, 비교, 교체 후보 기준, 9-3절의 검수 결과를 낸다.

실행:  cd ai-service && $PY -m tools.judgeft_report      # testdata/judgeft/report.md 를 쓴다

관문 (a) 에서 끝나도 보고서를 만든다. 그때 있는 결과만 내고, 돌리지 않은 모델과 비교는 "하지 않음" 으로 적는다.
관문 (a) 를 통과했는데 학습이 끝나지 않았으면(train_done.json 이 없으면) 만들지 않는다. 새 시험지의 학습 전 M3 결과를
학습이 끝나기 전에 열지 않기 위해서다(스펙 6-5절).

동결 시험지의 정답은 v2 의 정답 파일, 대상이 둘인 질문인지는 v2 의 질문 파일에서 읽는다. 모델마다 몇 번 돌린
결과를 쓰는지는 determinism.json 으로 정한다(judgeft_determinism.runs_for). 점수 읽기, 대조 수치, 부호 검정,
세 오류 수는 v2 의 함수(judge5, judge5v2_report)를 그대로 쓴다. 판정 문장은 v2 와 같은 세 가지뿐이다.
"""
from __future__ import annotations

import sys
from collections import Counter
from dataclasses import dataclass

from .judge5 import RULES_V2, SCALE, Comparison, compare, parse_result, sign_test_p, summarize
from .judge5v2_gate import fake_within1
from .judge5v2_report import _breakdown, error_counts
from .judgeft_determinism import runs_for
from .judgeft_files import (
    ANSWER_KEY, ASSIGNMENT, DETERMINISM, GATE_A, GATE_B, REPORT, SHEETS, TRAIN_DONE, TRAIN_DROPPED, TRAINING_LOG,
    TYPE_NAMES, V2_ANSWER_KEY, V2_QUESTIONS, read_json, read_jsonl,
)
from .judgeft_gate import review_conditions

DISPUTED = "3909377dbed6"   # 동결 시험지에서 M1 의 유일한 심각한 놓침. 정답 해석이 갈리는 문항(스펙 1-2절, 8-4절 기준 2)
NAMES = {"M1": "M1", "M3pre": "학습 전 M3", "M3ft": "학습 후 M3"}
BASIS = "대응표"


@dataclass(frozen=True)
class Metrics:
    within1: int
    exact: int
    mean_distance: float | None
    unread: int
    miss: int
    false_alarm: int
    severe: int
    severe8: int        # ⑧ 문항만의 심각한 놓침
    within1_ex8: int    # ⑧ 을 뺀 문항의 거리 1 이하(기준 3)
    fa_two: int         # ⑧ 을 뺀 문항 중 대상이 둘인 질문의 헛경보(기준 3)
    fa_one: int         # ⑧ 을 뺀 문항 중 그 밖의 질문의 헛경보(기준 3)


def keys() -> dict[str, dict[str, dict]]:
    """시험지마다 {문항 id: {type, score, two_targets}}."""
    new = {cid: {"type": k["type"], "score": k["score"], "two_targets": k["two_targets"]}
           for cid, k in read_json(ANSWER_KEY)["cases"].items()}
    contrast = {q["qid"]: q.get("contrast") is not None for q in read_jsonl(V2_QUESTIONS)}
    frozen = {cid: {"type": k["type"], "score": k["score"], "two_targets": contrast[k["qid"]]}
              for cid, k in read_json(V2_ANSWER_KEY)["cases"].items()}
    return {"new": new, "frozen": frozen}


def scores_of(rows: list[dict]) -> dict[str, int | None]:
    return {r["case_id"]: parse_result(r["output"], r.get("finish"), rules=RULES_V2)[0] for r in rows}


def unread_kinds(rows: list[dict]) -> dict[str, int]:
    """못 읽음을 원인별로 센다. missing, conflict, out_of_range 는 parse_result 의 상태이고,
    length 는 그중 512 토큰에서 잘린 것이다. 원인이 다르면 고칠 곳이 다르다(양식이 무너짐, 끝을 모름, 값이 틀림)."""
    out: Counter = Counter()
    for r in rows:
        score, state = parse_result(r["output"], r.get("finish"), rules=RULES_V2)
        if score is None:
            out[state] += 1
            out["length"] += r.get("finish") == "length"
    return {k: out[k] for k in ("missing", "conflict", "out_of_range", "length")}


def _kinds_text(k: dict[str, int]) -> str:
    return f"missing {k['missing']}(그중 잘림 {k['length']}), conflict {k['conflict']}, out_of_range {k['out_of_range']}"


def metrics(key: dict[str, dict], scores: dict[str, int | None]) -> Metrics:
    if missing := set(key) - set(scores):
        raise SystemExit(f"결과에 없는 문항이 {len(missing)}개 있습니다. 보고서를 만들지 않습니다(v2 스펙 6-5절).")
    pairs = [(k["score"], scores[c]) for c, k in key.items()]
    s, e = summarize(pairs), error_counts(pairs)
    ex8 = {c: k for c, k in key.items() if k["type"] != 8}
    within_ex8 = sum(1 for c, k in ex8.items() if scores[c] is not None and abs(scores[c] - k["score"]) <= 1)

    def fa(two: bool) -> int:
        return sum(1 for c, k in ex8.items() if k["score"] == 5 and k["two_targets"] == two
                   and scores[c] is not None and scores[c] <= 4)
    severe8 = sum(1 for c, k in key.items() if k["type"] == 8 and k["score"] == 1
                  and scores[c] is not None and scores[c] >= 4)
    return Metrics(s.within1, s.exact, s.mean_distance, s.unread, e.miss, e.false_alarm, e.severe_miss, severe8,
                   within_ex8, fa(True), fa(False))


def criteria(m: dict[str, dict[str, list[Metrics]]]) -> list[tuple[int, bool, str]]:
    """스펙 8-4절의 네 기준. 학습 후 M3 는 실행 중 가장 나쁜 값, 비교 상대는 가장 좋은 값을 쓴다."""
    post, pre, m1 = m["M3ft"], m["M3pre"], m["M1"]

    def worst(xs, f, high_is_bad=True):
        return (max if high_is_bad else min)(f(x) for x in xs)

    def best(xs, f, high_is_bad=True):
        return (min if high_is_bad else max)(f(x) for x in xs)
    out = []
    for no, sheet in ((1, "new"), (2, "frozen")):
        a, b = worst(post[sheet], lambda x: x.severe), best(m1[sheet], lambda x: x.severe)
        out.append((no, a <= b, f"{sheet}: 심각한 놓침 학습 후 M3 {a}, M1 {b}"))
    ok3, txt3 = True, []
    for sheet in SHEETS:
        w = (worst(post[sheet], lambda x: x.within1_ex8, False), best(pre[sheet], lambda x: x.within1_ex8, False))
        f2 = (worst(post[sheet], lambda x: x.fa_two), best(pre[sheet], lambda x: x.fa_two))
        f1 = (worst(post[sheet], lambda x: x.fa_one), best(pre[sheet], lambda x: x.fa_one))
        ok3 &= w[0] >= w[1] and f2[0] <= f2[1] and f1[0] <= f1[1]
        txt3.append(f"{sheet}: ⑧ 뺀 거리 1 이하 {w[0]} 대 {w[1]}, 헛경보(대상 둘) {f2[0]} 대 {f2[1]}, "
                    f"헛경보(그 밖) {f1[0]} 대 {f1[1]}")
    out.append((3, ok3, "; ".join(txt3) + " (학습 후 대 학습 전)"))
    ok4, txt4 = True, []
    for sheet in SHEETS:
        a, b = worst(post[sheet], lambda x: x.unread), best(m1[sheet], lambda x: x.unread)
        ok4 &= a <= b
        txt4.append(f"{sheet}: 못 읽음 학습 후 M3 {a}, M1 {b}")
    out.append((4, ok4, "; ".join(txt4)))
    return out


def eighth_change(key: dict[str, dict], pre: dict[str, int | None], post: dict[str, int | None]) -> Comparison:
    """⑧ 만의 짝 부호 검정(스펙 8-3절). a 는 학습 후 M3 가 나은 문항(학습 전에 심각하게 놓쳤고 학습 후에 놓치지 않음)."""
    excluded = fixed = broken = same = 0
    for c, k in key.items():
        if k["type"] != 8 or k["score"] != 1:   # severe8, 관문 (a) 와 같은 범위
            continue
        x, y = pre[c], post[c]
        if x is None or y is None:
            excluded += 1
        elif x >= 4 > y:
            fixed += 1
        elif y >= 4 > x:
            broken += 1
        else:
            same += 1
    return Comparison(excluded, fixed, broken, same, sign_test_p(fixed, fixed + broken))


def _fmt(x: float | None) -> str:
    return "-" if x is None else f"{x:.3f}"


def pipeline_lines(assignment: dict, dropped: dict) -> list[str]:
    """보충 회차에서 채운 수와 학습 데이터에서 뺀 수(스펙 4-4절, 5-2절). 보고서 맨 앞에 적는다."""
    out = []
    for sheet in ("test", "train"):
        rounds = [r for r in assignment["rounds"] if r["sheet"] == sheet]
        added = sum(len(r["types"]) + len(r["pairs"]) for r in rounds[1:])
        out.append(f"- {sheet}: 배정 회차 {len(rounds)}개, 보충 회차에서 채운 문항 {added}개")
    reasons: Counter = Counter(why for part in dropped.values() for whys in part.values() for why in whys)
    out.append(f"- 학습 데이터에서 뺀 문항: 본 문항 {len(dropped.get('main', {}))}개, 짝 {len(dropped.get('pair', {}))}개")
    out += [f"  - {why}: {n}" for why, n in reasons.most_common()]
    return out


def training_summary(lines: list[dict]) -> list[str]:
    """학습 기록(training_log.jsonl)을 요약한다. 단계마다 마지막 줄을 쓴다.

    끊긴 뒤 이어 하면 마지막 체크포인트 뒤의 단계를 다시 하므로 같은 단계의 줄이 두 번 적힐 수 있다.
    채점에 쓰는 어댑터는 다시 한 쪽의 결과이므로 마지막 줄이 맞는 값이다.
    """
    steps: dict[int, dict] = {}
    for line in lines:
        if "step" in line:
            steps[line["step"]] = line   # 같은 단계면 뒤의 줄이 앞의 줄을 덮는다
    sessions = sum(1 for line in lines if "session_start" in line and line.get("mode") == "train")
    resumed = [line["resumed_from"] for line in lines if "resumed_from" in line]
    bad = [(line["bad_checkpoint"], line["reason"]) for line in lines if "bad_checkpoint" in line]
    if not steps:
        return ["- 학습 기록에 단계가 없다"]
    order = sorted(steps)
    vals = [(n, steps[n]["val_loss"]) for n in order if "val_loss" in steps[n]]
    skipped = [n for n in order if steps[n].get("skipped")]
    out = [f"- 학습 단계 {len(order)}개(마지막 {order[-1]}), 학습 세션 {sessions}번, 이어 한 체크포인트 {resumed or '없음'}",
           f"- 학습 loss: 첫 단계 {steps[order[0]]['train_loss']:.4f}, 마지막 단계 {steps[order[-1]]['train_loss']:.4f}",
           "- 검증 loss(체크포인트마다): " + (", ".join(f"{n}단계 {v:.4f}" for n, v in vals) or "없음"),
           f"- loss scaling 으로 건너뛴 단계 {len(skipped)}개{(' ' + str(skipped)) if skipped else ''}, "
           f"마지막 scale {steps[order[-1]].get('scale')}"]
    if bad:
        out.append("- 깨져서 건너뛴 체크포인트: " + ", ".join(f"{n}단계({why})" for n, why in bad))
    return out


def review_lines(ak: dict) -> list[str]:
    """검수 결과(스펙 5-1절, 9-3절). 사용자 판단별 수, 버린 문항의 유형별 수, 검수 뒤 세 조건."""
    decisions = Counter(k["decision"] for k in ak["cases"].values())
    dropped = Counter(TYPE_NAMES[k["type"]] for k in ak["dropped"].values())
    out = [f"- 남은 문항 {len(ak['cases'])}개: 검수 점수와 같음 {decisions['match']}, 사용자가 정답 점수 유지 "
           f"{decisions['keep']}, 사용자가 점수를 바꿈 {decisions['override']}",
           f"- 버린 문항 {len(ak['dropped'])}개" + (": " + ", ".join(f"{t} {n}" for t, n in sorted(dropped.items()))
                                                   if dropped else "")]
    out += [f"- 검수 뒤 조건 {c.no}: {'통과' if c.ok else '실패'}. {c.text}" for c in review_conditions(ak["cases"])]
    return out


def gate_lines(gate_a: dict | None, gate_b: dict | None) -> list[str]:
    """학습 전 관문 결과(스펙 7절). 통과 여부와 관계없이 적는다. 기록이 없으면 하지 않았다고 적는다."""
    out = ["### 관문 (a): 학습 전 M3 가 새 시험지의 ⑧ 에서 속는가", ""]
    if gate_a is None:
        out.append("- 하지 않음(gate_a.json 이 없다)")
    else:
        out += [f"- 실행 {r['run']}: ⑧(정답 1점) {r['eighth']}문항, 못 읽음 {r['unread']}, 심각한 놓침 {r['severe']}, "
                f"비율 {r['ratio']:.1%}" for r in gate_a["runs"]]
        out.append(f"- 판정: {'통과' if gate_a['pass'] else '통과하지 못함'}(기준 {gate_a['threshold']:.0%} 이상, "
                   "비율이 가장 낮은 실행으로 판정)")
    out += ["", "### 관문 (b): 코랩 T4 에서 학습이 메모리에 올라가는가", ""]
    if gate_b is None:
        out.append("- 하지 않음(gate_b.json 이 없다. 관문 (a) 에서 끝났거나 메모리가 모자라 기록을 남기지 못했다)")
    else:
        out += [f"- 가장 긴 문항 {gate_b['longest_id']}({gate_b['longest_tokens']}토큰), GPU 메모리 최대 {gate_b['peak_gb']}GB",
                f"- 학습 단계 하나 {gate_b['step_seconds']}초, 전체 {gate_b['total_steps']}단계 어림 {gate_b['est_hours']}시간"
                f"(가장 긴 문항으로 잰 값이라 실제보다 길다), 체크포인트 간격 {gate_b['save_every']}단계",
                f"- loss 가 숫자였는가: {gate_b['finite']}({gate_b['losses']})"]
    return out


def available(model: str, sheet: str, det: dict) -> tuple[list[list[dict]] | None, list[str]]:
    """(그 모델과 시험지의 결과 줄(실행마다), 없는 것의 이름). 하나라도 없으면 결과는 None(하지 않음)이다.

    없는 것의 이름을 함께 돌려주는 이유: 세 실행 중 하나만 빠진 것과 아예 돌리지 않은 것이 표에서 같은
    "하지 않음" 으로 보이면, 마저 채점하면 되는 일을 실험이 끝난 것으로 읽게 된다.
    """
    try:
        paths = runs_for(model, sheet, det)
    except KeyError:   # det 에 pre 나 post 가 없다: 그 확인까지 가지 않았다
        return None, ["determinism.json 의 " + ("post" if model == "M3ft" else "pre")]
    # 이름은 "폴더/파일" 로 적는다. 새 실험의 결과는 new/ 와 frozen/, v2 의 결과는 v2 의 results/ 아래다.
    if missing := [f"{p.parent.name}/{p.name}" for p in paths if not p.exists()]:
        return None, missing
    return [read_jsonl(p) for p in paths], []


def _confusion(name: str, key: dict[str, dict], scores: dict[str, int | None]) -> list[str]:
    s = summarize([(k["score"], scores[c]) for c, k in key.items()])
    out = [f"#### {name} (첫 실행)", "", "| 정답 점수 \\ 모델 | " + " | ".join(str(v) for v in SCALE) + " |",
           "|---" * (len(SCALE) + 1) + "|"]
    return out + [f"| {h} | " + " | ".join(str(s.confusion[(h, v)]) for v in SCALE) + " |" for h in SCALE] + [""]


def build() -> str:
    gate_a = read_json(GATE_A) if GATE_A.exists() else None
    if gate_a is None:
        raise SystemExit("관문 (a) 의 결과(gate_a.json)가 없습니다. 보고서는 관문 (a) 뒤에 만듭니다.")
    if gate_a["pass"] and not TRAIN_DONE.exists():
        raise SystemExit("관문 (a) 를 통과했는데 학습이 끝나지 않았습니다(train_done.json 이 없다). 새 시험지의 결과를 "
                         "학습이 끝나기 전에 열지 않습니다(스펙 6-5절).")
    ks = keys()
    det = read_json(DETERMINISM) if DETERMINISM.exists() else {}
    found = {mod: {sh: available(mod, sh, det) for sh in SHEETS} for mod in NAMES}
    rows = {mod: {sh: found[mod][sh][0] for sh in SHEETS} for mod in NAMES}
    absent = {mod: {sh: found[mod][sh][1] for sh in SHEETS} for mod in NAMES}
    raw = {mod: {sh: [scores_of(r) for r in rows[mod][sh]] if rows[mod][sh] else None for sh in SHEETS} for mod in NAMES}
    m = {mod: {sh: [metrics(ks[sh], x) for x in raw[mod][sh]] if raw[mod][sh] else None for sh in SHEETS} for mod in NAMES}
    dropped = read_json(TRAIN_DROPPED) if TRAIN_DROPPED.exists() else {}
    lines = ["# 채점 모델 파인튜닝 실험 보고서", "", f"결정성: {det or '확인하지 않음'}", "",
             "## 문항과 학습 데이터의 경위", ""]
    lines += pipeline_lines(read_json(ASSIGNMENT), dropped) + ["", "## 새 시험지의 검수 결과 (스펙 5-1절)", ""]
    lines += review_lines(read_json(ANSWER_KEY)) + ["", "## 학습 전 관문 (스펙 7절)", ""]
    lines += gate_lines(gate_a, read_json(GATE_B) if GATE_B.exists() else None) + ["", "## 학습 기록 (스펙 6-3절, 6-4절)", ""]
    if TRAINING_LOG.exists():
        lines += training_summary(read_jsonl(TRAINING_LOG))
        if TRAIN_DONE.exists():
            lines.append(f"- 어댑터 SHA-256 {read_json(TRAIN_DONE)['adapter_sha256']}")
    else:
        lines.append("- 하지 않음(학습하지 않았다)")
    lines.append("")
    for sh in SHEETS:
        lines += [f"## 시험지 {sh} ({len(ks[sh])}문항)", "",
                  "| 모델 | 실행 | 거리 1 이하 | ⑧ 뺀 거리 1 이하 | 놓침 | 헛경보 | 헛경보(대상 둘) | 헛경보(그 밖) "
                  "| 심각한 놓침 | ⑧ 심각한 놓침 | 정확히 같음 | 평균 거리 | 못 읽음 | 못 읽음의 원인 |", "|" + "---|" * 14]
        for mod, name in NAMES.items():
            if m[mod][sh] is None:
                lines.append(f"| {name} | 하지 않음(관문에서 끝났거나 채점하지 않았다. 없는 것: "
                             f"{', '.join(absent[mod][sh])}) |" + " |" * 12)
                continue
            for i, (x, r) in enumerate(zip(m[mod][sh], rows[mod][sh]), 1):
                lines.append(f"| {name} | {i} | {x.within1} | {x.within1_ex8} | {x.miss} | {x.false_alarm} | {x.fa_two} "
                             f"| {x.fa_one} | {x.severe} | {x.severe8} | {x.exact} | {_fmt(x.mean_distance)} | {x.unread} "
                             f"| {_kinds_text(unread_kinds(r)) if x.unread else '-'} |")
        for v in sorted(SCALE, reverse=True):   # 다섯 가짜 모델(스펙 8-2절)
            x = metrics(ks[sh], {c: v for c in ks[sh]})
            lines.append(f"| 늘 {v}점 | - | {x.within1} | {x.within1_ex8} | {x.miss} | {x.false_alarm} | {x.fa_two} "
                         f"| {x.fa_one} | {x.severe} | {x.severe8} | {x.exact} | {_fmt(x.mean_distance)} | 0 | - |")
        fakes = fake_within1([k["score"] for k in ks[sh].values()])
        lines += ["", "가짜 모델의 거리 1 이하 비율: "
                  + ", ".join(f"늘 {k}점 {v:.1%}" for k, v in sorted(fakes.items(), reverse=True)), ""]
        human = {c: k["score"] for c, k in ks[sh].items()}
        for a, b in (("M3ft", "M3pre"), ("M3ft", "M1")):
            if raw[a][sh] is None or raw[b][sh] is None:
                lines.append(f"- {NAMES[a]} 와 {NAMES[b]}: 하지 않음. 결과가 없는 모델이 있다")
                continue
            c = compare(human, raw[a][sh][0], raw[b][sh][0])
            lines.append(f"- {NAMES[a]} 와 {NAMES[b]}(첫 실행): {NAMES[a]} 가 더 가까움 {c.a_closer}, "
                         f"{NAMES[b]} 가 더 가까움 {c.b_closer}, 같음 {c.ties}, 제외 {c.excluded}, p = {c.p_value:.4f}, "
                         f"판정 **{c.verdict(NAMES[a], NAMES[b], BASIS)}**")
        if sh == "new" and raw["M3pre"][sh] and raw["M3ft"][sh]:
            e = eighth_change(ks[sh], raw["M3pre"][sh][0], raw["M3ft"][sh][0])
            lines.append(f"- ⑧ 만의 짝 부호 검정(보고 항목): 학습 후 고쳐진 놓침 {e.a_closer}, 새로 생긴 놓침 "
                         f"{e.b_closer}, 제외 {e.excluded}, p = {e.p_value:.4f}, 판정 **{e.verdict(NAMES['M3ft'], NAMES['M3pre'], BASIS)}**")
        elif sh == "new":
            lines.append("- ⑧ 만의 짝 부호 검정: 하지 않음. 학습 후 M3 의 결과가 없다")
        else:
            lines.append(f"- {DISPUTED}(정답 해석이 갈리는 문항): " + ", ".join(
                f"{NAMES[mod]} {raw[mod][sh][0].get(DISPUTED)}점" for mod in NAMES if raw[mod][sh]))
        have = {NAMES[mod]: raw[mod][sh][0] for mod in NAMES if raw[mod][sh]}
        lines += ["", f"### 혼동행렬 (시험지 {sh}, 행은 정답 점수, 열은 모델 점수)", ""]
        for name, sc in have.items():
            lines += _confusion(name, ks[sh], sc)
        by_type = {TYPE_NAMES[t]: [c for c, k in ks[sh].items() if k["type"] == t]
                   for t in sorted({k["type"] for k in ks[sh].values()})}
        lines += _breakdown(f"유형별 (시험지 {sh}, 첫 실행, 판정에 쓰지 않는다)", by_type, human, have)
    lines += ["## 교체 후보의 기준 (스펙 8-4절)", ""]
    if any(m[mod][sh] is None for mod in NAMES for sh in SHEETS):
        lines.append("- 판정하지 않음. 결과가 없는 모델이 있다(관문에서 끝났거나 학습 후 채점을 하지 않았다)")
        return "\n".join(lines) + "\n"
    crit = criteria(m)
    lines += [f"- 기준 {no}: {'통과' if ok else '실패'}. {txt}" for no, ok, txt in crit]
    lines += ["", f"**학습 후 M3 는 교체 후보{'다' if all(ok for _, ok, _ in crit) else '가 아니다'}.**"]
    return "\n".join(lines) + "\n"


def main() -> int:
    REPORT.write_text(build(), encoding="utf-8")
    print(f"보고서: {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
