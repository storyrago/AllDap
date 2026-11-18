"""app/db.py 의 async 풀 생명주기 점검. DB 가 <없어도> 돈다(CI 용).

실행:
    cd ai-service && .venv/bin/python -m tools.adb_check

무엇을 재나
─────────────────────────────────────────────────────────────────────────────
① 풀을 열기 전에 acursor() 를 부르면 <한국어로> 죽는다(조용히 풀을 만들지 않는다).
② DB 가 꺼져 있어도 open_async_pool() 이 기동을 막지 않는다(wait=False).
   지금 uvicorn 은 DB 없이도 뜬다. 그 동작을 바꾸지 않는다는 약속이다.
③ 두 번 열어도 풀은 하나, 닫으면 None 으로 돌아간다.
"""
from __future__ import annotations

import asyncio

from app import db

_failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK  ' if ok else 'FAIL'} {name} {detail}")
    if not ok:
        _failures.append(name)


# `async def` 로 만든 함수는 부르기만 해서는 실행되지 않고 <코루틴 객체>를 돌려준다.
# 안에서 `await` 를 쓰려면 이 함수 자체가 async 여야 하고, 실제 실행은 아래 main 의
# asyncio.run() 이 이벤트 루프를 하나 만들어 끝날 때까지 돌려 준다.
async def _scenario() -> None:
    # ① `async with` 는 `with` 의 async 판이다. 들어갈 때·나올 때 await 가 필요한
    #    자원(여기선 풀에서 연결 빌리기)에 쓴다.
    try:
        async with db.acursor():
            pass
        check("열기 전 acursor 는 예외", False, "(예외가 안 났다)")
    except RuntimeError as e:
        check("열기 전 acursor 는 예외", "lifespan" in str(e), f"({e})")

    check("열기 전 stats 는 None", db.async_pool_stats() is None)
    # ② DB 가 없어도 이 await 가 <바로> 끝나야 한다. 오래 걸리면 기동이 그만큼 늦는다.
    await db.open_async_pool()
    first = db._apool
    await db.open_async_pool()
    check("두 번 열어도 풀은 하나", db._apool is first and first is not None)
    stats = db.async_pool_stats()
    check("연 뒤 stats 의 pool_max == 10", stats is not None and stats.get("pool_max") == 10, f"({stats})")

    # ④ DB 가 <닿으면> 실제로 한 번 읽는다. 위 ①~③ 은 연결 없이도 통과하므로,
    #    _aconfigure(register_vector_async) 를 빠뜨려도 초록이 된다. 그 구멍을 여기서 막는다.
    #    🔴 DB 가 없으면 "통과" 가 아니라 "건너뜀" 으로 따로 찍는다. 재지 않은 것과
    #       재서 통과한 것은 다른 사실이다(CI 에는 DB 가 없어 늘 건너뛴다).
    try:
        # wait() 는 min_size(1) 개의 연결이 실제로 생길 때까지 기다린다. 못 생기면 PoolTimeout.
        await db._apool.wait(timeout=3.0)
        reachable = True
    except Exception as e:  # noqa: BLE001 — PoolTimeout 외에 무엇이 와도 "닿지 않음" 이다
        reachable = False
        print(f"  ..   DB 에 닿지 않는다 — 실제 질의는 건너뛴다(통과가 아니다) ({type(e).__name__})")
    if reachable:
        async with db.acursor() as cur:
            await cur.execute("SELECT '[1,2,3]'::vector")
            row = await cur.fetchone()
        # 타입 등록이 안 됐으면 '[1,2,3]' 문자열이 온다. 등록됐으면 숫자 배열이다.
        got = row[0]
        check("acursor 로 읽은 vector 가 문자열이 아니다(register_vector_async)",
              not isinstance(got, str) and list(got) == [1.0, 2.0, 3.0], f"({type(got).__name__}: {got!r})")

    await db.close_async_pool()
    check("닫으면 None", db._apool is None)


def main() -> int:
    print("app/db.py async 풀 점검")
    asyncio.run(_scenario())
    print(f"\n{'실패 ' + ', '.join(_failures) if _failures else '전부 통과'}")
    return 1 if _failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
