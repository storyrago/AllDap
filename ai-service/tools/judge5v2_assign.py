"""채점 모델 비교 v2 의 변형 유형 배정(스펙 3-3절, 7-2절).

실행:
    cd ai-service
    $PY -m tools.judge5v2_assign first        # 첫 배정. assignment.json 이 없어야 한다
    $PY -m tools.judge5v2_assign supplement   # 관문을 통과하지 못했을 때 보충 배정. 새 회차를 덧붙인다

배정을 출제 세션의 판단이 아니라 시드로 정하는 이유: 출제 세션이 유형을 고르면 망가뜨리기 쉬운 질문에
어려운 유형이 몰릴 수 있다(스펙 3-3절).
"""
from __future__ import annotations

import argparse
import random
import sys
from collections import Counter

from .judge5 import sha256_file
from .judge5v2_files import (
    ANSWER_KEY, ASSIGNMENT, DOMAINS, QUESTIONS, QUOTA, RETRIEVED, REVIEW, SEED,
    latest_by_qid, read_json, read_jsonl, value_in, write_json,
)

# 자격 조건이 없는 유형을 채우는 순서(스펙 3-3절 3의 5).
REST_ORDER = (1, 2, 5, 7)


class Shortfall(Exception):
    """할당량을 채우지 못했다. short 는 {분야: {유형: 모자란 수}} 다."""

    def __init__(self, short: dict[str, dict[int, int]]) -> None:
        super().__init__(short)
        self.short = short


def eligible4(q: dict) -> bool:
    return q["claims"] >= 2 and q["claims"] % 2 == 0     # 주장 2 이상의 짝수(스펙 3-2절)


def eligible3(q: dict) -> bool:
    return q["claims"] >= 2                               # 주장 2 이상(스펙 3-2절)


def eligible6(q: dict) -> bool:
    # 답이 하나인 질문만(스펙 3-2절). 답이 두 가지인 질문에서 한쪽만 근거와 반대로 바꾸면 채점표의 1점("반대되는
    # 내용")과 3점("비슷한 정도로 섞여")에 모두 해당해 정답 점수가 하나로 정해지지 않는다.
    return not q["two_part"]


def eligible8(q: dict) -> bool:
    return not q["two_part"] and q["contrast"] is not None   # ⑥ 과 같은 이유로 답이 하나인 질문만


def assign_domain(pool: list[dict], needs: dict[int, int], rng: random.Random) -> tuple[dict, dict[int, int]]:
    """한 분야를 배정한다. 순서는 ④, ⑧, ③, ⑥, 나머지(스펙 3-3절 3).

    pool 을 qid 로 먼저 줄 세운다. 입력 순서와 무관하게 같은 시드에서 같은 배정이 나오게 하려는 것이다.
    rng.sample(목록, k) 는 목록에서 k 개를 중복 없이 뽑는다. 같은 시드의 Random 이면 늘 같은 k 개다.
    """
    pool = sorted(pool, key=lambda q: q["qid"])
    needs = dict(needs)
    types: dict[str, int] = {}
    short: dict[int, int] = {}

    def take(t: int, ok) -> int:
        cands = [q for q in pool if q["qid"] not in types and ok(q)]
        k = min(needs.get(t, 0), len(cands))
        for q in rng.sample(cands, k):
            types[q["qid"]] = t
        return needs.get(t, 0) - k

    if (n := take(4, eligible4)):         # := 는 값을 이름에 담으면서 그 값을 조건으로 쓴다
        short[4] = n
    moved = take(8, eligible8)            # ⑧ 이 모자란 수는 ⑥ 으로 돌린다(스펙 3-3절 5)
    needs[6] = needs.get(6, 0) + moved
    if (n := take(3, eligible3)):
        short[3] = n
    if (n := take(6, eligible6)):         # ⑥ 은 ⑧ 에서 돌린 수까지 합쳐 뽑는다. 그래서 ⑧ 다음이다
        short[6] = n

    rest = [q for q in pool if q["qid"] not in types]
    rng.shuffle(rest)
    i = 0
    for t in REST_ORDER:
        want = needs.get(t, 0)
        chunk = rest[i:i + want]
        if len(chunk) < want:
            short[t] = want - len(chunk)
        for q in chunk:
            types[q["qid"]] = t
        i += len(chunk)
    unused = sorted(q["qid"] for q in rest[i:])
    return {"types": types, "unused": unused, "eighth_to_sixth": moved}, short


