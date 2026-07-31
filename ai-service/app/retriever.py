"""임베딩 생성과 벡터 검색.

W4에서 여기에 키워드(BM25) 검색과 리랭커를 추가하고,
평가 점수를 before/after로 비교하는 것이 이 프로젝트의 핵심 스토리다.
그래서 search()의 시그니처를 미리 열어둔다.
"""
from __future__ import annotations

from uuid import UUID

from openai import OpenAI

from .config import get_settings
from .db import cursor
from .schemas import Source

_client: OpenAI | None = None


def _openai() -> OpenAI:
    global _client
    if _client is None:
        s = get_settings()
        if not s.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY가 설정되지 않았습니다 (.env 확인)")
        _client = OpenAI(api_key=s.openai_api_key)
    return _client


def embed(texts: list[str]) -> list[list[float]]:
    """여러 텍스트를 배치로 임베딩. 순서는 입력과 동일하게 보장된다."""
    if not texts:
        return []
    s = get_settings()
    out: list[list[float]] = []
    for i in range(0, len(texts), s.embedding_batch_size):
        batch = texts[i : i + s.embedding_batch_size]
        resp = _openai().embeddings.create(model=s.embedding_model, input=batch)
        # API가 순서를 보장하지만, 방어적으로 index 기준 정렬
        out.extend(d.embedding for d in sorted(resp.data, key=lambda d: d.index))
    return out


def embed_one(text: str) -> list[float]:
    return embed([text])[0]


def search(
    bot_id: UUID,
    query: str,
    *,
    top_k: int | None = None,
    max_distance: float | None = None,
) -> list[Source]:
    """질문과 가까운 청크를 찾는다. 관련도 낮은 건 잘라낸다."""
    s = get_settings()
    top_k = top_k or s.top_k
    max_distance = s.max_distance if max_distance is None else max_distance

    qvec = embed_one(query)

    # <=> 는 pgvector의 코사인 거리 연산자 (0에 가까울수록 유사)
    sql = """
        SELECT c.id, c.document_id, d.filename, c.content,
               c.embedding <=> %s::vector AS distance
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE c.bot_id = %s AND c.embedding IS NOT NULL
        ORDER BY distance
        LIMIT %s
    """
    with cursor() as cur:
        cur.execute(sql, (qvec, bot_id, top_k))
        rows = cur.fetchall()

    sources: list[Source] = []
    for chunk_id, doc_id, filename, content, distance in rows:
        if distance > max_distance:
            continue
        sources.append(
            Source(
                chunk_id=chunk_id,
                document_id=doc_id,
                filename=filename,
                score=round(1.0 - float(distance), 4),
                preview=content[:200],
            )
        )
    return sources


def fetch_contents(chunk_ids: list[UUID]) -> dict[UUID, str]:
    """근거 청크의 전체 본문을 가져온다 (preview는 잘려 있으므로)."""
    if not chunk_ids:
        return {}
    with cursor() as cur:
        cur.execute("SELECT id, content FROM chunks WHERE id = ANY(%s)", (chunk_ids,))
        return {row[0]: row[1] for row in cur.fetchall()}
