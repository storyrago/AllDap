"""평가 실행 — 테스트 질문을 실제 파이프라인에 태워 채점한다 (W3).

한 번의 실행이 하는 일
─────────────────────────────────────────────────────────────────────────────
활성 질문(is_active=true)을 하나씩 꺼내서:
    검색(retriever.search) → 답변 생성(generator.generate) → 채점(judge.score)
을 돌리고, 질문별 결과를 `eval_results` 에, 집계를 `eval_runs` 에 저장한다.

<실제 파이프라인을 그대로 태우는 것>이 핵심이다. 채팅과 다른 경로로 돌리면
"평가에서는 좋았는데 실사용에서는 다르다"가 되어 측정이 무의미해진다.

저장하는 숫자들과 그 관계 (반드시 같이 봐야 한다)
─────────────────────────────────────────────────────────────────────────────
  question_count    이 실행의 대상 질문 수 (비교의 기준 분모)
  scored_count      실제로 채점까지 간 질문 수 (avg_* 의 진짜 분모)
  answered_rate     fallback 하지 않고 답한 비율
  avg_faithfulness  <채점된 것들 중> 답변이 근거에 기반한 정도
  avg_relevancy     <채점된 것들 중> 질문에 맞는 답이었는지

⚠️ 응답률이 높다고 좋은 게 아니다. 근거 없이 마구 답하면 응답률은 오르고 충실성은 떨어진다.
   그래서 fallback 한 답변은 <채점에서 제외>하고 응답률로만 센다 —
   "모르겠다"는 근거에 충실하긴 하지만 그걸 1.0 으로 세면 평균이 거짓말이 된다.

🔴 <반대 방향이 더 위험하다 — 실제로 속았다.>
   avg_faithfulness 는 <답을 덜 할수록 저절로 올라간다.> fallback 이 채점에서 빠지므로,
   어려운 질문이 fallback 되면 남은 쉬운 질문들만 평균에 남는다(생존 편향).

   리랭커 before/after 실측(2026-08-02):
     충실성 0.714 → 0.789 로 <올랐다>. 그런데 0점짜리 2건이 fallback 된 결과였고,
     그 2건을 0 으로 환산하면 0.714 로 <완전히 동일>했다. 실제 개선은 없었다.

   그래서 설정을 비교할 때는 avg_faithfulness 를 <그대로 쓰면 안 된다.>
   question_count 를 분모로 되돌린 값을 봐야 한다:
       전체 충실성 = avg_faithfulness × scored_count / question_count
   이 값은 답을 덜 하면 같이 내려가므로 편향에 넘어가지 않는다.
   (V3__eval_run_counts.sql 이 그래서 만들어졌다)

config 에 실행 시점 설정을 저장하는 이유
─────────────────────────────────────────────────────────────────────────────
W4 의 목표가 "벡터 검색만 vs 하이브리드+리랭커" 비교표다.
같은 테스트셋을 설정만 바꿔 돌리고 점수를 나란히 놓으려면,
<그 실행이 어떤 설정이었는지>가 실행과 함께 박제돼야 한다.
config 가 없으면 나중에 "이 점수는 어떤 설정이었지?"를 알 수 없어 비교가 성립하지 않는다.
"""
from __future__ import annotations

import json
import logging
from uuid import UUID

from . import cf, judge, retriever
from .config import get_settings
from .db import cursor
from .generator import generate

_log = logging.getLogger(__name__)