def run_round(pools: dict[str, list[dict]], needs: dict[str, dict[int, int]], seed: int, no: int) -> dict[str, dict]:
    """네 분야를 한 회차로 배정한다. 분야마다 Random 을 따로 둔다(f"{seed}:{분야}:{회차}").
    따로 두는 이유: 한 분야의 질문 수가 바뀌어도 다른 분야의 배정이 흔들리지 않게 한다."""
    domains: dict[str, dict] = {}
    short: dict[str, dict[int, int]] = {}
    for d in DOMAINS:
        res, s = assign_domain(pools.get(d, []), needs.get(d, {}), random.Random(f"{seed}:{d}:{no}"))
        domains[d] = res
        if s:
            short[d] = s
    if short:
        raise Shortfall(short)
    return domains


def replay_round(rnd: dict, questions_by_id: dict[str, dict], seed: int, no: int) -> dict[str, dict]:
    """저장된 회차를 같은 입력으로 다시 돌린다. CI 가 배정이 시드로 재현되는지 볼 때 쓴다."""
    pools = {d: [questions_by_id[q] for q in rnd["pool"][d]] for d in DOMAINS}
    needs = {d: {int(t): n for t, n in rnd["needs"][d].items()} for d in DOMAINS}
    return run_round(pools, needs, seed, no)


def assigned_types(assignment: dict) -> dict[str, int]:
    out: dict[str, int] = {}
    for rnd in assignment["rounds"]:
        for res in rnd["domains"].values():
            out.update(res["types"])
    return out


def valid_contrast(contrast: dict, sources: list[dict]) -> str | None:
    """⑧ 조건이 맞으면 None, 아니면 이유. 두 값이 그 질문의 근거 청크에 글자 그대로 있고 서로 달라야 한다."""
    ids = set(contrast.get("chunk_ids") or [])
    texts = [s["content"] for s in sources if s["chunk_id"] in ids]
    if not ids or len(texts) != len(ids):
        return "chunk_ids 가 이 질문의 근거 청크가 아니다"
    asked, other = contrast["asked"]["value"], contrast["other"]["value"]
    if asked == other:
        return "두 대상의 값이 같다"
    joined = "\n".join(texts)
    if not value_in(asked, joined) or not value_in(other, joined):   # 단순 포함이 아니다(계획 형식 1)
        return "두 값이 chunk_ids 의 청크에 글자 그대로 있지 않다"
    return None


def pool_for(questions: list[dict], retrieved: list[dict]) -> dict[str, list[dict]]:
    """검색을 통과한 질문 중 멀쩡한 답변, 주장 수, ⑧ 조건이 제대로 적힌 것. 하나라도 잘못되면 멈춘다.
    검색 줄은 질문마다 마지막 줄만 본다(계획 형식 2)."""
    ok = {r["qid"]: r for r in latest_by_qid(retrieved) if r["status"] == "ok"}
    pools: dict[str, list[dict]] = {d: [] for d in DOMAINS}
    problems = []
    for q in questions:
        r = ok.get(q["qid"])
        if r is None:
            continue
        if not q.get("answer") or not isinstance(q.get("claims"), int) or q["claims"] < 1:
            problems.append(f"{q['qid']}: answer 또는 claims 가 비었다")
            continue
        if not isinstance(q.get("two_part"), bool):
            problems.append(f"{q['qid']}: two_part 가 true 나 false 가 아니다")
            continue
        if q["two_part"] and q.get("contrast") is not None:
            problems.append(f"{q['qid']}: 답이 두 가지인 질문에는 contrast 를 적지 않는다(⑧ 은 답이 하나인 질문에만 만든다)")
            continue
        if q.get("contrast") is not None and (why := valid_contrast(q["contrast"], r["sources"])):
            problems.append(f"{q['qid']}: ⑧ 조건이 잘못됐다({why})")
            continue
        pools[q["domain"]].append(q)
    if problems:
        raise ValueError("배정하지 않았습니다. questions.jsonl 을 고친 뒤 다시 실행하세요.\n  - " + "\n  - ".join(problems))
    return pools


