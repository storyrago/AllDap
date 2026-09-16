"""정답 청크가 검색 파이프라인 <어느 단계에서> 사라지는지 추적한다.

실행:
    cd ai-service && RERANKER_PROVIDER=local .venv/bin/python -m app.rank_trace --bot-id 1
    cd ai-service && RERANKER_PROVIDER=local .venv/bin/python -m app.rank_trace --bot-id 1 --qid 7
    cd ai-service && .venv/bin/python -m app.rank_trace --bot-id 1 --scores 7   # 제공자별 점수 비교

🔴 평가 실행(eval run)을 돌리지 않는다. 임베딩(질문당 약 0.025 뉴런)과 리랭커 호출만 쓴다.
   `RERANKER_PROVIDER=local` 로 돌리면 Cloudflare 뉴런은 임베딩분 말고 한 푼도 안 든다
   (2026-09-17 실측: 로컬 fp32 와 Cloudflare 의 순서가 16문항 × 3회 전부 같았다).

무엇을 답하는 도구인가
─────────────────────────────────────────────────────────────────────────────
평가에서 fallback 이나 오답이 난 문항을 놓고 **"리랭커를 고치면 회복되는가"** 를 가른다.
`eval_questions.source_chunk_id`(= 그 질문을 만들어낸 <정답 청크>)가 파이프라인의
각 단계에서 몇 위인지를 찍어, 아래 넷 중 무엇인지 판정한다.

  ① 후보 안인데 순위가 낮아 top_k 에 못 든다  → ✅ 리랭커가 할 일. 파인튜닝·융합이 노릴 자리
  ② 후보 밖이다                                → ❌ 검색·청킹 문제. 리랭커는 없는 것을 못 올린다
  ③ 게이트 또는 거리 컷이 잘랐다              → ❌ 임계값 문제. 게이트에 걸리면 근거가 통째로
                                                 비어 LLM 도 리랭커도 아예 돌지 않는다
  ④ 정답 청크가 근거에 들어갔다               → ❌ 리랭커 밖의 원인. 그런데도 fallback 이나
                                                 오답이 났다면 <질문이 문서에 없는 대상을
                                                 묻고 있는지> `testdata/corpus/` 를 직접 grep 할 것

⚠️ ④ 는 이 도구가 <단정하지 못한다.> 이 도구는 생성 모델을 부르지 않으므로
   "정답 청크가 근거에 들어갔다" 까지만 말한다. 그 뒤는 사람이 원문을 봐야 한다.
   2026-09-17 에 실제로 그랬다 - 질문은 "수습 직원" 을 묻는데 정답 청크는 "인턴" 규정이었고,
   생성 모델이 거절한 것이 옳은 동작이었다.

어떻게 읽는가
─────────────────────────────────────────────────────────────────────────────
  d1          벡터 최근접 거리. 이것이 `answerable_max_distance` 보다 크면 게이트가 근거를 통째로 버린다
  정답거리    정답 청크까지의 거리. `max_distance` 보다 크면 근거 목록에서 잘린다
  벡터순위    제한 없는 전체 순위. `rerank_candidates` 보다 크면 후보에 못 들어온다(판정 ②)
  RRF순위     하이브리드가 벡터 순위와 키워드 순위를 RRF 로 합친 뒤의 순위
  컷후순위    거리 컷을 통과한 것들 안에서의 순위. 리랭커가 <보는> 목록이다
  리랭킹후    리랭커가 다시 매긴 순위. 이것이 `top_k` 이하면 근거로 나간다
  top         최종 근거 진입 여부

🔴 **경계에 걸린 문항을 먼저 볼 것.** 리랭킹 후 순위가 정확히 `top_k` 인 문항은
   순위를 건드리는 <어떤> 변경에도 제일 먼저 깨진다. 표에 `경계` 로 표시한다.

설정은 박지 않는다 - 전부 `get_settings()` 에서 읽는다. 임계값을 바꾸면 이 도구도 따라간다.
그래서 **측정할 때와 같은 설정으로 돌려야 한다.** 다르면 그때의 순위를 재현하지 못한다.

재현 확인을 먼저 할 것
─────────────────────────────────────────────────────────────────────────────
`eval_results.retrieved_chunks` 에 그때 나간 근거가 박제돼 있다. 이 도구가 낸 top 목록이
그것과 같은지부터 보고 나서 표를 해석할 것. 다르면 설정이나 코퍼스가 그때와 다른 것이고,
그 상태의 순위로 "리랭커가 고칠 수 있다/없다" 를 말하면 안 된다.

CI 에서 돌지 않는다
─────────────────────────────────────────────────────────────────────────────
진짜 DB(청크·임베딩·평가 질문)와 리랭커 모델이 필요하다. `answerable_check` ·
`fallback_e2e_check` 와 같은 격의 <손으로 돌리는 진단 도구>다.
`parsers_check` · `retriever_check` 처럼 순수 함수만 보는 자체 점검이 아니다.
"""
from __future__ import annotations

