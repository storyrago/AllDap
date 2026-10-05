"""새 시험지와 학습 데이터를 만든다(스펙 4절, 5절).

실행:
    cd ai-service
    $PY -m tools.judgeft_export test draft        # 검수 전 새 시험지와 정답 파일
    $PY -m tools.judgeft_export test mismatches   # 검수 점수와 정답 점수가 다른 문항 목록(사용자 판단용)
    $PY -m tools.judgeft_export test final        # 검수를 반영한 최종 새 시험지
    # 검수 뒤 조건을 채우지 못해 보충했을 때(계획 E9 Step 4). 이 순서대로 한다.
    $PY -m tools.judgeft_export test draft --after-supplement    # 보충 회차의 문항을 더한 검수 전 시험지
    $PY -m tools.judgeft_export test pending --out <저장소 밖 폴더>/cases.jsonl   # 아직 검수하지 않은 문항만
    $PY -m tools.judgeft_export test append-review <검수 결과 파일>             # review.jsonl 에 덧붙인다
    $PY -m tools.judgeft_export train             # 학습 데이터(학습 묶음, 검증 묶음). 글자 확인과 누출 확인을 함께 한다

새 시험지는 v2 와 같은 모양이라 v2 의 build_cases(⑥, ⑧ 의 글자 확인 포함), apply_review, fence_for 를 그대로 쓴다.
시험지를 섞는 시드도 v2 의 build_cases 안의 값(20261005)을 그대로 쓴다. 섞는 순서는 결과에 영향이 없고,
v2 함수를 고치지 않으려는 것이다.
"""
from __future__ import annotations

import argparse
import random
import re
import sys
from collections import Counter
from pathlib import Path

from .judge5 import RULES_V2, build_messages, parse_result, prompt_sha256, sha256_file
from .judge5v2_export import ExportProblem, apply_review, build_cases, case_id_of, fence_for
from .judgeft_assign import assigned
from .judgeft_files import (
    ANSWER_KEY, ASSIGNMENT, CASES, CASES_SHA, CORPUS, FORBIDDEN_VALUES, GATE_A, MISMATCHES, QUESTIONS, RETRIEVED,
    PAIRS, REVIEW, ROOT, SEED, TABLE_SCORE, TEMPLATES, TRAIN_QUOTA, V2_CORPUS_DIRS, fields_doc, value_in,
    TRAIN, TRAIN_DROPPED, TRAIN_SHA, TYPE_NAMES, V2_CASES, VAL, VAL_FRACTION, VARIANTS, latest_by_qid, read_json,
    read_jsonl, write_json, write_jsonl,
)
from .judgeft_rationale import load_templates, record_problems, render, template_problems

MIN_LEAK_LEN = 20   # 이보다 짧은 근거 청크와 문장은 누출 확인에서 뺀다. "## 요금" 같은 제목이 우연히 겹칠 수 있다.
# 문장 경계: 마침표, 물음표, 느낌표 뒤의 공백, 또는 줄바꿈. (?<=...) 는 "바로 앞이 이 글자일 때" 만 맞는 조건이라
# 마침표 자체는 앞 문장에 남는다.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def _inputs() -> tuple[list[dict], list[dict], dict, list[dict]]:
    return read_jsonl(QUESTIONS), read_jsonl(RETRIEVED), read_json(ASSIGNMENT), read_jsonl(VARIANTS)


def build_test() -> tuple[list[dict], dict[str, dict]]:
    """새 시험지와 정답 키. 정답 키에는 v2 의 칸에 two_targets(대상이 둘인 질문인가)를 더한다(스펙 4-4절, 8-2절)."""
    questions, retrieved, assignment, variants = _inputs()
    types = assigned(assignment, "test")[0]
    rows, key = build_cases(questions, retrieved, types, variants)
    by = {q["qid"]: q for q in questions}
    for k in key.values():
        k["two_targets"] = by[k["qid"]].get("contrast") is not None
    return rows, key


def _write_test(rows: list[dict], doc: dict) -> str:
    write_jsonl(CASES, rows)
    sha = sha256_file(CASES)
    CASES_SHA.write_text(f"{sha}  cases.jsonl\n{prompt_sha256()}  prompt\n", encoding="utf-8")
    write_json(ANSWER_KEY, {**doc, "cases_sha256": sha, "prompt_sha256": prompt_sha256()})
    return sha


