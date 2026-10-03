"""채점 모델 비교 실험(2026-10-02)의 파일 만들기.

실행:
    cd ai-service
    .venv/bin/python -m tools.judge5_export labels   # 빈 새 라벨 파일(1~5)을 만든다
    .venv/bin/python -m tools.judge5_export cases    # 시험지 파일을 만든다(태스크 4)

DB 를 쓰지 않는다. 사례 44건은 옛 라벨 파일에 이미 전부 들어 있다(스펙 §1-2).
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from pathlib import Path

from .judge5 import CRITERIA, RUBRIC, SCALE, build_messages, prompt_sha256, sha256_file

# __file__ 은 ai-service/tools/judge5_export.py 다. 두 번 올라가면 ai-service/ 다.
# 실행 위치와 무관하게 같은 파일을 가리키려고 __file__ 기준으로 잡는다.
ROOT = Path(__file__).resolve().parent.parent
OLD_LABELS = ROOT / "testdata" / "judge_labels.json"
NEW_LABELS = ROOT / "testdata" / "judge_labels_5pt.json"

# 새 라벨 화면의 사례 순서를 섞는 시드. 옛 화면은 case_id 순서였다. 같은 사람이 같은 순서로 다시 보면
# "7번째는 0.5 였지" 같은 기억이 단서가 된다(스펙 §8). 시드를 고정하는 이유: 다시 만들어도 같은 순서가
# 나와야 시험지 해시가 재현된다.
SHUFFLE_SEED = 20261002
JUDGE5_DIR = ROOT / "testdata" / "judge5"
CASES = JUDGE5_DIR / "cases.jsonl"
CASES_SHA = JUDGE5_DIR / "cases.sha256"
RESULTS_DIR = JUDGE5_DIR / "results"

_README5 = (
    "label 칸에 1~5 정수만 적는다. 화면(python -m tools.judge_label_server --path testdata/judge_labels_5pt.json)으로 "
    "매기는 것을 권한다. 옛 라벨, 기대 답변, 모델 점수는 일부러 들어 있지 않다. 보고 매기면 끌려가 대조가 성립하지 않는다. "
    "기준은 rubric 칸이고, 네 채점 모델이 받는 채점표와 같은 글자다."
)


def make_label_file(old: dict) -> dict:
    """옛 라벨 파일에서 사례만 옮겨 빈 새 라벨 파일을 만든다.

    옮기지 않는 것: label, note(옛 라벨), ground_truth(스펙 §3-2: 충실성은 근거만 본다),
    question_id, seen_in_runs(문항 번호가 단서가 되지 않게).
    순서: case_id 로 먼저 줄 세운 뒤(입력 순서와 무관하게 하려고) 고정 시드로 섞는다.
    """
    cases = [
        {
            "case_id": c["case_id"],
            "question": c["question"],
            "generated_answer": c["generated_answer"],
            "sources": c["sources"],
            "label": None,
            "note": "",
        }
        # sorted(..., key=...) 는 case_id(해시) 순서로 줄 세운다. 입력 순서와 무관하게 하려는 것이고,
        # 최종 순서는 아래에서 섞는다(옛 화면의 순서와 같지 않다).
        for c in sorted(old["cases"], key=lambda c: c["case_id"])
    ]
    # random.Random(시드) 는 전역 난수와 따로 노는 난수 생성기다. shuffle 은 리스트를 제자리에서 섞는다.
    random.Random(SHUFFLE_SEED).shuffle(cases)
    return {
        "_readme": _README5,
        "scale": 5,
        "rubric": {"criteria": CRITERIA, "levels": {str(k): v for k, v in RUBRIC.items()}},
        "source_file": "testdata/judge_labels.json",
        "cases": cases,
    }


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cmd_labels() -> int:
    if NEW_LABELS.exists():
        # 이미 매긴 라벨을 빈 파일로 덮으면 사람이 들인 시간이 사라진다. 그래서 거절만 한다.
        print(f"{NEW_LABELS.relative_to(ROOT)} 가 이미 있습니다. 덮어쓰지 않습니다. 다시 만들려면 파일을 직접 지우세요.")
        return 1
    old = json.loads(OLD_LABELS.read_text(encoding="utf-8"))
    new = make_label_file(old)
    _write_json(NEW_LABELS, new)
    print(f"{NEW_LABELS.relative_to(ROOT)} 에 {len(new['cases'])}건을 비운 채로 썼습니다.")
    print("라벨링: .venv/bin/python -m tools.judge_label_server --path testdata/judge_labels_5pt.json")
    return 0


def labels_ready(labels: dict) -> list[str]:
    """새 라벨이 시험지를 만들어도 될 상태인지 본다. 문제를 문장으로 돌려준다."""
    problems = []
    empty = [c["case_id"] for c in labels["cases"] if c["label"] is None]
    if empty:
        problems.append(f"라벨이 빈 사례가 {len(empty)}건 있습니다(예: {empty[0]})")
    bad = [c["case_id"] for c in labels["cases"] if c["label"] is not None and c["label"] not in SCALE]
    if bad:
        problems.append(f"1~5 가 아닌 라벨이 {len(bad)}건 있습니다(예: {bad[0]})")
    return problems


def _committed(path: Path) -> list[str]:
    """파일이 git 에 커밋돼 있고 고친 흔적이 없는지 본다.

    커밋을 요구하는 이유: 모델 결과를 본 뒤 라벨을 고치면 대조가 성립하지 않는다.
    커밋 시점이 "모델을 돌리기 전에 라벨이 이랬다" 는 기록이 된다(스펙 §4-1).
    """
    rel = str(path.relative_to(ROOT))
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=ROOT, capture_output=True)
    if tracked.returncode != 0:
        return [f"{rel} 이 아직 커밋되지 않았습니다. 라벨을 커밋한 뒤 다시 실행하세요."]
    dirty = subprocess.run(["git", "status", "--porcelain", "--", rel], cwd=ROOT, capture_output=True, text=True)
    if dirty.stdout.strip():
        return [f"{rel} 에 커밋하지 않은 변경이 있습니다. 커밋한 뒤 다시 실행하세요."]
    return []


def make_cases(labels: dict) -> list[dict]:
    """시험지 파일의 줄들. 사례 번호와 완성된 지시문(messages)만 담는다. 라벨은 넣지 않는다."""
    return [
        {"case_id": c["case_id"], "messages": build_messages(c["question"], c["sources"], c["generated_answer"])}
        for c in labels["cases"]
    ]


def cmd_cases() -> int:
    labels = json.loads(NEW_LABELS.read_text(encoding="utf-8"))
    problems = labels_ready(labels) + _committed(NEW_LABELS)
    if problems:
        print("시험지를 만들지 않았습니다.")
        for p in problems:
            print(f"  - {p}")
        return 1
    JUDGE5_DIR.mkdir(parents=True, exist_ok=True)
    rows = make_cases(labels)
    # sort_keys=True: 키 순서를 고정해 같은 내용이면 같은 해시가 나오게 한다.
    CASES.write_text(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    sha = sha256_file(CASES)
    # 첫 줄은 시험지 파일 해시(다른 도구는 split()[0] 으로 이 값만 읽는다), 둘째 줄은 공통 지시문 해시(스펙 §3-2).
    CASES_SHA.write_text(f"{sha}  cases.jsonl\n{prompt_sha256()}  prompt\n", encoding="utf-8")
    print(f"{CASES.relative_to(ROOT)} 에 {len(rows)}건을 썼습니다.")
    print(f"SHA-256: {sha}")
    print(f"공통 지시문 SHA-256: {prompt_sha256()}")
    print("코랩 노트북의 EXPECTED_SHA256 에 이 값을 넣으세요(계획 태스크 7).")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="채점 모델 비교 실험의 파일을 만든다")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("labels", help="빈 새 라벨 파일(1~5)을 만든다")
    sub.add_parser("cases", help="시험지 파일을 만든다(새 라벨이 다 차고 커밋돼 있어야 한다)")
    args = p.parse_args(argv)
    if args.cmd == "labels":
        return cmd_labels()
    if args.cmd == "cases":
        return cmd_cases()
    return 2


if __name__ == "__main__":
    sys.exit(main())
