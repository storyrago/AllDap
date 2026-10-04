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
    ANSWER_KEY, ASSIGNMENT, DOMAINS, QUESTIONS, QUOTA, RETRIEVED, REVIEW, SEED, V2,
    latest_by_qid, read_json, read_jsonl, value_in, write_json,
)

# 자격 조건이 없는 유형을 채우는 순서(스펙 3-3절 3의 5).
REST_ORDER = (1, 2, 5, 7)

# 검색은 통과했지만 정답 청크가 근거 5청크 밖이라 멀쩡한 답변을 근거만으로 쓸 수 없는 질문. 출제 세션이 적는다.
# 모양: {"<qid>": {"reason": 아래 둘 중 하나, "note": "한국어 한 줄"}}. 파일이 없으면 제외가 없는 것이다.
# questions.jsonl 에 표시하지 않고 따로 두는 이유: 배정 회차의 pool 에 든 질문의 줄은 고치지 않는다(계획 E6).
EXCLUDED = V2 / "excluded.json"
EXCLUDE_REASONS = frozenset({"answer_not_in_top5", "partial_answer_not_in_top5"})


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
    """저장된 회차를 같은 입력으로 다시 돌린다. CI 가 배정이 시드로 재현되는지 볼 때 쓴다.

    회차에 적힌 제외 질문(excluded)이 그 회차의 후보에 들어 있으면 다시 돌리지 않고 멈춘다. 후보는 제외를 뺀 뒤의
    목록이어야 하므로, 들어 있으면 기록이 서로 어긋난 것이다.
    """
    pooled = {q for d in DOMAINS for q in rnd["pool"][d]}
    if again := sorted(pooled & set(rnd.get("excluded", {}))):
        raise ValueError(f"회차 {no} 의 후보에 제외한 질문이 들어 있다: {again[:5]}")
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
    # 값을 숫자(10000)로 적으면 아래 글자 비교(value_in)가 TypeError 로 멈춘다. 먼저 모양을 본다.
    values = [(contrast.get(side) or {}).get("value") for side in ("asked", "other")]
    if not all(isinstance(v, str) and v for v in values):
        return "asked.value 와 other.value 는 따옴표로 감싼 글자로 적는다"
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


def excluded_problems(excluded: dict, questions: list[dict], retrieved: list[dict]) -> list[str]:
    """excluded.json 의 내용이 규칙대로인가. 문제 목록을 돌려준다(빈 목록이면 통과).

    검색을 통과한(status ok) 질문만 제외할 수 있다. 검색에서 버린 질문은 이미 후보가 아니므로, 거기에 제외를
    겹쳐 적으면 보고서의 버린 원인이 두 번 세어진다. 없는 qid 는 오타일 가능성이 크다.
    """
    if not isinstance(excluded, dict):
        return ["excluded.json 은 {\"qid\": {\"reason\": ..., \"note\": ...}} 꼴의 객체여야 한다"]
    known = {q["qid"] for q in questions}
    latest = {r["qid"]: r for r in latest_by_qid(retrieved)}
    out = []
    for qid, e in sorted(excluded.items()):
        reason = e.get("reason") if isinstance(e, dict) else None
        if reason not in EXCLUDE_REASONS:
            out.append(f"{qid}: 제외 원인 {reason!r} 는 쓸 수 없다. {', '.join(sorted(EXCLUDE_REASONS))} 중 하나를 적는다")
        elif qid not in known:
            out.append(f"{qid}: questions.jsonl 에 없는 질문이다")
        elif qid not in latest:
            out.append(f"{qid}: 검색하지 않은 질문이다(retrieved.jsonl 에 없다)")
        elif latest[qid]["status"] != "ok":
            out.append(f"{qid}: 검색에서 이미 버린 질문이다({latest[qid]['drop_reason']}). 제외에 적지 않는다")
    return out


def load_excluded() -> tuple[dict, str | None]:
    """(excluded.json 내용, 그 파일의 SHA-256). 파일이 없으면 ({}, None) 이다."""
    if not EXCLUDED.exists():
        return {}, None
    return read_json(EXCLUDED), sha256_file(EXCLUDED)


