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

from app import db, metrics
from app.config import get_settings

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
    # 🔴 여기는 lifespan 을 안 거친 <맨 루프>라 anyio 기본값이 그대로 보인다.
    #    2026-09-10 S2 를 잰 조건이 이 값(40)이었으므로 before/after 를 대조할 때
    #    필요한 숫자다. 다만 <실패로 만들지 않는다>: 이제 상한은 lifespan 이
    #    설정값으로 덮어쓰므로, anyio 가 기본값을 바꿔도 우리 동작은 안 바뀐다.
    #    안 바뀐 것을 빨간불로 부르면 이 저장소가 이미 겪은 "정상을 실패로 부르는
    #    검사" 가 하나 더 느는 것이다. 실제로 지켜야 할 약속은 아래 ⑤ 가 검사한다.
    print(f"  ..   anyio 기본값(참고, S2 는 이 값으로 쟀다) total_tokens={total}")

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
            "alldap_db_pool_size",
            "alldap_db_pool_max",
            "alldap_db_pool_available",
            "alldap_db_pool_requests_waiting",
            "alldap_db_pool_open",
        ):
            check(f"본문에 {name}", name in body)

        # ⑤ 🔴 이 검사가 이 파일의 핵심이 됐다. lifespan 이 상한을 <실제로> 올렸는가.
        #    TestClient 를 with 로 써야 lifespan 이 돈다(그냥 호출하면 안 돈다).
        #    안 돌면 상한은 anyio 기본값 그대로인데 설정 파일에는 80 이 적혀 있어,
        #    "80 으로 올리고 쟀다" 는 <틀린 문장>이 리포트에 남는다.
        want = get_settings().anyio_max_threads
        got = _value("alldap_anyio_threads_total")
        check(f"lifespan 적용 후 total == 설정값({want})", got == float(want), f"(={got})")

        # ⑥ 풀을 안 만졌으니 open == 0. 🔴 "풀이 없다" 와 "풀이 비었다" 를 가르는
        #    지표라, 이게 1 로 나오면 <지표를 긁는 행위가 풀을 만든 것>이다.
        check("DB 풀 미사용 시 open == 0", _value("alldap_db_pool_open") == 0.0,
              f"(={_value('alldap_db_pool_open')})")
        check("지표 수집이 풀을 만들지 않는다", db._pool is None)

    # ⑦ 가짜 풀을 끼워 매핑을 확인한다. DB 없이 도는 검사라 CI 에서 돈다.
    #    네 값이 서로 <다른 자리>로 가는지를 본다 — 뒤바뀌어도 그래프는 멀쩡해 보이고,
    #    그때 "커넥션을 기다렸다" 를 "커넥션이 놀았다" 로 읽게 된다.
    class _StubPool:
        def get_stats(self) -> dict:
            return {"pool_size": 7, "pool_max": 10, "pool_available": 2,
                    "requests_waiting": 5, "requests_num": 123}

    db._pool = _StubPool()
    try:
        metrics.sample_db_pool()
        check("open == 1", _value("alldap_db_pool_open") == 1.0)
        check("size == 7", _value("alldap_db_pool_size") == 7.0)
        check("max == 10", _value("alldap_db_pool_max") == 10.0)
        check("available == 2", _value("alldap_db_pool_available") == 2.0)
        check("waiting == 5", _value("alldap_db_pool_requests_waiting") == 5.0)
    finally:
        db._pool = None

    # ⑧ 풀이 사라지면 <다섯 개 전부> 0 으로 돌아가야 한다.
    #    🔴 open 만 검사하면 안 된다. 게이지는 마지막 값을 계속 들고 있어서,
    #       sample_db_pool 이 open 만 내리고 나머지를 그냥 두면 이 검사는 통과하면서
    #       waiting 은 위 ⑦ 의 5.0 인 채로 남는다. 실제로 그 상태였다(2026-09-12).
    #       그때 계기판은 "지금 5건이 기다린다" 와 "옛날에 5건이었다" 를 같은 값으로 말한다.
    #       "정상을 실패로 부르는 검사" 의 반대편, <고쳐졌다고 믿게 만드는 검사> 다.
    metrics.sample_db_pool()
    check("풀이 없어지면 open == 0", _value("alldap_db_pool_open") == 0.0)
    for name in ("size", "max", "available", "requests_waiting"):
        got = _value(f"alldap_db_pool_{name}")
        check(f"풀이 없어지면 {name} == 0 (옛 값이 안 남는다)", got == 0.0, f"(={got})")

    print(f"\n{'실패 ' + ', '.join(_failures) if _failures else '전부 통과'}")
    return 1 if _failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
