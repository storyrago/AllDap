"""DB 커넥션 풀. psycopg3 + pgvector."""
from __future__ import annotations

import threading
from contextlib import contextmanager

from psycopg_pool import ConnectionPool
from pgvector.psycopg import register_vector

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
       기동 직후에는 없는 것이 정상이고, 그때 0 을 내보내면 "상한이 0" 이라는 거짓말이
       된다. 부르는 쪽(metrics.sample_db_pool)이 이 둘을 다른 값으로 그린다.

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
