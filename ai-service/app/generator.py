"""검색된 근거만으로 답변을 생성한다.

이 파일의 프롬프트가 제품 품질의 절반을 좌우한다.
핵심 원칙: 근거에 없으면 지어내지 말고 모른다고 말할 것(fallback).

제공자: Cloudflare Workers AI (2026-08-02 에 Google Gemini 에서 옮겼다).
왜 옮겼는지는 config.py 의 chat_model 주석 참고 — 요약하면 <무료 한도> 때문이다.
Gemini 무료는 모델당 하루 20회라 평가를 하루 한 번밖에 못 돌렸다.
"""
from __future__ import annotations

import logging
from uuid import UUID

from . import cf
from .config import get_settings
from .retriever import fetch_contents
from .schemas import Source

_log = logging.getLogger(__name__)

SYSTEM_PROMPT = """당신은 조직의 내부 문서를 근거로 질문에 답하는 도우미입니다.

반드시 지켜야 할 규칙:
1. 아래 <문서> 안의 내용만 근거로 사용하세요. 문서에 없는 내용은 절대 지어내지 마세요.
2. 문서에서 답을 찾을 수 없으면, 추측하지 말고 정확히 이렇게만 답하세요: "NO_ANSWER"
3. 답변에는 근거가 된 문서의 내용을 그대로 옮기기보다, 질문에 맞게 간결히 정리해서 답하세요.
4. 한국어로, 존댓말로 답하세요.
5. 확실하지 않은 부분은 "문서상으로는 ~까지만 확인됩니다"처럼 한계를 밝히세요."""

FALLBACK_TOKEN = "NO_ANSWER"


class GenerationFailed(RuntimeError):
    """답변을 <받지 못했다>. 근거가 없어 못 답한 것(fallback)과 완전히 다른 사실이다.

    왜 예외인가 — 돌려주지 않고 던지는 이유
    ─────────────────────────────────────────────────────────────────────────
    `(답변, is_fallback)` 로는 이 상태를 표현할 수 없다. 셋 중 어느 쪽으로 뭉개도
    거짓말이 된다:
      · `(fallback_message, True)`  → 근거를 찾고도 "문서에 답이 없다"고 말한다.
                                      제품의 핵심 주장이 무너진다. **이게 고치려는 버그다.**
      · `(잘린 답변, False)`         → 반쪽짜리 답을 완성된 답으로 내보내고, 평가가
                                      그걸 채점한다(측정이 오염된다).
    던지면 부르는 쪽이 <자기 맥락에 맞게> 다룬다. 실제로 이미 그렇게 돼 있다 —
    `evalrun` 은 이 질문을 응답률 분모에서 빼고(측정 실패), `main.chat` 은 오류로 안내한다.
    """


def _build_context(sources: list[Source]) -> str:
    contents = fetch_contents([s.chunk_id for s in sources])
    blocks = []
    for i, src in enumerate(sources, 1):
        body = contents.get(src.chunk_id, src.preview)
        blocks.append(f"[근거 {i}] (출처: {src.filename})\n{body}")
    return "\n\n".join(blocks)


def generate(
    question: str,
    sources: list[Source],
    *,
    fallback_message: str = "문서에서 답을 찾지 못했어요. 담당자에게 문의해주세요.",
) -> tuple[str, bool]:
    """(답변, is_fallback) 반환."""
    # 검색 단계에서 이미 걸러졌다면 LLM을 부를 필요도 없다 (비용 절감)
    if not sources:
        return fallback_message, True

    s = get_settings()
    user_content = (
        f"<문서>\n{_build_context(sources)}\n</문서>\n\n"
        f"질문: {question}"
    )

    result = cf.run(s.chat_model, {
        "messages": [
            # Cloudflare 는 system instruction 을 별도 인자가 아니라 messages 의
            # role="system" 으로 받는다. Gemini 의 system_instruction 과 같은 자리다.
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": s.max_tokens,
        # 0 = 매번 같은 답. 이 제품은 문서에 있는 사실을 그대로 전달하는 것이 일이라
        # 표현을 바꿔 말하는 것은 기능이 아니라 위험이다. 평가도 이래야 재현된다.
        "temperature": s.chat_temperature,
    })

    answer = cf.text_of(result).strip()
    reason = cf.finish_reason(result)

    # 🔴 순서가 중요하다. 모델이 명시적으로 거절했으면 그건 <완결된 신호>다.
    #    뒤가 잘렸든 아니든 "문서에 답이 없다"는 사실은 이미 전달됐으므로 fallback 이 맞다.
    #    이 검사를 아래로 내리면, 거절해놓고 잘린 응답이 <오류>로 둔갑한다.
    if FALLBACK_TOKEN in answer:
        return fallback_message, True

    # ⚠️ 예전에 여기가 `if FALLBACK_TOKEN in answer or not answer` 한 줄이었다.
    #    그 `or not answer` 가 <우리가 토큰을 덜 줘서 빈 응답>을 <문서에 답이 없다>로
    #    둔갑시켰다. 근거를 찾고도 "문서에서 답을 찾지 못했어요" 를 내보내는 것이다.
    #
    #    어떻게 비나: 사고(thinking) 토큰이 max_tokens 를 함께 쓰는 모델은 사고가 길어지면
    #    본문이 <시작도 못 하고> 잘린다. 실측 둘 —
    #      · 질문 생성에서 같은 원인으로 5회 중 3회가 잘렸다 (evaluator.py 주석)
    #      · K-EXAONE 은 max_tokens=8192 를 줘도 2000 에서 잘렸다 (2026-08-04, decisions.md)
    #
    #    잘렸는데 <본문이 있는> 경우도 실패로 친다. 반쪽짜리 답을 완성된 답으로 내보내면
    #    사용자는 잘린 줄 모르고, 평가는 그걸 정상 답변으로 채점한다(측정이 오염된다).
    #
    #    ⚠️ reason 이 None 이면 <모른다>는 뜻이라 잘림으로 단정하지 않는다(cf.finish_reason 참고).
    #       그래도 답변이 비어 있으면 실패다 — 빈 문자열이 정답인 경우는 없다.
    if reason == "length":
        raise GenerationFailed(
            f"답변이 max_tokens({s.max_tokens})에 걸려 잘렸습니다. "
            f"질문을 더 좁히거나 max_tokens 를 늘리세요. "
            f"받은 길이={len(answer)}자"
        )
    if not answer:
        raise GenerationFailed(
            f"모델이 빈 응답을 돌려줬습니다 (finish_reason={reason!r}). "
            f"모델·프롬프트를 확인하세요."
        )

    return answer, False
