"""tools.judgeft_labels 의 점검. 가짜 토크나이저로 본다. DB 도 외부 API 도 모델도 쓰지 않는다.

실행:  cd ai-service && python -m tools.judgeft_labels_check
"""
from __future__ import annotations

from .judgeft_labels import build_example

END = 999


def _apply(messages: list[dict]) -> str:
    return "".join(f"<{m['role']}>{m['content']}" for m in messages) + "<assistant>"


def _encode(text: str) -> list[int]:
    return [ord(c) for c in text]      # 글자 하나가 토큰 하나인 가짜 토크나이저


def check_end_token_is_last_and_inside_target() -> None:
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "질문"}]
    ids, n = build_example(_apply, _encode, msgs, "Fine. [RESULT] 5", END)
    assert ids[-1] == END                                   # 끝 토큰이 맨 뒤
    assert n == len("Fine. [RESULT] 5") + 1                  # 정답 쪽 길이에 끝 토큰이 들어간다
    assert "".join(chr(i) for i in ids[:-n]) == _apply(msgs)  # 입력 쪽은 대화 틀 그대로(시스템 메시지 포함)


CHECKS = [check_end_token_is_last_and_inside_target]


def main() -> None:
    for fn in CHECKS:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(CHECKS)}가지 전부 통과.")


if __name__ == "__main__":
    main()