def create_run(bot_id: UUID) -> tuple[UUID, int]:
    """실행 행을 만들고 (run_id, 대상 질문 수) 를 돌려준다.

    질문 수를 함께 세는 이유: 0건이면 실행을 시작할 필요가 없고,
    호출한 쪽이 "질문부터 만드세요"라고 안내해야 하기 때문이다.
    """
    s = get_settings()
    # 실행 시점의 설정을 통째로 박제한다. 나중에 이 실행이 어떤 조건이었는지 아는 유일한 단서다.
    config = {
        "top_k": s.top_k,
        "max_distance": s.max_distance,
        "chat_model": s.chat_model,
        "embedding_model": s.embedding_model,
        "judge_model": s.judge_model,
        # W4 에서 켜고 끄는 것들. 이 값이 before/after 비교의 <축>이다.
        "reranker": s.reranker_enabled,
        "reranker_model": s.reranker_model if s.reranker_enabled else None,
        "rerank_candidates": s.rerank_candidates if s.reranker_enabled else None,
        # 🔴 융합 여부도 박제한다. 이 값이 다르면 <같은 reranker=true 라도 다른 실험>이다.
        #    안 적으면 "0.844 는 어느 방식이었지?" 를 나중에 알 수 없다.
        "rerank_fusion": s.rerank_fusion if s.reranker_enabled else None,
        "hybrid": s.hybrid_enabled,
        "hybrid_candidates": s.hybrid_candidates if s.hybrid_enabled else None,
        "hybrid_rrf_k": s.hybrid_rrf_k if s.hybrid_enabled else None,
        # 🔴 청킹도 박제한다. 청킹은 <질의 시점>이 아니라 업로드 때 정해지는 값이라
        #    이 config 에 없으면 "이 점수가 어느 청킹이었는지"를 알 방법이 없다.
        #    2026-08-03 청킹 전후를 비교하다가 그 사실을 깨달아 추가했다 —
        #    분모를 안 적어 avg_faithfulness 를 해석하지 못했던 것과 같은 실수다.
        "chunk_size": s.chunk_size,
        "chunk_overlap": s.chunk_overlap,
        "chunk_split_headings": s.chunk_split_headings,
        # 🔴 온도도 박제한다. 0 이 아니면 <같은 설정으로도 점수가 달라지므로>,
        #    이 값을 모르면 두 실행의 차이가 설정 때문인지 운 때문인지 구분할 수 없다.
        "chat_temperature": s.chat_temperature,
        "judge_temperature": s.judge_temperature,
    }

    with cursor(commit=True) as cur:
        cur.execute(
            "SELECT count(*) FROM eval_questions WHERE bot_id=%s AND is_active",
            (bot_id,),
        )
        total = cur.fetchone()[0]

        cur.execute(
            """INSERT INTO eval_runs (bot_id, config, status)
               VALUES (%s, %s, 'running') RETURNING id""",
            (bot_id, json.dumps(config)),
        )
        run_id = cur.fetchone()[0]

    return run_id, total


def execute(run_id: UUID, bot_id: UUID) -> None:
    """실제 채점. 백그라운드에서 실행된다.

    ⚠️ 이 함수는 <절대 예외를 밖으로 내보내면 안 된다>.
       BackgroundTasks 에서 예외가 나면 아무도 못 보고, eval_runs 는
       영원히 'running' 으로 남는다. 화면은 끝나지 않는 로딩을 보여준다.
       그래서 통째로 try 로 감싸고 실패도 status 에 남긴다.
    """
    try:
        _execute(run_id, bot_id)
    except Exception as e:  # noqa: BLE001 - 어떤 실패든 상태로 남겨야 한다
        _log.exception("평가 실행 실패: run_id=%s", run_id)
        with cursor(commit=True) as cur:
            cur.execute("UPDATE eval_runs SET status='failed' WHERE id=%s", (run_id,))
        _ = e


