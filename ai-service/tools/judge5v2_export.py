"""채점 모델 비교 v2 의 시험지 파일과 정답 파일을 만든다(스펙 8-1절 5단계와 8단계).

실행:
    cd ai-service
    $PY -m tools.judge5v2_export draft        # 검수 전. 배정된 모든 문항으로 시험지를 만든다
    $PY -m tools.judge5v2_export mismatches   # 검수 뒤. 검수 점수와 정답 점수가 다른 문항을 사용자용으로 정리한다
    $PY -m tools.judge5v2_export final        # 관문 통과 뒤. 버린 문항을 빼고 고친 정답 점수를 넣는다

시험지 파일(cases.jsonl)에는 변형 유형, 정답 점수, qid 를 넣지 않는다. 채점 모델과 검수 세션은 이 파일만 읽는다.
"""
from __future__ import annotations

import argparse
import hashlib
import random
import re
import sys

from .judge5 import SCALE, build_messages, prompt_sha256, sha256_file
from .judge5v2_assign import assigned_types
from .judge5v2_files import (
    ANSWER_KEY, ASSIGNMENT, CASES, CASES_SHA, MISMATCHES, QUESTIONS, RETRIEVED, REVIEW, SEED, TABLE_SCORE,
    TYPE_NAMES, VARIANTS, latest_by_qid, read_json, read_jsonl, value_in, write_json, write_jsonl,
)

CASE_KEYS = frozenset({"case_id", "domain", "messages", "search_settings"})


def fence_for(text: str) -> str:
    """text 를 감쌀 마크다운 코드 울타리. text 안에서 가장 긴 백틱 연속보다 하나 길게(최소 셋) 만든다.

    고정 길이 셋이면 근거 청크(마크다운 문서)에 들어 있는 백틱 셋이 울타리를 일찍 닫아, mismatches.md 에서
    그 뒤의 내용이 코드 블록 밖으로 나와 제목이나 목록으로 그려진다. 마크다운은 여는 울타리보다 짧은 백틱 줄로는
    닫지 않는다. 백틱을 곱셈으로 만드는 이유: 글자 그대로 적으면 이 코드를 담은 문서의 코드 블록이 거기서 끝난다.
    """
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


class ExportProblem(RuntimeError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems[:5]))
        self.problems = problems


