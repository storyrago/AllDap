"""채점 모델 비교 v2 실험(2026-10-05)의 경로와 상수.

설계: docs/superpowers/specs/2026-10-05-judge-selfhost-v2-design.md

도구 여섯(search, assign, export, gate, report, check)이 같은 경로와 같은 상수를 읽게 하려고 한 곳에 둔다.
할당량이나 대응표가 도구마다 따로 적혀 있으면 언젠가 한쪽만 바뀐다.
외부 API 도 DB 도 부르지 않는다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# __file__ 은 ai-service/tools/judge5v2_files.py 다. 두 번 올라가면 ai-service/ 다.
ROOT = Path(__file__).resolve().parent.parent
V2 = ROOT / "testdata" / "judge5v2"

BOTS = V2 / "bots.json"
QUESTIONS = V2 / "questions.jsonl"
RETRIEVED = V2 / "retrieved.jsonl"
ASSIGNMENT = V2 / "assignment.json"
VARIANTS = V2 / "variants.jsonl"
REVIEW = V2 / "review.jsonl"
CASES = V2 / "cases.jsonl"
CASES_SHA = V2 / "cases.sha256"
ANSWER_KEY = V2 / "answer_key.json"
MISMATCHES = V2 / "mismatches.md"
GATE = V2 / "gate.md"
RESULTS_DIR = V2 / "results"
REPORT = V2 / "report.md"

# 스펙 2-1절의 네 분야. 튜플이라 순서가 고정된다. 보고서의 분야 순서도 이것을 따른다.
DOMAINS: tuple[str, ...] = ("hr", "shop", "manual", "finance")
CORPUS_DIRS: dict[str, Path] = {
    "hr": ROOT / "testdata" / "corpus",
    "shop": V2 / "corpus" / "shop",
    "manual": V2 / "corpus" / "manual",
    "finance": V2 / "corpus" / "finance",
}

# 스펙 3-2절의 변형 유형. 키는 유형 번호다(①이 1).
TYPE_NAMES: dict[int, str] = {
    1: "① 원본 그대로",
    2: "② 표현만 바꿈",
    3: "③ 사소한 말 하나 추가",
    4: "④ 절반 바꾸기",
    5: "⑤ 대부분 지어냄",
    6: "⑥ 핵심을 근거와 반대로",
    7: "⑦ 통째로 지어냄",
    8: "⑧ 다른 대상의 규정 끌어오기",
}
# 스펙 3-2절의 대응표. 변형 유형에서 정답 점수가 정해진다.
TABLE_SCORE: dict[int, int] = {1: 5, 2: 5, 3: 4, 4: 3, 5: 2, 6: 1, 7: 1, 8: 1}
# 스펙 7-1절. 분야마다의 할당량. 합이 60 이다.
QUOTA: dict[int, int] = {1: 9, 2: 9, 3: 9, 4: 9, 5: 6, 6: 7, 7: 5, 8: 6}
QUESTIONS_PER_DOMAIN = 75
# 배정과 시험지 섞기에 쓰는 시드. 고정해야 같은 입력에서 같은 배정과 같은 시험지 해시가 나온다.
SEED = 20261005
# 데모 봇(1)과 리랭커 실험 봇(7, 8). 이 실험의 도구는 이 번호를 받으면 거절한다(스펙 2-2절).
PROTECTED_BOTS: frozenset[int] = frozenset({1, 7, 8})


def read_jsonl(path: Path) -> list[dict]:
    """한 줄에 JSON 하나인 파일을 읽는다. 파일이 없으면 빈 목록이다(이어 하기의 첫 실행)."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    # sort_keys=True: 키 순서를 고정해 같은 내용이면 같은 해시가 나오게 한다(시험지 해시가 재현돼야 한다).
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), encoding="utf-8")


def append_jsonl(path: Path, row: dict) -> None:
    # "a" 는 이어 쓰기 모드다. 한 줄씩 바로 써 두면 중간에 멈춰도 그때까지의 결과가 남는다.
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# 다시 검색해도 결과가 같은 버림 원인(계획 형식 2). rerank_failed, keyword_failed 는 호출 실패라서 여기에 없다.
# 다시 부르면 풀릴 수 있으므로 검색 도구가 다음 실행에서 다시 검색한다.
SETTLED_DROPS: frozenset[str] = frozenset({"answerable", "max_distance"})


def latest_by_qid(rows: list[dict]) -> list[dict]:
    """retrieved.jsonl 은 시도마다 줄을 덧붙인다. 질문마다 마지막 줄만 남긴다(그 질문의 판정).

    dict 에 같은 키를 다시 넣으면 값은 바뀌고 자리는 처음 넣은 자리 그대로다. 그래서 순서는 첫 시도의 순서다.
    """
    last: dict[str, dict] = {}
    for r in rows:
        last[r["qid"]] = r
    return list(last.values())


def value_in(value: str, text: str) -> bool:
    """값이 text 안에 다른 값의 일부가 아닌 채로 있는가(계획 형식 1 의 값을 글자로 찾는 규칙).

    단순 포함(value in text)으로는 "10,000원" 이 "110,000원" 안에 있다고 나온다. 그래서 값의 끝이 숫자인
    쪽에만 경계를 건다. (?<!...) 는 "바로 앞이 ... 가 아니다", (?!...) 는 "바로 뒤가 ... 가 아니다" 는 뜻이다.
    앞쪽: 숫자나 "숫자 + 쉼표/점" 이 오면 안 된다. 뒤쪽: 숫자나 "쉼표/점 + 숫자" 가 오면 안 된다.
    값이 "원" 처럼 숫자가 아닌 글자로 끝나면 뒤쪽 경계를 걸지 않는다. 그래서 "10,000원." 의 마침표는 막지 않는다.
    """
    if not value:
        return False
    head = r"(?<!\d)(?<!\d[,.])" if value[0].isdigit() else ""
    tail = r"(?!\d|[,.]\d)" if value[-1].isdigit() else ""
    return re.search(head + re.escape(value) + tail, text) is not None
