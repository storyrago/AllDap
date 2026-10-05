"""파인튜닝 실험의 변형 유형 배정(스펙 4-2절, 4-4절).

실행:
    cd ai-service
    $PY -m tools.judgeft_assign count                 # ⑧ 자격 수를 세고 첫 배정을 돌려 본다(스펙 3-3절, 계획 E3, E5)
    $PY -m tools.judgeft_assign first                 # 첫 배정. 시험용과 학습용을 한 번에 한다
    $PY -m tools.judgeft_assign supplement test       # 검수 뒤 조건(스펙 4-4절)을 채우지 못했을 때
    $PY -m tools.judgeft_assign supplement train      # 글자 확인으로 학습 문항이 빠졌을 때(스펙 4-4절)

v2 의 judge5v2_assign 을 고치지 않고 자격 조건 함수(eligible3, 4, 6, 8), ⑧ 조건 확인(valid_contrast),
제외 확인(excluded_problems)만 가져다 쓴다. v2 의 배정 함수는 분야 넷과 ⑧ 이 모자라면 ⑥ 으로 돌리는 규칙에
묶여 있고, 이 실험은 짝 문항과 대상이 둘인 ①② 를 더 뽑아야 해서 순서가 다르다.

배정을 출제 세션의 판단이 아니라 시드로 정하는 이유는 v2 와 같다: 망가뜨리기 쉬운 질문에 어려운 유형이 몰리지 않게 한다.
"""
from __future__ import annotations

import argparse
import random
import sys
from collections import Counter

from .judge5 import sha256_file
from .judge5v2_assign import eligible3, eligible4, eligible6, eligible8, excluded_problems, valid_contrast
from .judgeft_files import (
    ASSIGNMENT, CONTRAST_FIVE, EXCLUDED, PAIRS, QUESTIONS, RETRIEVED, SEED, TEST_MIN_QUALIFIED, TEST_QUOTA,
    TRAIN_MIN_QUALIFIED, TRAIN_QUOTA, fields_doc, latest_by_qid, read_json, read_jsonl, write_json,
)

REST_ORDER = (1, 2, 5, 7)   # 자격 조건이 없는 유형을 채우는 순서(v2 스펙 3-3절과 같다)


class Shortfall(Exception):
    """할당량을 채우지 못했다. short 는 {이름: 모자란 수} 다. 이름은 유형 번호 문자열, "contrast1" 등, "pairs"."""

    def __init__(self, short: dict[str, int]) -> None:
        super().__init__(short)
        self.short = short


def _file_sha(path) -> str | None:
    return sha256_file(path) if path.exists() else None


def pools_by_sheet(questions: list[dict], retrieved: list[dict], excluded: dict, doc: dict) -> dict[str, list[dict]]:
    """검색을 통과했고 제외하지 않았으며 답변 칸이 제대로 적힌 질문을 시험용(test)과 학습용(train)으로 나눈다.

    열지 않은 분야(예비 분야)의 질문은 넣지 않는다. 칸이 하나라도 잘못되면 ValueError 로 전부 알린다.
    """
    # := 는 값을 이름에 담으면서 그 값으로 바로 if 를 판단한다(파이썬 3.8 의 대입식). 계산을 한 번만 하고 결과를 아래에서 다시 쓴다.
    if bad := excluded_problems(excluded, questions, retrieved):
        raise ValueError("excluded.json 을 고친다:\n  - " + "\n  - ".join(bad))
    ok = {r["qid"]: r for r in latest_by_qid(retrieved) if r["status"] == "ok"}
    sheet_of = {f: "test" for f in doc["test"]} | {f: "train" for f in doc["train"]}   # | 는 두 dict 를 합친다
    out: dict[str, list[dict]] = {"test": [], "train": []}
    problems = []
    for q in questions:
        r = ok.get(q["qid"])
        if r is None or q["qid"] in excluded or q["domain"] not in sheet_of:
            continue
        # type(x) is int: bool 도 int 의 하위형이라 isinstance 로는 true 가 1 로 통과한다. 정확히 int 만 받는다.
        if not q.get("answer") or type(q.get("claims")) is not int or q["claims"] < 1:
            problems.append(f"{q['qid']}: answer 또는 claims 가 비었다")
        elif not isinstance(q.get("two_part"), bool):
            problems.append(f"{q['qid']}: two_part 가 true 나 false 가 아니다")
        elif q["two_part"] and q.get("contrast") is not None:
            problems.append(f"{q['qid']}: 답이 두 가지인 질문에는 contrast 를 적지 않는다")
        elif q.get("contrast") is not None and (why := valid_contrast(q["contrast"], r["sources"])):
            problems.append(f"{q['qid']}: ⑧ 조건이 잘못됐다({why})")
        else:
            out[sheet_of[q["domain"]]].append(q)
    if problems:
        raise ValueError("questions.jsonl 을 고친다:\n  - " + "\n  - ".join(problems))
    return out