def case_id_of(domain: str, question: str, answer: str) -> str:
    """문항 id. 해시의 입력에 변형 유형과 정답 점수를 넣지 않는다(스펙 8-3절). 그래서 id 로 유형을 알 수 없다.
    "\\x00" 으로 잇는 이유: 경계가 옮겨 간 다른 입력("ab"+"c" 와 "a"+"bc")이 같은 해시가 되지 않게 한다."""
    raw = "\x00".join([domain, question, answer])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def build_cases(questions: list[dict], retrieved: list[dict], types: dict[str, int],
                variants: list[dict]) -> tuple[list[dict], dict[str, dict]]:
    """배정된 질문마다 문항 하나를 만든다. 형식이 하나라도 틀리면 ExportProblem 으로 전부 알린다."""
    q_by = {q["qid"]: q for q in questions}
    r_by = {r["qid"]: r for r in latest_by_qid(retrieved)}   # 질문마다 마지막 검색 줄이 판정이다(계획 형식 2)
    v_by: dict[str, dict] = {}
    problems: list[str] = []
    for v in variants:
        if v["qid"] in v_by:
            problems.append(f"{v['qid']}: 변형 답변이 두 줄 있다")
        v_by[v["qid"]] = v
    rows: list[dict] = []
    key: dict[str, dict] = {}
    for qid, t in sorted(types.items()):
        q, r, v = q_by.get(qid), r_by.get(qid), v_by.get(qid)
        if v is None:
            problems.append(f"{qid}: 변형 답변이 없다")
            continue
        if q is None or r is None or r["status"] != "ok":
            problems.append(f"{qid}: 질문이 없거나 검색을 통과하지 못했다")
            continue
        if v["type"] != t:
            problems.append(f"{qid}: 배정은 {t} 인데 변형 답변은 {v['type']} 이다")
            continue
        if t == 1 and v["answer"] != q["answer"]:
            problems.append(f"{qid}: ①은 멀쩡한 답변과 글자까지 같아야 한다")
        if t != 1 and v["answer"] == q["answer"]:
            problems.append(f"{qid}: 변형 답변이 멀쩡한 답변과 같다")
        if t in (6, 8) and q.get("two_part") is not False:
            problems.append(f"{qid}: ⑥, ⑧ 은 답이 하나인 질문(two_part false)에만 만든다")
        if t == 8:
            c = q.get("contrast") or {}
            other, asked = c.get("other", {}).get("value"), c.get("asked", {}).get("value")
            if not other or not value_in(other, v["answer"]) or (asked and value_in(asked, v["answer"])):
                problems.append(f"{qid}: ⑧ 은 다른 대상의 값({other})으로 답하고 묻는 대상의 값({asked})은 쓰지 않아야 한다")
        if t == 6:
            # 스펙 3-2절: 바꿔 넣은 값이 근거 청크 전문 어디에도 없어야 한다. 옛 값이나 다른 대상의 값이 근거에
            # 글자로 있으면 ⑥ 이 아니라 근거에 적힌 값으로 답한 것이 된다.
            new, old = v.get("new_value") or "", v.get("old_value") or ""
            if not isinstance(new, str) or not isinstance(old, str):
                # 35000 처럼 숫자로 적으면 value_in 의 글자 비교가 TypeError 로 멈춘다. 원인을 바로 알려 준다.
                problems.append(f"{qid}: ⑥ 의 old_value/new_value 는 따옴표로 감싼 글자로 적는다")
                continue
            if not new or not value_in(new, v["answer"]):
                problems.append(f"{qid}: ⑥ 은 바꿔 넣은 값을 new_value 에 답변의 글자 그대로 적어야 한다")
            elif any(value_in(new, s["content"]) for s in r["sources"]):
                problems.append(f"{qid}: ⑥ 의 새 값({new})이 근거 청크에 글자로 있다. 근거 어디에도 없는 값으로 바꾼다")
            # 바꾸기 전 값(old_value)이 변형 답변에 남으면 근거와 맞는 주장과 반대인 주장이 함께 있는 답변이 된다
            # ("35,000원 이상이면 무료입니다. 기존 기준은 30,000원입니다."). 1점(반대)과 3점(섞임) 사이에서 정답 점수가
            # 하나로 정해지지 않는다(스펙 3-2절의 원칙). 그래서 옛 값이 멀쩡한 답변에는 있고 변형 답변에는 없는지 본다.
            if not old or not value_in(old, q["answer"]):
                problems.append(f"{qid}: ⑥ 은 바꾸기 전 값을 old_value 에 멀쩡한 답변의 글자 그대로 적어야 한다")
            elif value_in(old, v["answer"]):
                problems.append(f"{qid}: ⑥ 의 변형 답변에 바꾸기 전 값({old})이 남아 있다. 옛 값을 답변에서 지운다")
        cid = case_id_of(q["domain"], q["question"], v["answer"])
        if cid in key:
            problems.append(f"{qid}: 다른 문항과 문항 id 가 같다({cid})")
            continue
        sources = [{"filename": s["filename"], "content": s["content"]} for s in r["sources"]]
        rows.append({"case_id": cid, "domain": q["domain"],
                     "messages": build_messages(q["question"], sources, v["answer"]),
                     "search_settings": r["settings"]})
        key[cid] = {"qid": qid, "domain": q["domain"], "type": t, "table_score": TABLE_SCORE[t]}
    if problems:
        raise ExportProblem(problems)
    # case_id 로 먼저 줄 세운 뒤 고정 시드로 섞는다. 분야나 유형 순서가 시험지 순서에 남지 않게 한다.
    rows.sort(key=lambda row: row["case_id"])
    random.Random(SEED).shuffle(rows)
    return rows, key


def load_and_build() -> tuple[list[dict], dict[str, dict]]:
    return build_cases(read_jsonl(QUESTIONS), read_jsonl(RETRIEVED),
                       assigned_types(read_json(ASSIGNMENT)), read_jsonl(VARIANTS))


def apply_review(key: dict[str, dict], reviews: list[dict]) -> tuple[dict, dict, list[str]]:
    """검수 결과를 반영한다(스펙 4절). (남긴 문항, 버린 문항, 문제 목록) 을 돌려준다.

    사용자가 판단하지 않은 불일치 문항을 조용히 버리지 않고 문제로 알린다. 버리는 것도 사용자의 판단으로
    review.jsonl 에 남아야 보고서에 버린 이유를 적을 수 있다.
    """
    by: dict[str, dict] = {}
    problems: list[str] = []
    for r in reviews:
        if r["case_id"] in by:
            problems.append(f"{r['case_id']}: 검수 줄이 두 개다")
        by[r["case_id"]] = r
    kept: dict[str, dict] = {}
    dropped: dict[str, dict] = {}
    for cid, k in sorted(key.items()):
        r = by.get(cid)
        if r is None or r.get("review_score") not in SCALE:
            problems.append(f"{cid}: 검수 점수가 없다")
            continue
        base = {**k, "review_score": r["review_score"]}   # {**a, ...} 는 a 를 복사하고 키를 더한 새 dict 다
        if r["review_score"] == k["table_score"]:
            kept[cid] = {**base, "score": k["table_score"], "decision": "match"}
            continue
        decision, reason = r.get("user_decision"), (r.get("reason") or "").strip()
        if decision == "keep" and reason:
            kept[cid] = {**base, "score": k["table_score"], "decision": "keep", "reason": reason}
        elif decision == "override" and r.get("override_score") in SCALE and reason:
            kept[cid] = {**base, "score": r["override_score"], "decision": "override", "reason": reason}
        elif decision == "drop" and reason:
            dropped[cid] = {**base, "reason": reason}
        else:
            problems.append(f"{cid}: 검수 점수({r['review_score']})와 정답 점수({k['table_score']})가 달라 "
                            f"사용자 판단(keep, override, drop)과 이유가 필요하다")
    for cid in sorted(set(by) - set(key)):
        problems.append(f"{cid}: 검수 파일에 있지만 시험지에 없는 문항이다")
    return kept, dropped, problems