import argparse

from .config import get_settings
from .db import close_pool, cursor
from .schemas import Id, Source


def _questions(bot_id: Id, qid: int | None) -> list[tuple]:
    sql = ("SELECT id, question, source_chunk_id FROM eval_questions "
           "WHERE bot_id = %s AND (%s::bigint IS NULL OR id = %s) ORDER BY id")
    with cursor() as cur:
        cur.execute(sql, (bot_id, qid, qid))
        return list(cur.fetchall())


def _candidate_rows(bot_id: Id, qvec: list[float], limit: int) -> list[tuple]:
    """search() 가 쓰는 후보 질의 그대로."""
    with cursor() as cur:
        cur.execute(
            """SELECT c.id, c.document_id, d.filename, c.content,
                      c.embedding <=> %s::vector AS distance
                 FROM chunks c JOIN documents d ON d.id = c.document_id
                WHERE c.bot_id = %s AND c.embedding IS NOT NULL
                ORDER BY distance LIMIT %s""",
            (qvec, bot_id, limit),
        )
        return list(cur.fetchall())


def _all_distances(bot_id: Id, qvec: list[float]) -> list[tuple]:
    """제한 없는 전체 순위. 정답 청크가 <후보 밖>인지(판정 ②)를 가르려면 필요하다."""
    with cursor() as cur:
        cur.execute(
            """SELECT c.id, c.embedding <=> %s::vector AS distance
                 FROM chunks c
                WHERE c.bot_id = %s AND c.embedding IS NOT NULL
                ORDER BY distance""",
            (qvec, bot_id),
        )
        return list(cur.fetchall())


def _rank(order: list, target) -> int | None:
    return order.index(target) + 1 if target in order else None


def _candidates(bot_id: Id, question: str, qvec: list[float]) -> tuple[list[tuple], list, list]:
    """search() 의 후보 구성을 재현한다. (RRF 정렬된 행, 벡터 순서, 키워드 순서)

    search() 를 부르지 않고 <베끼는> 이유: search() 는 최종 Source 목록만 돌려주므로
    중간 순위를 알 수 없다. 대신 retriever 의 내부 함수를 그대로 써서 어긋나지 않게 한다.
    """
    from . import retriever  # 늦은 import - 이 모듈을 열기만 해도 모델이 뜨면 안 된다

    s = get_settings()
    limit = max(s.top_k,
                s.rerank_candidates if s.reranker_enabled else 0,
                s.hybrid_candidates if s.hybrid_enabled else 0)
    rows = _candidate_rows(bot_id, qvec, limit)
    vec_order = [r[0] for r in rows]
    kw_order: list = []
    if s.hybrid_enabled:
        kw_rows = retriever._keyword_rows(bot_id, question, qvec, s.hybrid_candidates)
        kw_order = [r[0] for r in kw_rows]
        seen = set(vec_order)
        rows = rows + [r for r in kw_rows if r[0] not in seen]
        rows = retriever._rrf_reorder(rows, vec_order, kw_order, s.hybrid_rrf_k)
    return rows, vec_order, kw_order


def _cut(rows: list[tuple]) -> list[Source]:
    """거리 컷을 통과한 것만 Source 로. search() 의 그 자리와 같다."""
    s = get_settings()
    return [
        Source(chunk_id=r[0], document_id=r[1], filename=r[2],
               score=round(1.0 - float(r[4]), 4), preview=r[3][:200])
        for r in rows if float(r[4]) <= s.max_distance
    ]


