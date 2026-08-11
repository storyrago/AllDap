"""임베딩 생성과 벡터 검색.

W4에서 여기에 키워드(BM25) 검색과 리랭커를 추가하고,
평가 점수를 before/after로 비교하는 것이 이 프로젝트의 핵심 스토리다.
그래서 search()의 시그니처를 미리 열어둔다.

임베딩 제공자: Cloudflare Workers AI (@cf/baai/bge-m3, 1024차원).
2026-08-02 에 Google Gemini 에서 옮겼다 — 이유는 config.py 주석 참고(약관·한도).
제공자 배치: 임베딩·답변생성·채점 = Cloudflare / 질문생성 = Gemini(evaluator.py).
"""
from __future__ import annotations

import logging
import re
from uuid import UUID

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
    hybrid: bool | None = None,
) -> list[Source]:
    """질문과 가까운 청크를 찾는다. 관련도 낮은 건 잘라낸다.

    리랭커를 켜면 <벡터가 가져온 후보 안에서 순서만 바꾼다.>
    후보에 없는 청크는 살릴 수 없으므로 top_k 보다 넉넉히 뽑아(rerank_candidates)
    재정렬한 뒤 top_k 만 남긴다.

    하이브리드를 켜면 <후보 자체가 늘어난다.> 벡터가 못 데려온 청크를 키워드가
    데려올 수 있기 때문이다 — 리랭커와 결정적으로 다른 점이다.
    두 랭킹은 RRF 로 합친다(_rrf_reorder 주석 참고).

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
    hybrid = s.hybrid_enabled if hybrid is None else hybrid

    qvec = embed_one(query)
    # 리랭커·하이브리드를 쓸 때만 후보를 넉넉히 가져온다. 안 쓸 때 더 가져오면 DB 부담만 는다.
    limit = top_k
    if reranker:
        limit = max(limit, s.rerank_candidates)
    if hybrid:
        limit = max(limit, s.hybrid_candidates)

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
        rows = list(cur.fetchall())

    if hybrid:
        # 키워드가 데려온 청크를 <벡터 후보 뒤에> 덧붙인다. 순서는 아래 RRF 가 다시 매긴다.
        vec_order = [r[0] for r in rows]
        kw_rows = _keyword_rows(bot_id, query, qvec, s.hybrid_candidates)
        seen = set(vec_order)
        rows += [r for r in kw_rows if r[0] not in seen]
        rows = _rrf_reorder(rows, vec_order, [r[0] for r in kw_rows], s.hybrid_rrf_k)

    sources: list[Source] = []
    for chunk_id, doc_id, filename, content, distance in rows:
        # ⚠️ 키워드로 올라온 청크에도 <벡터 거리> 컷을 그대로 적용한다.
        #    여기를 풀면 "질문의 단어가 우연히 들어 있을 뿐 관련 없는 청크"가 근거가 되고,
        #    환각 억제 1차 방어선이 뚫린다. 성능을 이유로 완화하지 않는다.
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


# 한국어 조사. 토큰 끝에 붙어 있으면 떼어낸다.
# 긴 것부터 나열해야 "에서" 가 "에" 로 먼저 잘리지 않는다(정규식 교대는 앞에서부터 시도한다).
_JOSA = re.compile(r"(에서|에게|한테|부터|까지|으로|이나|라도|은|는|이|가|을|를|의|에|로|와|과|도|만|나)$")


def _keywords(query: str) -> list[str]:
    """질문에서 검색에 쓸 낱말을 뽑는다. 2글자 미만은 버린다.

    ⚠️ 형태소 분석기(mecab-ko 등)를 쓰지 않는 이유:
       PostgreSQL 의 `to_tsvector` 는 한국어를 모른다 — 조사가 붙어
       "정규직은" 과 "정규직의" 가 <다른 토큰>이 되어 매칭이 안 된다.
       제대로 하려면 형태소 분석기를 붙여야 하는데, 우리가 필요한 것은
       "질문의 핵심 낱말이 이 청크에 있는가" 뿐이다. <조사만 떼면> 부분 문자열
       매칭으로 충분하다. 활용형("일하는", "가능한가요")은 조사 제거로 안 잡히지만,
       그런 말은 청크에 그대로 있을 일이 적어 점수에 기여하지 않는다 = 무해하다.

    # ponytail: 조사 목록이 전부는 아니다. 형태소 분석기가 필요해지면 그때 붙인다.
    """
    out: list[str] = []
    for tok in re.findall(r"[가-힣]{2,}|[A-Za-z0-9]{2,}", query):
        # 🐛 조사를 뗀 결과가 한 글자면 <떼지 않는다.>
        #    "휴가" 의 끝 글자가 조사 '가' 와 같아서 "휴" 가 되고, 한 글자라 버려졌다.
        #    이 도메인의 핵심 낱말("휴가"·"평가"·"결과")이 통째로 사라지는 버그였다.
        #    retriever_check 가 잡았다.
        stripped = _JOSA.sub("", tok)
        tok = stripped if len(stripped) >= 2 else tok
        if len(tok) >= 2:
            out.append(tok)
    return list(dict.fromkeys(out))  # 중복 제거 + 등장 순서 유지


def _keyword_rows(bot_id: UUID, query: str, qvec: list[float], limit: int) -> list[tuple]:
    """질문의 낱말을 <많이 담고 있는> 청크 순으로 가져온다.

    벡터 거리도 함께 뽑는 이유: 키워드로만 올라온 청크에도 `max_distance` 컷을
    적용해야 하는데, 거리를 여기서 안 가져오면 호출부가 또 한 번 질의해야 한다.

    # ponytail: LIKE 전체 스캔이다. 지금 봇 하나가 306청크라 무시할 수준이고,
    #   수만 청크가 되면 tsvector + GIN 인덱스(또는 pg_bigm)로 바꿀 것.
    """
    keys = _keywords(query)
    if not keys:
        return []
    sql = """
        SELECT id, document_id, filename, content, distance FROM (
            SELECT c.id, c.document_id, d.filename, c.content,
                   c.embedding <=> %s::vector AS distance,
                   (SELECT count(*) FROM unnest(%s::text[]) k
                     WHERE c.content LIKE '%%' || k || '%%') AS hits
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE c.bot_id = %s AND c.embedding IS NOT NULL
        ) t
        WHERE hits > 0
        -- 같은 낱말 수면 벡터로 가까운 쪽을 위로. 키워드만으로는 동점이 흔하다.
        ORDER BY hits DESC, distance
        LIMIT %s
    """
    with cursor() as cur:
        cur.execute(sql, (qvec, keys, bot_id, limit))
        return list(cur.fetchall())


def _rrf_reorder(items: list, order_a: list, order_b: list, k: int, *, key=lambda r: r[0]) -> list:
    """두 랭킹을 RRF(Reciprocal Rank Fusion)로 합쳐 다시 정렬한다.

    각 목록에서 r 위인 문서에 1/(k+r) 을 주고 더한다. 양쪽에 다 있으면 두 번 받는다.

    ⚠️ 왜 점수를 정규화해 가중합하지 않는가:
       벡터 거리(0~2)와 낱말 일치 수(0~N)는 <단위가 다르다.> 섞으려면 정규화하고
       가중치를 정해야 하는데, 그 가중치의 근거가 우리에게 없다 — 결국 손으로 맞추게 되고
       그건 테스트셋에 과적합된다. RRF 는 <순위만> 쓰므로 그 문제가 아예 생기지 않는다.

    쓰는 곳이 둘이라 key 를 받는다:
      ① 하이브리드 — 벡터 순위 + 키워드 순위 (items 는 DB 행 튜플)
      ② 리랭커 융합 — 이전 순위 + 리랭커 순위 (items 는 Source)
    """
    score: dict = {}
    for order in (order_a, order_b):
        for rank, cid in enumerate(order, 1):
            score[cid] = score.get(cid, 0.0) + 1.0 / (k + rank)
    return sorted(items, key=lambda r: score.get(key(r), 0.0), reverse=True)


def _rerank(query: str, sources: list[Source]) -> list[Source]:
    """리랭커로 순서를 다시 매긴다. 실패하면 <원래 순서를 그대로 돌려준다.>

    실패 시 예외를 던지지 않는 이유: 리랭커는 <순서를 개선하는 부가 기능>이지
    검색의 필수 단계가 아니다. 리랭커가 죽었다고 채팅이 죽으면 안 된다.
    벡터 순서만으로도 답은 나온다.

    Cloudflare 응답은 {"response": [{"id": <입력 인덱스>, "score": ...}, ...]} 이고
    점수 내림차순으로 온다. id 는 우리가 보낸 contexts 배열의 인덱스다.

    ── `rerank_fusion` 이 켜져 있으면 리랭커 순서를 <그대로 쓰지 않는다> ──

    2026-08-11 측정에서 리랭커가 **정답 청크를 top5 밖으로 밀어내** 새 fallback 을
    2건 만들었다(재택 주2회 · 기간제 연차). 둘 다 벡터에서는 1~2위였다.
    리랭커 순서를 그대로 쓰면 <리랭커가 틀렸을 때 되돌릴 방법이 없다.>

    그래서 들어온 순서(벡터 또는 하이브리드 RRF 결과)와 리랭커 순서를 다시 RRF 로 합친다.
    벡터 1위 + 리랭커 15위 → 중간. 리랭커 1위 + 벡터 15위 → 중간. 둘 다 상위 → 최상위.
    **한쪽이 크게 틀려도 다른 쪽이 받쳐준다** = 밀어내기가 완화된다.
    대신 리랭커가 <옳게> 크게 끌어올린 것도 덜 올라간다. 그 값을 재는 것이 이 슬라이스다.
    """
    s = get_settings()
    # ⚠️ preview(앞 200자)가 아니라 <전체 본문>을 넘긴다.
    #
    # 🐛 처음엔 preview 를 넘겼고, 그 상태로 "리랭커가 벡터보다 나쁘다"고 판정했다.
    #    그런데 청크가 500자 단위라 <절반 이상을 리랭커가 못 본> 상태였다.
    #    정답이 250번째 글자에 있으면 리랭커에게는 없는 것과 같다.
    #    같은 실수를 judge.py 에서도 냈다(거기가 더 심각했다 — 채점이 통째로 틀렸다).
    #
    # 교훈: <판단하는 쪽은 판단 대상이 본 것과 같은 것을 봐야 한다.>
    #       덜 보여주고 "못 맞힌다"고 판정하면 그건 모델이 아니라 우리 잘못이다.
    contents = fetch_contents([src.chunk_id for src in sources])
    try:
        result = cf.run(s.reranker_model, {
            "query": query,
            "contexts": [
                {"text": contents.get(src.chunk_id, src.preview)} for src in sources
            ],
        })
        order = [item["id"] for item in result["response"]]
    except Exception as e:  # noqa: BLE001 - 순서 개선 실패가 검색 실패가 되면 안 된다
        _log.warning("리랭킹 실패(원래 순서 유지): %s: %s", type(e).__name__, e)
        return sources

    # 응답에 빠진 인덱스가 있어도 잃지 않도록, 재정렬된 것 뒤에 나머지를 붙인다.
    seen = set(order)
    reranked = [sources[i] for i in order if 0 <= i < len(sources)] + [
        src for i, src in enumerate(sources) if i not in seen
    ]
    if not s.rerank_fusion:
        return reranked

    # 들어온 순서(벡터 또는 하이브리드 RRF)와 리랭커 순서를 RRF 로 합친다.
    return _rrf_reorder(
        sources,
        [src.chunk_id for src in sources],
        [src.chunk_id for src in reranked],
        s.rerank_fusion_k,
        key=lambda src: src.chunk_id,
    )


def fetch_contents(chunk_ids: list[UUID]) -> dict[UUID, str]:
    """근거 청크의 전체 본문을 가져온다 (preview는 잘려 있으므로)."""
    if not chunk_ids:
        return {}
    with cursor() as cur:
        cur.execute("SELECT id, content FROM chunks WHERE id = ANY(%s)", (chunk_ids,))
        return {row[0]: row[1] for row in cur.fetchall()}
