"""search 와 asearch 가 <똑같은> 근거를 내는지 실제 DB 로 대조한다 (스펙 5-2).

실행:
    cd ai-service && EVAL_BOT_ID=1 .venv/bin/python -m tools.async_parity_check
필요: docker compose up -d, 코퍼스가 올라간 봇, ai-service/.env 의 Cloudflare 키(질문 임베딩에만 쓴다)

왜 "돌아간다" 가 아니라 "똑같다" 를 보나
─────────────────────────────────────────────────────────────────────────────
검색에는 환각 억제 1차 방어선이 있다. async 판이 한 청크라도 다르게 내면 채팅과 평가가
다른 근거로 답하게 된다. 그래서 청크 id·점수·순서와 fallback 판정(빈 목록)이
<전부> 같아야 통과한다.

흔들림을 빼는 장치 둘
─────────────────────────────────────────────────────────────────────────────
① 질문 벡터: 진짜 임베딩을 <한 번만> 받아 두 판에 같은 벡터를 넣는다.
② 리랭커: 원격 모델 응답이 섞이지 않게 두 판 모두 같은 가짜 순서(뒤집기)를 쓴다.
   arun 자체가 run 과 같다는 것은 tools/cf_check.py 가 따로 잰다.

CI 에서 돌지 않는 이유: DB(코퍼스가 올라간 봇)와 실제 임베딩 호출이 필요하다.
"""
from __future__ import annotations

import asyncio
import sys

from app import generator, retriever
from app.db import close_async_pool, close_pool, open_async_pool
from tools.fallback_e2e_check import GROUNDED, KNOWN_RETRIEVAL_GAP, UNGROUNDED, resolve_bot_id

# (리랭커, 하이브리드) 네 조합을 다 본다. 기본값만 보면 꺼진 갈래가 안 덮인다.
CONFIGS = [(True, True), (True, False), (False, True), (False, False)]


def _fake_order(query: str, texts: list[str]) -> list[int]:
    return list(reversed(range(len(texts))))


async def _afake_order(query: str, texts: list[str]) -> list[int]:
    return _fake_order(query, texts)


def _key(sources) -> list[tuple]:
    return [(s.chunk_id, s.score) for s in sources]


async def _run(bot_id: int) -> int:
    grounded = {q for q, _ in GROUNDED}
    questions = ([q for q, _ in UNGROUNDED] + [q for q, _ in GROUNDED]
                 + [q for q, _ in KNOWN_RETRIEVAL_GAP])
    vecs = {q: retriever.embed_one(q) for q in questions}

    async def aembed_one(q: str) -> list[float]:
        return vecs[q]

    # 모듈 속성을 갈아 끼운다. search·asearch 가 이 이름들을 <모듈 전역에서> 찾기 때문에
    # 두 판 모두 같은 벡터·같은 가짜 순서를 쓰게 된다.
    retriever.embed_one = lambda q: vecs[q]
    retriever.aembed_one = aembed_one
    retriever._rerank_order = _fake_order
    retriever._arerank_order = _afake_order

    await open_async_pool()
    try:
        mismatches = non_empty = grounded_non_empty = total = 0
        for reranker, hybrid in CONFIGS:
            for q in questions:
                want = retriever.search(bot_id, q, reranker=reranker, hybrid=hybrid)
                got = await retriever.asearch(bot_id, q, reranker=reranker, hybrid=hybrid)
                total += 1
                non_empty += bool(want)
                grounded_non_empty += bool(want) and q in grounded
                if _key(want) != _key(got):
                    mismatches += 1
                    print(f"  ❌ rerank={reranker} hybrid={hybrid} {q[:30]}\n"
                          f"     sync ={_key(want)}\n     async={_key(got)}")
        want_p = generator.fetch_bot_prompt(bot_id)
        got_p = await generator.afetch_bot_prompt(bot_id)
        prompt_same = want_p == got_p
    finally:
        await close_async_pool()

    print(f"\n검색 일치 {total - mismatches}/{total} · 근거가 있던 경우 {non_empty}건 "
          f"(대조군 {grounded_non_empty}/{len(GROUNDED) * len(CONFIGS)}) · "
          f"봇 지침 일치 {prompt_same}")
    # 🔴 전부 빈 목록끼리 같아서 통과하는 <거짓 통과>를 막는다. 대조군 질문은 모든 조합에서
    #    근거가 있어야 한다. 전체 non_empty 로 세면 근거 없는 질문이 우연히 통과한 건수가
    #    대조군의 빈 자리를 메워 가드가 안 걸릴 수 있어서, 대조군만 따로 센다.
    if grounded_non_empty < len(GROUNDED) * len(CONFIGS):
        print("🔴 대조군 질문에 근거가 없던 경우가 있습니다. 코퍼스가 올라간 봇인지"
              "(EVAL_BOT_ID) 확인하세요.")
        return 1
    return 0 if mismatches == 0 and prompt_same else 1


def main() -> int:
    bot_id = resolve_bot_id()
    try:
        return asyncio.run(_run(bot_id))
    finally:
        close_pool()


if __name__ == "__main__":
    sys.exit(main())
