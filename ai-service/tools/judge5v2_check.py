"""채점 모델 비교 v2 의 자체 점검 입구. DB 도 외부 API 도 쓰지 않는다. CI 에서 돈다.

실행:  cd ai-service && python -m tools.judge5v2_check

도구마다 점검 파일이 따로 있다(도구를 서로 다른 세션이 동시에 만들었기 때문이다). 이 파일은 그것들을 모두
부르고, 도구 하나로는 볼 수 없는 것을 더 본다: 노트북이 judge5 와 같은 값을 쓰는가, 커밋된 시험지에
정답이 새지 않았는가(draft 와 final 모두), 커밋된 최종 시험지가 커밋된 입력에서 그대로 다시 만들어지는가,
커밋된 배정이 시드로 재현되고 후보 목록이 규칙대로인가(스펙 8-3절의 judge5v2_check 항목).

커밋된 파일을 보는 점검은 파일이 아직 없으면 아무것도 보지 않고 통과한다. 그래서 그 점검마다 같은 판정 함수를
일부러 고장 낸 입력에 먹여 실패하는지 보는 점검을 짝으로 둔다. 짝이 없으면 판정 함수가 늘 빈 목록을 돌려줘도
CI 는 초록이다.
"""
from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

from . import (judge5v2_assign_check, judge5v2_export_check, judge5v2_gate_check, judge5v2_report_check,
               judge5v2_search_check)
from .judge5 import MAX_NEW_TOKENS, MODELS, SCALE, sha256_file, smoke_messages
from .judge5_check import (
    check_parse_v2_keeps_result_rules, check_parse_v2_reads_bracket_tail, check_parse_v2_refuses_truncated_tail,
    check_parse_v2_tail_is_strict,
)
from .judge5v2_assign import (
    assigned_types, eligible3, eligible4, eligible6, eligible8, replay_round, run_round,
)
from .judge5v2_assign_check import _pool
from .judge5v2_export import CASE_KEYS, apply_review, build_cases
from .judge5v2_export_check import _inputs
from .judge5v2_files import (
    ANSWER_KEY, ASSIGNMENT, CASES, CASES_SHA, DOMAINS, QUESTIONS, QUESTIONS_PER_DOMAIN, QUOTA, RETRIEVED, REVIEW,
    ROOT, VARIANTS, latest_by_qid, read_json, read_jsonl, write_jsonl,
)

NOTEBOOK = ROOT / "notebooks" / "judge5v2_colab.ipynb"


def _notebook_code() -> str:
    nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    return "\n".join(c["source"] if isinstance(c["source"], str) else "".join(c["source"])
                     for c in nb["cells"] if c["cell_type"] == "code")


def _final_key() -> dict | None:
    if not ANSWER_KEY.exists():
        return None
    ak = read_json(ANSWER_KEY)
    return ak if ak.get("stage") == "final" else None


# ---------------------------------------------------------------------------------------------------------------
# 판정 함수. 파일을 읽지 않고 내용만 받는다. 커밋된 파일과 일부러 고장 낸 입력에 똑같이 쓰기 위해서다.
# 모두 문제 목록을 돌려준다. 빈 목록이면 통과다(assert 하나로 멈추지 않고 문제를 전부 보여 주려는 것이다).
# ---------------------------------------------------------------------------------------------------------------

def _qno(qid: str) -> int:
    # "shop-007" 에서 7. rsplit("-", 1) 은 오른쪽에서 한 번만 자른다.
    return int(qid.rsplit("-", 1)[1])