def qualified_counts(pools: dict[str, list[dict]]) -> dict[str, dict[str, int]]:
    """분야마다 {"pool": 후보 수, "qualified": ⑧ 자격 질문 수}. 스펙 3-3절의 분야 늘리기와 계획 E3 의 비율에 쓴다."""
    out: dict[str, dict[str, int]] = {}
    for qs in pools.values():
        for q in qs:
            c = out.setdefault(q["domain"], {"pool": 0, "qualified": 0})
            c["pool"] += 1
            c["qualified"] += int(eligible8(q))
    return out


class _Picker:
    """한 배정 회차의 뽑기. 질문은 qid 순으로 먼저 줄 세운다(입력 순서와 무관하게 같은 시드에서 같은 결과)."""

    def __init__(self, pool: list[dict], rng: random.Random) -> None:
        self.pool = sorted(pool, key=lambda q: q["qid"])
        self.rng = rng
        self.types: dict[str, int] = {}
        self.short: dict[str, int] = {}

    def take(self, t: int, n: int, ok, name: str | None = None) -> list[str]:
        """자격(ok)을 만족하고 아직 쓰지 않은 질문에서 n 개를 뽑아 유형 t 를 붙인다. 모자라면 short 에 적는다.
        rng.sample(목록, k) 는 목록에서 k 개를 중복 없이 뽑는다. 같은 시드의 Random 이면 늘 같은 k 개다."""
        cands = [q for q in self.pool if q["qid"] not in self.types and ok(q)]
        got = self.rng.sample(cands, min(n, len(cands)))
        for q in got:
            self.types[q["qid"]] = t
        if len(got) < n:
            self.short[name or str(t)] = n - len(got)
        return sorted(q["qid"] for q in got)

    def rest(self, needs: dict[int, int]) -> list[str]:
        """자격 조건이 없는 유형을 REST_ORDER 대로 남은 질문을 섞어 앞에서부터 채운다. 남은 질문을 돌려준다."""
        rest = [q for q in self.pool if q["qid"] not in self.types]
        self.rng.shuffle(rest)
        i = 0
        for t in REST_ORDER:
            chunk = rest[i:i + needs.get(t, 0)]
            if len(chunk) < needs.get(t, 0):
                self.short[str(t)] = needs[t] - len(chunk)
            for q in chunk:
                self.types[q["qid"]] = t
            i += len(chunk)
        return sorted(q["qid"] for q in rest[i:])


def assign_test(pool: list[dict], needs: dict[int, int], contrast: dict[int, int], rng: random.Random) -> dict:
    """새 시험지 배정. 순서: ④, ⑧, 대상이 둘인 ①②, ③, ⑥, 나머지(①, ②, ⑤, ⑦).

    ⑧ 다음에 대상이 둘인 ①② 를 뽑는 이유: 둘 다 ⑧ 자격 질문에서 나오므로, ③ 이나 나머지가 먼저 가져가면
    모자랄 수 있다. ⑧ 이 모자라도 ⑥ 으로 돌리지 않는다. 이 시험지의 목적이 ⑧ 이라 분야를 늘린다(스펙 3-3절).
    """
    p = _Picker(pool, rng)
    p.take(4, needs.get(4, 0), eligible4)
    p.take(8, needs.get(8, 0), eligible8)
    five = []
    for t in (1, 2):
        five += p.take(t, contrast.get(t, 0), eligible8, f"contrast{t}")
    p.take(3, needs.get(3, 0), eligible3)
    p.take(6, needs.get(6, 0), eligible6)
    rest_needs = {t: needs.get(t, 0) - contrast.get(t, 0) for t in REST_ORDER}
    unused = p.rest(rest_needs)
    if p.short:
        raise Shortfall(p.short)
    return {"types": p.types, "contrast_five": sorted(five), "pairs": [], "unused": unused}


