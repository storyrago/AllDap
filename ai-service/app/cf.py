"""Cloudflare Workers AI 호출 공용부.

왜 이 파일이 생겼나
─────────────────────────────────────────────────────────────────────────────
Cloudflare 를 부르는 곳이 셋이 됐다 — 임베딩(retriever), 채점(judge), 답변 생성(generator).
같은 클라이언트 코드를 3벌 복사하면 반드시 한 곳이 어긋난다.
특히 <응답 형태가 두 가지>라는 사실(아래 text_of 참고)을 한 곳만 알고 있으면,
모르는 쪽에서 조용히 실패한다. 실제로 그 버그를 냈다.

여기 모으는 것은 딱 세 가지다:
  ① 커넥션 풀을 재사용하는 httpx 클라이언트
  ② 호출 + 실패 판정 (Cloudflare 는 HTTP 200 이어도 본문의 success 로 실패를 알린다)
  ③ 생성 계열 응답에서 텍스트를 꺼내기 (형태가 두 가지다)

<프롬프트나 모델 선택은 여기 두지 않는다.> 그건 각 모듈의 일이다.
이 파일은 "어떻게 부르는가"만 안다.
"""
from __future__ import annotations

import httpx

from .config import get_settings

_http: httpx.Client | None = None


def _client() -> httpx.Client:
    """커넥션 풀을 들고 있는 클라이언트 하나를 재사용한다.

    요청마다 새로 만들면 TCP 연결과 TLS 악수를 매번 다시 한다.
    `global` 은 "이 함수 안에서 바깥 변수를 <바꾸겠다>"는 선언이다. 안 쓰면 파이썬이
    _http 를 함수 안의 새 지역 변수로 만들어버려 캐시가 전혀 동작하지 않는다.
    """
    global _http
    s = get_settings()
    if not s.cf_account_id or not s.cf_api_token:
        raise RuntimeError(
            "CF_ACCOUNT_ID / CF_API_TOKEN 이 설정되지 않았습니다 (ai-service/.env 확인)"
        )
    if _http is None:
        _http = httpx.Client(
            headers={"Authorization": f"Bearer {s.cf_api_token}"},
            # 임베딩 배치 100개가 0.7초, 생성이 1~3초쯤 걸린다(실측).
            # 네트워크가 느릴 때를 감안해 넉넉히 준다.
            timeout=120.0,
        )
    return _http


def run(model: str, payload: dict) -> dict:
    """모델 하나를 호출하고 `result` 를 돌려준다. 실패하면 예외.

    ⚠️ Cloudflare 는 <HTTP 200 을 주고도> 본문의 `success: false` 로 실패를 알린다.
       상태 코드만 보면 실패를 성공으로 착각한다. 그래서 둘 다 확인한다.
    """
    s = get_settings()
    url = f"https://api.cloudflare.com/client/v4/accounts/{s.cf_account_id}/ai/run/{model}"

    resp = _client().post(url, json=payload)
    resp.raise_for_status()          # 4xx·5xx 는 여기서 예외
    body = resp.json()
    if not body.get("success", False):
        raise RuntimeError(f"Cloudflare 호출 실패 ({model}): {body.get('errors')}")
    return body.get("result") or {}


def text_of(result: dict) -> str:
    """생성 계열 응답에서 모델이 뱉은 텍스트를 꺼낸다.

    ⚠️ 같은 모델이 같은 엔드포인트로 <두 가지 모양>을 준다 (2026-08-02 실측).
        result["response"]                         ← Workers AI 고유 형식
        result["choices"][0]["message"]["content"]  ← OpenAI 호환 형식
    보통 둘 다 들어 있고 내용이 같지만, <한쪽이 비어 있는 응답이 실제로 왔다.>
    한쪽만 보던 코드가 채점 3건 중 1건을 통째로 날렸다.
    그래서 둘 다 훑고 먼저 <내용이 있는> 쪽을 쓴다.

    이 지식이 파일 하나에만 있으면 다른 호출부가 모르고 같은 버그를 낸다 —
    이 함수가 공용 모듈에 있는 이유가 그것이다.
    """
    text = result.get("response")
    if isinstance(text, str) and text.strip():
        return text

    choices = result.get("choices")
    if isinstance(choices, list) and choices:
        content = (choices[0].get("message") or {}).get("content")
        if isinstance(content, str) and content.strip():
            return content

    return ""