def trace(bot_id: Id, qid: int, question: str, gold: Id | None) -> dict:
    """한 문항에 대해 search() 를 재현하며 단계별 순위를 기록한다."""
    from . import retriever  # 늦은 import

    s = get_settings()
    out: dict = {"qid": qid, "question": question, "gold": gold}
    if gold is None:
        out["verdict"] = "정답 청크 없음 (source_chunk_id IS NULL)"
        return out

    qvec = retriever.embed_one(question)

    allrows = _all_distances(bot_id, qvec)
    dist = {cid: float(d) for cid, d in allrows}
    out["d1"] = round(float(allrows[0][1]), 4)
    out["gate_pass"] = (s.answerable_max_distance is None
                        or out["d1"] <= s.answerable_max_distance)
    out["gold_dist"] = round(dist[gold], 4) if gold in dist else None
    out["gold_cut_pass"] = out["gold_dist"] is not None and out["gold_dist"] <= s.max_distance
    out["vec_rank"] = _rank([cid for cid, _ in allrows], gold)
    out["total_chunks"] = len(allrows)

    if not out["gate_pass"]:
        # 게이트는 근거를 통째로 버린다. 아래 단계는 <일어나지도 않는다.>
        out["verdict"] = "③ 게이트가 잘라 근거가 비었다"
        return out

    rows, vec_order, kw_order = _candidates(bot_id, question, qvec)
    out["keywords"] = retriever._keywords(question) if s.hybrid_enabled else []
    out["kw_rank"] = _rank(kw_order, gold)
    out["in_candidates"] = gold in vec_order or gold in kw_order
    out["cand_size"] = len(rows)
    out["rrf_rank"] = _rank([r[0] for r in rows], gold)

    sources = _cut(rows)
    out["after_cut_size"] = len(sources)
    out["cut_rank"] = _rank([x.chunk_id for x in sources], gold)

    if s.reranker_enabled and len(sources) > 1:
        sources = retriever._rerank(question, sources)
    final_order = [x.chunk_id for x in sources]
    out["rerank_rank"] = _rank(final_order, gold)
    out["top"] = [(cid, next(x.filename for x in sources if x.chunk_id == cid))
                  for cid in final_order[:s.top_k]]
    out["in_top_k"] = gold in final_order[:s.top_k]
    out["boundary"] = out["rerank_rank"] == s.top_k

    if not out["gold_cut_pass"]:
        out["verdict"] = "③ 거리 컷(max_distance)이 잘랐다"
    elif out["cut_rank"] is None:
        out["verdict"] = "② 후보 밖이다"
    elif not out["in_top_k"]:
        out["verdict"] = "① 후보 안인데 순위가 낮다 (리랭커가 고칠 수 있다)"
    else:
        out["verdict"] = "④ 정답 청크가 근거에 들어갔다 (실패했다면 리랭커 밖의 원인)"
    return out