def _write(rows: list[dict], doc: dict) -> str:
    write_jsonl(CASES, rows)
    sha = sha256_file(CASES)
    # 첫 줄은 시험지 해시(다른 도구는 split()[0] 으로 이 값만 읽는다), 둘째 줄은 공통 지시문 해시(앞 실험과 같다).
    CASES_SHA.write_text(f"{sha}  cases.jsonl\n{prompt_sha256()}  prompt\n", encoding="utf-8")
    write_json(ANSWER_KEY, {**doc, "cases_sha256": sha, "prompt_sha256": prompt_sha256()})
    return sha


def cmd_draft() -> int:
    # 동결(E11) 뒤에 draft 를 다시 만들면 최종 시험지와 정답 파일을 검수 전 판으로 덮는다. M1 채점 도구는 단계를
    # 보지 않고 같은 폴더의 해시만 대조하므로, 그대로 E12 를 돌리면 검수 전 시험지에 뉴런을 쓴다. 그래서 거절한다.
    if ANSWER_KEY.exists() and read_json(ANSWER_KEY).get("stage") == "final":
        print(f"{ANSWER_KEY.name} 가 이미 최종본(final)입니다. draft 로 덮지 않습니다. "
              "보충으로 다시 만들어야 하면 사용자에게 알린 뒤 final 커밋을 되돌리고 다시 실행하세요.")
        return 1
    rows, key = load_and_build()
    sha = _write(rows, {"stage": "draft", "seed": SEED, "cases": key, "dropped": {}})
    reviewed = {r["case_id"] for r in read_jsonl(REVIEW)}
    todo = sum(1 for cid in key if cid not in reviewed)
    print(f"시험지 {len(rows)}문항, SHA-256 {sha}. 검수 점수가 아직 없는 문항 {todo}개.")
    return 0


def cmd_mismatches() -> int:
    rows, key = load_and_build()
    by_id = {r["case_id"]: r for r in rows}
    notes = {v["qid"]: v.get("note", "") for v in read_jsonl(VARIANTS)}
    reviews = {r["case_id"]: r for r in read_jsonl(REVIEW)}
    out = ["# 검수 점수와 정답 점수가 다른 문항", "",
           "이 파일에는 변형 유형이 적혀 있다. 검수 세션에 주지 않는다.", ""]
    n = 0
    for cid, k in sorted(key.items()):
        r = reviews.get(cid)
        if r is None or r.get("review_score") == k["table_score"] or r.get("user_decision"):
            continue
        n += 1
        body = by_id[cid]["messages"][1]["content"]
        fence = fence_for(body)
        out += [f"## {cid}", "",
                f"- 분야 {k['domain']}, {TYPE_NAMES[k['type']]}, 대응표 점수 {k['table_score']}, 검수 점수 {r['review_score']}",
                f"- 검수 메모: {r.get('review_note', '')}",
                f"- 출제 메모: {notes.get(k['qid'], '')}", "",
                fence, body, fence, ""]
    MISMATCHES.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"사용자 판단이 필요한 문항 {n}개. 목록: {MISMATCHES}")
    return 0


def cmd_final() -> int:
    rows, key = load_and_build()
    kept, dropped, problems = apply_review(key, read_jsonl(REVIEW))
    if problems:
        print("최종 시험지를 만들지 않았습니다.")
        for p in problems[:20]:
            print(f"  - {p}")
        return 1
    rows = [r for r in rows if r["case_id"] in kept]   # 섞인 순서를 그대로 두고 버린 문항만 뺀다
    sha = _write(rows, {"stage": "final", "seed": SEED, "cases": kept, "dropped": dropped})
    print(f"최종 시험지 {len(rows)}문항(버린 문항 {len(dropped)}개). SHA-256: {sha}")
    print("코랩 노트북(notebooks/judge5v2_colab.ipynb)의 EXPECTED_SHA256 에 이 값을 넣으세요(계획 E11).")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="채점 모델 비교 v2 의 시험지 파일과 정답 파일을 만든다")
    p.add_argument("cmd", choices=("draft", "mismatches", "final"))
    args = p.parse_args(argv)
    try:
        return {"draft": cmd_draft, "mismatches": cmd_mismatches, "final": cmd_final}[args.cmd]()
    except ExportProblem as e:
        print("시험지를 만들지 않았습니다. 아래를 고친 뒤 다시 실행하세요.")
        for p_ in e.problems[:30]:
            print(f"  - {p_}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