def assign_train(pool: list[dict], needs: dict[int, int], n_pairs: int, pair_from: list[str],
                 rng: random.Random) -> dict:
    """학습 데이터 배정. 순서: ④, ⑧, ③, ⑥, 나머지. 그다음 짝 문항을 ⑧ 질문에서 뽑는다(스펙 4-2절).

    pair_from 은 앞 회차에서 ⑧ 을 받았지만 짝이 없는 질문이다(보충 회차에서만 쓴다). 이번 회차의 ⑧ 과 합쳐 뽑는다.
    """
    p = _Picker(pool, rng)
    p.take(4, needs.get(4, 0), eligible4)
    p.take(8, needs.get(8, 0), eligible8)
    p.take(3, needs.get(3, 0), eligible3)
    p.take(6, needs.get(6, 0), eligible6)
    unused = p.rest(needs)
    cands = sorted({q for q, t in p.types.items() if t == 8} | set(pair_from))
    pairs = sorted(rng.sample(cands, min(n_pairs, len(cands))))
    if len(pairs) < n_pairs:
        p.short["pairs"] = n_pairs - len(pairs)
    if p.short:
        raise Shortfall(p.short)
    return {"types": p.types, "contrast_five": [], "pairs": pairs, "unused": unused}


def run_round(sheet: str, pool: list[dict], rnd: dict, seed: int) -> dict:
    """회차 기록(rnd)의 needs 로 배정한다. 분야가 아니라 시험지(test, train)마다 Random 을 따로 둔다."""
    rng = random.Random(f"{seed}:{sheet}:{rnd['round']}")
    needs = {int(t): n for t, n in rnd["needs"].items()}
    if sheet == "test":
        return assign_test(pool, needs, {int(t): n for t, n in rnd["contrast_needs"].items()}, rng)
    return assign_train(pool, needs, rnd["pair_needs"], rnd.get("pair_from", []), rng)


def replay(assignment: dict, questions_by_id: dict[str, dict]) -> list[str]:
    """저장된 회차를 같은 입력으로 다시 돌려 같은 결과가 나오는지 본다. 다른 회차 번호 목록(빈 목록이면 통과)."""
    bad = []
    for rnd in assignment["rounds"]:
        got = run_round(rnd["sheet"], [questions_by_id[q] for q in rnd["pool"]], rnd, assignment["seed"])
        if any(got[k] != rnd[k] for k in ("types", "contrast_five", "pairs", "unused")):
            bad.append(f"{rnd['sheet']} 회차 {rnd['round']}")
    return bad


def assigned(assignment: dict, sheet: str) -> tuple[dict[str, int], set[str], set[str]]:
    """그 시험지의 (질문마다 유형, 짝 문항 질문, 대상이 둘인 ①② 질문). 모든 회차를 합친다."""
    types: dict[str, int] = {}
    pairs: set[str] = set()
    five: set[str] = set()
    for rnd in assignment["rounds"]:
        if rnd["sheet"] == sheet:
            types.update(rnd["types"])
            pairs |= set(rnd["pairs"])
            five |= set(rnd["contrast_five"])
    return types, pairs, five


def _round(no: int, sheet: str, pool: list[dict], needs: dict, extra: dict, excluded_sha: str | None) -> dict:
    return {"round": no, "sheet": sheet, "questions_sha256": _file_sha(QUESTIONS),
            "retrieved_sha256": _file_sha(RETRIEVED), "excluded_sha256": excluded_sha,
            "pool": sorted(q["qid"] for q in pool), "needs": {str(t): n for t, n in sorted(needs.items())}, **extra}


def _load() -> tuple[list[dict], dict, dict[str, list[dict]]]:
    questions = read_jsonl(QUESTIONS)
    excluded = read_json(EXCLUDED) if EXCLUDED.exists() else {}
    pools = pools_by_sheet(questions, read_jsonl(RETRIEVED), excluded, fields_doc())
    return questions, excluded, pools


FIELD_SHORT = ("8", "contrast1", "contrast2", "pairs")   # 분야를 늘려서 채우는 모자람(스펙 3-3절). 나머지는 질문을 더 쓴다