def pool_for(questions: list[dict], retrieved: list[dict], excluded: dict | None = None) -> dict[str, list[dict]]:
    """검색을 통과한 질문 중 제외하지 않았고 멀쩡한 답변, 주장 수, ⑧ 조건이 제대로 적힌 것. 하나라도 잘못되면 멈춘다.
    검색 줄은 질문마다 마지막 줄만 본다(계획 형식 2). excluded 는 excluded.json 의 내용이다(없으면 제외 없음)."""
    excluded = excluded or {}
    if bad := excluded_problems(excluded, questions, retrieved):
        raise ValueError("배정하지 않았습니다. excluded.json 을 고친 뒤 다시 실행하세요.\n  - " + "\n  - ".join(bad))
    ok = {r["qid"]: r for r in latest_by_qid(retrieved) if r["status"] == "ok"}
    pools: dict[str, list[dict]] = {d: [] for d in DOMAINS}
    problems = []
    for q in questions:
        r = ok.get(q["qid"])
        # 제외한 질문은 답변 칸을 보기 전에 건너뛴다. 근거로 답을 쓸 수 없는 질문이라 답변이 비어 있을 수 있다.
        if r is None or q["qid"] in excluded:
            continue
        # type(x) is int: isinstance(True, int) 는 True 라서 claims 에 true 를 적어도 1 로 통과한다. bool 을 막으려고 정확히 int 만 받는다.
        if not q.get("answer") or type(q.get("claims")) is not int or q["claims"] < 1:
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


def supplement_pools(pools: dict[str, list[dict]], assignment: dict) -> dict[str, list[dict]]:
    """보충 회차의 후보. 앞 회차들에서 유형을 받은 질문은 빼고, 받지 않은 질문(unused)은 남긴다(스펙 7-2절).
    버린 문항의 질문도 뺀다. 같은 질문에 다른 유형을 붙여 다시 쓰면 그 질문의 검수 판단이 두 번 쓰이기 때문이다."""
    used = set(assigned_types(assignment))
    return {d: [q for q in ps if q["qid"] not in used] for d, ps in pools.items()}