def supplement_needs(assignment: dict, dropped_qids: set[str], domain_of: dict[str, str]) -> dict[str, dict[int, int]]:
    """보충할 할당량. 분야마다 (목표 - 남은 문항) 이다. 목표는 QUOTA 에서 ⑧ 을 ⑥ 으로 돌린 수를 반영한 값이다."""
    target = {d: dict(QUOTA) for d in DOMAINS}
    for rnd in assignment["rounds"]:
        for d, res in rnd["domains"].items():
            target[d][8] -= res["eighth_to_sixth"]
            target[d][6] += res["eighth_to_sixth"]
    kept = {d: Counter() for d in DOMAINS}
    for qid, t in assigned_types(assignment).items():
        if qid not in dropped_qids:
            kept[domain_of[qid]][t] += 1
    return {d: {t: max(0, target[d][t] - kept[d][t]) for t in QUOTA} for d in DOMAINS}


def _round_doc(no: int, pools: dict[str, list[dict]], needs: dict[str, dict[int, int]], domains: dict) -> dict:
    return {
        "round": no,
        "questions_sha256": sha256_file(QUESTIONS),
        "retrieved_sha256": sha256_file(RETRIEVED),
        "pool": {d: sorted(q["qid"] for q in pools[d]) for d in DOMAINS},
        # JSON 의 키는 글자뿐이라 유형 번호를 글자로 바꿔 적는다. replay_round 가 다시 정수로 읽는다.
        "needs": {d: {str(t): n for t, n in needs[d].items()} for d in DOMAINS},
        "domains": domains,
    }


def _print_short(e: Shortfall) -> None:
    print("할당량을 채우지 못했습니다. 아래 분야의 질문을 더 써서 questions.jsonl 에 더한 뒤(계획 E2 의 보충),")
    print("검색(E3)과 멀쩡한 답변(E4)을 거쳐 다시 실행하세요.")
    for d, s in e.short.items():
        print(f"  - {d}: " + ", ".join(f"유형 {t} 이 {n}개 모자람" for t, n in sorted(s.items())))
    print("유형 4는 주장 수 2 이상의 짝수, 유형 3은 주장 수 2 이상, 유형 6은 답이 하나인(two_part false) 질문이 필요하다.")


def cmd_first() -> int:
    if ASSIGNMENT.exists():
        print(f"{ASSIGNMENT.name} 가 이미 있습니다. 보충은 supplement 를 쓰세요. 덮어쓰지 않습니다.")
        return 1
    pools = pool_for(read_jsonl(QUESTIONS), read_jsonl(RETRIEVED))
    needs = {d: dict(QUOTA) for d in DOMAINS}
    try:
        domains = run_round(pools, needs, SEED, 0)
    except Shortfall as e:
        _print_short(e)
        return 1
    write_json(ASSIGNMENT, {"seed": SEED, "rounds": [_round_doc(0, pools, needs, domains)]})
    for d in DOMAINS:
        res = domains[d]
        print(f"{d}: 배정 {len(res['types'])}, 쓰지 않음 {len(res['unused'])}, ⑧ 을 ⑥ 으로 {res['eighth_to_sixth']}")
    return 0


def cmd_supplement() -> int:
    assignment = read_json(ASSIGNMENT)
    key = read_json(ANSWER_KEY)
    every = {**key["cases"], **key.get("dropped", {})}
    drops = {r["case_id"] for r in read_jsonl(REVIEW) if r.get("user_decision") == "drop"}
    dropped_qids = {every[c]["qid"] for c in drops if c in every}
    questions = read_jsonl(QUESTIONS)
    domain_of = {q["qid"]: q["domain"] for q in questions}
    needs = supplement_needs(assignment, dropped_qids, domain_of)
    if not any(n for s in needs.values() for n in s.values()):
        print("보충할 할당량이 없습니다. 관문이 할당량 밖의 이유로 실패했다면 사용자에게 알리고 멈춥니다.")
        return 1
    used = set(assigned_types(assignment))
    pools = {d: [q for q in ps if q["qid"] not in used] for d, ps in pool_for(questions, read_jsonl(RETRIEVED)).items()}
    no = len(assignment["rounds"])
    try:
        domains = run_round(pools, needs, assignment["seed"], no)
    except Shortfall as e:
        _print_short(e)
        return 1
    assignment["rounds"].append(_round_doc(no, pools, needs, domains))
    write_json(ASSIGNMENT, assignment)
    print(f"회차 {no}: " + ", ".join(f"{d} {len(domains[d]['types'])}문항" for d in DOMAINS))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="채점 모델 비교 v2 의 변형 유형을 배정한다")
    p.add_argument("cmd", choices=("first", "supplement"))
    args = p.parse_args(argv)
    return cmd_first() if args.cmd == "first" else cmd_supplement()


if __name__ == "__main__":
    sys.exit(main())
