"""LLM-as-Judge — 생성된 답변을 채점한다 (W3).

이 파일이 왜 중요한가
─────────────────────────────────────────────────────────────────────────────
이 프로젝트의 최종 산출물은 "검색 방식을 바꾸기 <전/후> 품질 점수 비교표"다.
즉 여기서 나오는 숫자가 프로젝트의 결론 그 자체다. 채점이 틀리면 결론도 틀린다.

⚠️ 채점 모델은 <답변 생성 모델과 반드시 달라야 한다>
─────────────────────────────────────────────────────────────────────────────
답변을 만든 모델이 자기 답변을 채점하면 자기 것에 후한 점수를 준다(self-preference).
그런데 이 프로젝트에서는 단순한 편향을 넘어 <같은 실수를 반복>하는 게 더 큰 문제다:

  생성기가 환각을 낸 이유는 "그 문맥에서 그 문장이 근거에 맞다고 판단했기 때문"이다.
  같은 모델이 채점하면 같은 판단을 그대로 반복한다.
  → 반드시 잡아야 할 케이스에서 판정기가 가장 눈이 먼다.

그래서 이렇게 갈랐다 (2026-08-02 답변 생성이 Cloudflare 로 옮겨온 뒤 기준):
  답변 생성 : @cf/meta/llama-3.3-70b-instruct-fp8-fast   (Meta 계열)
  채점      : @cf/mistralai/mistral-small-3.1-24b-instruct (Mistral 계열)
제공자는 같아졌지만 <모델 계열이 다르다>. 가중치를 공유하지 않으므로
"같은 실수를 반복하는" 문제는 그대로 피한다.
⚠️ 답변 생성 모델을 바꿀 때 이 모델과 겹치지 않는지 반드시 확인할 것.

왜 이 모델인가 (2026-08-02 실측)
─────────────────────────────────────────────────────────────────────────────
정답이 정해진 한국어 3케이스(충실한 답 / 지어낸 답 / 절반만 맞는 답)로 후보를 걸렀다.

  mistral-small-3.1-24b : 1 / 0 / 0.5  전부 정확, 약 1000ms   ← 채택
  qwen3-30b-a3b-fp8     : 1 / 0 / 0.5  정확하지만 2.9~5.3초
  llama-3.3-70b-fast    : 1 / 0 / 0    "절반만 맞는 답"을 0으로 깎는다
  gpt-oss-120b          : JSON 파싱 실패
  glm-5.2               : 무료 플랜에서 403

⚠️ 아직 <사람 라벨과 대조하지 않았다>. "채점을 어떻게 믿느냐"에 답하려면
   사람이 매긴 30~50건과의 일치율(카파)이 필요하다. TODO(W4).
   지금 있는 근거는 위 3케이스뿐이고, 그건 "쓸 수 있다"까지만 말해준다.
"""
from __future__ import annotations

import json
import logging

from pydantic import BaseModel

from . import cf
from .config import get_settings
from .retriever import fetch_contents
from .schemas import Source

_log = logging.getLogger(__name__)

class Scores(BaseModel):
    """채점 결과 한 건.

    두 지표를 <한 번의 호출>로 받는다. 나눠 부르면 호출 수가 2배가 되는데,
    두 판단이 같은 재료(질문·근거·답변)를 보므로 나눌 이유가 없다.
    """

    faithfulness: float
    relevancy: float
    reason: str = ""


SYSTEM_PROMPT = """당신은 문서 기반 챗봇의 답변을 채점하는 평가자입니다.

두 가지를 각각 0.0~1.0 으로 채점하세요.

[충실성 faithfulness] — 답변이 <근거>에 실제로 적혀 있는 내용만 말하는가
- 1.0 : 답변의 모든 주장이 근거에 있다
- 0.5 : 일부는 근거에 있고 일부는 근거에 없다
- 0.0 : 근거에 없는 내용을 지어냈다
⚠️ 답변이 그럴듯한지, 세상의 상식에 맞는지는 보지 마세요.
   오직 "이 근거에 적혀 있는가"만 보세요. 사실이더라도 근거에 없으면 깎아야 합니다.

[관련성 relevancy] — 답변이 <질문>에 대한 답이 되는가
- 1.0 : 질문에 정확히 답했고 <기대 답변>과 일치한다
- 0.5 : 질문과 관련은 있으나 일부만 답했거나 기대 답변과 어긋난다
- 0.0 : 질문에 답하지 않았다
⚠️ 표현이 달라도 뜻이 같으면 감점하지 마세요.

반드시 아래 JSON 형식으로만 답하세요. 다른 말을 덧붙이지 마세요.
{"faithfulness": 숫자, "relevancy": 숫자, "reason": "한국어 한 문장"}"""


