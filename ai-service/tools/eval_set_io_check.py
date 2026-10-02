"""eval_set 의 파일 입출력 점검. DB 를 쓰지 않는다. CI 에서 돈다.

실행:  cd ai-service && .venv/bin/python -m tools.eval_set_io_check

보는 것 (2026-10-01, 리랭커 파인튜닝 실험이 계기)
  ① --file 이 없으면 봇 1번 평가셋 파일을 가리킨다(기존 동작 유지)
  ② 상대 경로는 ai-service/ 기준이다(실행 위치에 따라 다른 파일을 쓰지 않는다)
  ③ dump 가 기존 파일의 style 을 이어받는다(안 하면 dump 한 번에 말투 표시가 지워진다)
  ④ style 이 없던 문항에는 style 칸을 만들지 않는다(봇 1번 파일에 빈 칸이 생기지 않는다)
  ⑤ 봇 1번이 아닌데 --file 이 없으면 dump, load 둘 다 거절한다(봇 1번 파일을 덮어쓰지 않는다)
  ⑥ --file 로 준 파일이 없으면 dump 가 아니라 경로를 확인하라고 안내한다
"""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from . import eval_set


def _row(question: str) -> tuple:
    # fetch_questions 가 돌려주는 행 모양: (db id, 질문, 정답, 활성, 파일명, 청크 본문)
    return (1, question, "답", True, "a.md", "본문")


def check_default_file_is_bot1_file() -> None:
    assert eval_set.resolve_file(None) == eval_set.EVAL_SET_PATH


def check_relative_file_is_under_ai_service() -> None:
    got = eval_set.resolve_file("testdata/finetune/test_questions.json")
    assert got == eval_set._AI_SERVICE_DIR / "testdata" / "finetune" / "test_questions.json", got


def check_previous_annotations_reads_given_file_and_style() -> None:
    with TemporaryDirectory() as tmp:
        f = Path(tmp) / "x.json"
        f.write_text(json.dumps({"questions": [{"question": "질문1", "style": "typo"}]},
                                ensure_ascii=False), encoding="utf-8")
        ann = eval_set.previous_annotations(f)
    assert ann["질문1"]["style"] == "typo", ann
    assert ann["질문1"]["review"] == {"verdict": "", "note": ""}, ann


def check_missing_file_gives_empty_annotations() -> None:
    assert eval_set.previous_annotations(Path("/없는/경로/x.json")) == {}


def check_build_payload_keeps_style_only_when_present() -> None:
    payload = eval_set.build_payload([_row("질문1"), _row("질문2")], {"질문1": {"style": "casual"}})
    q1, q2 = payload["questions"]
    assert q1["style"] == "casual", q1
    assert "style" not in q2, q2


def check_other_bot_without_file_is_refused() -> None:
    assert eval_set.target_file(1, None) == eval_set.EVAL_SET_PATH
    got = eval_set.target_file(3, "testdata/finetune/test_questions.json")
    assert got == eval_set.resolve_file("testdata/finetune/test_questions.json"), got
    try:
        eval_set.target_file(3, None)
    except SystemExit as e:
        assert "--file" in str(e) and "덮어쓰" in str(e), e
    else:
        raise AssertionError("봇 3 에 --file 없이 실행했는데 거절하지 않았다")


def check_missing_given_file_asks_to_check_path() -> None:
    try:
        eval_set.read_payload(eval_set.resolve_file("testdata/없는_파일.json"))
    except SystemExit as e:
        assert "ai-service/ 기준으로 확인" in str(e) and "dump" not in str(e), e
    else:
        raise AssertionError("없는 파일을 읽었는데 멈추지 않았다")


def main() -> None:
    checks = [
        check_default_file_is_bot1_file,
        check_relative_file_is_under_ai_service,
        check_previous_annotations_reads_given_file_and_style,
        check_missing_file_gives_empty_annotations,
        check_build_payload_keeps_style_only_when_present,
        check_other_bot_without_file_is_refused,
        check_missing_given_file_asks_to_check_path,
    ]
    for fn in checks:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(checks)}가지 전부 통과.")


if __name__ == "__main__":
    main()
