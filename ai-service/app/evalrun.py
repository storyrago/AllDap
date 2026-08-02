"""평가 실행 — 테스트 질문을 실제 파이프라인에 태워 채점한다 (W3).

한 번의 실행이 하는 일
─────────────────────────────────────────────────────────────────────────────
활성 질문(is_active=true)을 하나씩 꺼내서:
    검색(retriever.search) → 답변 생성(generator.generate) → 채점(judge.score)
을 돌리고, 질문별 결과를 `eval_results` 에, 집계를 `eval_runs` 에 저장한다.

<실제 파이프라인을 그대로 태우는 것>이 핵심이다. 채팅과 다른 경로로 돌리면
"평가에서는 좋았는데 실사용에서는 다르다"가 되어 측정이 무의미해진다.

세 가지 숫자와 그 관계 (같이 봐야 한다)
─────────────────────────────────────────────────────────────────────────────
  answered_rate     fallback 하지 않고 답한 비율
  avg_faithfulness  <답한 것들 중> 답변이 근거에 기반한 비율
  avg_relevancy     <답한 것들 중> 질문에 맞는 답이었는지

⚠️ 응답률이 높다고 좋은 게 아니다. 근거 없이 마구 답하면 응답률은 오르고 충실성은 떨어진다.
   반대로 아무것도 답 안 하면 충실성은 완벽해 보이고 응답률이 0이 된다.
   그래서 fallback 한 답변은 <채점에서 제외>하고 응답률로만 센다 —
   "모르겠다"는 근거에 충실하긴 하지만 그걸 1.0 으로 세면 평균이 거짓말이 된다.

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

from . import judge, retriever
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
        # W4 에서 켜고 끌 것들. 아직 구현 전이라 항상 false 지만,
        # 지금부터 남겨둬야 나중 실행과 <같은 모양으로> 비교된다.
        "hybrid": False,
        "reranker": False,
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

    with cursor(commit=True) as cur:
        cur.executemany(
            """INSERT INTO eval_results
                 (run_id, question_id, generated_answer, retrieved_chunks, faithfulness, relevancy)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            rows,
        )
        cur.execute(
            """UPDATE eval_runs
                  SET avg_faithfulness=%s, avg_relevancy=%s, answered_rate=%s, status='completed'
                WHERE id=%s""",
            (avg_f, avg_r, answered_rate, run_id),
        )

    _log.info(
        "평가 실행 완료 run_id=%s 질문 %d개 · 처리 %d개(실패 %d) · 답변 %d개 · 채점 %d개",
        run_id, total, processed, total - processed, answered, len(faiths),
    )