def kept_test() -> tuple[dict[str, int], set[str], set[str]]:
    """최종 새 시험지에 남은 (질문마다 유형, 빈 집합, 대상이 둘인 ①② 질문). 배정 도구의 보충이 쓴다."""
    ak = read_json(ANSWER_KEY)
    if ak.get("stage") != "final":
        raise ValueError("새 시험지의 보충은 test final 뒤에 한다(검수 결과가 반영돼야 남은 문항을 안다)")
    types = {k["qid"]: k["type"] for k in ak["cases"].values()}
    five = {k["qid"] for k in ak["cases"].values() if k["type"] in (1, 2) and k["two_targets"]}
    return types, set(), five


def pending_rows(rows: list[dict], reviews: list[dict]) -> list[dict]:
    """아직 검수 줄이 없는 문항. 보충 뒤에는 새 회차의 문항만 남는다(앞 회차의 문항은 이미 검수 줄이 있다)."""
    done = {r["case_id"] for r in reviews}
    return [r for r in rows if r["case_id"] not in done]


def merge_reviews(existing: list[dict], new: list[dict], pending_ids: set[str]) -> tuple[list[dict], list[str]]:
    """새 검수 결과를 기존 review.jsonl 뒤에 붙인다. (합친 목록, 문제 목록). 문제가 있으면 합친 목록을 쓰지 않는다.

    이미 검수한 문항을 다시 검수한 줄이 섞이면 apply_review 가 "검수 줄이 두 개다" 로 멈추므로 여기서 먼저 막는다.
    """
    problems = []
    seen: set[str] = set()
    for r in new:
        cid = r.get("case_id")
        if cid in seen:
            problems.append(f"{cid}: 새 검수 결과에 같은 문항이 두 번 있다")
        elif cid not in pending_ids:
            problems.append(f"{cid}: 검수할 문항(pending)이 아니다. 이미 검수했거나 시험지에 없다")
        seen.add(cid)
    if missing := sorted(pending_ids - seen):
        problems.append(f"검수 결과에 없는 문항 {len(missing)}개: {', '.join(missing[:5])}")
    return existing + new, problems


def _in_repo(path: Path) -> bool:
    """검수 폴더가 저장소 안이면 검수 세션이 변형 유형이 적힌 파일을 볼 수 있다(v2 계획 E8)."""
    return path.resolve().is_relative_to(ROOT.parent.resolve())


