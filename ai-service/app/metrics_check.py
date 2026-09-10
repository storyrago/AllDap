"""app/metrics.py 자체 점검. LLM 도 DB 도 없이 돈다.

실행:
    cd ai-service && .venv/bin/python -m app.metrics_check

무엇을 재나
─────────────────────────────────────────────────────────────────────────────
"지표가 나온다" 가 아니라 <숫자가 진짜 스레드풀 점유를 따라가는가> 를 잰다.
S2 의 1순위 가설(anyio 스레드풀 40 이 먼저 찬다)은 이 숫자 하나로 판정되므로,
이 숫자가 굳어 있으면 <가설이 틀린 것>과 <계측이 고장 난 것>이 같은 그림으로 보인다.
이 저장소가 반복해 걸린 부류다(원인이 다른 두 사실을 같은 값으로 뭉개는 것).
"""
from __future__ import annotations

import time

import anyio
import anyio.to_thread

from app import metrics

_failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK  ' if ok else 'FAIL'} {name} {detail}")
    if not ok:
        _failures.append(name)


def _value(name: str) -> float:
    """레지스트리에서 지표 하나의 현재 값을 읽는다."""
    from prometheus_client import REGISTRY

    got = REGISTRY.get_sample_value(name)
    return -1.0 if got is None else got


async def _scenario() -> None:
    # ① 아무도 안 쓸 때: borrowed 0, total 40
    metrics.sample_anyio_threads()
    check("유휴 borrowed == 0", _value("alldap_anyio_threads_borrowed") == 0.0,
          f"(={_value('alldap_anyio_threads_borrowed')})")
    total = _value("alldap_anyio_threads_total")
    # 🔴 40 은 <설정값이 아니라 anyio 기본값>이다. 버전이 올라가 이 값이 바뀌면
    #    Grafana 의 "40 에 붙었다" 판정이 조용히 거짓이 된다. 그래서 검사로 못 박는다.
    check("total_tokens == 40 (anyio 기본값)", total == 40.0, f"(={total})")

    # ② 스레드 3개를 점유한 상태: borrowed 가 따라 올라간다
    async def occupy() -> None:
        await anyio.to_thread.run_sync(lambda: time.sleep(0.5))

    async with anyio.create_task_group() as tg:
        for _ in range(3):
            tg.start_soon(occupy)
        await anyio.sleep(0.2)
        metrics.sample_anyio_threads()
        borrowed = _value("alldap_anyio_threads_borrowed")
        check("점유 중 borrowed == 3", borrowed == 3.0, f"(={borrowed})")


def main() -> int:
    print("app/metrics.py 자체 점검")
    anyio.run(_scenario)

    # ③ 루프 밖에서 부르면 <죽어야 한다>. 이 제약을 검사로 남기지 않으면
    #    나중에 누가 /internal/metrics 를 `def` 로 바꿔도 아무도 모르고,
    #    부하 한가운데서 지표 엔드포인트만 500 을 낸다.
    try:
        metrics.sample_anyio_threads()
        check("이벤트 루프 밖에서는 예외", False, "(예외가 안 났다)")
    except Exception as exc:  # noqa: BLE001
        check("이벤트 루프 밖에서는 예외", True, f"({type(exc).__name__})")

    # ④ 라우트가 실제로 200 을 주고, 지표 이름 4개가 다 있는가.
    #    🔴 모듈 단위 검사만으로는 <라우트를 async def 로 뒀는가> 를 못 본다.
    #       그게 이 PR 에서 가장 조용히 깨지는 자리다.
    from fastapi.testclient import TestClient

    from app.main import app  # noqa: PLC0415  (지표 등록 뒤에 import 해야 한다)

    with TestClient(app) as client:
        resp = client.get("/internal/metrics")
        check("GET /internal/metrics == 200", resp.status_code == 200, f"({resp.status_code})")
        body = resp.text
        for name in (
            "alldap_anyio_threads_borrowed",
            "alldap_anyio_threads_total",
            "alldap_chat_duration_seconds",
            "alldap_chat_inflight",
        ):
            check(f"본문에 {name}", name in body)

    print(f"\n{'실패 ' + ', '.join(_failures) if _failures else '전부 통과'}")
    return 1 if _failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
