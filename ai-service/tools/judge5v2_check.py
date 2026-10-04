"""채점 모델 비교 v2 의 자체 점검 입구. DB 도 외부 API 도 쓰지 않는다. CI 에서 돈다.

실행:  cd ai-service && python -m tools.judge5v2_check

도구마다 점검 파일이 따로 있다(도구를 서로 다른 세션이 동시에 만들었기 때문이다). 이 파일은 그것들을 모두
부르고, 도구 하나로는 볼 수 없는 것 셋을 더 본다: 노트북이 judge5 와 같은 값을 쓰는가, 커밋된 최종 시험지에
정답이 새지 않았는가, 커밋된 배정이 시드로 재현되는가(스펙 8-3절의 judge5v2_check 항목).
"""
from __future__ import annotations

import json
import re

from . import (judge5v2_assign_check, judge5v2_export_check, judge5v2_gate_check, judge5v2_report_check,
               judge5v2_search_check)
from .judge5 import MAX_NEW_TOKENS, MODELS, SCALE, sha256_file, smoke_messages
from .judge5_check import (
    check_parse_v2_keeps_result_rules, check_parse_v2_reads_bracket_tail, check_parse_v2_refuses_truncated_tail,
    check_parse_v2_tail_is_strict,
)
from .judge5v2_assign import assigned_types, eligible3, eligible4, eligible6, eligible8, replay_round
from .judge5v2_export import CASE_KEYS
from .judge5v2_files import ANSWER_KEY, ASSIGNMENT, CASES, CASES_SHA, QUESTIONS, ROOT, read_json, read_jsonl

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


def check_committed_final_cases_are_blind() -> None:
    """최종 시험지에는 변형 유형, 정답 점수, qid 가 없어야 한다. 해시 셋(파일, 해시 파일, 정답 파일)이 같아야 한다."""
    ak = _final_key()
    if ak is None:
        return
    rows = read_jsonl(CASES)
    assert all(set(r) == CASE_KEYS for r in rows)
    assert sha256_file(CASES) == ak["cases_sha256"] == CASES_SHA.read_text(encoding="utf-8").split()[0]
    assert {r["case_id"] for r in rows} == set(ak["cases"])
    assert all(c["score"] in SCALE for c in ak["cases"].values())
    assert not set(ak["cases"]) & set(ak.get("dropped", {}))


def check_committed_assignment_replays_and_is_eligible() -> None:
    """같은 입력과 같은 시드로 다시 돌리면 같은 배정이 나와야 한다(스펙 3-3절). ③, ④, ⑥, ⑧ 은 자격 조건을 만족해야 한다."""
    if not ASSIGNMENT.exists():
        return
    a = read_json(ASSIGNMENT)
    by_id = {q["qid"]: q for q in read_jsonl(QUESTIONS)}
    for no, rnd in enumerate(a["rounds"]):
        assert replay_round(rnd, by_id, a["seed"], no) == rnd["domains"], f"회차 {no} 가 재현되지 않는다"
    for qid, t in assigned_types(a).items():
        if t == 4:
            assert eligible4(by_id[qid]), qid
        if t == 3:
            assert eligible3(by_id[qid]), qid
        if t == 6:
            assert eligible6(by_id[qid]), qid     # 답이 하나인 질문(스펙 3-2절)
        if t == 8:
            assert eligible8(by_id[qid]), qid


OWN = [
    check_parse_v2_reads_bracket_tail,
    check_parse_v2_tail_is_strict,
    check_parse_v2_refuses_truncated_tail,
    check_parse_v2_keeps_result_rules,
    check_v2_notebook_matches_the_module,
    check_v2_notebook_hash_matches_final_cases,
    check_committed_final_cases_are_blind,
    check_committed_assignment_replays_and_is_eligible,
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