def assignment_problems(a: dict, questions: list[dict], retrieved: list[dict]) -> list[str]:
    """배정 파일(계획 형식 3)이 규칙대로인가.

    1. 회차 0 의 후보(pool)는 처음 쓴 질문(번호 1~75) 중 검색을 통과한 것 전부다. 검색 줄은 질문마다 마지막 줄이
       판정이다(계획 형식 2). 후보에서 질문 하나를 빼고 돌려도 재현 점검은 통과하므로(그 후보로 다시 돌리니까)
       후보 자체를 따로 본다.
    2. 각 회차의 후보에는 앞 회차들에서 유형을 받은 질문이 없다(보충 배정, 스펙 7-2절).
    3. 같은 후보, 같은 할당량, 같은 시드로 다시 돌리면 같은 배정이 나온다(스펙 3-3절).
    4. ③, ④, ⑥, ⑧ 을 받은 질문은 그 자격 조건을 만족한다.
    """
    problems: list[str] = []
    by_id = {q["qid"]: q for q in questions}
    if a["rounds"]:
        latest = latest_by_qid(retrieved)
        want = {d: sorted(r["qid"] for r in latest if r["domain"] == d and r["status"] == "ok"
                          and _qno(r["qid"]) <= QUESTIONS_PER_DOMAIN) for d in DOMAINS}
        got = {d: sorted(a["rounds"][0]["pool"].get(d, [])) for d in DOMAINS}
        for d in DOMAINS:
            if got[d] != want[d]:
                missing, extra = sorted(set(want[d]) - set(got[d])), sorted(set(got[d]) - set(want[d]))
                problems.append(f"회차 0 의 {d} 후보가 검색을 통과한 질문과 다르다(빠짐 {missing[:5]}, 더 있음 {extra[:5]})")
    used: set[str] = set()
    for no, rnd in enumerate(a["rounds"]):
        pool = {q for d in DOMAINS for q in rnd["pool"].get(d, [])}
        if again := sorted(pool & used):
            problems.append(f"회차 {no} 의 후보에 앞 회차에서 쓴 질문이 있다: {again[:5]}")
        try:
            if replay_round(rnd, by_id, a["seed"], no) != rnd["domains"]:
                problems.append(f"회차 {no} 가 같은 시드로 재현되지 않는다")
        except Exception as e:  # noqa: BLE001 - 질문이 없거나 할당량을 못 채우면 재현이 아니라 실패로 센다
            problems.append(f"회차 {no} 를 다시 돌리지 못했다: {type(e).__name__}: {e}")
        used |= {q for res in rnd["domains"].values() for q in res["types"]}
    rules = {3: eligible3, 4: eligible4, 6: eligible6, 8: eligible8}
    for qid, t in assigned_types(a).items():
        if t in rules and (qid not in by_id or not rules[t](by_id[qid])):
            problems.append(f"{qid}: 유형 {t} 의 자격 조건을 만족하지 않는다")
    return problems


def cases_problems(ak: dict, rows: list[dict], file_sha: str, recorded_sha: str) -> list[str]:
    """시험지 파일에 정답이 새지 않았고 해시 셋이 맞는가. draft 와 final 모두 본다.

    draft 도 보는 이유: 검수 세션(Codex)이 draft 시험지를 읽는다. 거기에 유형이나 정답 점수가 있으면 검수가
    대응표를 베끼게 되어 두 모델이 함께 놓친 실수만 통과시킨다는 검수의 뜻이 없어진다(스펙 4절).
    """
    problems: list[str] = []
    for r in rows:
        if set(r) != CASE_KEYS:
            problems.append(f"{r.get('case_id')}: 시험지 줄의 키가 {sorted(set(r) ^ CASE_KEYS)} 만큼 다르다")
    if not file_sha == ak.get("cases_sha256") == recorded_sha:
        problems.append(f"해시가 다르다: 파일 {file_sha}, 정답 파일 {ak.get('cases_sha256')}, 해시 파일 {recorded_sha}")
    if {r["case_id"] for r in rows} != set(ak["cases"]):
        problems.append("시험지의 문항 id 와 정답 파일의 문항 id 가 다르다")
    if ak.get("stage") == "final":
        if bad := [c for c, v in ak["cases"].items() if v.get("score") not in SCALE]:
            problems.append(f"정답 점수가 1~5 가 아닌 문항: {bad[:5]}")
        if both := sorted(set(ak["cases"]) & set(ak.get("dropped", {}))):
            problems.append(f"남긴 문항과 버린 문항에 함께 있다: {both[:5]}")
    return problems