def _extract_json(raw: str) -> dict | None:
    """모델이 뱉은 텍스트에서 JSON 만 꺼낸다.

    왜 그냥 json.loads 하면 안 되나 — 모델마다 버릇이 다르다.
    ```json 코드펜스를 씌우기도 하고, 앞뒤에 설명을 붙이기도 한다.
    Cloudflare 의 이 모델들은 구조화 출력(JSON 스키마 강제)을 Gemini 처럼
    보장해주지 않으므로, 받는 쪽에서 방어해야 한다.
    """
    text = raw.strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    # 앞뒤 잡소리를 버리고 첫 '{' 부터 마지막 '}' 까지만 남긴다.
    if "{" in text and "}" in text:
        text = text[text.index("{") : text.rindex("}") + 1]
    try:
        d = json.loads(text)
        return d if isinstance(d, dict) else None
    except Exception:  # noqa: BLE001 - 형식이 깨졌으면 결론은 하나다: 채점 실패
        return None


def _clamp(v: object) -> float | None:
    """모델이 준 점수를 0.0~1.0 사이 실수로 정리한다.

    문자열("0.5")로 주거나 1보다 큰 값을 주는 모델이 있다.
    DB 컬럼이 NUMERIC(4,3) 이라 범위를 벗어나면 INSERT 에서 터진다.
    """
    try:
        f = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, f))


def score(question: str, ground_truth: str, sources: list[Source], answer: str) -> Scores | None:
    """답변 한 건을 채점한다. 실패하면 None.

    None 은 "0점"이 아니라 "채점하지 못했다"이다. 호출하는 쪽이
    평균에서 <제외>해야 한다. 0점으로 처리하면 채점 실패가 품질 저하로 둔갑한다.
    """
    s = get_settings()

    # ⚠️ preview(앞 200자)가 아니라 <전체 본문>을 준다.
    #
    # 🐛 여기서 실제로 심각한 버그를 냈다(2026-08-02).
    #    생성 모델은 fetch_contents 로 <전체 본문>을 보고 답하는데(generator._build_context),
    #    채점자는 preview 만 봤다. 그래서 청크 250번째 글자에 있던 "HR-310" 을
    #    생성 모델은 읽고 정확히 답했는데 채점자는 못 보고
    #    <"근거에 없는 내용을 지어냈다"며 0점>을 줬다.
    #
    #    답변은 "양식 HR-310을 사용해야 합니다"로 완벽했다. 채점만 틀린 것이다.
    #    청크가 500자 단위라 <절반 이상이 채점자에게 안 보였다>.
    #
    # 교훈: <채점자는 생성 모델이 본 것과 정확히 같은 것을 봐야 한다.>
    #       하나라도 덜 보면 "근거에 없다"는 판정이 거짓이 된다.
    contents = fetch_contents([src.chunk_id for src in sources])
    context = "\n\n".join(
        f"[근거 {i}] (출처: {src.filename})\n{contents.get(src.chunk_id, src.preview)}"
        for i, src in enumerate(sources, 1)
    )
    user = (
        f"<근거>\n{context}\n</근거>\n\n"
        f"<질문>\n{question}\n\n"
        f"<기대 답변>\n{ground_truth}\n\n"
        f"<채점할 답변>\n{answer}"
    )

    try:
        result = cf.run(s.judge_model, {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            # 결과 JSON 은 100토큰이면 충분한데 넉넉히 준다.
            # 모자라면 JSON 이 중간에 끊겨 파싱에 실패하고, 그 질문은 점수 없이 날아간다.
            "max_tokens": 1024,
            # 🔴 채점자는 무조건 0 이다. 같은 답변에 매번 다른 점수를 주는 자를
            #    기준으로 삼을 수는 없다. 여기서 흔들리면 <모든 비교가 무의미해진다.>
            "temperature": s.judge_temperature,
        })
    except Exception as e:  # noqa: BLE001 - 한 건 실패가 실행 전체를 죽이면 안 된다
        _log.warning("채점 호출 실패: %s: %s", type(e).__name__, e)
        return None

    raw = cf.text_of(result)
    d = _extract_json(raw)
    if d is None:
        # ⚠️ 로그에 <모델이 뱉은 텍스트>를 남긴다. 예전엔 응답 dict 전체를 찍었는데,
        #    그러면 앞부분이 메타데이터로 채워져 정작 본문이 안 보였다.
        #    실패를 고치려면 "무엇을 뱉었길래 파싱이 안 됐는지"가 보여야 한다.
        _log.warning("채점 응답을 JSON 으로 읽지 못했습니다. 원문=%r", raw[:300] or "(비어 있음)")
        return None

    faith, rel = _clamp(d.get("faithfulness")), _clamp(d.get("relevancy"))
    if faith is None or rel is None:
        _log.warning("채점 점수가 숫자가 아닙니다: %s", d)
        return None

    return Scores(faithfulness=faith, relevancy=rel, reason=str(d.get("reason", ""))[:500])
