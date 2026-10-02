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
import sys
from pathlib import Path

from .judge5 import CRITERIA, RUBRIC

# __file__ 은 ai-service/tools/judge5_export.py 다. 두 번 올라가면 ai-service/ 다.
# 실행 위치와 무관하게 같은 파일을 가리키려고 __file__ 기준으로 잡는다.
ROOT = Path(__file__).resolve().parent.parent
OLD_LABELS = ROOT / "testdata" / "judge_labels.json"
NEW_LABELS = ROOT / "testdata" / "judge_labels_5pt.json"

_README5 = (
    "label 칸에 1~5 정수만 적는다. 화면(python -m tools.judge_label_server --path testdata/judge_labels_5pt.json)으로 "
    "매기는 것을 권한다. 옛 라벨, 기대 답변, 모델 점수는 일부러 들어 있지 않다. 보고 매기면 끌려가 대조가 성립하지 않는다. "
    "기준은 rubric 칸이고, 네 채점 모델이 받는 채점표와 같은 글자다."
)


def make_label_file(old: dict) -> dict:
    """옛 라벨 파일에서 사례만 옮겨 빈 새 라벨 파일을 만든다.

    옮기지 않는 것: label, note(옛 라벨), ground_truth(스펙 §3-2: 충실성은 근거만 본다),
    question_id, seen_in_runs(문항 번호가 단서가 되지 않게).
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
        # sorted(..., key=...) 는 case_id(해시) 순서로 줄 세운다. 옛 파일과 같은 순서다.
        for c in sorted(old["cases"], key=lambda c: c["case_id"])
    ]
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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="채점 모델 비교 실험의 파일을 만든다")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("labels", help="빈 새 라벨 파일(1~5)을 만든다")
    args = p.parse_args(argv)
    if args.cmd == "labels":
        return cmd_labels()
    return 2


if __name__ == "__main__":
    sys.exit(main())
