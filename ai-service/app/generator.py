"""검색된 근거만으로 답변을 생성한다.

이 파일의 프롬프트가 제품 품질의 절반을 좌우한다.
핵심 원칙: 근거에 없으면 지어내지 말고 모른다고 말할 것(fallback).
"""
from __future__ import annotations

from uuid import UUID

from google import genai
from google.genai import types

from .config import get_settings
from .retriever import fetch_contents
from .schemas import Source

_client: genai.Client | None = None

SYSTEM_PROMPT = """당신은 조직의 내부 문서를 근거로 질문에 답하는 도우미입니다.

반드시 지켜야 할 규칙:
1. 아래 <문서> 안의 내용만 근거로 사용하세요. 문서에 없는 내용은 절대 지어내지 마세요.
2. 문서에서 답을 찾을 수 없으면, 추측하지 말고 정확히 이렇게만 답하세요: "NO_ANSWER"
3. 답변에는 근거가 된 문서의 내용을 그대로 옮기기보다, 질문에 맞게 간결히 정리해서 답하세요.
4. 한국어로, 존댓말로 답하세요.
5. 확실하지 않은 부분은 "문서상으로는 ~까지만 확인됩니다"처럼 한계를 밝히세요."""

FALLBACK_TOKEN = "NO_ANSWER"


def _gemini() -> genai.Client:
    global _client
    if _client is None:
        s = get_settings()
        if not s.google_api_key:
            raise RuntimeError("GOOGLE_API_KEY가 설정되지 않았습니다 (.env 확인)")
        _client = genai.Client(api_key=s.google_api_key)
    return _client


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

    resp = _gemini().models.generate_content(
        model=s.chat_model,
        contents=user_content,
        config=types.GenerateContentConfig(
            # Anthropic 의 system= 에 해당한다. 이 프롬프트가 NO_ANSWER 를 강제한다.
            system_instruction=SYSTEM_PROMPT,
            max_output_tokens=s.max_tokens,
        ),
    )
    # resp.text 는 None 일 수 있다(안전 필터 차단 등). 그대로 쓰면 아래 in 검사에서 터진다.
    answer = (resp.text or "").strip()

    if FALLBACK_TOKEN in answer or not answer:
        return fallback_message, True
    return answer, False