def dry_run(sheet: str, pool: list[dict], seed: int) -> dict:
    """첫 배정(회차 0)을 저장하지 않고 그대로 돌려 본다. {"short": 모자란 수, "eighth_left": ④ 를 뽑은 뒤 남은 ⑧ 자격 수}.

    ⑧ 자격 질문 수만 세면 모자람을 놓친다. 배정은 ④ 를 ⑧ 보다 먼저 뽑는데, 주장이 2 인 ⑧ 자격 질문은 ④ 의
    자격도 있어 ④ 가 먼저 가져갈 수 있기 때문이다. 그래서 같은 시드, 같은 순서로 배정을 끝까지 돌려
    first 가 성공할지를 그대로 본다. 같은 Random 을 같은 순서로 쓰므로 first 와 결과가 같다.
    """
    rnd = {"round": 0, "needs": {str(t): n for t, n in (TEST_QUOTA if sheet == "test" else TRAIN_QUOTA).items()},
           "contrast_needs": {str(t): n for t, n in CONTRAST_FIVE.items()}, "pair_needs": PAIRS, "pair_from": []}
    try:
        run_round(sheet, pool, rnd, seed)
        short: dict[str, int] = {}
    except Shortfall as e:
        short = e.short
    # ④ 가 가져간 뒤의 ⑧ 자격 수. run_round 와 같은 Random 으로 ④ 만 뽑아 본다(④ 가 늘 첫 뽑기다).
    p = _Picker(pool, random.Random(f"{seed}:{sheet}:0"))
    four = set(p.take(4, int(rnd["needs"].get("4", 0)), eligible4))
    left = sum(1 for q in pool if eligible8(q) and q["qid"] not in four)
    return {"short": short, "eighth_left": left}


def cmd_count() -> int:
    """분야마다 ⑧ 비율(계획 E3)과, 시험지마다 첫 배정을 돌려 본 판정(계획 E5)을 낸다.

    종료 코드: 0 둘 다 충분, 2 분야를 늘려야 한다, 3 질문을 더 써야 한다(④, ③, ⑥ 등). 분야와 질문이 둘 다 모자라면 2.
    """
    _, _, pools = _load()
    counts = qualified_counts(pools)
    doc = fields_doc()
    more_fields = more_questions = False
    for sheet, need in (("test", TEST_MIN_QUALIFIED), ("train", TRAIN_MIN_QUALIFIED)):
        fields = doc[sheet]
        total = sum(counts.get(f, {}).get("qualified", 0) for f in fields)
        for f in fields:
            c = counts.get(f, {"pool": 0, "qualified": 0})
            ratio = c["qualified"] / c["pool"] if c["pool"] else 0.0
            print(f"{sheet} {f}: 후보 {c['pool']}개, ⑧ 자격 {c['qualified']}개({ratio:.0%})")
        d = dry_run(sheet, pools[sheet], SEED)
        field_short = {k: v for k, v in d["short"].items() if k in FIELD_SHORT}
        other_short = {k: v for k, v in d["short"].items() if k not in FIELD_SHORT}
        print(f"{sheet} 합계 ⑧ 자격 {total}개(기준 {need}개 이상), ④ 를 뽑은 뒤 남은 ⑧ 자격 {d['eighth_left']}개")
        if total < need or field_short:
            more_fields = True
            verdict = f"모자람(스펙 3-3절대로 분야를 늘린다. 첫 배정을 돌려 본 모자람: {field_short})"
        elif other_short:
            more_questions = True
            verdict = f"모자람(그 분야의 질문을 더 쓴다. 첫 배정을 돌려 본 모자람: {other_short})"
        else:
            verdict = "충분(첫 배정을 그대로 돌려 봤다)"
        print(f"{sheet} 판정: {verdict}")
    return 2 if more_fields else 3 if more_questions else 0


def _report_short(e: Shortfall, sheet: str) -> int:
    print(f"{sheet} 배정을 하지 않았습니다. 모자란 수: {e.short}")
    print("④, ③, ⑥ 이 모자라면 그 분야의 질문을 더 쓴다. ⑧ 이나 대상이 둘인 ①②, 짝이 모자라면 "
          "스펙 3-3절대로 분야를 늘린다(계획 E5). 시드나 할당량을 바꾸지 않는다.")
    return 2


def cmd_first() -> int:
    if ASSIGNMENT.exists():
        print("assignment.json 이 이미 있습니다. 첫 배정은 한 번만 합니다. 보충은 supplement 로 합니다.")
        return 1
    _, excluded, pools = _load()
    ex_sha = _file_sha(EXCLUDED)
    rounds = []
    specs = (("test", TEST_QUOTA, {"contrast_needs": {str(t): n for t, n in CONTRAST_FIVE.items()}}),
             ("train", TRAIN_QUOTA, {"pair_needs": PAIRS, "pair_from": []}))
    for sheet, quota, extra in specs:
        rnd = _round(0, sheet, pools[sheet], quota, extra, ex_sha)
        try:
            rnd.update(run_round(sheet, pools[sheet], rnd, SEED))
        except Shortfall as e:
            return _report_short(e, sheet)
        rounds.append(rnd)
    write_json(ASSIGNMENT, {"seed": SEED, "rounds": rounds})
    for rnd in rounds:
        print(f"{rnd['sheet']}: {Counter(rnd['types'].values())}, 짝 {len(rnd['pairs'])}, "
              f"대상이 둘인 ①② {len(rnd['contrast_five'])}, 쓰지 않은 질문 {len(rnd['unused'])}")
    return 0


