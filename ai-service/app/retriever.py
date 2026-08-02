"""임베딩 생성과 벡터 검색.

W4에서 여기에 키워드(BM25) 검색과 리랭커를 추가하고,
평가 점수를 before/after로 비교하는 것이 이 프로젝트의 핵심 스토리다.
그래서 search()의 시그니처를 미리 열어둔다.

임베딩 제공자: Cloudflare Workers AI (@cf/baai/bge-m3, 1024차원).
2026-08-02 에 Google Gemini 에서 옮겼다 — 이유는 config.py 주석 참고(약관·한도).
<생성(답변·질문)은 여전히 Gemini 다.> 이 파일만 제공자가 다르다.
"""
from __future__ import annotations

from uuid import UUID

import httpx

from .config import get_settings
from .db import cursor
from .schemas import Source

_http: httpx.Client | None = None


def _cf() -> tuple[httpx.Client, str]:
    """Cloudflare Workers AI 클라이언트와 호출 URL.

    왜 전역에 하나만 두고 재사용하는가 — httpx.Client 는 안에 커넥션 풀을 들고 있다.
    요청마다 새로 만들면 TCP 연결과 TLS 악수를 매번 다시 한다.
    위의 _gemini() 가 _client 를 캐시하는 것과 정확히 같은 이유다.

    `global` 은 "이 함수 안에서 바깥 변수를 <바꾸겠다>"는 선언이다.
    안 쓰면 파이썬은 _http 를 함수 안의 새 지역 변수로 만들어버려서,
    함수를 나가는 순간 사라진다 — 캐시가 전혀 동작하지 않는다.
    """
    global _http
    s = get_settings()
    if not s.cf_account_id or not s.cf_api_token:
        raise RuntimeError(
            "CF_ACCOUNT_ID / CF_API_TOKEN 이 설정되지 않았습니다 (ai-service/.env 확인)"
        )
    if _http is None:
        _http = httpx.Client(
            headers={"Authorization": f"Bearer {s.cf_api_token}"},
            # 배치 100개가 0.7초쯤 걸린다(실측). 네트워크가 느릴 때를 감안해 넉넉히 준다.
            timeout=60.0,
        )
    url = (
        f"https://api.cloudflare.com/client/v4/accounts/{s.cf_account_id}"
        f"/ai/run/{s.embedding_model}"
    )
    return _http, url


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
    client, url = _cf()

    out: list[list[float]] = []
    for i in range(0, len(texts), s.embedding_batch_size):
        batch = texts[i : i + s.embedding_batch_size]
        resp = client.post(url, json={"text": batch})
        # 4xx·5xx 면 여기서 예외가 난다. 조용히 넘어가면 빈 벡터가 DB 에 들어간다.
        resp.raise_for_status()
        body = resp.json()
        # Cloudflare 는 성공/실패를 <HTTP 코드가 아니라 본문의 success 로도> 알린다.
        if not body.get("success", False):
            raise RuntimeError(f"Cloudflare 임베딩 실패: {body.get('errors')}")
        out.extend(body["result"]["data"])

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