def cmd_test(stage: str, after_supplement: bool = False, path: str | None = None) -> int:
    final_now = ANSWER_KEY.exists() and read_json(ANSWER_KEY).get("stage") == "final"
    if stage == "draft" and final_now and not after_supplement:
        print("정답 파일이 이미 최종본입니다. draft 로 덮지 않습니다(v2 와 같은 이유: 검수 전 시험지로 모델을 돌리게 된다). "
              "보충 회차를 더한 것이면 --after-supplement 를 붙입니다(계획 E9 Step 4).")
        return 1
    if stage == "draft" and after_supplement and GATE_A.exists():
        print("관문 (a) 의 결과(gate_a.json)가 이미 있습니다. 모델이 돈 뒤에는 새 시험지를 바꾸지 않습니다(스펙 6-5절).")
        return 1
    try:
        rows, key = build_test()
    except ExportProblem as e:
        print("새 시험지를 만들지 않았습니다.\n  - " + "\n  - ".join(e.problems[:20]))
        return 1
    reviews = read_jsonl(REVIEW) if REVIEW.exists() else []
    if stage == "draft":
        if after_supplement and not pending_rows(rows, reviews):
            print("검수하지 않은 새 문항이 없습니다. 보충 회차(judgeft_assign supplement test)와 변형 답변을 먼저 씁니다.")
            return 1
        sha = _write_test(rows, {"stage": "draft", "seed": SEED, "cases": key, "dropped": {}})
        print(f"새 시험지 {len(rows)}문항(검수하지 않은 문항 {len(pending_rows(rows, reviews))}개), SHA-256 {sha}")
        return 0
    if stage == "pending":
        out = Path(path or "")
        if not path or _in_repo(out):
            print("--out 에 저장소 밖의 새 폴더 안 경로를 줍니다(검수 세션이 저장소의 파일을 보지 않게 한다).")
            return 1
        todo = pending_rows(rows, reviews)
        out.parent.mkdir(parents=True, exist_ok=True)
        write_jsonl(out, todo)
        print(f"검수할 문항 {len(todo)}개: {out}")
        return 0
    if stage == "append-review":
        new = read_jsonl(Path(path or ""))
        merged, problems = merge_reviews(reviews, new, {r["case_id"] for r in pending_rows(rows, reviews)})
        if problems:
            print("review.jsonl 에 덧붙이지 않았습니다.\n  - " + "\n  - ".join(problems[:20]))
            return 1
        write_jsonl(REVIEW, merged)
        print(f"review.jsonl 에 {len(new)}줄을 덧붙였습니다(모두 {len(merged)}줄).")
        return 0
    if stage == "mismatches":
        reviews = {r["case_id"]: r for r in reviews}
        notes = {v["qid"]: v.get("note", "") for v in read_jsonl(VARIANTS)}
        body_of = {r["case_id"]: r["messages"][1]["content"] for r in rows}
        out = ["# 검수 점수와 정답 점수가 다른 문항", "", "이 파일에는 변형 유형이 적혀 있다. 검수 세션에 주지 않는다.", ""]
        n = 0
        for cid, k in sorted(key.items()):
            r = reviews.get(cid)
            if r is None or r.get("review_score") == k["table_score"] or r.get("user_decision"):
                continue
            n += 1
            fence = fence_for(body_of[cid])
            out += [f"## {cid}", "", f"- 분야 {k['domain']}, {TYPE_NAMES[k['type']]}, 대응표 점수 {k['table_score']}, "
                    f"검수 점수 {r['review_score']}", f"- 검수 메모: {r.get('review_note', '')}",
                    f"- 출제 메모: {notes.get(k['qid'], '')}", "", fence, body_of[cid], fence, ""]
        MISMATCHES.write_text("\n".join(out) + "\n", encoding="utf-8")
        print(f"사용자 판단이 필요한 문항 {n}개: {MISMATCHES}")
        return 0
    kept, dropped, problems = apply_review(key, reviews)
    if problems:
        print("최종 새 시험지를 만들지 않았습니다.\n  - " + "\n  - ".join(problems[:20]))
        return 1
    rows = [r for r in rows if r["case_id"] in kept]
    sha = _write_test(rows, {"stage": "final", "seed": SEED, "cases": kept, "dropped": dropped})
    print(f"최종 새 시험지 {len(rows)}문항(버린 문항 {len(dropped)}개). SHA-256 {sha}")
    return 0


