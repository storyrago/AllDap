"""`generator.generate` 의 3갈래 판정을 API 호출 없이 검증한다.

실행:
    cd ai-service && .venv/bin/python -m app.generator_check

왜 이 파일이 있어야 하나
─────────────────────────────────────────────────────────────────────────────
이 함수는 <서로 다른 세 가지 사실>을 가려낸다. 셋을 섞으면 제품이 거짓말을 한다:

  ① 문서에 답이 없다      → fallback (제품이 제대로 동작한 것)
  ② 답변을 못 받았다      → 실패     (우리 인프라 문제. 사용자 잘못도 봇 품질 문제도 아니다)
  ③ 답변을 받았다        → 정상

②를 ①로 뭉갠 것이 2026-08-04 에 고친 버그다(`or not answer` 한 줄). 이 프로젝트가
같은 부류의 실수를 네 번 냈으므로(`answered_rate` 분모 · 채점자 200자 ·
noanswer_check 판정문구 · 이것) 다섯 번째를 막을 그물이 필요하다.

⚠️ <실제 모델을 부르지 않는다.> 여기서 재는 것은 "모델이 잘하는가"가 아니라
   "받은 응답을 우리가 올바르게 해석하는가" 하나뿐이다. 모델 품질은
   `noanswer_check.py` 가 실제 호출로 잰다. 둘은 다른 일이며 섞으면 안 된다 —
   섞으면 쿼터가 없는 날 이 검사도 같이 못 돌린다.
"""
from __future__ import annotations

from uuid import uuid4

from . import cf, generator
from .generator import FALLBACK_TOKEN, GenerationFailed, generate
from .schemas import Source

FALLBACK_MSG = "문서에서 답을 찾지 못했어요."


def _sources() -> list[Source]:
    """근거 1건. 내용은 중요하지 않다 — 여기서 재는 것은 <응답 해석>이다."""
    return [Source(chunk_id=uuid4(), document_id=uuid4(),
                   filename="취업규칙.md", score=0.9, preview="노트북 교체 주기는 3년")]


def _reply(text: str, reason: str | None = "stop") -> dict:
    """Cloudflare 의 OpenAI 호환 응답 모양을 흉내낸다.

    reason=None 은 Workers AI 고유 형식(`result["response"]` 만 오는 경우)이다.
    그때는 finish_reason 을 <알 수 없다>.
    """
    if reason is None:
        return {"response": text}
    return {"choices": [{"finish_reason": reason,
                         "message": {"content": text}}]}


def _run(result: dict):
    """cf.run 을 대신할 가짜. 무엇을 물어보든 정해진 응답을 돌려준다."""
    return lambda model, payload: result


def main() -> None:
    # `from .retriever import fetch_contents` 로 <generator 의 이름공간에> 묶여 있으므로
    # retriever 가 아니라 generator 쪽을 갈아끼워야 한다. DB 를 안 부르게 하는 것이 목적이다.
    generator.fetch_contents = lambda ids: {}
    real_run = cf.run
    ok = 0

    def case(name: str, result: dict | None, expect_fallback: bool | None,
             *, sources: list[Source] | None = None) -> None:
        """expect_fallback: True=fallback / False=정상답변 / None=GenerationFailed"""
        nonlocal ok
        cf.run = _run(result) if result is not None else real_run
        srcs = _sources() if sources is None else sources
        try:
            answer, is_fallback = generate("노트북 교체 주기는?", srcs,
                                           fallback_message=FALLBACK_MSG)
        except GenerationFailed as e:
            got = f"실패({str(e)[:40]}…)"
            passed = expect_fallback is None
        else:
            got = f"fallback={is_fallback} answer={answer[:24]!r}"
            passed = expect_fallback is not None and is_fallback is expect_fallback
        ok += passed
        print(f"  {'✅' if passed else '❌'} {name}\n       → {got}")

    print("generator.generate 판정 검사\n")

    # ── ① 문서에 답이 없다 → fallback ──────────────────────────────────
    case("근거가 아예 없으면 LLM 을 부르지 않고 fallback", None, True, sources=[])
    case("NO_ANSWER 토큰 → fallback", _reply(FALLBACK_TOKEN), True)
    # 🔴 순서 검사. 거절은 <완결된 신호>라 뒤가 잘려도 fallback 이어야 한다.
    #    이 검사를 통과하려면 FALLBACK_TOKEN 확인이 잘림 확인보다 <먼저>여야 한다.
    case("NO_ANSWER 인데 뒤가 잘림 → 그래도 fallback",
         _reply(FALLBACK_TOKEN, "length"), True)

    # ── ② 답변을 못 받았다 → 실패(예외) ────────────────────────────────
    # 🔴 이것이 고친 버그다. 예전에는 이 케이스가 fallback 으로 둔갑했다.
    case("잘려서 본문이 비었다 → 실패 (예전엔 fallback 으로 둔갑)",
         _reply("", "length"), None)
    case("잘렸는데 본문은 있다 → 실패 (반쪽 답을 정상으로 내보내면 채점이 오염된다)",
         _reply("노트북 교체 주기는 3년이며 파손 시", "length"), None)
    case("빈 응답인데 잘린 것도 아니다 → 실패", _reply("", "stop"), None)

    # ── ③ 정상 ────────────────────────────────────────────────────────
    case("정상 답변", _reply("노트북 교체 주기는 3년입니다."), False)
    # finish_reason 을 모르는 형식(Workers AI 고유)에서도 정상은 정상으로 통과해야 한다.
    # None 을 "잘렸다"로 단정하면 멀쩡한 답변이 전부 실패가 된다.
    case("finish_reason 이 없는 응답 형식 + 정상 본문 → 정상",
         _reply("노트북 교체 주기는 3년입니다.", None), False)

    cf.run = real_run
    print(f"\n{ok}/8 통과")
    if ok != 8:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
