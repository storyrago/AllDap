"""evaluator 의 <LLM 없이 검증 가능한 부분>을 확인하는 자체 점검.

실행:  cd ai-service && .venv/bin/python -m app.evaluator_check

왜 pytest 가 아닌가
─────────────────────────────────────────────────────────────────────────────
ai-service 에는 아직 테스트 프레임워크가 없다. 이 슬라이스 하나 때문에 pytest·픽스처·
설정 파일을 들이는 건 과하다. 여기서 필요한 건 "로직이 깨지면 알아채는 최소한의 장치"이고,
assert 와 `python -m` 만으로 충분하다. 테스트가 늘어나면 그때 pytest 로 옮기면 된다.

무엇을 확인하나 (그리고 무엇을 확인하지 <않>나)
─────────────────────────────────────────────────────────────────────────────
확인함: LLM 응답을 받은 <다음>의 판정 로직 — 빈 값·공백·NO_ANSWER 오염을 걸러내는가.
        이게 깨지면 ground_truth 가 NOT NULL 이라 INSERT 에서 터지거나,
        더 나쁘게는 NO_ANSWER 가 섞인 질문이 저장돼 나중에 채점을 오염시킨다.
확인 안 함: 실제 LLM 호출·SQL. 둘 다 외부(네트워크·DB)가 있어야 하고,
        그건 이 파일이 아니라 curl 로 하는 종단 확인의 몫이다.
"""
from __future__ import annotations

from unittest.mock import patch

from .evaluator import QuestionPair, make_question


class _FakeResponse:
    """genai 응답 흉내. make_question 이 쓰는 것만 갖고 있으면 된다.

    parsed 를 None 으로 두면 make_question 이 text 를 json.loads 하는 경로를 탄다.
    """

    def __init__(self, parsed=None, text=None):
        self.parsed = parsed
        self.text = text
        self.candidates = []


def _run(parsed=None, text=None) -> QuestionPair | None:
    """LLM 호출만 가짜로 바꿔치고 make_question 을 그대로 돌린다."""
    fake = _FakeResponse(parsed=parsed, text=text)
    with patch("app.evaluator._gemini") as gemini:
        gemini.return_value.models.generate_content.return_value = fake
        return make_question("아무 내용")


def main() -> None:
    # ① 정상 — 구조화 출력이 제대로 온 경우
    ok = _run(parsed=QuestionPair(question="연차는 며칠인가요?", ground_truth="15일입니다."))
    assert ok is not None and ok.question == "연차는 며칠인가요?", ok

    # ② 정상 — parsed 가 비어 text 의 JSON 으로 되살리는 경로
    ok = _run(text='{"question":"반차는요?","ground_truth":"오전/오후 중 하나입니다."}')
    assert ok is not None and ok.ground_truth.startswith("오전"), ok

    # ③ 빈 응답 → None (안전 필터 차단·토큰 잘림)
    assert _run(text="") is None
    assert _run(text=None) is None

    # ④ JSON 이 깨진 경우 → None (MAX_TOKENS 로 중간에 끊긴 모양)
    assert _run(text='{"question":"징계 종류는","ground_') is None

    # ⑤ 한쪽이 비면 → None. eval_questions.ground_truth 가 NOT NULL 이라 저장할 수 없다.
    assert _run(parsed=QuestionPair(question="질문만 있음", ground_truth="")) is None
    assert _run(parsed=QuestionPair(question="   ", ground_truth="정답만 있음")) is None

    # ⑥ NO_ANSWER 오염 → None.
    #    이게 저장되면 채점 때 generator 의 부분 문자열 검사에 걸려
    #    그 질문의 답변이 무조건 미답변으로 뒤집힌다. 가장 중요한 검사다.
    assert _run(parsed=QuestionPair(question="NO_ANSWER 가 뭔가요?", ground_truth="정답")) is None
    assert _run(parsed=QuestionPair(question="질문", ground_truth="답은 NO_ANSWER 입니다")) is None

    # ⑦ LLM 호출 자체가 터져도 예외가 밖으로 새지 않고 None 이어야 한다.
    #    (429 쿼터 초과가 실제로 났고, 이때 요청 전체가 죽으면 안 된다)
    with patch("app.evaluator._gemini") as gemini:
        gemini.return_value.models.generate_content.side_effect = RuntimeError("429")
        assert make_question("아무 내용") is None

    print("evaluator 자체 점검 통과 (7가지)")


if __name__ == "__main__":
    main()