def build_train(questions: list[dict], retrieved: list[dict], assignment: dict, variants: list[dict],
                templates: dict) -> tuple[list[dict], dict[str, dict[str, list[str]]]]:
    """학습 문항 목록과 뺀 문항. 스펙 5-2절의 네 확인을 문항마다 하고, 하나라도 어긋나면 그 문항만 뺀다.

    v2 의 build_cases 는 문제가 하나라도 있으면 전체를 멈춘다. 학습 데이터는 어긋난 문항만 빼야 하므로(스펙 5-2절)
    질문 하나씩 build_cases 에 넣어 그 질문의 문제만 받는다. 확인 2, 3(⑥, ⑧ 의 글자)은 build_cases 안에 있다.
    """
    # 같은 질문의 변형 줄이 둘이면 dict 로 만들 때 뒤의 줄이 조용히 앞의 줄을 덮는다. 어느 쪽이 맞는지는 출제
    # 세션만 아므로 멈춘다. Counter 는 값마다 몇 번 나왔는지 센다.
    if dups := sorted(q for q, n in Counter(v["qid"] for v in variants).items() if n > 1):
        raise ValueError(f"variants.jsonl 에 같은 질문의 줄이 여러 개다: {', '.join(dups[:10])}. 하나만 남긴다")
    types, pairs, _ = assigned(assignment, "train")
    q_by = {q["qid"]: q for q in questions}
    r_by = {r["qid"]: r for r in latest_by_qid(retrieved)}
    v_by = {v["qid"]: v for v in variants}
    items: list[dict] = []
    dropped: dict[str, dict[str, list[str]]] = {"main": {}, "pair": {}}
    for qid, t in sorted(types.items()):
        q, r, v = q_by.get(qid), r_by.get(qid), v_by.get(qid)
        try:
            build_cases([q] if q else [], [r] if r else [], {qid: t}, [v] if v else [])   # 확인 2, 3
        except ExportProblem as e:
            dropped["main"][qid] = e.problems
            continue
        if bad := record_problems(t, v, q, r["sources"]):                                 # 확인 1
            dropped["main"][qid] = bad
            continue
        items.append(_item(q, r, v["answer"], t, v, "main", templates))
    kept_main = {i["qid"] for i in items}
    for qid in sorted(pairs):
        if qid not in kept_main:
            dropped["pair"][qid] = ["짝의 ⑧ 문항이 빠져서 짝도 뺀다"]
            continue
        q, r, v = q_by[qid], r_by[qid], v_by[qid]
        # 짝 문항은 멀쩡한 답변이 질문 대상의 값을 그대로 말해야 5점이다. 값이 없으면 ⑧ 과 짝이 대조가 되지 않는다.
        if not value_in(q["contrast"]["asked"]["value"], q["answer"]):
            dropped["pair"][qid] = ["멀쩡한 답변에 질문 대상의 값(contrast.asked.value)이 없다"]
            continue
        items.append(_item(q, r, q["answer"], 1, {"target": v["target"], "evidence": v["evidence"]}, "pair", templates))
    for it in list(items):                                                                 # 확인 4
        if parse_result(it["target"], "stop", rules=RULES_V2) != (it["score"], "ok"):
            items.remove(it)
            dropped[it["kind"]][it["qid"]] = ["모범 답안을 읽으면 정답 점수가 나오지 않는다"]
    return items, dropped


def _item(q: dict, r: dict, answer: str, t: int, rec: dict, kind: str, templates: dict) -> dict:
    sources = [{"filename": s["filename"], "content": s["content"]} for s in r["sources"]]
    item_id = case_id_of(q["domain"], q["question"], answer)
    return {"id": item_id, "qid": q["qid"], "domain": q["domain"], "kind": kind, "type": t,
            "score": TABLE_SCORE[t], "messages": build_messages(q["question"], sources, answer),
            "target": render(t, rec, q, item_id, templates)}


def split_val(items: list[dict], seed: int = SEED) -> tuple[list[dict], list[dict]]:
    """질문 단위로 약 10% 를 검증 묶음으로 뗀다. 같은 질문의 ⑧ 과 짝은 같은 쪽에 간다(스펙 6-3절).
    학습 묶음은 id 로 줄 세운 뒤 고정 시드로 섞는다. 같은 입력이면 같은 파일(같은 해시)이 나온다."""
    qids = sorted({i["qid"] for i in items})
    val_q = set(random.Random(f"{seed}:val").sample(qids, round(VAL_FRACTION * len(qids))))
    train = sorted((i for i in items if i["qid"] not in val_q), key=lambda i: i["id"])
    val = sorted((i for i in items if i["qid"] in val_q), key=lambda i: i["id"])
    random.Random(f"{seed}:train-order").shuffle(train)
    return train, val


def leak_problems(items: list[dict], questions: list[dict], retrieved: list[dict], test_texts: list[str]) -> list[str]:
    """스펙 5-3절의 확인 1, 2. 학습 문항의 질문, 근거 청크 본문, 모범 답안이 시험지의 입력 글에 나오지 않는가.
    test_texts 는 새 시험지와 동결 시험지의 user 메시지 전체다. 확인 3(틀의 한글)은 template_problems 가 본다."""
    q_by = {q["qid"]: q for q in questions}
    r_by = {r["qid"]: r for r in latest_by_qid(retrieved)}
    blob = "\n".join(test_texts)
    out = []
    for it in items:
        q, r = q_by[it["qid"]], r_by[it["qid"]]
        pieces = [("질문", q["question"]), ("모범 답안", it["target"])]
        pieces += [("근거 청크", s["content"]) for s in r["sources"] if len(s["content"]) >= MIN_LEAK_LEN]
        for name, text in pieces:
            if text in blob:
                out.append(f"{it['qid']}({it['kind']}): 학습 문항의 {name}이 시험지에 나온다")
    return out