def _execute(run_id: UUID, bot_id: UUID) -> None:
    # 💰 이 실행이 쓴 뉴런을 센다. 응답이 호출당 정확한 값을 주므로 추정할 필요가 없다.
    #    ⚠️ 전역 누적이라 평가를 <동시에> 두 개 돌리면 섞인다. 보통 하나씩 돈다.
    cf.reset_neurons()
    with cursor() as cur:
        cur.execute(
            """SELECT id, question, ground_truth
                 FROM eval_questions
                WHERE bot_id=%s AND is_active
                ORDER BY created_at""",
            (bot_id,),
        )
        questions = cur.fetchall()

    # 집계용. 채점에 성공한 것만 담는다.
    faiths: list[float] = []
    rels: list[float] = []
    answered = 0
    # ⚠️ processed 는 <검색·생성이 실제로 돌아간> 질문 수다. total 과 다를 수 있다.
    #    응답률의 분모가 되며, 이걸 total 로 쓰면 안 되는 이유는 아래 집계 부분 주석 참고.
    processed = 0
    rows: list[tuple] = []

    for qid, question, ground_truth in questions:
        # ── 실제 파이프라인을 그대로 태운다 ──────────────────────────────
        # ⚠️ DB 커서 밖이다. 검색·생성·채점이 수십 초 걸리는데 트랜잭션 안에 두면
        #    커넥션 풀(10개)이 말라 채팅·업로드까지 멈춘다.
        try:
            sources = retriever.search(bot_id, question)
            answer, is_fallback = generate(question, sources)
        except Exception as e:  # noqa: BLE001
            # 한 질문이 실패했다고 실행 전체를 죽이지 않는다(429 쿼터 등).
            # 점수 없이 행만 남겨 "이 질문은 못 쟀다"를 보이게 한다.
            #
            # ⚠️ processed 를 <올리지 않는다>. 이건 "답을 못 했다"가 아니라
            #    "물어보지도 못했다"이기 때문이다 — 우리 인프라가 실패한 것이지
            #    챗봇의 품질 문제가 아니다. 응답률 분모에 넣으면 점수가 거짓이 된다.
            #    (generated_answer 가 NULL 로 남아 fallback 과 구분된다)
            _log.warning("질문 처리 실패(건너뜀) qid=%s: %s: %s", qid, type(e).__name__, e)
            rows.append((run_id, qid, None, json.dumps([]), None, None))
            continue

        processed += 1

        retrieved = json.dumps(
            [{"chunk_id": str(s.chunk_id), "filename": s.filename, "score": s.score} for s in sources],
            ensure_ascii=False,
        )

        if is_fallback:
            # fallback 은 채점하지 않는다(위 모듈 주석 참고). 답변 본문은 남겨서
            # 나중에 "무엇을 못 답했나"를 볼 수 있게 한다.
            rows.append((run_id, qid, answer, retrieved, None, None))
            continue

        answered += 1
        sc = judge.score(question, ground_truth, sources, answer)
        if sc is None:
            # 채점 실패는 0점이 아니다. 평균에서 빼고 행만 남긴다.
            rows.append((run_id, qid, answer, retrieved, None, None))
            continue

        faiths.append(sc.faithfulness)
        rels.append(sc.relevancy)
        rows.append((run_id, qid, answer, retrieved, sc.faithfulness, sc.relevancy))

    # ── 저장은 한 트랜잭션에 몰아서 ────────────────────────────────────
    total = len(questions)
    avg_f = sum(faiths) / len(faiths) if faiths else None
    avg_r = sum(rels) / len(rels) if rels else None

    # ⚠️ 분모가 total 이 아니라 processed 다. 여기서 total 을 쓰면 <응답률이 거짓말을 한다.>
    #
    # 실제로 그 버그를 냈다(2026-08-02): 질문 21개 중 5개가 429 쿼터 초과로 아예 처리되지
    # 않았는데 분모에 그대로 들어가 응답률이 0.762 로 찍혔다. 진짜 값은 16/16 = 1.0 이다.
    # <"답을 못 했다"와 "물어보지도 못했다"는 완전히 다른 상태다.>
    # 전자는 챗봇의 품질이고 후자는 우리 인프라의 문제인데, 섞으면 W4 비교표에서
    # 쿼터가 모자란 날의 실행이 "품질이 나쁜 설정"으로 둔갑한다.
    #
    # AGENTS.md 가 W2 에서 이미 경고한 항목이다 — "Python 호출이 실패하면 질문만 남고
    # 답변 행이 없다. 이건 fallback 과 다른 상태다 — W3 에서 미답변을 집계할 때 섞지 말 것."
    #
    # 처리 실패 건수는 별도 컬럼이 없어 저장하지 않는다. 대신 eval_results 에
    # generated_answer=NULL 인 행으로 남으므로 화면이 세어 보여줄 수 있다.
    answered_rate = answered / processed if processed else None

    # 🔴 처리하지 못한 질문이 있으면 <그 실행은 다른 설정과 비교할 수 없다.>
    #
    #   completed  전 질문을 처리했다 = 설정 비교에 쓸 수 있다
    #   partial    일부가 처리 실패했다(429·타임아웃) = <분모가 달라> 비교하면 안 된다
    #   failed     한 문항도 처리하지 못했다 = 측정 자체가 없다
    #
    # 2026-08-12 에 전멸(failed)을 먼저 겪어 고쳤는데, **그때 partial 을 안 만든 것이
    # 바로 다음 날 나를 물었다.** 16문항 중 13개만 처리된 실행이 completed 로 남았고,
    # 그 실행의 0.782 를 유효한 측정으로 읽어 "리랭커 융합은 손해다"라고 결론냈다.
    # 한도가 풀린 뒤 온전히 3회 재보니 0.844·0.875·0.875 로 <차이가 없었다.>
    # 즉 결론이 통째로 틀렸고, 원인은 <덜 잰 실행과 다 잰 실행을 같은 값으로 뭉갠 것>이다.
    #
    # 그때 커밋 메시지에 "일부만 실패한 실행은 그대로 completed 다(그건 측정이 됐다)"
    # 라고 적었는데 그 판단이 틀렸다. 측정은 됐지만 <비교>는 안 된다. 분모가 다르다.
    if not processed:
        status = "failed"
    elif processed < total:
        status = "partial"
    else:
        status = "completed"

    with cursor(commit=True) as cur:
        cur.executemany(
            """INSERT INTO eval_results
                 (run_id, question_id, generated_answer, retrieved_chunks, faithfulness, relevancy)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            rows,
        )
        cur.execute(
            """UPDATE eval_runs
                  SET avg_faithfulness=%s, avg_relevancy=%s, answered_rate=%s,
                      question_count=%s, scored_count=%s, status=%s
                WHERE id=%s""",
            (avg_f, avg_r, answered_rate, total, len(faiths), status, run_id),
        )

    used = cf.neurons_used()
    _log.info(
        "평가 실행 완료 run_id=%s 질문 %d개 · 처리 %d개(실패 %d) · 답변 %d개 · 채점 %d개 "
        "· 💰 %.1f 뉴런 (%s)",
        run_id, total, processed, total - processed, answered, len(faiths),
        sum(used.values()),
        " / ".join(f"{m.rsplit('/', 1)[-1]} {n:.1f}" for m, n in sorted(used.items(), key=lambda x: -x[1])),
    )