def rebuild_problems(ak: dict, cases_bytes: bytes, questions: list[dict], retrieved: list[dict], assignment: dict,
                     variants: list[dict], reviews: list[dict]) -> list[str]:
    """커밋된 입력으로 최종 시험지를 다시 만들면 커밋된 시험지와 바이트까지 같은가.

    cases_problems 는 시험지와 해시가 서로 맞는지만 본다. 시험지를 만든 뒤 변형 답변이나 검수 판단을 고치고
    final 을 다시 돌리지 않으면 셋은 여전히 서로 맞지만 입력과는 어긋난다. 그걸 여기서 잡는다.
    아래 세 줄은 judge5v2_export.cmd_final 과 같은 순서다(그 함수는 파일을 쓰므로 여기서 부르지 않는다).
    두 곳이 갈라지면 이 점검이 실패하므로 조용히 어긋나지는 않는다.
    """
    try:
        rows, key = build_cases(questions, retrieved, assigned_types(assignment), variants)
    except Exception as e:  # noqa: BLE001 - ExportProblem 등. 다시 만들지 못한 것도 문제로 센다
        return [f"최종 시험지를 다시 만들지 못했다: {type(e).__name__}: {e}"]
    kept, dropped, review_problems = apply_review(key, reviews)
    problems = [f"검수 반영: {p}" for p in review_problems[:5]]
    rows = [r for r in rows if r["case_id"] in kept]
    # 같은 함수(write_jsonl)로 써야 같은 바이트가 나온다. 직렬화 규칙을 여기 한 번 더 적으면 두 곳이 갈라질 수 있다.
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "cases.jsonl"
        write_jsonl(p, rows)
        rebuilt = p.read_bytes()
    if rebuilt != cases_bytes:
        problems.append("커밋된 입력으로 다시 만든 시험지가 커밋된 cases.jsonl 과 다르다. tools.judge5v2_export final 을 다시 실행하라")
    if kept != ak["cases"] or dropped != ak.get("dropped", {}):
        problems.append("커밋된 입력으로 다시 만든 정답 점수나 버린 문항이 answer_key.json 과 다르다")
    return problems


# ---------------------------------------------------------------------------------------------------------------
# 점검
# ---------------------------------------------------------------------------------------------------------------

def check_v2_notebook_matches_the_module() -> None:
    """노트북은 judge5 를 import 하지 못한다(코랩에는 이 저장소가 없다). 그래서 글자가 같은지 여기서 본다."""
    code = _notebook_code()
    assert f"MAX_NEW_TOKENS = {MAX_NEW_TOKENS}" in code
    for key in ("M3", "M4"):
        assert f'"{key}": "{MODELS[key]}"' in code, key
    assert '"M2":' not in code                                         # v2 스펙 5절: M2 를 뺀다
    assert "for key in ('M3', 'M4'):" in code
    assert "zip((1,), paths)" in code and "for r in (1,)]" in code     # 한 번만 채점한다
    assert "/content/drive/MyDrive/alldap_judge5v2'" in code
    assert "alldap_judge5v2_results.zip" in code
    assert "'domain': row['domain']" in code                            # 결과 줄에 분야를 옮긴다
    assert re.search(r"GenerationConfig\([^)]*do_sample=False", code)
    assert "model.generate(**enc, generation_config=gen, use_model_defaults=False)" in code
    line = next(l for l in code.splitlines() if l.startswith("SMOKE_MESSAGES = "))
    assert json.loads(line.split("=", 1)[1]) == smoke_messages()


def check_v2_notebook_hash_matches_final_cases() -> None:
    """최종 시험지가 있으면 노트북의 기대 해시가 그 해시와 같아야 한다. 검수 전 시험지(draft)는 보지 않는다."""
    m = re.search(r'EXPECTED_SHA256\s*=\s*"([0-9a-f]{64}|)"', _notebook_code())
    assert m, "노트북에 EXPECTED_SHA256 줄이 없다"
    ak = _final_key()
    if ak is not None:
        assert m.group(1) == ak["cases_sha256"], "노트북 해시를 최종 시험지 해시로 갱신하라(계획 E11)"


def check_committed_cases_are_blind() -> None:
    """커밋된 시험지(draft 든 final 이든)에 유형, 정답 점수, qid 가 없고 해시 셋이 맞는다."""
    if not ANSWER_KEY.exists():
        return
    ak = read_json(ANSWER_KEY)
    problems = cases_problems(ak, read_jsonl(CASES), sha256_file(CASES), CASES_SHA.read_text(encoding="utf-8").split()[0])
    assert not problems, "\n".join(problems)


