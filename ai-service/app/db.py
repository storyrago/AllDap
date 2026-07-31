"""DB 커넥션 풀. psycopg3 + pgvector."""
from __future__ import annotations

from contextlib import contextmanager

from psycopg_pool import ConnectionPool
from pgvector.psycopg import register_vector

from .config import get_settings

_pool: ConnectionPool | None = None


def _configure(conn) -> None:
    register_vector(conn)


def get_pool() -> ConnectionPool:
    global _pool
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
