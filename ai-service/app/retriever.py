"""임베딩 생성과 벡터 검색.

W4에서 여기에 키워드(BM25) 검색과 리랭커를 추가하고,
평가 점수를 before/after로 비교하는 것이 이 프로젝트의 핵심 스토리다.
그래서 search()의 시그니처를 미리 열어둔다.
"""
from __future__ import annotations

from uuid import UUID

from google import genai
from google.genai import types

from .config import get_settings
from .db import cursor
from .schemas import Source

_client: genai.Client | None = None


def _gemini() -> genai.Client:
    global _client
    if _client is None:
        s = get_settings()
        if not s.google_api_key:
            raise RuntimeError("GOOGLE_API_KEY가 설정되지 않았습니다 (.env 확인)")
        _client = genai.Client(api_key=s.google_api_key)
    return _client


def embed(texts: list[str], *, task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
    """여러 텍스트를 배치로 임베딩. 순서는 입력과 동일하게 보장된다.

    task_type 을 왜 나누는가 — 이건 OpenAI 에는 없던 기능이다.
    같은 문장이라도 "검색될 문서"로 쓸 때와 "검색하는 질문"으로 쓸 때
    좋은 벡터의 모양이 다르다. 색인할 때는 RETRIEVAL_DOCUMENT,
    질문할 때는 RETRIEVAL_QUERY 를 주면 검색 품질이 올라간다.
    """
    if not texts:
        return []
    s = get_settings()
    out: list[list[float]] = []
    for i in range(0, len(texts), s.embedding_batch_size):
        batch = texts[i : i + s.embedding_batch_size]
        resp = _gemini().models.embed_content(
            model=s.embedding_model,
            contents=batch,
            config=types.EmbedContentConfig(
                task_type=task_type,
                # 기본 3072차원을 1536으로 잘라 쓴다. DB 컬럼이 VECTOR(1536)이라서.
                output_dimensionality=s.embedding_dim,
            ),
        )
        # 응답은 입력 순서 그대로 온다. .values 가 실제 float 리스트.
        out.extend(e.values for e in resp.embeddings)
    if len(out) != len(texts):
        # embedding-2 처럼 입력을 합쳐 1개만 돌려주는 모델을 쓰면 여기서 걸린다.
        # 조용히 뭉개진 채로 DB에 들어가는 것보다 지금 죽는 편이 낫다.
        raise RuntimeError(
            f"임베딩 개수가 입력과 다릅니다 (입력 {len(texts)}, 응답 {len(out)}). "
            f"모델({s.embedding_model})이 입력을 합쳐서 처리하고 있는지 확인하세요."
        )
    return out


def embed_one(text: str) -> list[float]:
    """질문 임베딩. 색인용과 달리 RETRIEVAL_QUERY 를 쓴다."""
    return embed([text], task_type="RETRIEVAL_QUERY")[0]


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
