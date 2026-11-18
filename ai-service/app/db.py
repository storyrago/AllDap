"""DB 커넥션 풀. psycopg3 + pgvector."""
from __future__ import annotations

import threading
from contextlib import asynccontextmanager, contextmanager

from psycopg_pool import AsyncConnectionPool, ConnectionPool
from pgvector.psycopg import register_vector, register_vector_async

from .config import get_settings

_pool: ConnectionPool | None = None
# 🔴 첫 생성만 보호하는 잠금. 없으면 <동시에 처음 들어온 요청들>이 각자 풀을 만들고
#    마지막 하나만 _pool 에 남는다. 나머지는 커넥션을 쥔 채 아무도 close() 하지
#    않는 유령이 된다. 스레드 상한을 40 -> 80 으로 올리면서 실제로 커질 수 있는
#    창이라 같이 막는다. 부수적으로 <지표도 이것 없이는 거짓말을 한다>:
#    pool_stats() 는 _pool 하나만 보므로, 유령 풀이 쓰는 커넥션은 어디에도 안 세진다.
_pool_lock = threading.Lock()


def _configure(conn) -> None:
    register_vector(conn)


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        with _pool_lock:
            # 잠금을 얻는 동안 다른 스레드가 이미 만들었을 수 있어 다시 본다.
            if _pool is None:
                s = get_settings()
                _pool = ConnectionPool(
                    s.database_url,
                    min_size=1,
                    max_size=10,
                    configure=_configure,
                    open=True,
                )
    return _pool


def pool_stats() -> dict[str, int] | None:
    """psycopg 풀의 현재 상태. 풀이 <아직 안 만들어졌으면> None.

    🔴 None 과 "전부 0" 은 다른 사실이라 섞지 않는다. 풀은 첫 DB 사용 때 만들어지므로
       기동 직후에는 없는 것이 정상이다. 그 둘을 가르는 것은 <값이 0 인지>가 아니라
       alldap_db_pool_open 이라는 별도 게이지다(metrics.sample_db_pool). 그래서
       풀이 없을 때 나머지 네 게이지는 0 으로 내려도 오독되지 않고, 오히려 내려야 한다
       - 안 내리면 꺼진 풀의 옛 waiting 값이 계기판에 계속 남는다.

    🔴 여기서 절대 get_pool() 을 부르면 안 된다. 그러면 <지표를 긁는 행위가> 풀을
       만들고(open=True 라 커넥션을 하나 실제로 연다), 그 대기가 이벤트 루프를 막는다.
       관측이 관측 대상을 바꾸는 자리다.

    ⚠️ psycopg_pool 의 get_stats() 는 잠금을 잡지 않고 deque 길이 두 개와 dict 복사만
       한다(3.3.1 소스 확인). 그래서 이벤트 루프에서 불러도 안전하다. 라이브러리를
       올릴 때 이 전제가 유지되는지 확인할 것.
    """
    if _pool is None:
        return None
    return _pool.get_stats()


@contextmanager
def cursor(commit: bool = False):
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            yield cur
        if commit:
            conn.commit()


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


# ── async 풀 (채팅 전용, 2026-11-18) ───────────────────────────────────
#
# 🔴 동기 풀과 <따로> 둔다. 동기 풀은 워커·평가·tools 가 쓰고, 이 풀은 async 채팅만 쓴다.
#    크기는 같게 둔다(10). 합쳐서 최대 20 연결 — 로컬 Postgres 기본 한도(100) 안이다.
#
# 🔴 lifespan 에서 연다(처음 쓸 때가 아니라). 여는 데 `await` 가 들어가서, 처음 쓸 때
#    만들면 첫 요청이 여는 도중 멈춘 사이 둘째 요청이 "풀이 없다" 고 보고 하나 더 만든다.
#    동기 풀은 그걸 threading.Lock 으로 막았다(get_pool). 여기서는 요청이 오기 <전에>
#    만들어 경쟁할 기회 자체를 없앤다. 또 async 풀은 만든 이벤트 루프에 묶이므로,
#    루프가 확실히 도는 lifespan 이 맞는 자리다.
_apool: AsyncConnectionPool | None = None


async def _aconfigure(conn) -> None:
    # 🔴 빠뜨리면 벡터가 문자열로 오가 검색이 깨진다(동기 판의 _configure 와 같은 일).
    #    async 연결에서는 타입 등록도 DB 왕복이라 await 해야 한다. 그래서 _configure 를
    #    그대로 못 쓰고 register_vector_async 를 부르는 async 판을 따로 둔다.
    await register_vector_async(conn)


async def open_async_pool() -> None:
    global _apool
    if _apool is not None:
        return
    s = get_settings()
    pool = AsyncConnectionPool(
        s.database_url,
        min_size=1,
        max_size=10,
        configure=_aconfigure,
        # open=False 로 만들고 아래에서 await 로 연다. async 풀을 생성자에서 열면
        # psycopg-pool 이 경고를 낸다(생성자는 await 할 수 없어서다).
        open=False,
    )
    # wait=False: DB 연결을 <기다리지 않는다>. DB 가 꺼져 있어도 서버는 뜨고,
    # 첫 채팅이 연결을 기다리다 실패한다. 지금 동기 풀의 동작과 같다.
    await pool.open(wait=False)
    _apool = pool


async def close_async_pool() -> None:
    global _apool
    if _apool is not None:
        await _apool.close()
        _apool = None


def async_pool_stats() -> dict[str, int] | None:
    """async 풀의 현재 상태. 안 열렸으면 None (pool_stats 와 같은 약속).

    ⚠️ AsyncConnectionPool.get_stats() 도 잠금 없이 dict 복사와 deque 길이만 읽는다
       (psycopg-pool 3.3.1: base.get_stats → pool_async._get_measures, 2026-11-18 확인).
       그래서 이벤트 루프에서 불러도 안전하다. 라이브러리를 올릴 때 다시 확인할 것.
    """
    if _apool is None:
        return None
    return _apool.get_stats()


# @asynccontextmanager 는 @contextmanager(위 cursor) 의 async 판이다.
# `yield` 앞이 "들어갈 때", 뒤가 "나올 때" 이고, 그 사이에 `async with` 블록 본문이 돈다.
# 안쪽에서 `async with` 로 연결·커서를 겹쳐 잡으므로, 블록이 어떻게 끝나든
# (정상·예외·취소) 바깥쪽부터 거꾸로 풀려 연결이 풀로 돌아간다.
@asynccontextmanager
async def acursor(commit: bool = False):
    """cursor() 의 async 판. `async with acursor() as cur:` 로 쓴다.

    `async with` 블록을 빠져나가는 순간 연결이 풀로 돌아간다 — 정상 종료·예외·취소 모두.
    """
    if _apool is None:
        # 🔴 여기서 풀을 <만들지 않는다>. 만들면 "lifespan 이 안 돌았다" 는 사실이
        #    조용히 묻히고, 루프 밖에서 만든 풀이 엉뚱한 루프에 묶일 수 있다.
        raise RuntimeError(
            "async DB 풀이 열려 있지 않습니다. app.main 의 lifespan 이 open_async_pool() 을 "
            "부르는지 확인하세요. 스크립트(tools/)에서는 동기 cursor() 를 쓰세요."
        )
    async with _apool.connection() as conn:
        async with conn.cursor() as cur:
            yield cur
        if commit:
            await conn.commit()