def check_committed_final_cases_rebuild() -> None:
    """최종 시험지가 있으면 커밋된 입력으로 다시 만들어 바이트까지 대조한다."""
    ak = _final_key()
    if ak is None:
        return
    problems = rebuild_problems(ak, CASES.read_bytes(), read_jsonl(QUESTIONS), read_jsonl(RETRIEVED),
                                read_json(ASSIGNMENT), read_jsonl(VARIANTS), read_jsonl(REVIEW))
    assert not problems, "\n".join(problems)


def check_committed_assignment_replays_and_is_eligible() -> None:
    """커밋된 배정의 후보, 재현, 자격 조건(assignment_problems)."""
    if not ASSIGNMENT.exists():
        return
    problems = assignment_problems(read_json(ASSIGNMENT), read_jsonl(QUESTIONS), read_jsonl(RETRIEVED))
    assert not problems, "\n".join(problems)


def _assignment_fixture() -> tuple[dict, list[dict], list[dict]]:
    """분야마다 질문 75개(번호 0~74)로 회차 0 을 돌린 배정과 그 입력. 고장 내기 전에는 문제가 없어야 한다."""
    pools = {d: _pool(d) for d in DOMAINS}
    questions = [q for d in DOMAINS for q in pools[d]]
    retrieved = [{"qid": q["qid"], "domain": q["domain"], "status": "ok"} for q in questions]
    needs = {d: {str(t): n for t, n in QUOTA.items()} for d in DOMAINS}
    seed = 20261005
    domains = run_round(pools, {d: dict(QUOTA) for d in DOMAINS}, seed, 0)
    rnd0 = {"pool": {d: [q["qid"] for q in pools[d]] for d in DOMAINS}, "needs": needs, "domains": domains}
    return {"seed": seed, "rounds": [rnd0]}, questions, retrieved


def check_assignment_problems_catch_broken_inputs() -> None:
    """assignment_problems 가 고장 하나하나를 잡는가. 커밋된 파일이 없을 때도 이 점검은 실제로 돈다."""
    a, qs, rs = _assignment_fixture()
    assert assignment_problems(a, qs, rs) == []

    # 회차 0 의 후보에서 질문 하나를 뺐다. 재현 점검만으로는 못 잡는 경우다(빠진 후보로 다시 돌리면 같게 나올 수 있다).
    b = json.loads(json.dumps(a))   # 깊은 복사. 고장 낸 것이 다음 경우에 새지 않게 한다
    b["rounds"][0]["pool"]["shop"].remove(sorted(b["rounds"][0]["domains"]["shop"]["unused"])[0])
    assert any("회차 0 의 shop 후보" in p for p in assignment_problems(b, qs, rs))

    # 검색을 다시 해서 마지막 줄이 버림이 된 질문이 후보에 남아 있다.
    dropped = rs + [{"qid": "hr-010", "domain": "hr", "status": "dropped", "drop_reason": "answerable"}]
    assert any("회차 0 의 hr 후보" in p for p in assignment_problems(a, qs, dropped))

    # 보충 회차의 후보에 회차 0 에서 쓴 질문이 있다. 그 후보로 배정을 실제로 돌려 재현은 맞게 만든다.
    used_q = sorted(a["rounds"][0]["domains"]["manual"]["types"])[0]
    pools1 = {d: [q for q in qs if q["domain"] == d][:3] for d in DOMAINS}
    pools1["manual"].append(next(q for q in qs if q["qid"] == used_q))
    needs1 = {d: {t: (1 if t == 1 else 0) for t in QUOTA} for d in DOMAINS}
    rnd1 = {"pool": {d: [q["qid"] for q in pools1[d]] for d in DOMAINS},
            "needs": {d: {str(t): n for t, n in needs1[d].items()} for d in DOMAINS},
            "domains": run_round(pools1, needs1, a["seed"], 1)}
    c = {"seed": a["seed"], "rounds": a["rounds"] + [rnd1]}
    got = assignment_problems(c, qs, rs)
    assert any("회차 1 의 후보에 앞 회차에서 쓴 질문" in p for p in got), got

    # 시드가 바뀌었다.
    assert any("재현되지 않는다" in p for p in assignment_problems(dict(a, seed=1), qs, rs))

    # ④ 를 받은 질문의 주장 수를 홀수로 바꿨다.
    q4 = next(q for q, t in assigned_types(a).items() if t == 4)
    qs4 = [dict(q, claims=3) if q["qid"] == q4 else q for q in qs]
    assert any(p.startswith(f"{q4}: 유형 4") for p in assignment_problems(a, qs4, rs))