def _print_table(results: list[dict]) -> None:
    s = get_settings()
    print(f"\n임계값: answerable={s.answerable_max_distance} · max_distance={s.max_distance}"
          f" · top_k={s.top_k} · rerank_candidates={s.rerank_candidates}"
          f" · reranker={s.reranker_enabled}/{s.reranker_provider} · hybrid={s.hybrid_enabled}\n")
    head = (f"{'q':>3} {'d1':>7} {'게이트':>6} {'정답거리':>8} {'컷':>4} "
            f"{'벡터':>5} {'RRF':>5} {'컷후':>5} {'리랭킹후':>9} {'top':>4}  판정")
    print(head)
    print("-" * 96)
    for r in results:
        if "d1" not in r:
            print(f"{r['qid']:>3}  {r['verdict']}")
            continue
        gate = "통과" if r["gate_pass"] else "차단"
        if not r["gate_pass"]:
            # 게이트에 걸려도 <거리 컷 통과 여부는 찍는다.> 둘 다 걸리는 문항은
            # 게이트만 올려서는 살아나지 않기 때문이다(2026-09-17 의 q6 이 그랬다).
            print(f"{r['qid']:>3} {r['d1']:>7} {gate:>6} {str(r['gold_dist']):>8} "
                  f"{'O' if r['gold_cut_pass'] else 'X':>4} "
                  f"{str(r['vec_rank']):>5} {'-':>5} {'-':>5} {'-':>9} {'X':>4}  {r['verdict']}")
            continue
        rr = f"{r['rerank_rank']}{' 경계' if r['boundary'] else ''}"
        print(f"{r['qid']:>3} {r['d1']:>7} {gate:>6} {str(r['gold_dist']):>8} "
              f"{'O' if r['gold_cut_pass'] else 'X':>4} {str(r['vec_rank']):>5} "
              f"{str(r['rrf_rank']):>5} {str(r['cut_rank']):>5} {rr:>9} "
              f"{'O' if r['in_top_k'] else 'X':>4}  {r['verdict']}")
    print("\n⚠️  '경계' 는 리랭킹 후 순위가 정확히 top_k 라는 뜻이다.")
    print("    순위를 건드리는 어떤 변경도 이 문항을 <제일 먼저> 깨뜨린다.")
    print("⚠️  판정 ④ 는 이 도구가 단정하지 못한다. testdata/corpus/ 원문을 직접 볼 것.")


def _print_scores(bot_id: Id, qid: int, variants: list[str]) -> None:
    """같은 후보 목록에 제공자를 바꿔 넣고 <점수를> 나란히 찍는다.

    순위만 보면 "밀렸다" 까지만 알 수 있고 <얼마나 아슬아슬했는지>를 모른다.
    2026-09-17 에 INT8 이 잃은 문항을 이걸로 갈랐다: fp32 에서 정답 청크가 경계보다
    0.695 점 위였는데 INT8 에서 0.733 점 떨어져 뒤집혔다. 여유가 없어서가 아니라
    양자화 오차가 항목마다 <다른 방향으로> 실려서였다(상위 2개는 오히려 점수가 올랐다).
    """
    from . import local_reranker, retriever  # 늦은 import

    s = get_settings()
    rows = _questions(bot_id, qid)
    if not rows:
        print(f"질문 {qid} 이(가) 봇 {bot_id} 에 없습니다.")
        return
    _, question, gold = rows[0]

    qvec = retriever.embed_one(question)
    cand, _, _ = _candidates(bot_id, question, qvec)
    srcs = _cut(cand)
    contents = retriever.fetch_contents([x.chunk_id for x in srcs])
    texts = [contents.get(x.chunk_id, x.preview) for x in srcs]

    print(f"\n질문 {qid}: {question}")
    print(f"정답 청크: {gold} · 후보 {len(srcs)}개 · top_k={s.top_k}")
    for variant in variants:
        print(f"\n── {variant} ──")
        result = local_reranker.rerank(question, texts, variant=variant)
        for rank, item in enumerate(result["response"], 1):
            if rank > s.top_k + 3:
                break
            src = srcs[item["id"]]
            tail = "  <<< 정답" if src.chunk_id == gold else ""
            if rank == s.top_k:
                tail += "   | top_k 경계"
            print(f"{rank:>3}. score={item['score']:>12.6f}  chunk={str(src.chunk_id):<5} "
                  f"{src.filename[:28]}{tail}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="정답 청크가 검색 파이프라인 어느 단계에서 사라지는지 추적한다")
    parser.add_argument("--bot-id", type=int, required=True)
    parser.add_argument("--qid", type=int, default=None, help="이 질문 하나만 추적")
    parser.add_argument("--scores", type=int, default=None, metavar="QID",
                        help="이 질문의 리랭커 점수를 제공자별로 나란히 찍는다")
    parser.add_argument("--variants", default="local,local_int8",
                        help="--scores 와 함께 쓸 로컬 제공자 목록(쉼표 구분)")
    args = parser.parse_args()

    if args.scores is not None:
        _print_scores(args.bot_id, args.scores, args.variants.split(","))
        return

    results = [trace(args.bot_id, qid, question, gold)
               for qid, question, gold in _questions(args.bot_id, args.qid)]
    _print_table(results)


if __name__ == "__main__":
    try:
        main()
    finally:
        close_pool()
