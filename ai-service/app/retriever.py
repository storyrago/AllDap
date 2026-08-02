"""임베딩 생성과 벡터 검색.

W4에서 여기에 키워드(BM25) 검색과 리랭커를 추가하고,
평가 점수를 before/after로 비교하는 것이 이 프로젝트의 핵심 스토리다.
그래서 search()의 시그니처를 미리 열어둔다.

임베딩 제공자: Cloudflare Workers AI (@cf/baai/bge-m3, 1024차원).
2026-08-02 에 Google Gemini 에서 옮겼다 — 이유는 config.py 주석 참고(약관·한도).
제공자 배치: 임베딩·답변생성·채점 = Cloudflare / 질문생성 = Gemini(evaluator.py).
"""
from __future__ import annotations

from uuid import UUID

import logging

from . import cf
from .config import get_settings
from .db import cursor
from .schemas import Source

_log = logging.getLogger(__name__)

def embed(texts: list[str], *, task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
    """여러 텍스트를 배치로 임베딩. 순서는 입력과 동일하게 보장된다.

    task_type 은 <지금 모델에서는 쓰이지 않는다.>
    Gemini 시절에는 "검색될 문서"와 "검색하는 질문"에 서로 다른 벡터 모양이 좋다고 보고
    RETRIEVAL_DOCUMENT / RETRIEVAL_QUERY 를 구분해 넘겼다. bge-m3 에는 그 개념이 없다.

    그런데도 파라미터를 남겨둔 이유: <호출부가 이미 그 정보를 알고 있기 때문>이다.
    W4 에서 임베딩 모델을 비교할 때 후보 중에는 질문에 "query: " 접두어를 요구하는
    모델이 있다(arctic-embed 계열). 지금 지웠다가 그때 다시 넣으면 호출부를 또 고쳐야 한다.
    ⚠️ 다만 <지금은 아무 효과가 없다>. 이 값이 검색 품질에 영향을 준다고 착각하지 말 것.
    """
    if not texts:
        return []
    s = get_settings()

    out: list[list[float]] = []
    for i in range(0, len(texts), s.embedding_batch_size):
        batch = texts[i : i + s.embedding_batch_size]
        out.extend(cf.run(s.embedding_model, {"text": batch})["data"])

    if len(out) != len(texts):
        # 입력을 합쳐 벡터 1개만 돌려주는 모델을 쓰면 여기서 걸린다
        # (Gemini 의 embedding-2 가 그렇다). 조용히 뭉개진 채로 DB 에 들어가는 것보다
        # 지금 죽는 편이 낫다. 제공자를 바꿔도 이 가드는 그대로 유효하다.
        raise RuntimeError(
            f"임베딩 개수가 입력과 다릅니다 (입력 {len(texts)}, 응답 {len(out)}). "
            f"모델({s.embedding_model})이 입력을 합쳐서 처리하고 있는지 확인하세요."
        )
    if out and len(out[0]) != s.embedding_dim:
        # 차원이 어긋나면 INSERT 할 때 psycopg 가 터지는데, 그때는 원인이 안 보인다.
        # 여기서 잡아야 "모델을 바꿨는데 embedding_dim 을 안 바꿨구나"가 바로 읽힌다.
        raise RuntimeError(
            f"임베딩 차원이 설정과 다릅니다 (설정 {s.embedding_dim}, 응답 {len(out[0])}). "
            f"config 의 embedding_dim 과 DB 의 VECTOR(n) 을 함께 확인하세요."
        )
    return out


def embed_one(text: str) -> list[float]:
    """질문 하나를 임베딩."""
    return embed([text], task_type="RETRIEVAL_QUERY")[0]


def search(
    bot_id: UUID,
    query: str,
    *,
    top_k: int | None = None,
    max_distance: float | None = None,
    reranker: bool | None = None,
) -> list[Source]:
    """질문과 가까운 청크를 찾는다. 관련도 낮은 건 잘라낸다.

    리랭커를 켜면 <벡터가 가져온 후보 안에서 순서만 바꾼다.>
    후보에 없는 청크는 살릴 수 없으므로 top_k 보다 넉넉히 뽑아(rerank_candidates)
    재정렬한 뒤 top_k 만 남긴다.

    ⚠️ max_distance 컷은 <리랭커와 무관하게 벡터 거리로> 그대로 적용한다.
       리랭커 점수로 자르지 않는 이유 둘:
         ① 점수 스케일이 다르다. 같은 0.55 가 전혀 다른 뜻이 된다.
         ② before/after 비교는 <변수를 하나만> 바꿔야 성립한다.
            리랭커를 켜면서 fallback 판정 기준까지 바뀌면 무엇 때문에 점수가 변했는지 모른다.
    """
    s = get_settings()
    top_k = top_k or s.top_k
    max_distance = s.max_distance if max_distance is None else max_distance
    reranker = s.reranker_enabled if reranker is None else reranker

    qvec = embed_one(query)
    # 리랭커를 쓸 때만 후보를 넉넉히 가져온다. 안 쓸 때 더 가져오면 DB 부담만 는다.
    limit = max(top_k, s.rerank_candidates) if reranker else top_k

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
        cur.execute(sql, (qvec, bot_id, limit))
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

    if reranker and len(sources) > 1:
        sources = _rerank(query, sources)

    return sources[:top_k]


def _rerank(query: str, sources: list[Source]) -> list[Source]:
    """리랭커로 순서를 다시 매긴다. 실패하면 <원래 순서를 그대로 돌려준다.>

    실패 시 예외를 던지지 않는 이유: 리랭커는 <순서를 개선하는 부가 기능>이지
    검색의 필수 단계가 아니다. 리랭커가 죽었다고 채팅이 죽으면 안 된다.
    벡터 순서만으로도 답은 나온다.

    Cloudflare 응답은 {"response": [{"id": <입력 인덱스>, "score": ...}, ...]} 이고
    점수 내림차순으로 온다. id 는 우리가 보낸 contexts 배열의 인덱스다.
    """
    s = get_settings()
    try:
        result = cf.run(s.reranker_model, {
            "query": query,
            "contexts": [{"text": src.preview} for src in sources],
        })
        order = [item["id"] for item in result["response"]]
    except Exception as e:  # noqa: BLE001 - 순서 개선 실패가 검색 실패가 되면 안 된다
        _log.warning("리랭킹 실패(원래 순서 유지): %s: %s", type(e).__name__, e)
        return sources

    # 응답에 빠진 인덱스가 있어도 잃지 않도록, 재정렬된 것 뒤에 나머지를 붙인다.
    seen = set(order)
    return [sources[i] for i in order if 0 <= i < len(sources)] + [
        src for i, src in enumerate(sources) if i not in seen
    ]


def fetch_contents(chunk_ids: list[UUID]) -> dict[UUID, str]:
    """근거 청크의 전체 본문을 가져온다 (preview는 잘려 있으므로)."""
    if not chunk_ids:
        return {}
    with cursor() as cur:
        cur.execute("SELECT id, content FROM chunks WHERE id = ANY(%s)", (chunk_ids,))
        return {row[0]: row[1] for row in cur.fetchall()}
