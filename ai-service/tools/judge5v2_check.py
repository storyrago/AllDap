"""채점 모델 비교 v2 의 자체 점검 입구. DB 도 외부 API 도 쓰지 않는다. CI 에서 돈다.

실행:  cd ai-service && python -m tools.judge5v2_check

도구마다 점검 파일이 따로 있다(도구를 서로 다른 세션이 동시에 만들었기 때문이다). 이 파일은 그것들을 모두
부르고, 도구 하나로는 볼 수 없는 것을 더 본다: 노트북이 judge5 와 같은 값을 쓰는가, 커밋된 시험지에
정답이 새지 않았는가(draft 와 final 모두), 커밋된 최종 시험지가 커밋된 입력에서 그대로 다시 만들어지는가,
커밋된 배정이 시드로 재현되고 후보 목록이 규칙대로인가(스펙 8-3절의 judge5v2_check 항목).

커밋된 파일을 보는 점검은 파일이 아직 없으면 아무것도 보지 않고 통과한다. 그래서 그 점검마다 같은 판정 함수를
일부러 고장 낸 입력에 먹여 실패하는지 보는 점검을 짝으로 둔다. 짝이 없으면 판정 함수가 늘 빈 목록을 돌려줘도
CI 는 초록이다. 고장 점검의 입력(픽스처)은 이 파일 안에 따로 둔다. 다른 도구의 점검 파일에서 빌려 오면
그 파일의 픽스처가 바뀔 때 이 점검이 무엇을 보는지가 소리 없이 바뀐다.
"""
from __future__ import annotations

