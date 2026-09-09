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

import time

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
    url = f"{s.cf_base_url}/accounts/{s.cf_account_id}/ai/run/{model}"

    started = time.perf_counter()
    resp = _client().post(url, json=payload)
    _latencies.setdefault(model, []).append((time.perf_counter() - started) * 1000)
    resp.raise_for_status()          # 4xx·5xx 는 여기서 예외
    body = resp.json()
    if not body.get("success", False):
        raise RuntimeError(f"Cloudflare 호출 실패 ({model}): {body.get('errors')}")
    result = body.get("result") or {}
    _record_neurons(model, result, resp)
    return result


# ── 뉴런(비용) 집계 ────────────────────────────────────────────────────
#
# 🔴 응답이 <호출당 정확한 뉴런>을 준다: result.usage.neurons (헤더 cf-ai-neurons 도 같다).
#    2026-08-13 에 발견했다. 그전까지 AGENTS.md 는 "대시보드를 사람이 읽어야 한다"고
#    적어놨고, 실제로 그것 때문에 비용을 <추정으로만> 남긴 결정이 여럿 있었다.
#    (리랭커를 "수십 뉴런일 것"으로 추정해 켰는데 실측은 11 뉴런, 평가 1회의 0.94% 였다)
#
# ⚠️ 하루 한도(10,000 뉴런)를 이 값으로 <예측할 수는 없다.> 이 프로세스가 쓴 것만 세기
#    때문이다. 다른 프로세스·다른 날의 사용량은 모른다. 여기서 아는 것은
#    "이 실행이 얼마를 썼는가" 하나이고, 그것만으로도 설정 비교에는 충분하다.
#
# ⚠️ 스레드 안전하지 않다. FastAPI 가 스레드풀에서 돌리므로 동시 호출이 겹치면
#    합계가 조금 틀릴 수 있다. <로깅 용도>라 근사치로 충분하다 —
#    정확한 청구액이 필요하면 대시보드를 봐야 한다.
_neurons: dict[str, float] = {}


def _record_neurons(model: str, result: dict, resp=None) -> None:
    """⚠️ 응답 <모양이 모델 계열마다 다르다> (2026-08-13 실측).

        생성·채점·리랭커  result.usage.neurons
        임베딩            result.meta.neurons   ← usage 가 아예 없다
        전부 공통         헤더 cf-ai-neurons    ← 단 소수점 2자리로 <반올림>된다

    본문을 먼저 보는 이유는 정밀도다. 임베딩 1회가 0.0236 인데 헤더는 0.02 로 오므로,
    수백 번 누적하면 오차가 눈에 띄게 쌓인다.
    헤더는 <새 모델이 또 다른 모양을 줄 때>를 위한 마지막 그물이다 —
    한쪽만 보다가 임베딩이 통째로 빠진 것을 이미 한 번 겪었다.
    """
    n = (result.get("usage") or {}).get("neurons")
    if n is None:
        n = (result.get("meta") or {}).get("neurons")
    if n is None and resp is not None:
        try:
            n = float(resp.headers.get("cf-ai-neurons", ""))
        except (TypeError, ValueError):
            n = None
    if isinstance(n, (int, float)):
        _neurons[model] = _neurons.get(model, 0.0) + float(n)


# ── 지연(ms) 집계 ──────────────────────────────────────────────────────
#
# 왜 뉴런과 <따로> 두나: 뉴런은 실패한 호출에 없지만 지연은 실패한 호출에도 있다.
# 한 dict 에 뭉치면 "느렸다" 와 "비쌌다" 가 같은 자리에 섞인다.
#
# ⚠️ 누적은 <프로세스 수명 동안> 쌓인다. 리셋 함수를 두지 않은 것은 일부러다,
#    "리셋했나?" 를 사람이 기억해야 하는 순간 그 측정은 못 믿는다.
#    측정 구간의 시작은 <프로세스를 다시 띄우는 것>으로 만든다(s1_baseline 이 그렇게 한다).
#
# ⚠️ 스레드 안전하지 않다. _neurons 와 같은 이유이고 같은 한계다(측정용 근사치).
_latencies: dict[str, list[float]] = {}


def latency_percentiles() -> dict[str, dict[str, float]]:
    """모델별 호출 수와 p50/p95/p99(ms).

    ⚠️ 평균을 안 준다. 평균은 느린 꼬리를 감춘다,
       이 저장소는 avg_faithfulness 로 이미 한 번 데였다(생존 편향).
    """
    out: dict[str, dict[str, float]] = {}
    for model, values in _latencies.items():
        ordered = sorted(values)

        def pct(p: float, ordered: list[float] = ordered) -> float:
            # nearest-rank. 표본이 적을 때 보간이 <있지도 않은 값>을 만들지 않는다.
            idx = max(0, min(len(ordered) - 1, int(-(-len(ordered) * p // 100)) - 1))
            return ordered[idx]

        out[model] = {
            "count": len(ordered),
            "p50": pct(50),
            "p95": pct(95),
            "p99": pct(99),
        }
    return out


def neurons_used() -> dict[str, float]:
    """모델별 누적 뉴런. reset_neurons() 이후의 값이다."""
    return dict(_neurons)


def reset_neurons() -> None:
    """누적을 0 으로. 측정 구간의 <시작>에 부른다."""
    _neurons.clear()


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


def finish_reason(result: dict) -> str | None:
    """생성이 <왜> 끝났는지 돌려준다. `"length"` 면 max_tokens 에 걸려 잘린 것이다.

    ⚠️ 이 값을 왜 봐야 하나: 잘린 답변은 <내용이 비어 보일 수 있다.> 그걸 그냥
       "빈 답변"으로 다루면 "문서에 답이 없다"와 구분이 안 된다. 원인이 정반대인
       두 사실이 같은 결과로 뭉개지는 것이다 (generator.generate 주석 참고).

    ⚠️ `None` 은 "잘리지 않았다"가 아니라 <모른다>는 뜻이다. Workers AI 고유 형식
       (`result["response"]`)만 오는 응답에는 이 값이 없다. text_of 가 응답 모양이
       두 가지라고 말하는 것과 같은 이유이며, 그래서 이 함수도 여기 있다 —
       응답의 모양을 아는 것은 이 파일의 일이다.
    """
    choices = result.get("choices")
    if isinstance(choices, list) and choices:
        reason = choices[0].get("finish_reason")
        if isinstance(reason, str):
            return reason
    return None
