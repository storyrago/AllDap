"""FriendliAI 서버리스 호출부.

왜 별도 파일인가
─────────────────────────────────────────────────────────────────────────────
`cf.py` 는 <Cloudflare 를 어떻게 부르는가>만 아는 파일이다. 그 안에 두 번째
제공자를 끼워 넣으면 "어느 분기가 어느 제공자였더라"가 시작된다. 제공자마다
파일을 하나씩 두고, 부르는 쪽이 고른다.

FriendliAI 는 <OpenAI 호환> API 라 Cloudflare 보다 오히려 단순하다.
Cloudflare 처럼 "HTTP 200 인데 본문 success 가 false" 같은 함정이 없고,
응답 형태도 한 가지다(choices[0].message.content).

⚠️ 이 파일은 지금 <실험용>이다. K-EXAONE 의 서버리스 Model API 가
   2026-08-20 에 종료 예정이라 프로덕션 경로로 쓰지 않는다. 자세한 근거는
   docs/decisions.md 참고.
"""
from __future__ import annotations

import httpx

from .config import get_settings

BASE_URL = "https://api.friendli.ai/serverless/v1"

_http: httpx.Client | None = None


def _client() -> httpx.Client:
    """커넥션 풀을 들고 있는 클라이언트 하나를 재사용한다(cf.py 와 같은 이유)."""
    global _http
    s = get_settings()
    if not s.friendli_token:
        raise RuntimeError(
            "FRIENDLI_TOKEN 이 설정되지 않았습니다 (ai-service/.env 확인)"
        )
    if _http is None:
        headers = {"Authorization": f"Bearer {s.friendli_token}"}
        # 팀을 안 적으면 <기본 팀>으로 청구된다. 팀이 하나면 없어도 되지만,
        # 여러 팀에 속하게 되면 어디로 청구되는지 모르게 되므로 적을 수 있게 열어둔다.
        if s.friendli_team_id:
            headers["X-Friendli-Team"] = s.friendli_team_id
        _http = httpx.Client(
            base_url=BASE_URL,
            headers=headers,
            timeout=httpx.Timeout(60.0, connect=10.0),
        )
    return _http


class Truncated(RuntimeError):
    """사고 토큰이 max_tokens 를 다 먹어 본문이 시작도 못 한 경우."""


def chat(model: str, messages: list[dict], *, temperature: float = 0.0,
         max_tokens: int = 2048) -> str:
    """chat/completions 를 부르고 <본문 텍스트만> 돌려준다.

    실패는 여기서 RuntimeError 로 바꾼다. 부르는 쪽이 httpx 예외를 알 필요가 없다.
    """
    r = _client().post(
        "/chat/completions",
        json={
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
    )
    if r.status_code != 200:
        # 402/403 은 결제수단 미등록·크레딧 소진일 가능성이 높다.
        # 그걸 "모델이 이상하다"로 오해하지 않도록 본문을 그대로 실어 보낸다.
        raise RuntimeError(f"FriendliAI HTTP {r.status_code}: {r.text[:300]}")
    data = r.json()
    try:
        choice = data["choices"][0]
        msg = choice["message"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"FriendliAI 응답 형태가 예상과 다릅니다: {data}") from e

    content = (msg.get("content") or "").strip()
    if content:
        return content

    # 🔴 여기가 중요하다. K-EXAONE 은 <추론 모델>이라 사고를 `reasoning_content` 로
    #    따로 내보내고, 그 사고가 max_tokens 를 먼저 다 먹으면 본문이 <시작도 못 한다>.
    #    이걸 그냥 빈 문자열로 돌려주면 부르는 쪽이 "모델이 답을 안 했다"고 오해한다 —
    #    실제로는 <우리가 토큰을 덜 준 것>이다. 둘은 완전히 다른 사실이다.
    #
    #    이 프로젝트는 이미 같은 함정을 겪었다: 답변이 잘려 빈 값이 되면
    #    generator 의 `not answer` 분기에 걸려 fallback 으로 둔갑했다
    #    (근거를 찾고도 "모른다"고 답하는 것). AGENTS.md 의 gemini-3.5-flash 항목 참고.
    #    그래서 조용히 넘기지 않고 <구분되는 예외>로 올린다.
    if choice.get("finish_reason") == "length":
        used = data.get("usage", {}).get("completion_tokens", "?")
        reasoning = (msg.get("reasoning_content") or msg.get("reasoning") or "")
        raise Truncated(
            f"본문이 시작되기 전에 잘렸습니다 (max_tokens={max_tokens}, 사용={used}). "
            f"이 모델은 사고 토큰이 max_tokens 를 함께 씁니다. "
            f"사고 앞부분: {reasoning[:80]!r}"
        )
    return ""


def close() -> None:
    global _http
    if _http is not None:
        _http.close()
        _http = None