def supplement_needs(sheet: str, assignment: dict, kept_types: dict[str, int], kept_pairs: set[str],
                     kept_five: set[str]) -> dict:
    """보충할 수. 할당량에서 남은 문항 수를 뺀다. 같은 명령을 두 번 돌려도 이미 채운 만큼은 다시 요구하지 않는다.

    시험용은 검수 뒤 조건(스펙 4-4절)에 걸리는 ⑧, ①, ② 만 채운다. ④ 는 보충하지 않는다(스펙 4-4절).
    학습용은 일곱 유형과 짝을 모두 채운다. 짝이 없는 ⑧ 질문은 pair_from 으로 넘겨 짝 후보에 넣는다.
    """
    have = Counter(kept_types.values())
    if sheet == "test":
        five_have = Counter(kept_types[q] for q in kept_five if q in kept_types)
        needs = {t: max(0, TEST_QUOTA[t] - have[t]) for t in (1, 2, 8)}
        contrast = {t: max(0, CONTRAST_FIVE[t] - five_have[t]) for t in CONTRAST_FIVE}
        # ①② 의 needs 는 대상이 둘인 몫을 포함한 수다(assign_test 가 나머지 몫을 needs - contrast 로 계산한다).
        for t in contrast:
            needs[t] = max(needs[t], contrast[t])
        return {"needs": needs, "contrast_needs": {str(t): n for t, n in contrast.items()}}
    needs = {t: max(0, TRAIN_QUOTA[t] - have[t]) for t in TRAIN_QUOTA}
    eighth_without_pair = sorted(q for q, t in kept_types.items() if t == 8 and q not in kept_pairs)
    return {"needs": needs, "pair_needs": max(0, PAIRS - len(kept_pairs)), "pair_from": eighth_without_pair}


def cmd_supplement(sheet: str) -> int:
    """보충 회차를 덧붙인다. 남은 문항은 test 는 정답 파일(검수 반영), train 은 train_dropped.json 으로 정한다."""
    from .judgeft_export import kept_test, kept_train   # 늦은 import: export 가 이 모듈을 불러 순환을 피한다
    assignment = read_json(ASSIGNMENT)
    _, _, pools = _load()
    kept_types, kept_pairs, kept_five = kept_test() if sheet == "test" else kept_train()
    plan = supplement_needs(sheet, assignment, kept_types, kept_pairs, kept_five)
    if not any(plan["needs"].values()) and not plan.get("pair_needs"):
        print(f"{sheet}: 보충할 문항이 없습니다.")
        return 0
    used = set(assigned(assignment, sheet)[0])
    pool = [q for q in pools[sheet] if q["qid"] not in used]   # 앞 회차에서 유형을 받은 질문은 다시 쓰지 않는다
    no = 1 + max(r["round"] for r in assignment["rounds"] if r["sheet"] == sheet)
    extra = {k: v for k, v in plan.items() if k != "needs"}
    rnd = _round(no, sheet, pool, plan["needs"], extra, _file_sha(EXCLUDED))
    try:
        rnd.update(run_round(sheet, pool, rnd, assignment["seed"]))
    except Shortfall as e:
        return _report_short(e, sheet)
    assignment["rounds"].append(rnd)
    write_json(ASSIGNMENT, assignment)
    print(f"{sheet} 회차 {no}: {Counter(rnd['types'].values())}, 짝 {len(rnd['pairs'])}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="파인튜닝 실험의 변형 유형을 배정한다")
    p.add_argument("cmd", choices=("count", "first", "supplement"))
    p.add_argument("sheet", nargs="?", choices=("test", "train"))
    args = p.parse_args(argv)
    try:
        if args.cmd == "count":
            return cmd_count()
        if args.cmd == "first":
            return cmd_first()
        if args.sheet is None:
            print("supplement 에는 test 또는 train 을 준다.")
            return 1
        return cmd_supplement(args.sheet)
    except ValueError as e:
        print(f"배정하지 않았습니다. {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