import hashlib
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
from .judge5v2_export import CASE_KEYS, apply_review, build_cases
from .judge5v2_files import (
    ANSWER_KEY, ASSIGNMENT, CASES, CASES_SHA, DOMAINS, QUESTIONS, QUOTA, RETRIEVED, REVIEW, ROOT, VARIANTS,
    latest_by_qid, read_json, read_jsonl, write_jsonl,
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


def _settings_kind(settings: dict | None) -> str:
    # dict 는 집합에 넣을 수 없어서 키 순서를 고정한 JSON 글자로 바꿔 종류를 센다.
    return json.dumps(settings, ensure_ascii=False, sort_keys=True)


# ---------------------------------------------------------------------------------------------------------------
# 판정 함수. 파일을 읽지 않고 내용만 받는다. 커밋된 파일과 일부러 고장 낸 입력에 똑같이 쓰기 위해서다.
# 모두 문제 목록을 돌려준다. 빈 목록이면 통과다(assert 하나로 멈추지 않고 문제를 전부 보여 주려는 것이다).
# ---------------------------------------------------------------------------------------------------------------

def retrieved_prefix(raw: bytes, sha: str) -> list[dict] | None:
    """raw(retrieved.jsonl 의 바이트)의 줄 경계 앞부분 중 SHA-256 이 sha 인 것을 찾아 그 줄들을 돌려준다.

    retrieved.jsonl 은 덧붙이기만 하는 파일이다(계획 형식 2). 배정 회차는 그때의 파일 해시를 기록하므로, 그 뒤에
    줄이 더 붙어도 기록된 해시는 지금 파일의 어느 줄 경계 앞부분과 같아야 한다. 없으면 앞 줄이 고쳐졌거나 지워진
    것이다. 해시를 한 줄씩 이어 계산하므로(update) 파일 길이에 비례하는 시간만 든다.
    빈 파일의 해시(아무 줄도 없을 때)도 앞부분으로 본다.
    """
    h = hashlib.sha256()
    if h.hexdigest() == sha:
        return []
    start = 0
    while start < len(raw):
        end = raw.find(b"\n", start)
        end = len(raw) if end < 0 else end + 1    # 마지막 줄에 줄바꿈이 없으면 파일 끝까지가 한 줄이다
        h.update(raw[start:end])
        if h.hexdigest() == sha:   # hexdigest 는 해시를 끝내지 않는다. 이어서 update 할 수 있다
            # 맞는 앞부분을 찾은 뒤에만 JSON 으로 읽는다. 그 뒤의 줄(잘렸거나 쓰는 중인 줄)은 읽지 않는다.
            return [json.loads(line) for line in raw[:end].splitlines() if line.strip()]
        start = end
    return None


def assignment_problems(a: dict, questions: list[dict], retrieved_raw: bytes) -> list[str]:
    """배정 파일(계획 형식 3)이 규칙대로인가.

    1. 회차 0 의 후보(pool)는 그 회차를 돌릴 때의 검색 파일에서 검색을 통과하고 멀쩡한 답변이 있는 질문 전부다
       (pool_for 와 같은 조건). 그때의 검색 파일은 회차에 기록된 retrieved_sha256 으로 지금 파일에서 찾는다.
       지금 파일 전체로 정답을 만들면 회차 0 뒤에 다시 검색해 ok 가 된 질문(호출 실패로 버렸던 질문)이
       거짓 실패를 낸다. 번호(75 이하)로 거르는 것은 보충 질문(076 이후)만 막고 이 경우를 막지 못한다.
       후보에서 질문 하나를 빼고 돌려도 재현 점검은
       통과하므로(그 후보로 다시 돌리니까) 후보 자체를 따로 본다.
    2. 각 회차의 후보에는 앞 회차들에서 유형을 받은 질문이 없다(보충 배정, 스펙 7-2절).
    3. 같은 후보, 같은 할당량, 같은 시드로 다시 돌리면 같은 배정이 나온다(스펙 3-3절).
    4. ③, ④, ⑥, ⑧ 을 받은 질문은 그 자격 조건을 만족한다.
    """
    problems: list[str] = []
    by_id = {q["qid"]: q for q in questions}
    if a["rounds"]:
        rnd0 = a["rounds"][0]
        prefix = retrieved_prefix(retrieved_raw, rnd0.get("retrieved_sha256", ""))
        if prefix is None:
            problems.append("회차 0 에 기록된 retrieved_sha256 과 같은 앞부분이 지금 retrieved.jsonl 에 없다. "
                            "앞 줄이 고쳐졌거나 지워졌다(이 파일은 덧붙이기만 한다)")
        else:
            ok = [r for r in latest_by_qid(prefix) if r["status"] == "ok" and by_id.get(r["qid"], {}).get("answer")]
            want = {d: sorted(r["qid"] for r in ok if r["domain"] == d) for d in DOMAINS}
            got = {d: sorted(rnd0["pool"].get(d, [])) for d in DOMAINS}
            for d in DOMAINS:
                if got[d] != want[d]:
                    missing, extra = sorted(set(want[d]) - set(got[d])), sorted(set(got[d]) - set(want[d]))
                    problems.append(f"회차 0 의 {d} 후보가 그때 검색을 통과한 질문과 다르다"
                                    f"(빠짐 {missing[:5]}, 더 있음 {extra[:5]})")
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
    final 은 검색 설정이 한 가지인지도 본다. 스펙 2-3절은 모든 문항을 같은 기본 설정으로 검색한다. 검색 도구의
    --allow-nondefault 로 돌린 줄이 섞이면 문항마다 근거를 뽑은 방식이 달라진다.
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
        kinds = {_settings_kind(r.get("search_settings")) for r in rows}
        if len(kinds) > 1:
            problems.append(f"최종 시험지의 검색 설정이 {len(kinds)}가지다. 모든 문항을 같은 설정으로 검색해야 한다(스펙 2-3절)")
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
    raw = RETRIEVED.read_bytes() if RETRIEVED.exists() else b""
    problems = assignment_problems(read_json(ASSIGNMENT), read_jsonl(QUESTIONS), raw)
    assert not problems, "\n".join(problems)


# ---------------------------------------------------------------------------------------------------------------
# 고장 점검의 픽스처. 다른 점검 파일에서 빌려 오지 않는다(모듈 설명 끝 문단).
# ---------------------------------------------------------------------------------------------------------------

_SEED = 20261005
_CONTRAST = {"asked": {"target": "골드", "value": "10,000원"}, "other": {"target": "실버", "value": "20,000원"},
             "chunk_ids": [1]}


def _questions(domain: str, n: int = 75, start: int = 1) -> list[dict]:
    """할당량을 채울 수 있는 질문 n 개. 0~19 번째는 주장 2개(답 두 가지, ④ 와 ③ 몫), 20~34 번째는 주장 3개,
    나머지는 주장 1개다. 답이 하나인 질문 중 7 번째마다 ⑧ 조건(contrast)을 붙인다. 번호는 start 부터다."""
    out = []
    for i in range(n):
        claims = 2 if i < 20 else 3 if i < 35 else 1
        two_part = i < 20
        out.append({"qid": f"{domain}-{start + i:03d}", "domain": domain, "question": f"질문 {i}", "answer": f"답 {i}",
                    "claims": claims, "two_part": two_part,
                    "contrast": _CONTRAST if not two_part and i % 7 == 0 else None})
    return out


def _lines(rows: list[dict]) -> bytes:
    # 검색 도구가 쓰는 꼴(append_jsonl)과 같게 한 줄에 JSON 하나다.
    return "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows).encode("utf-8")


def _ok(q: dict) -> dict:
    return {"qid": q["qid"], "domain": q["domain"], "status": "ok", "drop_reason": None}


def _assignment_fixture() -> tuple[dict, list[dict], bytes]:
    """분야마다 질문 75개로 회차 0 을 돌린 배정, 질문, 검색 파일 바이트. 고장 내기 전에는 문제가 없어야 한다.
    hr-075 는 회차 0 때 리랭커 호출이 실패해 버려진 상태라 후보에 없다(뒤늦게 ok 가 되는 정상 경로에 쓴다)."""
    questions = [q for d in DOMAINS for q in _questions(d)]
    late = "hr-075"
    lines = [_ok(q) if q["qid"] != late else {"qid": late, "domain": "hr", "status": "dropped",
                                             "drop_reason": "rerank_failed"} for q in questions]
    raw = _lines(lines)
    pools = {d: [q for q in questions if q["domain"] == d and q["qid"] != late] for d in DOMAINS}
    domains = run_round(pools, {d: dict(QUOTA) for d in DOMAINS}, _SEED, 0)
    rnd0 = {"retrieved_sha256": hashlib.sha256(raw).hexdigest(),
            "pool": {d: [q["qid"] for q in pools[d]] for d in DOMAINS},
            "needs": {d: {str(t): n for t, n in QUOTA.items()} for d in DOMAINS}, "domains": domains}
    return {"seed": _SEED, "rounds": [rnd0]}, questions, raw


def check_assignment_problems_catch_broken_inputs() -> None:
    """assignment_problems 가 고장 하나하나를 잡는가. 커밋된 파일이 없을 때도 이 점검은 실제로 돈다."""
    a, qs, raw = _assignment_fixture()
    assert assignment_problems(a, qs, raw) == []

    # 회차 0 의 후보에서 질문 하나를 뺐다. 재현 점검만으로는 못 잡는 경우다(빠진 후보로 다시 돌리면 같게 나올 수 있다).
    b = json.loads(json.dumps(a))   # 깊은 복사. 고장 낸 것이 다음 경우에 새지 않게 한다
    b["rounds"][0]["pool"]["shop"].remove(sorted(b["rounds"][0]["domains"]["shop"]["unused"])[0])
    assert any("회차 0 의 shop 후보" in p for p in assignment_problems(b, qs, raw))

    # 회차 0 의 후보였던 질문의 멀쩡한 답변을 나중에 지웠다(형식 1: 후보에 든 질문의 줄은 고치지 않는다).
    pooled = a["rounds"][0]["pool"]["finance"][0]
    no_answer = [dict(q, answer=None) if q["qid"] == pooled else q for q in qs]
    assert any("회차 0 의 finance 후보" in p for p in assignment_problems(a, no_answer, raw))

    # 회차 0 뒤에 앞 줄을 고쳤다(덧붙이기만 하는 파일인데 첫 줄의 판정을 바꿨다).
    first, rest = raw.split(b"\n", 1)
    edited = first.replace(b'"status": "ok"', b'"status": "dropped"') + b"\n" + rest
    assert edited != raw
    assert any("앞 줄이 고쳐졌거나" in p for p in assignment_problems(a, qs, edited))
    assert any("앞 줄이 고쳐졌거나" in p for p in assignment_problems(a, qs, raw[: len(raw) // 2]))   # 잘렸다

    # 보충 회차의 후보에 회차 0 에서 쓴 질문이 있다. 그 후보로 배정을 실제로 돌려 재현은 맞게 만든다.
    used_q = sorted(a["rounds"][0]["domains"]["manual"]["types"])[0]
    pools1 = {d: [q for q in qs if q["domain"] == d][:3] for d in DOMAINS}
    pools1["manual"].append(next(q for q in qs if q["qid"] == used_q))
    needs1 = {d: {t: (1 if t == 1 else 0) for t in QUOTA} for d in DOMAINS}
    rnd1 = {"pool": {d: [q["qid"] for q in pools1[d]] for d in DOMAINS},
            "needs": {d: {str(t): n for t, n in needs1[d].items()} for d in DOMAINS},
            "domains": run_round(pools1, needs1, a["seed"], 1)}
    c = {"seed": a["seed"], "rounds": a["rounds"] + [rnd1]}
    got = assignment_problems(c, qs, raw)
    assert any("회차 1 의 후보에 앞 회차에서 쓴 질문" in p for p in got), got

    # 시드가 바뀌었다.
    assert any("재현되지 않는다" in p for p in assignment_problems(dict(a, seed=1), qs, raw))

    # ④ 를 받은 질문의 주장 수를 홀수로 바꿨다.
    q4 = next(q for q, t in assigned_types(a).items() if t == 4)
    qs4 = [dict(q, claims=3) if q["qid"] == q4 else q for q in qs]
    assert any(p.startswith(f"{q4}: 유형 4") for p in assignment_problems(a, qs4, raw))


def check_assignment_problems_pass_normal_later_lines() -> None:
    """회차 0 뒤에 검색 파일에 줄이 덧붙는 정상 경로 둘은 통과해야 한다.
    1. 보충 질문(076 이후)을 쓰고 검색했다. 2. 호출 실패로 버린 질문(hr-075)을 다시 검색해 ok 가 됐다.
    번호로 거르던 옛 판은 1 은 통과하고 2 에서 거짓 실패했다. 1 은 앞부분 방식으로 바꿔도 깨지지 않는지 보려고 둔다."""
    a, qs, raw = _assignment_fixture()
    extra = [q for d in DOMAINS for q in _questions(d, 3, start=76)]
    later = raw + _lines([_ok(q) for q in extra]) + _lines([{**_ok(qs[0]), "qid": "hr-075"}])
    got = assignment_problems(a, qs + extra, later)
    assert got == [], got


def _final_fixture(d: Path) -> tuple[dict, bytes, tuple]:
    """최종 시험지 하나를 만든다. 변형 유형은 ①, ②, ⑤ 만 쓴다(⑥, ⑧ 의 형식 규칙은 내보내기 도구 쪽 점검이 본다).
    검수는 모두 정답 점수와 같다고 둔다."""
    src = [{"chunk_id": 1, "filename": "a.md", "content": "골드 10,000원 / 실버 20,000원 / 브론즈 30,000원."}]
    settings = {"top_k": 5}
    questions = [{"qid": f"shop-00{i}", "domain": "shop", "question": f"{g} 무료 기준은?",
                  "answer": f"{g}는 {v} 이상이면 무료입니다.", "claims": 1, "two_part": False, "contrast": None}
                 for i, (g, v) in enumerate([("골드", "10,000원"), ("실버", "20,000원"), ("브론즈", "30,000원")], start=1)]
    retrieved = [{"qid": q["qid"], "domain": "shop", "status": "ok", "settings": settings, "sources": src} for q in questions]
    types = {"shop-001": 1, "shop-002": 2, "shop-003": 5}
    variants = [{"qid": "shop-001", "type": 1, "answer": questions[0]["answer"], "note": ""},
                {"qid": "shop-002", "type": 2, "answer": "실버 등급은 20,000원부터 배송비가 없습니다.", "note": ""},
                {"qid": "shop-003", "type": 5, "answer": "브론즈는 30,000원 이상이면 무료이고 매달 쿠폰도 나옵니다.", "note": ""}]
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
        assert len(rows) == 3
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
        # 한 문항만 다른 검색 설정으로 뽑았다(final 에서만 본다. draft 는 검수 전이라 보충으로 다시 만든다).
        mixed = [dict(rows[0], search_settings={"top_k": 8})] + rows[1:]
        assert any("검색 설정이 2가지" in p for p in cases_problems(ak, mixed, sha, sha))
        assert not any("검색 설정" in p for p in cases_problems(dict(ak, stage="draft"), mixed, sha, sha))

        questions, retrieved, assignment, variants, reviews = inputs
        # 시험지를 만든 뒤 변형 답변을 고쳤다. 시험지와 해시는 여전히 서로 맞으므로 cases_problems 는 못 잡는다.
        v2 = [dict(v, answer=v["answer"] + " 감사합니다.") if v["type"] == 2 else v for v in variants]
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
    check_assignment_problems_pass_normal_later_lines,
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
