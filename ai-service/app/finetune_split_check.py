"""리랭커 파인튜닝 실험의 누출 검사. CI 에서 돈다.

실행:
    cd ai-service && .venv/bin/python -m app.finetune_split_check
    cd ai-service && .venv/bin/python -m app.finetune_split_check --show-chunks 50_부설연구소_별도규정.md

설계: docs/superpowers/specs/2026-10-01-reranker-finetune-design.md §8

무엇을 막는가
─────────────────────────────────────────────────────────────────────────────
파인튜닝 전후 비교가 뜻을 가지려면 시험 문제의 답을 학습 때 보지 않았어야 한다.
이 검사는 파일끼리의 관계(어느 문서가 어느 쪽인가, 어느 청크가 학습 데이터에 나오는가)만
본다. DB 와 외부 API 를 쓰지 않으므로 CI 에서 돈다. 이 검사가 있어야 "학습 때 시험 문제를
본 것 아닌가" 라는 질문에 "CI 가 매번 확인한다" 고 답할 수 있다.

번호는 스펙 §8 의 번호다.
  1. 시험용 문서와 학습용 문서가 겹치지 않는다
  2. 시험, 예비 시험 문제의 정답 청크(와 쌍둥이 청크)가 학습 데이터에 나오지 않는다
  3. 쌍둥이 청크의 두 문서가 다른 쪽으로 갈리지 않았다
  4. 취업규칙, 휴가규정을 정답 문서로 쓰지 않았다
  5. 문제의 정답 문서가 그 문제 종류의 쪽에 있다
  6. train_pairs.jsonl 의 해시가 노트북에 적힌 값과 같다
  7. 연습, 예비 시험 문제의 질문에 시험용 대상 낱말이 없다

파일이 아직 없으면 그 항목은 건너뛰고 건너뛰었다고 출력한다. 단 split.json 과
twins.json 은 검사의 기준이라 없으면 실패한다(스펙 §8 마지막 문단).

먼저 자기 점검을 돈다
─────────────────────────────────────────────────────────────────────────────
규칙 함수마다 일부러 틀린 작은 입력을 넣어 위반을 잡는지 확인한 뒤에 실제 파일을 본다.
실제 파일이 깨끗하면 규칙이 아무것도 못 잡는 상태여도 초록불이 나기 때문이다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Callable
from functools import cache
from pathlib import Path

from .chunker import chunk_text
from .parsers import extract_text

# __file__ 은 app/finetune_split_check.py 이므로 두 번 올라가면 ai-service/ 다.
# 실행 위치(cwd)와 무관하게 같은 파일을 가리키려고 __file__ 기준으로 잡는다.
ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = ROOT / "testdata" / "corpus"
FT_DIR = ROOT / "testdata" / "finetune"
SPLIT_FILE = FT_DIR / "split.json"
TWINS_FILE = FT_DIR / "twins.json"
PAIRS_FILE = FT_DIR / "train_pairs.jsonl"
NOTEBOOK_FILE = ROOT / "notebooks" / "train_reranker.ipynb"
QUESTION_FILES = {
    "train": FT_DIR / "train_questions.json",
    "test": FT_DIR / "test_questions.json",
    "holdout": FT_DIR / "holdout_questions.json",
}

# 업로드할 때와 같은 청킹 설정. 문제 파일과 twins.json 도 이 값이어야 한다.
CHUNKING = {"chunk_size": 500, "chunk_overlap": 50, "chunk_split_headings": True}
EXPECTED_SIDE_COUNTS = {"train": 36, "test": 20}
EXPECTED_TWIN_PAIRS = 27
# 문제 종류 → 정답 문서가 있어야 하는 쪽. 예비 시험 문제는 학습용 문서에서 뽑는다(스펙 §0).
QUESTION_SIDE = {"train": "train", "holdout": "train", "test": "test"}
FORBIDDEN_GOLD_DOCS = ("취업규칙.md", "휴가규정.md")
# (문서, 청크 번호, 이 청크를 정답으로 쓰면 안 되는 문제 종류). 스펙 §4-4 규칙 10.
# 08 의 4번 청크는 "직장 내 괴롭힘", 34 의 5번 청크는 "불이익 금지" 다(2026-10-01 확인).
FORBIDDEN_GOLD_CHUNKS = (
    ("08_징계_및_고충처리.md", 4, ("train", "holdout")),
    ("34_직장내괴롭힘_예방.md", 5, ("test",)),
)
# 스펙 §8 7번의 낱말 그대로다. "지사" 는 "공지사항" 에도 걸린다. 걸리면 질문을 다르게 쓴다
# (낱말을 목록에서 빼지 않는다. 빼면 "지사 직원" 같은 질문이 통과한다).
TEST_TARGET_WORDS = (
    "파견", "연구직", "연구소", "해외지사", "지사", "자회사",
    "시간제", "재택근무 전담", "촉탁", "현장실습", "주재원",
)
STYLES = ("polite", "casual", "keyword", "situation", "typo")
REQUIRED_QUESTION_FIELDS = ("id", "question", "ground_truth", "source_doc", "source_text", "style")
# 노트북 코드 칸에서 해시를 찾는 정규식. ([0-9a-f]{64}) 는 SHA-256 16진수 64자리를 꺼낸다.
_SHA_RE = re.compile(r'EXPECTED_SHA256\s*=\s*"([0-9a-f]{64})"')

# 타입 별칭. "문서 이름을 받아 청크 본문 목록(없으면 None)을 돌려주는 함수" 라는 뜻이다.
# 규칙 함수가 코퍼스를 직접 읽지 않고 이 함수를 받게 하면, 자기 점검에서 가짜 코퍼스를 넣을 수 있다.
ChunksOf = Callable[[str], "list[str] | None"]


@cache  # 같은 문서를 여러 문항이 가리키므로 한 번만 자른다. functools.cache 는 인자별로 결과를 기억한다.
def _corpus_chunks(name: str) -> tuple[str, ...] | None:
    path = CORPUS_DIR / name
    if not path.is_file():
        return None
    # 업로드 경로(app/main.py)와 같게 extract_text → chunk_text 순서로 자른다.
    # Path.read_text 로 바로 읽으면 정규화 한 겹이 빠져 실제 청크와 갈린다(eval_set_check 와 같은 이유).
    _, text = extract_text(name, path.read_bytes())
    chunks = chunk_text(
        text,
        size=CHUNKING["chunk_size"],
        overlap=CHUNKING["chunk_overlap"],
        split_headings=CHUNKING["chunk_split_headings"],
    )
    return tuple(c.content for c in chunks)  # tuple 은 바꿀 수 없어 캐시된 값을 누가 고칠 수 없다


def chunks_of(name: str) -> list[str] | None:
    got = _corpus_chunks(name)
    return list(got) if got is not None else None


# ─────────────────────────────────────────────────────────────────────────────
# 규칙 함수. 전부 위반 메시지 목록을 돌려준다(빈 목록 = 통과).
# ─────────────────────────────────────────────────────────────────────────────

def side_of(split: dict) -> dict[str, str]:
    """split.json → {문서: 쪽}. 같은 문서가 두 번 있으면 처음 것을 쓴다(중복은 check_split 이 잡는다)."""
    out: dict[str, str] = {}
    for d in split.get("documents") or []:
        out.setdefault(d.get("file"), d.get("side"))
    return out


def check_split(split: dict, corpus_files: set[str]) -> list[str]:
    """스펙 §8 1번 + 코퍼스 전체가 정확히 한 번씩 나오는가."""
    docs = split.get("documents")
    if not isinstance(docs, list):
        return ["split.json 에 documents 배열이 없습니다."]
    errors: list[str] = []
    seen: dict[str, str] = {}
    for d in docs:
        f, side, reason = d.get("file"), d.get("side"), d.get("reason")
        if side not in ("train", "test"):
            errors.append(f"{f}: side 는 train 또는 test 여야 합니다 (지금: {side!r}).")
        if not isinstance(reason, str) or not reason.strip():
            errors.append(f"{f}: reason 이 비어 있습니다. 왜 그쪽인지 적어주세요.")
        if f in seen:
            errors.append(f"{f}: 두 번 나옵니다 ({seen[f]}, {side}). 한 문서는 한쪽에만 있어야 합니다.")
        seen.setdefault(f, side)
    for f in sorted(corpus_files - set(seen)):
        errors.append(f"{f}: 코퍼스에 있는데 split.json 에 없습니다.")
    for f in sorted(set(seen) - corpus_files):
        errors.append(f"{f}: split.json 에 있는데 코퍼스에 없습니다.")
    counts = {s: sum(1 for v in seen.values() if v == s) for s in EXPECTED_SIDE_COUNTS}
    if counts != EXPECTED_SIDE_COUNTS:
        errors.append(f"쪽별 문서 수가 {counts} 입니다. 스펙 §2-6 의 {EXPECTED_SIDE_COUNTS} 와 다릅니다.")
    return errors


def check_twins(twins: dict, chunks: ChunksOf, sides: dict[str, str]) -> list[str]:
    """twins.json 의 본문이 실제 청크인가 + 스펙 §8 3번(쌍둥이 청크가 경계를 넘지 않는다)."""
    pairs = twins.get("pairs") or []
    errors: list[str] = []
    if len(pairs) != EXPECTED_TWIN_PAIRS:
        errors.append(f"쌍둥이 청크가 {len(pairs)}쌍입니다. 감사 문서의 {EXPECTED_TWIN_PAIRS}쌍이어야 합니다.")
    for p in pairs:
        pid = p.get("id")
        for key in ("a", "b"):
            c = p.get(key) or {}
            doc, idx, text = c.get("doc"), c.get("index"), c.get("text")
            got = chunks(doc) if isinstance(doc, str) else None
            if got is None:
                errors.append(f"쌍 {pid}{key}: 문서 {doc} 가 코퍼스에 없습니다.")
            elif not isinstance(idx, int) or not 0 <= idx < len(got) or got[idx] != text:
                errors.append(f"쌍 {pid}{key}: {doc} 의 {idx}번 청크 본문과 다릅니다. "
                              "코퍼스나 청킹 설정이 바뀌었는지 확인해주세요.")
        da = (p.get("a") or {}).get("doc")
        db = (p.get("b") or {}).get("doc")
        if da in sides and db in sides and sides[da] != sides[db]:
            errors.append(f"쌍 {pid}: {da}({sides[da]}) 와 {db}({sides[db]}) 가 다른 쪽입니다. "
                          "쌍둥이 청크가 경계를 넘으면 시험 답을 학습에서 본 것과 같습니다.")
    return errors


def twin_texts(text: str, twins: dict) -> set[str]:
    """그 본문과 쌍을 이루는 청크 본문들. 직접 연결된 쌍만 본다.

    한 다리 건너(A~B, B~C 이면 A~C)까지 따라가지 않는 이유: 쌍둥이 청크는 같은 규정을
    거의 같은 문장으로 적은 쌍이라, A 와 C 가 직접 쌍이 아니면 감사에서 같은 규정으로
    판정되지 않은 것이다.
    """
    out: set[str] = set()
    for p in twins.get("pairs") or []:
        a, b = p["a"]["text"], p["b"]["text"]
        if text == a:
            out.add(b)
        if text == b:
            out.add(a)
    return out


def check_questions(kind: str, payload: dict, chunks: ChunksOf,
                    sides: dict[str, str], twins: dict) -> list[str]:
    """문제 파일 하나. 스펙 §8 4번, 5번, 7번 + §4-4 규칙 5, 8, 10."""
    errors: list[str] = []
    if payload.get("chunking") != CHUNKING:
        errors.append(f"{kind}: chunking 이 {CHUNKING} 이 아닙니다.")
    questions = payload.get("questions")
    if not isinstance(questions, list) or not questions:
        return errors + [f"{kind}: questions 가 비어 있습니다."]
    want = QUESTION_SIDE[kind]
    # 집합 내포(set comprehension). 이 문제 종류에 해당하는 (문서, 청크 번호)만 모은다.
    forbidden = {(doc, idx) for doc, idx, kinds in FORBIDDEN_GOLD_CHUNKS if kind in kinds}
    ids: set[str] = set()
    for q in questions:
        qid = q.get("id", "(id 없음)")
        blanks = [f for f in REQUIRED_QUESTION_FIELDS
                  if not isinstance(q.get(f), str) or not q[f].strip()]
        if blanks:
            errors.append(f"{kind} [{qid}]: 비어 있거나 문자열이 아닌 칸: {', '.join(blanks)}")
            continue
        if qid in ids:
            errors.append(f"{kind} [{qid}]: id 가 중복입니다.")
        ids.add(qid)
        if q["style"] not in STYLES:
            errors.append(f"{kind} [{qid}]: style {q['style']!r} 은 {STYLES} 중 하나여야 합니다.")
        doc = q["source_doc"]
        if doc in FORBIDDEN_GOLD_DOCS:
            errors.append(f"{kind} [{qid}]: {doc} 는 정답 문서로 쓰지 않습니다(스펙 §4-4 규칙 4).")
        if sides.get(doc) != want:
            errors.append(f"{kind} [{qid}]: 정답 문서 {doc} 가 {sides.get(doc)} 쪽입니다. "
                          f"{want} 쪽 문서여야 합니다(스펙 §8 5번).")
        got = chunks(doc)
        if got is None or q["source_text"] not in got:
            errors.append(f"{kind} [{qid}]: source_text 가 {doc} 의 실제 청크와 글자까지 같지 않습니다. "
                          f"`python -m app.finetune_split_check --show-chunks {doc}` 로 본문을 복사해주세요.")
            continue
        if (doc, got.index(q["source_text"])) in forbidden:
            errors.append(f"{kind} [{qid}]: 이 청크는 {kind} 문제의 정답으로 쓰지 않습니다"
                          "(08 과 34 의 경계를 넘는 모순 짝, 스펙 §4-4 규칙 10).")
        if kind != "test":
            hits = [w for w in TEST_TARGET_WORDS if w in q["question"]]
            if hits:
                errors.append(f"{kind} [{qid}]: 질문에 시험용 대상 낱말 {hits} 가 있습니다"
                              "(스펙 §4-4 규칙 7). 질문을 다르게 써주세요.")
        if kind == "holdout" and twin_texts(q["source_text"], twins):
            errors.append(f"holdout [{qid}]: 정답 청크에 쌍둥이 청크가 있습니다(스펙 §4-4 규칙 8).")
    return errors


def protected_texts(payloads: dict[str, dict], twins: dict) -> set[str]:
    """학습 데이터에 나오면 안 되는 본문: 시험, 예비 시험 문제의 정답 청크와 그 쌍둥이 청크."""
    out: set[str] = set()
    for kind in ("test", "holdout"):
        for q in (payloads.get(kind) or {}).get("questions") or []:
            text = q.get("source_text")
            if text:
                out.add(text)
                out |= twin_texts(text, twins)  # |= 는 집합에 다른 집합을 합쳐 넣는다
    return out


def check_pairs(pairs: list[dict], protected: set[str]) -> list[str]:
    """스펙 §8 2번. 정답으로도 오답 예시로도 나오면 안 된다."""
    errors: list[str] = []
    for p in pairs:
        if p.get("positive") in protected:
            errors.append(f"train_pairs [{p.get('id')}]: 정답 청크가 시험 또는 예비 시험 문제의 "
                          "정답(또는 그 쌍둥이 청크)입니다.")
        leaked = [n for n in p.get("negatives") or [] if n in protected]
        if leaked:
            errors.append(f"train_pairs [{p.get('id')}]: 오답 예시 {len(leaked)}개가 시험 또는 "
                          "예비 시험 문제의 정답(또는 그 쌍둥이 청크)입니다.")
    return errors


def _code_of(notebook: dict) -> str:
    """노트북의 코드 칸을 이어 붙인다. ipynb 의 source 는 문자열일 수도, 줄 목록일 수도 있다."""
    parts = []
    for cell in notebook.get("cells") or []:
        if cell.get("cell_type") != "code":
            continue
        src = cell.get("source") or ""
        parts.append("".join(src) if isinstance(src, list) else src)
    return "\n".join(parts)


def check_notebook_hash(pairs_bytes: bytes, notebook: dict) -> list[str]:
    """스펙 §8 6번."""
    m = _SHA_RE.search(_code_of(notebook))
    if not m:
        return ['노트북 코드에 EXPECTED_SHA256 = "<64자리>" 줄이 없습니다.']
    actual = hashlib.sha256(pairs_bytes).hexdigest()
    if m.group(1) != actual:
        return [f"노트북의 해시({m.group(1)[:12]}...)와 train_pairs.jsonl 의 해시({actual[:12]}...)가 "
                "다릅니다. 학습 데이터를 다시 만들었다면 노트북의 EXPECTED_SHA256 도 고쳐주세요."]
    return []


# ─────────────────────────────────────────────────────────────────────────────
# 자기 점검: 규칙마다 틀린 입력을 넣어 잡는지 본다.
# ─────────────────────────────────────────────────────────────────────────────

def _self_test() -> list[str]:
    """잡아야 할 것을 못 잡은 규칙의 설명 목록(빈 목록 = 전부 잡았다)."""
    fake = {
        "a.md": ["# A", "## 재택\n주 2회"],
        "b.md": ["# B", "## 재택\n주 2회 같음"],
        "t.md": ["# T", "## 재택\n주 5회"],
        "취업규칙.md": ["# 취업규칙", "## 제1조"],
        "08_징계_및_고충처리.md": ["0", "1", "2", "3", "## 직장 내 괴롭힘\n신고"],
    }
    chunks = fake.get  # dict.get 은 없는 키에 None 을 돌려주므로 ChunksOf 모양과 같다
    sides = {"a.md": "train", "b.md": "train", "t.md": "test",
             "취업규칙.md": "train", "08_징계_및_고충처리.md": "train"}
    twins = {"pairs": [{"id": 1, "a": {"doc": "a.md", "index": 1, "text": fake["a.md"][1]},
                        "b": {"doc": "b.md", "index": 1, "text": fake["b.md"][1]}}]}

    def q(**over) -> dict:
        base = {"id": "x1", "question": "재택 몇 번", "ground_truth": "주 2회",
                "source_doc": "a.md", "source_text": fake["a.md"][1], "style": "keyword"}
        return base | over  # 딕셔너리 합치기(3.9+). 오른쪽 값이 이긴다

    def payload(*qs: dict) -> dict:
        return {"chunking": CHUNKING, "questions": list(qs)}

    def caught(errors: list[str], word: str) -> bool:
        return any(word in e for e in errors)

    misses: list[str] = []
    dup_split = {"documents": [{"file": "a.md", "side": "train", "reason": "r"},
                               {"file": "a.md", "side": "test", "reason": "r"}]}
    if not caught(check_split(dup_split, {"a.md"}), "두 번"):
        misses.append("check_split 이 한 문서가 양쪽에 있는 것을 못 잡았다")
    cross = {"pairs": [{"id": 9, "a": {"doc": "a.md", "index": 1, "text": fake["a.md"][1]},
                        "b": {"doc": "t.md", "index": 1, "text": fake["t.md"][1]}}]}
    if not caught(check_twins(cross, chunks, sides), "다른 쪽"):
        misses.append("check_twins 가 경계를 넘는 쌍둥이 청크를 못 잡았다")
    wrong = {"pairs": [{"id": 9, "a": {"doc": "a.md", "index": 1, "text": "다른 본문"},
                        "b": {"doc": "b.md", "index": 1, "text": fake["b.md"][1]}}]}
    if not caught(check_twins(wrong, chunks, sides), "본문과 다릅니다"):
        misses.append("check_twins 가 실제 청크가 아닌 본문을 못 잡았다")
    if check_questions("train", payload(q()), chunks, sides, twins):
        misses.append("check_questions 가 깨끗한 연습 문제를 위반으로 봤다")
    if not caught(check_questions("train", payload(q(source_doc="t.md", source_text=fake["t.md"][1])),
                                  chunks, sides, twins), "쪽 문서여야"):
        misses.append("check_questions 가 시험용 문서를 정답으로 쓴 연습 문제를 못 잡았다")
    if not caught(check_questions("train", payload(q(question="자회사 재택")), chunks, sides, twins),
                  "시험용 대상 낱말"):
        misses.append("check_questions 가 연습 문제의 시험용 대상 낱말을 못 잡았다")
    if not caught(check_questions("holdout", payload(q()), chunks, sides, twins), "쌍둥이"):
        misses.append("check_questions 가 쌍둥이 청크가 있는 예비 시험 정답을 못 잡았다")
    if not caught(check_questions("train", payload(q(source_doc="취업규칙.md",
                                                     source_text=fake["취업규칙.md"][1])),
                                  chunks, sides, twins), "정답 문서로 쓰지 않습니다"):
        misses.append("check_questions 가 취업규칙을 정답 문서로 쓴 것을 못 잡았다")
    if not caught(check_questions("holdout", payload(q(source_doc="08_징계_및_고충처리.md",
                                                       source_text=fake["08_징계_및_고충처리.md"][4])),
                                  chunks, sides, twins), "규칙 10"):
        misses.append("check_questions 가 08 의 괴롭힘 청크를 정답으로 쓴 것을 못 잡았다")
    if not caught(check_questions("train", payload(q(style="formal")), chunks, sides, twins), "style"):
        misses.append("check_questions 가 모르는 말투를 못 잡았다")
    if not caught(check_questions("train", payload(q(source_text="없는 본문")), chunks, sides, twins),
                  "글자까지"):
        misses.append("check_questions 가 실제 청크가 아닌 정답 본문을 못 잡았다")
    protected = protected_texts({"test": payload(q(source_doc="t.md", source_text=fake["t.md"][1]))}, twins)
    leak = [{"id": "p1", "positive": fake["a.md"][1], "negatives": [fake["t.md"][1]]}]
    if not caught(check_pairs(leak, protected), "오답 예시"):
        misses.append("check_pairs 가 오답 예시로 새어 들어간 시험 정답을 못 잡았다")
    if protected_texts({"holdout": payload(q())}, twins) != {fake["a.md"][1], fake["b.md"][1]}:
        misses.append("protected_texts 가 예비 시험 정답의 쌍둥이 청크를 넣지 않았다")
    nb = {"cells": [{"cell_type": "code", "source": ['EXPECTED_SHA256 = "' + "0" * 64 + '"\n']}]}
    if not check_notebook_hash(b"data", nb):
        misses.append("check_notebook_hash 가 다른 해시를 못 잡았다")
    good = {"cells": [{"cell_type": "code",
                       "source": f'EXPECTED_SHA256 = "{hashlib.sha256(b"data").hexdigest()}"'}]}
    if check_notebook_hash(b"data", good):
        misses.append("check_notebook_hash 가 같은 해시를 위반으로 봤다")
    return misses


# ─────────────────────────────────────────────────────────────────────────────
# 실행
# ─────────────────────────────────────────────────────────────────────────────

def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"❌ JSON 을 읽지 못했습니다 ({path.name}): {e.lineno}번째 줄, {e.msg}")
        return None


def _show_chunks(name: str) -> int:
    """문제 작성용. 청크 번호와 JSON 문자열로 쓴 본문을 찍는다(그대로 붙여 넣으면 된다)."""
    got = chunks_of(name)
    if got is None:
        print(f"코퍼스에 {name} 가 없습니다. 파일 이름을 testdata/corpus/ 에서 확인해주세요.")
        return 1
    for i, text in enumerate(got):
        print(f"[{i}] {json.dumps(text, ensure_ascii=False)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="리랭커 파인튜닝 실험의 누출 검사")
    parser.add_argument("--show-chunks", metavar="DOC", default=None,
                        help="코퍼스 문서 하나의 청크를 번호와 함께 찍는다(문제 작성용)")
    args = parser.parse_args()
    if args.show_chunks:
        return _show_chunks(args.show_chunks)

    misses = _self_test()
    if misses:
        for m in misses:
            print(f"❌ 자기 점검: {m}")
        return 1
    print("✅ 자기 점검: 규칙 함수마다 틀린 입력을 잡았습니다")

    failures = 0

    def report(name: str, errors: list[str]) -> None:
        # nonlocal: 바깥 함수(main)의 변수 failures 를 이 안쪽 함수에서 고치겠다는 선언이다.
        nonlocal failures
        if errors:
            failures += len(errors)
            for e in errors:
                print(f"❌ [{name}] {e}")
        else:
            print(f"✅ {name}")

    def skip(message: str) -> None:
        print(f"⏭  {message}")

    for base in (SPLIT_FILE, TWINS_FILE):
        if not base.exists():
            print(f"❌ 기준 파일이 없습니다: {base}. 이 파일은 건너뛰지 않습니다(스펙 §8).")
            return 1
    split, twins = _read_json(SPLIT_FILE), _read_json(TWINS_FILE)
    if split is None or twins is None:
        return 1

    corpus_files = {p.name for p in CORPUS_DIR.glob("*.md")}
    report("1. 학습용과 시험용 문서가 겹치지 않는다", check_split(split, corpus_files))
    sides = side_of(split)
    report("3. 쌍둥이 청크가 실제 청크이고 경계를 넘지 않는다", check_twins(twins, chunks_of, sides))
    if twins.get("chunking") != CHUNKING:
        report("3. twins.json 청킹 설정", [f"twins.json 의 chunking 이 {CHUNKING} 이 아닙니다."])

    payloads: dict[str, dict] = {}
    for kind, path in QUESTION_FILES.items():
        if not path.exists():
            skip(f"{path.name} 이 아직 없어 이 파일의 4, 5, 7번 검사를 건너뜁니다")
            continue
        loaded = _read_json(path)
        if loaded is None:
            failures += 1
            continue
        payloads[kind] = loaded
        report(f"4, 5, 7. {path.name}", check_questions(kind, loaded, chunks_of, sides, twins))

    if not PAIRS_FILE.exists():
        skip("train_pairs.jsonl 이 아직 없어 2번, 6번 검사를 건너뜁니다")
    else:
        lines = PAIRS_FILE.read_text(encoding="utf-8").splitlines()
        pairs = [json.loads(line) for line in lines if line.strip()]
        # 보호 목록은 시험, 예비 시험 문제 파일로 만든다. 둘 중 하나라도 없으면 보호 목록이
        # 비거나 반쪽이라 무엇을 넣어도 통과한다. "검사하지 못함" 을 "검사해서 통과" 와 같은 ✅ 로
        # 찍지 않으려고 실패로 센다. 계획 순서상 두 파일이 train_pairs 보다 먼저 있어야 하므로
        # 건너뛸 상황이 아니다.
        missing = [QUESTION_FILES[k].name for k in ("test", "holdout") if k not in payloads]
        if missing:
            report("2. 시험, 예비 시험 정답이 학습 데이터에 없다",
                   [f"train_pairs.jsonl 은 있는데 {', '.join(missing)} 이 없거나 읽지 못해 "
                    "보호 목록을 만들 수 없습니다. 문제 파일을 먼저 만든 뒤 다시 실행해주세요."])
        else:
            report("2. 시험, 예비 시험 정답이 학습 데이터에 없다",
                   check_pairs(pairs, protected_texts(payloads, twins)))
        if not NOTEBOOK_FILE.exists():
            skip("노트북이 아직 없어 6번 검사를 건너뜁니다")
        else:
            notebook = _read_json(NOTEBOOK_FILE)
            if notebook is None:
                failures += 1
            else:
                report("6. 노트북의 해시가 학습 데이터와 같다",
                       check_notebook_hash(PAIRS_FILE.read_bytes(), notebook))

    print(f"\n❌ {failures}건 실패." if failures else "\n전부 통과.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