def sentences(text: str, template: str) -> set[str]:
    """20자 이상 문장. 공통 지시문(template)에 들어 있는 문장은 뺀다. 모든 문항이 같은 지시문을 쓰므로 겹쳐도 누출이 아니다."""
    out = set()
    for s in _SENTENCE_SPLIT.split(text):
        s = s.strip()
        if len(s) >= MIN_LEAK_LEN and s not in template:
            out.add(s)
    return out


def overlap_problems(train: dict[str, str], test: dict[str, str], template: str) -> list[str]:
    """학습 쪽 글과 시험 쪽 글을 문장 단위로 양쪽에서 대조한다. 이름마다 한 줄만 낸다.

    leak_problems 는 학습 문항의 글 전체가 시험지에 들어 있는지만 본다. 문서의 한 문장만 옮겨 쓴 경우나
    시험 쪽 글이 학습 쪽에 들어간 경우는 놓친다. 그래서 문장으로 잘라 두 방향을 모두 본다.
    """
    out = []
    for name_a, side_a, side_b, where in (("학습", train, test, "시험"), ("시험", test, train, "학습")):
        blob = "\n".join(side_b.values())
        for name, text in side_a.items():
            if hit := next((s for s in sorted(sentences(text, template)) if s in blob), None):
                out.append(f"{name_a} 쪽 {name} 의 문장이 {where} 쪽에 나온다: {hit[:40]}")
    return out


def forbidden_problems(texts: dict[str, str]) -> list[str]:
    """스펙 4-5절의 금지 값(FORBIDDEN_VALUES)이 학습 데이터, 문장 틀, 노트북에 없는가."""
    return [f"{name}: 금지 값 {v!r} 가 있다(스펙 4-5절)" for name, text in texts.items() for v in FORBIDDEN_VALUES
            if v in text]


def _corpus_texts(dirs: list[Path]) -> dict[str, str]:
    return {f"문서 {p.parent.name}/{p.name}": p.read_text(encoding="utf-8")
            for d in dirs for p in sorted(d.glob("*.md"))}


def overlap_sides(items: list[dict], questions: list[dict], retrieved: list[dict]) -> tuple[dict, dict]:
    """(학습 쪽, 시험 쪽). 학습 쪽은 학습용 분야의 문서와 학습 문항, 시험 쪽은 시험용 분야와 v2 의 문서와 두 시험지다."""
    doc = fields_doc()
    q_by = {q["qid"]: q for q in questions}
    r_by = {r["qid"]: r for r in latest_by_qid(retrieved)}
    train = _corpus_texts([CORPUS / f for f in doc["train"]])
    for it in items:
        train[f"학습 문항 {it['id']}({it['qid']})"] = "\n".join(
            [q_by[it["qid"]]["question"], it["target"]] + [s["content"] for s in r_by[it["qid"]]["sources"]])
    test = _corpus_texts([CORPUS / f for f in doc["test"]] + list(V2_CORPUS_DIRS.values()))
    test["시험지"] = "\n".join(test_texts())
    return train, test


def test_texts() -> list[str]:
    """새 시험지(최종본)와 동결 시험지의 user 메시지. 시험지 파일이 없으면 멈춘다."""
    if not CASES.exists() or read_json(ANSWER_KEY).get("stage") != "final":
        raise SystemExit("새 시험지 최종본이 없습니다. 누출 확인은 test final 뒤에 합니다(계획 E10).")
    return [m["content"] for path in (CASES, V2_CASES) for row in read_jsonl(path)
            for m in row["messages"] if m["role"] == "user"]


def kept_train() -> tuple[dict[str, int], set[str], set[str]]:
    """학습 데이터에 남은 (⑧ 등 본 문항의 질문마다 유형, 짝 문항 질문, 빈 집합). 배정 도구의 보충이 쓴다."""
    items = read_jsonl(TRAIN) + read_jsonl(VAL)
    if not items:
        raise ValueError("학습 데이터가 아직 없다. 먼저 `judgeft_export train` 을 한다")
    return ({i["qid"]: i["type"] for i in items if i["kind"] == "main"},
            {i["qid"] for i in items if i["kind"] == "pair"}, set())