def _final_fixture(d: Path) -> tuple[dict, bytes, tuple]:
    """judge5v2_export_check 의 입력 셋으로 최종 시험지를 만든다. 검수는 모두 정답 점수와 같다고 둔다."""
    questions, retrieved, types, variants = _inputs()
    assignment = {"seed": 1, "rounds": [{"domains": {"shop": {"types": types}}}]}
    rows, key = build_cases(questions, retrieved, types, variants)
    reviews = [{"case_id": c, "review_score": k["table_score"]} for c, k in key.items()]
    kept, dropped, _ = apply_review(key, reviews)
    p = d / "cases.jsonl"
    write_jsonl(p, [r for r in rows if r["case_id"] in kept])
    ak = {"stage": "final", "cases_sha256": sha256_file(p), "cases": kept, "dropped": dropped}
    return ak, p.read_bytes(), (questions, retrieved, assignment, variants, reviews)


def check_cases_and_rebuild_problems_catch_broken_inputs() -> None:
    """cases_problems 와 rebuild_problems 가 고장 하나하나를 잡는가."""
    with tempfile.TemporaryDirectory() as tmp:
        ak, raw, inputs = _final_fixture(Path(tmp))
        rows = [json.loads(l) for l in raw.decode("utf-8").splitlines()]
        sha = ak["cases_sha256"]
        assert cases_problems(ak, rows, sha, sha) == []
        assert rebuild_problems(ak, raw, *inputs) == []

        # 시험지 줄에 유형이 샜다. draft 단계에서도 잡아야 한다.
        leaked = [dict(rows[0], type=8)] + rows[1:]
        for stage in ("draft", "final"):
            assert any("키가" in p for p in cases_problems(dict(ak, stage=stage), leaked, sha, sha)), stage
        # 해시 파일이 다른 시험지의 것이다.
        assert any("해시가 다르다" in p for p in cases_problems(ak, rows, sha, "0" * 64))
        # 남긴 문항과 버린 문항에 함께 있다.
        both = dict(ak, dropped={next(iter(ak["cases"])): {}})
        assert any("함께 있다" in p for p in cases_problems(both, rows, sha, sha))

        questions, retrieved, assignment, variants, reviews = inputs
        # 시험지를 만든 뒤 변형 답변을 고쳤다. 시험지와 해시는 여전히 서로 맞으므로 cases_problems 는 못 잡는다.
        v2 = [dict(v, answer=v["answer"] + " 감사합니다.") if v["type"] == 6 else v for v in variants]
        assert any("다시 만든 시험지" in p for p in rebuild_problems(ak, raw, questions, retrieved, assignment, v2, reviews))
        # 시험지를 만든 뒤 검수 판단을 고쳤다(한 문항을 사용자가 3점으로 고침).
        cid = next(c for c, k in ak["cases"].items() if k["table_score"] == 5)
        r2 = [dict(r, review_score=3, user_decision="override", override_score=3, reason="다시 봤다")
              if r["case_id"] == cid else r for r in reviews]
        assert any("정답 점수나 버린 문항" in p for p in rebuild_problems(ak, raw, questions, retrieved, assignment, variants, r2))


OWN = [
    check_parse_v2_reads_bracket_tail,
    check_parse_v2_tail_is_strict,
    check_parse_v2_refuses_truncated_tail,
    check_parse_v2_keeps_result_rules,
    check_v2_notebook_matches_the_module,
    check_v2_notebook_hash_matches_final_cases,
    check_committed_cases_are_blind,
    check_committed_final_cases_rebuild,
    check_committed_assignment_replays_and_is_eligible,
    check_assignment_problems_catch_broken_inputs,
    check_cases_and_rebuild_problems_catch_broken_inputs,
]
CHECKS = (judge5v2_search_check.CHECKS + judge5v2_assign_check.CHECKS + judge5v2_export_check.CHECKS
          + judge5v2_gate_check.CHECKS + judge5v2_report_check.CHECKS + OWN)


def main() -> None:
    for fn in CHECKS:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(CHECKS)}가지 전부 통과.")


if __name__ == "__main__":
    main()
