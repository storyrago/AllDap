"""app/cf.py 의 <응답 판정> 점검. 네트워크도 Cloudflare 키도 없이 돈다.

실행:
    cd ai-service && .venv/bin/python -m tools.cf_check

왜 이 파일이 있나
─────────────────────────────────────────────────────────────────────────────
채팅을 async 로 바꾸면서 Cloudflare 를 부르는 길이 둘(run · arun)이 된다.
두 길이 <같은 판정>을 해야 한다: 지연 기록 → 상태코드 → success:false → 뉴런 기록.
한쪽만 고쳐지면 채팅 비용만 조용히 틀리게 기록된다(임베딩 뉴런이 통째로 빠진 일을
이미 겪었다). 그래서 판정을 _finish 하나로 모으고, 그 함수를 여기서 못박는다.
"""
from __future__ import annotations

import time

import httpx

from app import cf

_failures: list[str] = []
_REQ = httpx.Request("POST", "http://cf.test/run")
OK_BODY = {"success": True, "result": {"response": "hi", "usage": {"neurons": 1.5}}}
FAIL_BODY = {"success": False, "errors": [{"message": "bad"}]}


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK  ' if ok else 'FAIL'} {name} {detail}")
    if not ok:
        _failures.append(name)


def _resp(status: int, body: dict) -> httpx.Response:
    # raise_for_status() 는 응답에 request 가 붙어 있어야 동작한다(httpx 규칙).
    return httpx.Response(status, json=body, request=_REQ)


def _outcome(call) -> str:
    """결과를 <문자열 하나>로 접는다. 동기·async 결과를 == 로 비교하려는 것이다."""
    try:
        result = call()
    except httpx.HTTPStatusError:
        return "HTTPStatusError"
    except RuntimeError:
        return "RuntimeError"
    return f"ok:{result.get('response')}"


def _check_finish() -> None:
    model = "@test/finish"
    started = time.perf_counter()
    check("성공 → result 를 돌려준다",
          _outcome(lambda: cf._finish(model, _resp(200, OK_BODY), started)) == "ok:hi")
    check("성공 → 뉴런 1.5 기록", cf.neurons_used().get(model) == 1.5)
    check("HTTP 200 + success:false → RuntimeError",
          _outcome(lambda: cf._finish(model, _resp(200, FAIL_BODY), started)) == "RuntimeError")
    check("HTTP 500 → HTTPStatusError",
          _outcome(lambda: cf._finish(model, _resp(500, {}), started)) == "HTTPStatusError")
    # 🔴 실패한 호출도 지연에는 센다(느려서 터진 호출이야말로 지연 통계에 있어야 한다).
    check("실패한 호출도 지연 count 에 들어간다(3건)",
          cf.latency_percentiles()[model]["count"] == 3)
    check("실패한 호출은 뉴런에 안 들어간다", cf.neurons_used().get(model) == 1.5)


def main() -> int:
    print("app/cf.py 응답 판정 점검")
    _check_finish()
    print(f"\n{'실패 ' + ', '.join(_failures) if _failures else '전부 통과'}")
    return 1 if _failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