def train_short(items: list[dict]) -> dict[str, int]:
    """할당량(스펙 4-4절)에 모자란 수. {유형 번호 문자열 또는 "pairs": 모자란 수}. 빈 dict 면 할당량을 다 채웠다."""
    have = Counter(i["type"] for i in items if i["kind"] == "main")
    short = {str(t): n - have[t] for t, n in TRAIN_QUOTA.items() if have[t] < n}
    if (n_pairs := sum(1 for i in items if i["kind"] == "pair")) < PAIRS:
        short["pairs"] = PAIRS - n_pairs
    return short


def cmd_train() -> int:
    templates = load_templates()
    if bad := template_problems(templates):
        print("문장 틀 파일이 규칙과 다릅니다.\n  - " + "\n  - ".join(bad))
        return 1
    questions, retrieved, assignment, variants = _inputs()
    try:
        items, dropped = build_train(questions, retrieved, assignment, variants, templates)
    except ValueError as e:
        print(f"학습 데이터를 만들지 않았습니다. {e}")
        return 1
    template = "\n".join(m["content"] for m in build_messages("", [], ""))
    leaks = leak_problems(items, questions, retrieved, test_texts())
    leaks += overlap_problems(*overlap_sides(items, questions, retrieved), template)
    leaks += forbidden_problems({f"학습 문항 {i['id']}": i["target"] + "".join(m["content"] for m in i["messages"])
                                 for i in items} | {"문장 틀": TEMPLATES.read_text(encoding="utf-8")})
    if leaks:
        print("학습 데이터가 시험지와 겹치거나 금지 값이 있습니다. 학습하지 않고 사용자에게 보입니다(스펙 5-3절).\n  - "
              + "\n  - ".join(leaks[:20]))
        return 1
    train, val = split_val(items)
    write_jsonl(TRAIN, train)
    write_jsonl(VAL, val)
    write_json(TRAIN_DROPPED, dropped)
    TRAIN_SHA.write_text("".join(f"{sha256_file(p)}  {p.name}\n" for p in (TRAIN, VAL, TEMPLATES))
                         + f"{prompt_sha256()}  prompt\n", encoding="utf-8")
    n_drop = sum(len(v) for v in dropped.values())
    print(f"학습 묶음 {len(train)}문항, 검증 묶음 {len(val)}문항, 뺀 문항 {n_drop}개"
          f"(본 문항 {len(dropped['main'])}, 짝 {len(dropped['pair'])})")
    # 종료 코드는 뺀 문항이 있었는가가 아니라 남은 문항이 할당량에 닿았는가로 정한다. 앞 회차에서 빠진
    # 문항은 train_dropped.json 에 계속 남으므로, 보충으로 채운 뒤에도 "뺀 문항 n개" 는 0 이 되지 않는다.
    if short := train_short(items):
        print(f"할당량에 모자랍니다: {short}. `judgeft_assign supplement train` 으로 채운 뒤 출제 세션이 변형 답변을 쓰고 "
              "이 명령을 다시 한다.")
        return 2
    if n_drop:
        print("뺀 문항은 보충 회차로 이미 채웠습니다. 할당량을 모두 채웠습니다.")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="새 시험지와 학습 데이터를 만든다")
    p.add_argument("what", choices=("test", "train"))
    p.add_argument("stage", nargs="?", choices=("draft", "mismatches", "final", "pending", "append-review"))
    p.add_argument("path", nargs="?", help="append-review 의 검수 결과 파일")
    p.add_argument("--after-supplement", action="store_true", help="보충 회차를 더해 draft 를 다시 만든다")
    p.add_argument("--out", help="pending 이 쓸 파일(저장소 밖)")
    args = p.parse_args(argv)
    if args.what == "train":
        return cmd_train()
    if args.stage is None:
        print("test 에는 draft, mismatches, final, pending, append-review 중 하나를 준다.")
        return 1
    # argparse 는 --after-supplement 를 after_supplement 로 바꿔 담는다(- 는 이름에 쓸 수 없어서).
    return cmd_test(args.stage, args.after_supplement, args.out if args.stage == "pending" else args.path)


if __name__ == "__main__":
    sys.exit(main())