def _round_doc(no: int, pools: dict[str, list[dict]], needs: dict[str, dict[int, int]], domains: dict,
               excluded: dict, excluded_sha: str | None, domain_of: dict[str, str]) -> dict:
    counts: dict[str, dict[str, int]] = {d: {} for d in DOMAINS}
    for qid, e in sorted(excluded.items()):
        counts[domain_of[qid]][e["reason"]] = counts[domain_of[qid]].get(e["reason"], 0) + 1
    return {
        "round": no,
        "questions_sha256": sha256_file(QUESTIONS),
        "retrieved_sha256": sha256_file(RETRIEVED),
        # 이 회차가 쓴 제외. 파일이 나중에 바뀌어도 이 회차의 후보가 무엇을 뺀 것인지 기록에서 알 수 있게
        # 해시(파일이 없었으면 null)와 질문별 원인, 분야별 원인 수를 함께 적는다. 보고서는 excluded_counts 를 읽는다.
        "excluded_sha256": excluded_sha,
        "excluded": {qid: e["reason"] for qid, e in sorted(excluded.items())},
        "excluded_counts": counts,
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


def _stop_if_eighth_moved(domains: dict[str, dict], stage: str, undo: bool = False) -> int:
    """이번 회차에서 ⑧ 을 ⑥ 으로 돌린 분야가 있으면 알리고 2, 없으면 0 을 돌려준다. first 와 supplement 가 같이 쓴다.

    stage 는 이 멈춤을 다루는 계획의 단계 이름이다(first 는 "E5", supplement 는 "E10, 스펙 7-2절 경우 2").
    undo 가 참이면(supplement) 덧붙인 회차를 되돌리는 명령과 그대로 갈 때 할 일을 함께 찍는다. supplement 는
    이미 커밋된 assignment.json 에 회차를 덧붙이므로, first 와 달리 파일을 지우는 것으로는 되돌릴 수 없다.
    """
    moved = {d: domains[d]["eighth_to_sixth"] for d in DOMAINS if domains[d]["eighth_to_sixth"]}
    if not moved:
        return 0
    # 이 경우 커밋하지 않고 사용자 판단을 받는다. 출력 한 줄로는 지나치기 쉬워서 종료 코드를 따로 둔다.
    # 1(배정 못 함)과 나누는 이유: 파일은 만들어졌다. 사용자가 그대로 가기로 하면 이 파일을 그대로 쓴다.
    print(f"멈춘다: 계획 {stage}. ⑧ 을 ⑥ 으로 돌린 분야가 있다("
          + ", ".join(f"{d} {n}개" for d, n in moved.items())
          + f"). {ASSIGNMENT.name} 는 남겼지만 커밋하지 않는다. 사용자에게 보충할지 그대로 갈지 묻는다.")
    if undo:
        print("  되돌리려면: git checkout -- ai-service/testdata/judge5v2/assignment.json")
        print("  그대로 가면: 변형 답변(E6)과 검수를 거친 뒤 관문 4(⑧ 15개 이상)를 다시 본다.")
    return 2


def cmd_first() -> int:
    if ASSIGNMENT.exists():
        print(f"{ASSIGNMENT.name} 가 이미 있습니다. 보충은 supplement 를 쓰세요. 덮어쓰지 않습니다.")
        return 1
    questions = read_jsonl(QUESTIONS)
    excluded, excluded_sha = load_excluded()
    try:
        pools = pool_for(questions, read_jsonl(RETRIEVED), excluded)
    except ValueError as e:
        print(e)   # pool_for 의 메시지가 이미 한국어로 고칠 곳을 줄마다 적는다
        return 1
    needs = {d: dict(QUOTA) for d in DOMAINS}
    try:
        domains = run_round(pools, needs, SEED, 0)
    except Shortfall as e:
        _print_short(e)
        return 1
    domain_of = {q["qid"]: q["domain"] for q in questions}
    doc = _round_doc(0, pools, needs, domains, excluded, excluded_sha, domain_of)
    write_json(ASSIGNMENT, {"seed": SEED, "rounds": [doc]})
    for d in DOMAINS:
        res = domains[d]
        print(f"{d}: 배정 {len(res['types'])}, 쓰지 않음 {len(res['unused'])}, ⑧ 을 ⑥ 으로 {res['eighth_to_sixth']}")
    if excluded:
        print("제외한 질문: " + ", ".join(f"{d} {sum(c.values())}개" for d, c in doc["excluded_counts"].items() if c))
    return _stop_if_eighth_moved(domains, "E5")


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
    excluded, excluded_sha = load_excluded()
    # 이미 유형을 받은 질문을 제외에 적으면, 그 질문은 앞 회차의 배정으로 시험지에 남으면서 이번 회차의 기록에는
    # 제외로 적힌다. 같은 질문이 서로 다른 두 사실로 기록되므로 멈춘다. 그런 질문은 검수에서 drop 한다.
    if both := sorted(set(excluded) & set(assigned_types(assignment))):
        print(f"excluded.json 에 이미 배정된 질문이 있습니다: {', '.join(both[:10])}. "
              "이미 배정된 질문은 제외에 적지 않고 검수에서 drop 한다(계획 E6, E9). excluded.json 에서 지운 뒤 다시 실행하세요.")
        return 1
    try:
        pools = supplement_pools(pool_for(questions, read_jsonl(RETRIEVED), excluded), assignment)
    except ValueError as e:
        print(e)
        return 1
    no = len(assignment["rounds"])
    try:
        domains = run_round(pools, needs, assignment["seed"], no)
    except Shortfall as e:
        _print_short(e)
        return 1
    assignment["rounds"].append(_round_doc(no, pools, needs, domains, excluded, excluded_sha, domain_of))
    write_json(ASSIGNMENT, assignment)
    print(f"회차 {no}: " + ", ".join(f"{d} {len(domains[d]['types'])}문항" for d in DOMAINS))
    # 보충 회차에서 ⑧ 을 ⑥ 으로 돌리면 스펙 7-2절 끝의 경우 2 다. 보충 배정은 돌린 ⑧ 을 다시 요구하지 않으므로
    # 다음 보충으로도 ⑧ 이 늘지 않는다. 그래서 first 와 같이 멈추고 사용자에게 보인다.
    return _stop_if_eighth_moved(domains, "E10, 스펙 7-2절 경우 2", undo=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="채점 모델 비교 v2 의 변형 유형을 배정한다")
    p.add_argument("cmd", choices=("first", "supplement"))
    args = p.parse_args(argv)
    return cmd_first() if args.cmd == "first" else cmd_supplement()


if __name__ == "__main__":
    sys.exit(main())
