"""정답 청크가 검색 파이프라인 <어느 단계에서> 사라지는지 추적한다.

실행:
    cd ai-service && RERANKER_PROVIDER=local .venv/bin/python -m app.rank_trace --bot-id 1
    cd ai-service && RERANKER_PROVIDER=local .venv/bin/python -m app.rank_trace --bot-id 1 --qid 7
    cd ai-service && RERANKER_PROVIDER=local .venv/bin/python -m app.rank_trace --bot-id 1 --all
    cd ai-service && .venv/bin/python -m app.rank_trace --bot-id 1 --scores 7   # 제공자별 점수 비교
    cd ai-service && .venv/bin/python -m app.rank_trace --bot-id 3 --compare local --gate local
    cd ai-service && .venv/bin/python -m app.rank_trace --bot-id 3 --compare local,local_int8,local_ft,local_ft_int8 --pair local:local_ft --pair local_ft:local_ft_int8 --out testdata/finetune/compare_test.json

🔴 기본은 <활성 문항만>(`is_active=true`) 추적한다. 평가(`evalrun`)가 보는 것과 같은 집합이다.
   `--all` 을 붙이면 비활성까지 찍되 표에 상태 칸이 붙고, 판정 개수는 그래도 활성만 센다.
   근거는 `_questions` 주석에 있다(비활성 문항이 판정 ① 개수에 섞이면 BACKLOG §5 를 오독한다).

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
import json
import math
from datetime import date
from pathlib import Path

from .config import get_settings
from .db import close_pool, cursor
from .schemas import Id, Source


def _questions(bot_id: Id, qid: int | None, include_inactive: bool = False) -> list[tuple]:
    """추적할 문항을 고른다. 기본은 <활성 문항만>이다.

    🔴 기본값이 활성만인 이유는 오독을 막기 위해서다. 평가(`evalrun`)는
    `WHERE is_active` 로 걸러 돌리는데(`evalrun.py` 의 질문 조회 두 곳) 이 도구가 안 걸러
    찍으면, <평가에 들어가지도 않는 문항>이 판정 ①("후보 안인데 순위가 낮다") 개수에 섞인다.
    그 개수가 곧 `docs/BACKLOG.md` §5 가 "리랭커 파인튜닝을 할 값어치가 있는가" 를
    판단하는 바로 그 숫자라, 섞이면 "회복 여지가 생겼다" 는 <틀린 결론>이 나온다.
    이 저장소가 여덟 번 낸 <원인이 다른 사실들을 한 값으로 뭉개는> 부류다.
    (2026-09-18 에 실제로 오독할 뻔했다 - 비활성 문항 하나가 ① 로 찍혔다)

    ⚠️ `--qid` 로 문항 하나를 콕 집어 부를 때는 거르지 않는다. 그건 "이 문항을 보겠다" 는
       명시적 지시이고, 한 줄짜리 표라 개수에 섞일 것이 없다. 대신 비활성 표시는 붙는다.
    """
    sql = ("SELECT id, question, source_chunk_id, is_active FROM eval_questions "
           "WHERE bot_id = %s AND (%s::bigint IS NULL OR id = %s) "
           "AND (%s OR is_active) ORDER BY id")
    with cursor() as cur:
        cur.execute(sql, (bot_id, qid, qid, include_inactive))
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


def trace(bot_id: Id, qid: int, question: str, gold: Id | None,
          active: bool = True) -> dict:
    """한 문항에 대해 search() 를 재현하며 단계별 순위를 기록한다.

    `active` 는 추적에 영향을 주지 않는다. 표와 요약이 <두 부류를 갈라 보여주기> 위해서만 쓴다.
    """
    from . import retriever  # 늦은 import

    s = get_settings()
    out: dict = {"qid": qid, "question": question, "gold": gold, "active": active}
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


def _print_table(results: list[dict], show_state: bool = False,
                 summary: bool = True) -> None:
    """표와 요약을 찍는다.

    `show_state` 가 참이면 <활성/비활성> 칸을 하나 더 둔다. 비활성까지 섞어 찍을 때
    두 부류가 겉보기에 같으면 판정 개수를 사람이 그대로 세어 오독하기 때문이다.
    """
    s = get_settings()
    print(f"\n임계값: answerable={s.answerable_max_distance} · max_distance={s.max_distance}"
          f" · top_k={s.top_k} · rerank_candidates={s.rerank_candidates}"
          f" · reranker={s.reranker_enabled}/{s.reranker_provider} · hybrid={s.hybrid_enabled}\n")
    state_head = f"{'상태':>6} " if show_state else ""
    head = (f"{'q':>3} {state_head}{'d1':>7} {'게이트':>6} {'정답거리':>8} {'컷':>4} "
            f"{'벡터':>5} {'RRF':>5} {'컷후':>5} {'리랭킹후':>9} {'top':>4}  판정")
    print(head)
    print("-" * (96 + (7 if show_state else 0)))
    for r in results:
        st = (f"{('활성' if r.get('active', True) else '비활성'):>6} ") if show_state else ""
        if "d1" not in r:
            print(f"{r['qid']:>3} {st} {r['verdict']}")
            continue
        gate = "통과" if r["gate_pass"] else "차단"
        if not r["gate_pass"]:
            # 게이트에 걸려도 <거리 컷 통과 여부는 찍는다.> 둘 다 걸리는 문항은
            # 게이트만 올려서는 살아나지 않기 때문이다(2026-09-17 의 q6 이 그랬다).
            print(f"{r['qid']:>3} {st}{r['d1']:>7} {gate:>6} {str(r['gold_dist']):>8} "
                  f"{'O' if r['gold_cut_pass'] else 'X':>4} "
                  f"{str(r['vec_rank']):>5} {'-':>5} {'-':>5} {'-':>9} {'X':>4}  {r['verdict']}")
            continue
        rr = f"{r['rerank_rank']}{' 경계' if r['boundary'] else ''}"
        print(f"{r['qid']:>3} {st}{r['d1']:>7} {gate:>6} {str(r['gold_dist']):>8} "
              f"{'O' if r['gold_cut_pass'] else 'X':>4} {str(r['vec_rank']):>5} "
              f"{str(r['rrf_rank']):>5} {str(r['cut_rank']):>5} {rr:>9} "
              f"{'O' if r['in_top_k'] else 'X':>4}  {r['verdict']}")
    # 요약은 여러 문항을 함께 볼 때만 뜻이 있다. `--qid` 한 줄짜리에서는 개수가 늘 0 아니면 1 이라
    # 오히려 "활성 0개 기준" 같은 오해를 부른다.
    if summary:
        _print_summary(results)
    print("\n⚠️  '경계' 는 리랭킹 후 순위가 정확히 top_k 라는 뜻이다.")
    print("    순위를 건드리는 어떤 변경도 이 문항을 <제일 먼저> 깨뜨린다.")
    print("⚠️  판정 ④ 는 이 도구가 단정하지 못한다. testdata/corpus/ 원문을 직접 볼 것.")


# 판정 앞머리 기호 → 요약에 찍을 이름. 표를 사람이 세지 않게 하려는 것이다.
_VERDICT_LABELS = {
    "①": "① 후보 안인데 순위가 낮다 (리랭커가 고칠 수 있다)",
    "②": "② 후보 밖이다 (검색·청킹 문제)",
    "③": "③ 게이트 또는 거리 컷이 잘랐다 (임계값 문제)",
    "④": "④ 정답 청크가 근거에 들어갔다 (리랭커 밖의 원인)",
}


def _print_summary(results: list[dict]) -> None:
    """무엇을 몇 개 기준으로 센 것인지와 판정별 개수를 찍는다.

    🔴 개수를 도구가 직접 찍는 이유: `docs/BACKLOG.md` §5 가 읽는 것이 ① 의 개수인데,
       사람이 표를 세면 비활성 문항이나 '정답 청크 없음' 행이 조용히 섞인다.
    """
    n_active = sum(1 for r in results if r.get("active", True))
    n_inactive = len(results) - n_active
    counts: dict[str, int] = {}
    for r in results:
        if not r.get("active", True):
            continue  # 개수는 <활성 문항만> 센다. 평가가 보는 것과 같은 집합이어야 한다.
        key = r["verdict"][0]
        counts[key] = counts.get(key, 0) + 1

    print(f"\n요약: 활성 {n_active}개 기준"
          + (f" (비활성 {n_inactive}개는 표에만 찍고 개수에서 뺐다)" if n_inactive else ""))
    for mark, label in _VERDICT_LABELS.items():
        print(f"  {counts.get(mark, 0):>3}  {label}")
    other = sum(v for k, v in counts.items() if k not in _VERDICT_LABELS)
    if other:
        print(f"  {other:>3}  판정 불가 (정답 청크 없음 등)")


def _print_scores(bot_id: Id, qid: int, variants: list[str]) -> None:
    """같은 후보 목록에 제공자를 바꿔 넣고 <점수를> 나란히 찍는다.

    순위만 보면 "밀렸다" 까지만 알 수 있고 <얼마나 아슬아슬했는지>를 모른다.
    2026-09-17 에 INT8 이 잃은 문항을 이걸로 갈랐다: fp32 에서 정답 청크가 경계보다
    0.695 점 위였는데 INT8 에서 0.733 점 떨어져 뒤집혔다. 여유가 없어서가 아니라
    양자화 오차가 항목마다 <다른 방향으로> 실려서였다(상위 2개는 오히려 점수가 올랐다).
    """
    from . import local_reranker, retriever  # 늦은 import

    s = get_settings()
    # 문항 하나를 콕 집은 것이므로 비활성이어도 보여준다(`_questions` 주석 참고).
    rows = _questions(bot_id, qid, include_inactive=True)
    if not rows:
        print(f"질문 {qid} 이(가) 봇 {bot_id} 에 없습니다.")
        return
    _, question, gold, is_active = rows[0]

    qvec = retriever.embed_one(question)
    cand, _, _ = _candidates(bot_id, question, qvec)
    srcs = _cut(cand)
    contents = retriever.fetch_contents([x.chunk_id for x in srcs])
    texts = [contents.get(x.chunk_id, x.preview) for x in srcs]

    print(f"\n질문 {qid}{'' if is_active else ' [비활성 - 평가에 들어가지 않는 문항이다]'}: {question}")
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

# ─────────────────────────────────────────────────────────────────────────────
# 여러 모델 비교 (2026-10-01, 리랭커 파인튜닝 실험)
# 설계: docs/superpowers/specs/2026-10-01-reranker-finetune-design.md §5
# ─────────────────────────────────────────────────────────────────────────────
#
# 무엇이 위의 trace() 와 다른가
#   trace() 는 설정의 reranker_provider 하나로 잰다. 비교 모드는 같은 리랭커 후보에
#   로컬 변형 여러 개를 차례로 넣는다. 후보를 한 번만 만들기 때문에, 변형끼리의 차이는
#   리랭커 하나에서만 생긴다.
#
# 문제마다 상태가 넷 중 하나다(스펙 §0 "고칠 수 있는 문제", §5-4).
#   fixable  거리 게이트를 통과했고 정답 청크가 거리 컷을 통과해 리랭커 후보 안에 있다
#   gate     거리 게이트에 걸려 근거가 모두 버려진다(리랭커가 불리지 않는다)
#   cut      정답 청크가 거리 컷(max_distance)에 잘린다
#   outside  정답 청크가 리랭커 후보 밖이다
# gate, cut, outside 는 리랭커가 바꿀 수 없으므로 모든 변형에서 결과가 같다.

STATUSES = ("fixable", "gate", "cut", "outside")
_STATUS_LABELS = {
    "fixable": "고칠 수 있는 문제",
    "gate": "거리 게이트에 걸림",
    "cut": "정답 청크가 거리 컷에 잘림",
    "outside": "정답 청크가 리랭커 후보 밖",
}
ALPHA = 0.05            # 판정 유의수준. 결과를 보기 전에 정했다(스펙 §5-3).
GATE_MIN_RATIO = 0.25   # 관문: 고칠 수 있는데 5위 밖인 문제가 시험 문제 전체의 4분의 1 이상(스펙 §5-2).


def sign_test_p(improved: int, worsened: int) -> float:
    """양측 부호 검정의 p 값.

    갈린 문제 n 개가 동전 던지기처럼 반반으로 갈린다고 가정할 때, 지금보다 한쪽으로 더
    치우친 결과가 나올 확률이다. 작은 쪽 개수를 k 라 하면
        p = 2 × (C(n,0) + C(n,1) + ... + C(n,k)) / 2^n
    math.comb(n, i) 가 C(n, i)(n 개 중 i 개를 고르는 경우의 수)다. scipy 를 쓰지 않는 이유는
    CI 가 requirements.txt 만 설치하고, 식이 이 한 줄이라 의존성을 늘릴 값어치가 없어서다.
    """
    n = improved + worsened
    if n == 0:
        return 1.0
    k = min(improved, worsened)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)  # 양쪽이 같으면 2 × tail 이 1 을 넘으므로 자른다


def judge(improved: int, worsened: int) -> str:
    """스펙 §5-3 의 판정 규칙."""
    p = sign_test_p(improved, worsened)
    if p < ALPHA and improved > worsened:
        return "효과 있음"
    if p < ALPHA and worsened > improved:
        return "악화"
    return "구별되지 않음"


def _in_top(r: dict, variant: str, top_k: int) -> bool:
    return r["status"] == "fixable" and r["ranks"][variant] <= top_k


def summarize(results: list[dict], variant: str, top_k: int) -> dict:
    """한 변형의 지표. 대표 지표의 분모는 시험 문제 전체다(고칠 수 없는 문제 포함)."""
    fixable = [r for r in results if r["status"] == "fixable"]
    hit = sum(1 for r in fixable if r["ranks"][variant] <= top_k)
    n = len(results)
    return {
        "variant": variant,
        "n": n,
        "fixable": len(fixable),
        "hit": hit,
        "top_rate": hit / n if n else 0.0,
        "fixable_rate": hit / len(fixable) if fixable else 0.0,
        # 평균 순위는 고칠 수 있는 문제만으로 낸다. 다른 문제에는 리랭커 순위가 없다.
        "mean_rank": (sum(r["ranks"][variant] for r in fixable) / len(fixable)) if fixable else None,
        "status_counts": {s: sum(1 for r in results if r["status"] == s) for s in STATUSES},
    }


def paired(results: list[dict], base: str, target: str, top_k: int) -> tuple[list[dict], list[dict]]:
    """(좋아진 문제, 나빠진 문제). 둘 다 5위 안이거나 둘 다 5위 밖인 동점은 뺀다."""
    up = [r for r in results if not _in_top(r, base, top_k) and _in_top(r, target, top_k)]
    down = [r for r in results if _in_top(r, base, top_k) and not _in_top(r, target, top_k)]
    return up, down


def gate_count(results: list[dict], variant: str, top_k: int) -> tuple[int, int]:
    """(고칠 수 있는데 5위 밖인 문제 수, 시험 문제 전체 수). 분모를 전체로 잡는 이유는 스펙 §5-2."""
    room = sum(1 for r in results if r["status"] == "fixable" and r["ranks"][variant] > top_k)
    return room, len(results)


def _chunk_counts(bot_id: Id) -> tuple[int, int]:
    """(그 봇의 청크 수, 그중 임베딩이 빈 청크 수)."""
    with cursor() as cur:
        # count(*) FILTER (WHERE ...) 는 조건에 맞는 행만 센다. 한 번 읽어 두 수를 함께 낸다.
        cur.execute("SELECT count(*), count(*) FILTER (WHERE embedding IS NULL) "
                    "FROM chunks WHERE bot_id = %s", (bot_id,))
        total, empty = cur.fetchone()
    return total, empty


def chunks_not_ready(bot_id: Id, total: int, empty: int) -> str | None:
    """재기 전에 막을 사유. 없으면 None. DB 를 쓰지 않아 rank_trace_check 가 시험한다."""
    if total == 0 or empty:
        return (f"봇 {bot_id} 의 문서 처리가 끝나지 않았습니다(청크 {total}개 중 임베딩이 빈 것 "
                f"{empty}개). 임베딩이 빈 정답 청크는 거리 컷에 잘린 것으로 잘못 세어집니다. "
                "문서 처리가 끝난 뒤 다시 실행해주세요.")
    return None


def measure_variants(bot_id: Id, variants: list[str]) -> list[dict]:
    """봇의 활성 평가 질문마다 리랭커 후보를 한 번 만들고, 변형마다 정답 청크의 순위를 잰다."""
    from . import local_reranker, retriever  # 늦은 import: 이 모듈을 열기만 해서 모델이 뜨면 안 된다

    s = get_settings()
    if s.rerank_fusion:
        # 이 모드는 리랭커 순서를 그대로 최종 순서로 본다. 융합이 켜져 있으면 실제 검색과 달라진다.
        raise SystemExit("rerank_fusion 이 켜져 있습니다. 비교 모드는 기본값(꺼짐)에서만 돌립니다. "
                         "RERANK_FUSION=false 로 다시 실행해주세요.")
    if not s.reranker_enabled:
        raise SystemExit("reranker_enabled 가 꺼져 있습니다. RERANKER_ENABLED=true 로 다시 실행해주세요.")

    rows = _questions(bot_id, None)
    no_gold = [qid for qid, _, gold, _ in rows if gold is None]
    if no_gold:
        raise SystemExit(f"정답 청크가 끊긴 문항이 있습니다: {no_gold}. "
                         "`python -m app.eval_set load --file ...` 로 다시 적재해주세요.")
    if not rows:
        raise SystemExit(f"봇 {bot_id} 에 활성 평가 질문이 없습니다. 먼저 문제 파일을 적재해주세요.")
    # 아래 거리 질의는 embedding IS NOT NULL 만 본다. 임베딩이 빈 정답 청크는 cut 으로 뭉개져
    # 관문 분모가 조용히 낮아지므로, 처리가 덜 끝난 봇은 재지 않는다.
    not_ready = chunks_not_ready(bot_id, *_chunk_counts(bot_id))
    if not_ready:
        raise SystemExit(not_ready)

    out: list[dict] = []
    for i, (qid, question, gold, _active) in enumerate(rows, 1):
        r: dict = {"qid": qid, "question": question, "ranks": {}}
        qvec = retriever.embed_one(question)
        allrows = _all_distances(bot_id, qvec)
        dist = {cid: float(d) for cid, d in allrows}
        d1 = float(allrows[0][1])
        # trace() 는 d1, gold_dist 를 소수 넷째 자리로 반올림한 뒤 비교하고, 이 모드는 반올림하지
        # 않는다(search() 와 같다). 두 결과가 한 문항에서 갈리면 이 차이부터 볼 것.
        if s.answerable_max_distance is not None and d1 > s.answerable_max_distance:
            r["status"] = "gate"
        elif gold not in dist or dist[gold] > s.max_distance:
            r["status"] = "cut"
        else:
            cand, _, _ = _candidates(bot_id, question, qvec)
            sources = _cut(cand)
            ids = [x.chunk_id for x in sources]
            if gold not in ids:
                r["status"] = "outside"
            else:
                r["status"] = "fixable"
                contents = retriever.fetch_contents(ids)
                texts = [contents.get(x.chunk_id, x.preview) for x in sources]
                for variant in variants:
                    ranked = sources
                    if len(sources) > 1:  # 후보가 하나면 리랭커를 부르지 않는다(search() 와 같다)
                        resp = local_reranker.rerank(question, texts, variant=variant)
                        ranked = retriever._apply_order(sources, [it["id"] for it in resp["response"]])
                    r["ranks"][variant] = [x.chunk_id for x in ranked].index(gold) + 1
        out.append(r)
        print(f"  {i}/{len(rows)} 질문 {qid}: {r['status']} {r['ranks'] or ''}", flush=True)
    return out


def _print_compare(results: list[dict], variants: list[str], pairs: list[tuple[str, str]],
                   gate: str | None, top_k: int) -> None:
    print(f"\n시험 문제 {len(results)}개, top_k={top_k}")
    print(f"{'변형':<15} {'상위 5개 진입률':>14} {'고칠 수 있는 문제 기준':>20} {'정답 평균 순위':>14}")
    for v in variants:
        m = summarize(results, v, top_k)
        mean = f"{m['mean_rank']:.2f}" if m["mean_rank"] is not None else "-"
        print(f"{v:<15} {m['hit']:>3}/{m['n']:<3} {m['top_rate']:>6.3f}   "
              f"{m['hit']:>3}/{m['fixable']:<3} {m['fixable_rate']:>6.3f}       {mean:>8}")
    counts = summarize(results, variants[0], top_k)["status_counts"]
    print("\n따로 세는 문제(모든 변형에서 결과가 같다, 스펙 §5-4):")
    for status in STATUSES[1:]:
        print(f"  {counts[status]:>3}  {_STATUS_LABELS[status]}")

    for base, target in pairs:
        up, down = paired(results, base, target, top_k)
        p = sign_test_p(len(up), len(down))
        print(f"\n비교 {base} → {target}: 좋아짐 {len(up)}, 나빠짐 {len(down)}, "
              f"부호 검정 p={p:.4f} → {judge(len(up), len(down))}")
        # 나빠진 문제는 판정과 관계없이 전부 찍는다(스펙 §5-3 마지막 줄).
        for r in down:
            print(f"    나빠짐 [{r['qid']}] {r['ranks'][base]}위 → {r['ranks'][target]}위  {r['question']}")
        for r in up:
            print(f"    좋아짐 [{r['qid']}] {r['ranks'][base]}위 → {r['ranks'][target]}위  {r['question']}")

    if gate:
        room, n = gate_count(results, gate, top_k)
        ratio = room / n if n else 0.0
        verdict = "통과" if ratio >= GATE_MIN_RATIO else "통과하지 못함"
        print(f"\n관문({gate}): 고칠 수 있는데 5위 밖 {room}/{n} = {ratio:.3f} "
              f"(기준 {GATE_MIN_RATIO} 이상) → {verdict}")


def _write_compare(path: Path, bot_id: Id, variants: list[str], results: list[dict]) -> None:
    s = get_settings()
    payload = {
        "bot_id": bot_id,
        "measured_on": date.today().isoformat(),
        # 설정을 함께 적는다. 다른 설정으로 잰 결과와 이어 붙이지 않기 위해서다.
        "settings": {
            "answerable_max_distance": s.answerable_max_distance,
            "max_distance": s.max_distance,
            "top_k": s.top_k,
            "rerank_candidates": s.rerank_candidates,
            "hybrid_enabled": s.hybrid_enabled,
            "rerank_fusion": s.rerank_fusion,
        },
        "variants": variants,
        "results": results,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n{path} 에 썼습니다.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="정답 청크가 검색 파이프라인 어느 단계에서 사라지는지 추적한다")
    parser.add_argument("--bot-id", type=int, required=True)
    parser.add_argument("--qid", type=int, default=None,
                        help="이 질문 하나만 추적 (비활성이어도 보여준다)")
    parser.add_argument("--all", action="store_true",
                        help="비활성(is_active=false) 문항까지 함께 추적한다. "
                             "표에 상태 칸이 붙고, 판정 개수는 그래도 활성만 센다")
    parser.add_argument("--scores", type=int, default=None, metavar="QID",
                        help="이 질문의 리랭커 점수를 제공자별로 나란히 찍는다")
    parser.add_argument("--variants", default="local,local_int8",
                        help="--scores 와 함께 쓸 로컬 제공자 목록(쉼표 구분)")
    parser.add_argument("--compare", default=None, metavar="V1,V2",
                        help="활성 문항 전부를 이 로컬 변형들로 잰다(쉼표 구분). 예: local,local_ft")
    parser.add_argument("--pair", action="append", default=[], metavar="BASE:TARGET",
                        help="--compare 와 함께. 좋아짐, 나빠짐, 부호 검정을 낼 짝. 여러 번 줄 수 있다")
    parser.add_argument("--gate", default=None, metavar="VARIANT",
                        help="--compare 와 함께. 이 변형으로 학습 전 관문(4분의 1)을 판정한다")
    parser.add_argument("--out", default=None, metavar="PATH",
                        help="--compare 결과를 JSON 으로 쓴다(ai-service/ 기준 상대 경로)")
    args = parser.parse_args()

    if args.compare:
        variants = [v.strip() for v in args.compare.split(",") if v.strip()]
        # "a:b" 를 (a, b) 로. split(":", 1) 은 처음 콜론에서 한 번만 자른다.
        pairs = [tuple(p.split(":", 1)) for p in args.pair]
        for pair in pairs:
            if len(pair) != 2 or pair[0] not in variants or pair[1] not in variants:
                raise SystemExit(f"--pair {':'.join(pair)} 의 두 변형이 --compare 목록에 있어야 합니다.")
        if args.gate and args.gate not in variants:
            raise SystemExit(f"--gate {args.gate} 가 --compare 목록에 없습니다.")
        results = measure_variants(args.bot_id, variants)
        _print_compare(results, variants, pairs, args.gate, get_settings().top_k)
        if args.out:
            out = Path(args.out)
            if not out.is_absolute():
                out = Path(__file__).resolve().parent.parent / out
            _write_compare(out, args.bot_id, variants, results)
        return

    if args.scores is not None:
        _print_scores(args.bot_id, args.scores, args.variants.split(","))
        return

    # 기본은 활성 문항만이다. 이유는 `_questions` 주석에 있다.
    include_inactive = args.all or args.qid is not None
    rows = _questions(args.bot_id, args.qid, include_inactive=include_inactive)
    results = [trace(args.bot_id, qid, question, gold, active=bool(active))
               for qid, question, gold, active in rows]
    _print_table(results,
                 show_state=any(not r["active"] for r in results),
                 summary=args.qid is None)


if __name__ == "__main__":
    try:
        main()
    finally:
        close_pool()
