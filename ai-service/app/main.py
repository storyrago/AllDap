"""AllDap AI 서비스 (내부 API).

이 서비스는 외부에 직접 노출하지 않는다.
W2부터 Spring Boot API 서버가 앞단에서 인증·권한·트랜잭션을 처리하고,
AI 관련 작업만 이 서비스로 위임(REST)한다.
그래서 엔드포인트 경로를 모두 /internal/* 로 둔다.
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile

from . import conflicts, evaluator, evalrun, retriever
from .chunker import chunk_text
from .config import get_settings
from .db import close_pool, cursor
from .generator import GenerationFailed, build_system_prompt, fetch_bot_prompt, generate
from .parsers import ParseError, extract_text
from .schemas import (
    ChatRequest,
    ChatResponse,
    ConflictOut,
    ConflictScanOut,
    ConflictStatusRequest,
    DocumentOut,
    EvalQuestionOut,
    EvalResultOut,
    EvalRunOut,
    GenerateQuestionsRequest,
)

# 🔴 로깅 설정이 <없었다>. 루트 로거에 핸들러가 없으면 파이썬의 lastResort 가
#    WARNING 이상만 stderr 로 내보낸다 — 즉 `_log.info` 가 <한 번도 안 보였다>.
#    "평가 실행 완료 …" 도, 그 안의 비용 집계도 전부 조용히 사라지고 있었다.
#    2026-08-13 에 뉴런 로그를 붙이다 발견했다.
#    ⚠️ uvicorn 은 자기 로거를 따로 설정하고 propagate=False 라 중복 출력은 안 난다.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

_log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    close_pool()


app = FastAPI(title="AllDap AI Service", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    with cursor() as cur:
        cur.execute("SELECT 1")
        cur.fetchone()
    return {"status": "ok"}


# ── 문서 처리 ────────────────────────────────────────────────────────

def _process_document(doc_id: UUID, bot_id: UUID, filename: str, data: bytes) -> None:
    """업로드 응답과 분리해 백그라운드에서 실행.

    ※ MVP 한정. 프로세스가 죽으면 작업이 유실되므로,
       트래픽이 붙으면 Redis + RQ 같은 큐로 옮겨야 한다.
    """
    s = get_settings()

    def _fail(reason: str) -> None:
        with cursor(commit=True) as cur:
            cur.execute(
                "UPDATE documents SET status='failed', error_message=%s WHERE id=%s",
                (reason, doc_id),
            )

    try:
        with cursor(commit=True) as cur:
            cur.execute("UPDATE documents SET status='processing' WHERE id=%s", (doc_id,))

        try:
            _, text = extract_text(filename, data)
        except ParseError as e:
            _fail(str(e))
            return

        chunks = chunk_text(
            text,
            size=s.chunk_size,
            overlap=s.chunk_overlap,
            split_headings=s.chunk_split_headings,
        )
        if not chunks:
            _fail("문서에서 유효한 내용을 찾지 못했습니다.")
            return

        vectors = retriever.embed([c.content for c in chunks])

        with cursor(commit=True) as cur:
            cur.executemany(
                """INSERT INTO chunks (document_id, bot_id, chunk_index, content, embedding, meta)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                [
                    (doc_id, bot_id, c.index, c.content, v, __import__("json").dumps(c.meta))
                    for c, v in zip(chunks, vectors)
                ],
            )
            cur.execute(
                """UPDATE documents
                   SET status='ready', char_count=%s, chunk_count=%s, error_message=NULL
                   WHERE id=%s""",
                (len(text), len(chunks), doc_id),
            )
    except Exception as e:  # noqa: BLE001 - 어떤 실패든 상태로 남겨야 한다
        _fail(f"처리 중 오류가 발생했습니다: {type(e).__name__}")


@app.post("/internal/bots/{bot_id}/documents", response_model=DocumentOut, status_code=202)
async def upload_document(
    bot_id: UUID,
    background: BackgroundTasks,
    file: UploadFile = File(...),
) -> DocumentOut:
    s = get_settings()
    data = await file.read()

    if len(data) > s.upload_max_bytes:
        raise HTTPException(413, f"파일이 너무 큽니다 (최대 {s.upload_max_bytes // 1024 // 1024}MB)")
    if not data:
        raise HTTPException(400, "빈 파일입니다.")

    filename = file.filename or "unknown"
    try:
        from .parsers import detect_type
        ftype = detect_type(filename)
    except ParseError as e:
        raise HTTPException(400, str(e)) from e

    with cursor(commit=True) as cur:
        cur.execute(
            """INSERT INTO documents (bot_id, filename, file_type, status)
               VALUES (%s, %s, %s, 'pending') RETURNING id""",
            (bot_id, filename, ftype),
        )
        doc_id = cur.fetchone()[0]

    background.add_task(_process_document, doc_id, bot_id, filename, data)
    return DocumentOut(id=doc_id, filename=filename, file_type=ftype, status="pending")


@app.get("/internal/bots/{bot_id}/documents", response_model=list[DocumentOut])
def list_documents(bot_id: UUID) -> list[DocumentOut]:
    with cursor() as cur:
        cur.execute(
            """SELECT id, filename, file_type, status, error_message, char_count, chunk_count
               FROM documents WHERE bot_id=%s ORDER BY created_at DESC""",
            (bot_id,),
        )
        rows = cur.fetchall()
    return [
        DocumentOut(
            id=r[0], filename=r[1], file_type=r[2], status=r[3],
            error_message=r[4], char_count=r[5], chunk_count=r[6],
        )
        for r in rows
    ]


# response_model=None 이 왜 필요한가:
#   FastAPI 0.89부터 함수의 반환 타입 애너테이션(-> None)을 보고 응답 모델을 자동으로 추론한다.
#   그런데 204 No Content 는 정의상 본문을 가질 수 없어서, 추론된 모델이 있으면
#   "Status code 204 must not have a response body" 로 앱이 뜨지도 못하고 죽는다.
#   (요청이 올 때가 아니라 라우트를 등록하는 import 시점에 터진다)
#   response_model=None 은 "애너테이션에서 추론하지 말라"는 명시적 지시다.
@app.delete("/internal/documents/{doc_id}", status_code=204, response_model=None)
def delete_document(doc_id: UUID) -> None:
    with cursor(commit=True) as cur:
        cur.execute("DELETE FROM documents WHERE id=%s", (doc_id,))  # 청크는 CASCADE


# ── 채팅 ─────────────────────────────────────────────────────────────

@app.post("/internal/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    started = time.perf_counter()

    sources = retriever.search(req.bot_id, req.message)
    try:
        # 봇별 지침(PRD F-06). 없으면 기본 규칙만 쓴다.
        # ⚠️ 대체가 아니라 <덧붙임>이다 — build_system_prompt 주석 참고.
        answer, is_fallback = generate(
            req.message,
            sources,
            system_prompt=build_system_prompt(fetch_bot_prompt(req.bot_id)),
        )
    except GenerationFailed as e:
        # 🔴 fallback 으로 뭉개지 않는다. 근거는 찾았는데 <답변을 못 받은> 것이라
        #    "문서에서 답을 찾지 못했어요" 로 내보내면 제품이 거짓말을 한다.
        #    오류로 올려야 대화 로그에도 답변 행이 남지 않는다 — 그게 사실이다.
        #
        # ⚠️ 왜 로그를 남기나: 아래 detail 은 사용자에게 닿지 않는다. Spring 이 Python 5xx 를
        #    AI_SERVICE_UNAVAILABLE 로 바꿔 자기 문구를 내보내기 때문이다. 원인(잘림인지
        #    빈 응답인지, max_tokens 가 얼마였는지)은 여기서만 볼 수 있다.
        _log.warning("답변 생성 실패 bot_id=%s: %s", req.bot_id, e)
        raise HTTPException(
            503,
            "답변을 완성하지 못했습니다. 질문을 더 좁혀서 다시 물어봐 주세요.",
        ) from e

    latency_ms = int((time.perf_counter() - started) * 1000)
    return ChatResponse(
        answer=answer,
        sources=sources,
        is_fallback=is_fallback,
        latency_ms=latency_ms,
    )


# ── 품질 평가 (W3) ───────────────────────────────────────────────────

@app.post(
    "/internal/bots/{bot_id}/eval/questions/generate",
    response_model=list[EvalQuestionOut],
)
def generate_eval_questions(
    bot_id: UUID, req: GenerateQuestionsRequest
) -> list[EvalQuestionOut]:
    """문서 청크에서 테스트 질문·정답 쌍을 만들어 저장한다.

    왜 <동기>인가 (업로드는 202 인데)
    ─────────────────────────────────────────────────────────────────────
    업로드가 202 로 즉시 답하고 백그라운드로 도는 건 `documents.status` 라는
    <폴링할 행>이 있기 때문이다. 화면이 pending → ready 를 지켜볼 수 있다.
    그런데 `eval_questions` 에는 상태 컬럼이 없다. 202 를 돌려줘도
    프론트가 무엇을 폴링해야 할지가 없고, 그걸 만들려면 V2 마이그레이션이 필요하다.
    게다가 BackgroundTasks 는 프로세스가 죽으면 작업이 유실되는데(위 _process_document 주석),
    여기엔 "유실됐다"를 적어둘 자리조차 없다.
    → 대신 count 상한으로 응답 시간을 통제한다. Spring 의 읽기 타임아웃은 120초다.
    TODO(W3): 실측 지연이 상한에 가까워지면 그때 상태 컬럼(V2)과 함께 비동기로 바꾼다.

    def 이지 async def 가 아닌 이유
    ─────────────────────────────────────────────────────────────────────
    Gemini SDK 호출이 <블로킹>이라 async def 안에 두면 이벤트 루프를 통째로 막는다.
    그러면 이 요청 하나가 도는 동안 다른 채팅·업로드 요청이 전부 멈춘다.
    일반 def 로 두면 FastAPI(Starlette)가 알아서 스레드풀에서 돌려준다.
    `/internal/chat` 이 같은 이유로 def 다.
    """
    s = get_settings()

    # 상한 검사를 여기서 하는 이유는 GenerateQuestionsRequest 주석 참고(설정값을 늦게 읽는다).
    if req.count > s.eval_max_questions:
        raise HTTPException(
            400,
            f"한 번에 만들 수 있는 질문은 최대 {s.eval_max_questions}개입니다. "
            f"개수를 줄여서 다시 시도해주세요.",
        )

    chunks = evaluator.sample_chunks(bot_id, req.count)

    if not chunks:
        # 0건인 이유가 둘이고, 관리자가 해야 할 일이 서로 다르다. 갈라서 안내한다.
        if evaluator.count_ready_chunks(bot_id) == 0:
            raise HTTPException(
                400,
                "처리가 끝난 문서가 없습니다. 문서를 올린 뒤 상태가 '준비됨'이 되면 다시 시도해주세요.",
            )
        raise HTTPException(
            400,
            "이미 모든 문서 조각으로 질문을 만들었습니다. "
            "새 문서를 올리거나, 기존 질문을 수정해서 쓰세요.",
        )

    # ⚠️ LLM 호출은 반드시 cursor() 블록 <밖>이다.
    #    커넥션 풀이 10개뿐이라(db.py) 수십 초짜리 외부 호출을 트랜잭션 안에 두면
    #    풀이 말라 이 요청과 무관한 채팅·업로드까지 전부 멈춘다.
    #    업로드가 `상태 UPDATE → (밖) 임베딩 → INSERT` 로 쪼개져 있는 것과 같은 이유다.
    pairs = []
    for chunk_id, content in chunks:
        pair = evaluator.make_question(content)
        # None 은 실패가 아니라 "이 청크로는 문제를 못 냈다"이다. 건너뛰고 계속한다.
        if pair is not None:
            pairs.append((chunk_id, pair))

    if not pairs:
        # 청크는 뽑았는데 한 건도 못 만들었다 = 우리 쪽(LLM) 문제다.
        # 사용자가 입력으로 고칠 수 있는 게 없으므로 4xx 가 아니라 5xx 로 알린다.
        raise HTTPException(
            502, "질문을 만들지 못했습니다. 잠시 후 다시 시도해주세요."
        )

    rows = evaluator.save_questions(bot_id, pairs)
    return [
        EvalQuestionOut(
            id=r[0], question=r[1], ground_truth=r[2],
            source_chunk_id=r[3], is_active=r[4], created_at=r[5],
        )
        for r in rows
    ]


@app.get("/internal/bots/{bot_id}/eval/questions", response_model=list[EvalQuestionOut])
def list_eval_questions(bot_id: UUID) -> list[EvalQuestionOut]:
    """테스트 질문 목록. 비활성(is_active=false) 도 함께 준다 — 화면에서 켜고 꺼야 하기 때문."""
    with cursor() as cur:
        cur.execute(
            """SELECT id, question, ground_truth, source_chunk_id, is_active, created_at
                 FROM eval_questions WHERE bot_id=%s ORDER BY created_at""",
            (bot_id,),
        )
        rows = cur.fetchall()
    return [
        EvalQuestionOut(
            id=r[0], question=r[1], ground_truth=r[2],
            source_chunk_id=r[3], is_active=r[4], created_at=r[5],
        )
        for r in rows
    ]


@app.post("/internal/bots/{bot_id}/eval/runs", response_model=EvalRunOut, status_code=202)
def start_eval_run(bot_id: UUID, background: BackgroundTasks) -> EvalRunOut:
    """평가를 시작한다. 즉시 running 상태의 실행을 돌려주고 채점은 백그라운드에서 진행한다.

    왜 <비동기>인가 — 질문 생성(/eval/questions/generate)은 동기인데
    ─────────────────────────────────────────────────────────────────────
    차이는 딱 하나다: **폴링할 대상이 있는가.**
      · eval_questions 에는 상태 컬럼이 없다 → 202 를 줘도 화면이 볼 게 없다 → 동기
      · eval_runs 에는 status('running'/'completed'/'failed') 가 있다 → 202 가 성립한다
    그리고 여기는 질문 수만큼 (검색 + 생성 + 채점)이 돌아 <반드시> 수십 초를 넘긴다.
    질문 20개면 호출이 40번이다. 동기로 두면 Spring 의 읽기 타임아웃(120초)에 걸린다.

    ⚠️ BackgroundTasks 는 프로세스가 죽으면 작업이 유실된다(업로드와 같은 한계).
       다만 여기는 유실돼도 status 가 'running' 으로 남아 <흔적이 보인다>.
       TODO(W4): 오래 running 인 실행을 failed 로 정리하는 절차가 필요하다.
    """
    run_id, total = evalrun.create_run(bot_id)

    if total == 0:
        # 질문이 없으면 돌릴 게 없다. 만들어둔 실행 행은 지워서 빈 실행이 목록에 쌓이지 않게 한다.
        with cursor(commit=True) as cur:
            cur.execute("DELETE FROM eval_runs WHERE id=%s", (run_id,))
        raise HTTPException(
            400,
            "평가할 테스트 질문이 없습니다. 먼저 문서에서 질문을 생성한 뒤 다시 시도해주세요.",
        )

    background.add_task(evalrun.execute, run_id, bot_id)

    with cursor() as cur:
        cur.execute(
            "SELECT id, status, config, created_at FROM eval_runs WHERE id=%s", (run_id,)
        )
        r = cur.fetchone()
    return EvalRunOut(id=r[0], status=r[1], config=r[2], created_at=r[3])


@app.get("/internal/bots/{bot_id}/eval/runs", response_model=list[EvalRunOut])
def list_eval_runs(bot_id: UUID) -> list[EvalRunOut]:
    """실행 이력. 최신순.

    화면은 이 목록을 폴링해 status 가 completed 로 바뀌는 걸 본다.
    W4 의 before/after 비교표도 이 목록에서 두 실행을 골라 만든다 — config 가 그 축이다.
    """
    with cursor() as cur:
        cur.execute(
            """SELECT id, status, config, avg_faithfulness, avg_relevancy, answered_rate, created_at
                 FROM eval_runs WHERE bot_id=%s ORDER BY created_at DESC""",
            (bot_id,),
        )
        rows = cur.fetchall()
    return [
        EvalRunOut(
            id=r[0], status=r[1], config=r[2],
            # NUMERIC 은 psycopg 가 Decimal 로 준다. float 로 바꿔야 JSON 으로 나간다.
            avg_faithfulness=float(r[3]) if r[3] is not None else None,
            avg_relevancy=float(r[4]) if r[4] is not None else None,
            answered_rate=float(r[5]) if r[5] is not None else None,
            created_at=r[6],
        )
        for r in rows
    ]


@app.get("/internal/eval/runs/{run_id}/results", response_model=list[EvalResultOut])
def list_eval_results(run_id: UUID) -> list[EvalResultOut]:
    """질문별 채점 결과. <점수 낮은 순>이 기본 정렬이다.

    잘된 답을 구경하는 화면이 아니라 <못한 답을 찾아 고치는 화면>이기 때문이다.
    NULL(채점 못 함)을 먼저 보여준다 — 그것도 들여다봐야 할 대상이다.
    """
    with cursor() as cur:
        cur.execute(
            """SELECT r.question_id, q.question, q.ground_truth,
                      r.generated_answer, r.retrieved_chunks, r.faithfulness, r.relevancy
                 FROM eval_results r
                 JOIN eval_questions q ON q.id = r.question_id
                WHERE r.run_id = %s
                ORDER BY r.faithfulness ASC NULLS FIRST, r.relevancy ASC NULLS FIRST""",
            (run_id,),
        )
        rows = cur.fetchall()
    return [
        EvalResultOut(
            question_id=r[0], question=r[1], ground_truth=r[2],
            generated_answer=r[3], retrieved_chunks=r[4] or [],
            faithfulness=float(r[5]) if r[5] is not None else None,
            relevancy=float(r[6]) if r[6] is not None else None,
        )
        for r in rows
    ]


# ── 문서 간 모순 (진단) ───────────────────────────────────────────────

@app.post("/internal/bots/{bot_id}/conflicts/scan", response_model=ConflictScanOut)
def scan_conflicts(bot_id: UUID) -> ConflictScanOut:
    """문서끼리 어긋나는 곳을 훑는다.

    왜 <동기>인가 (평가 실행은 202 인데)
    ─────────────────────────────────────────────────────────────────────
    기준은 하나다: **폴링할 대상이 있는가.**
      · eval_runs 에는 status 가 있다 → 202 를 주면 화면이 그걸 본다
      · doc_conflicts 에는 "스캔 한 번" 을 가리키는 행이 없다 → 202 를 줘도 볼 게 없다
    그래서 질문 생성(/eval/questions/generate)과 같은 선택을 한다 —
    <상한(conflict_max_pairs)으로 응답 시간을 통제하는 동기 API>.

    ⚠️ 후보가 상한보다 많으면 가까운 쌍부터 처리하고 나머지는 남는다.
       판정 결과를 'clear' 로도 저장하므로 다시 부르면 남은 것부터 이어서 한다.
       응답의 candidates 가 상한과 같으면 "아직 남았을 수 있다"는 신호다.

    def 이지 async def 가 아닌 이유는 /internal/chat 과 같다 —
    LLM 호출이 블로킹이라 async 에 두면 이벤트 루프를 통째로 막는다.
    """
    return ConflictScanOut(**conflicts.scan(bot_id).model_dump())


@app.get("/internal/bots/{bot_id}/conflicts", response_model=list[ConflictOut])
def list_conflicts(bot_id: UUID, status: str = "open") -> list[ConflictOut]:
    """충돌 목록. 기본은 관리자가 아직 안 본 것(open)만.

    ⚠️ bot_id 로 반드시 좁힌다. /internal/* 에는 인증이 없어서
       이 조건 하나가 봇 간 격리의 전부다.

    청크 원문을 함께 준다 — 관리자가 판정을 <검증>할 수 있어야 하기 때문이다.
    요약(topic/a_says/b_says)만 주면 "정말 그렇게 쓰여 있나"를 확인할 방법이 없고,
    확인할 수 없는 지적은 무시당한다.
    """
    with cursor() as cur:
        cur.execute(
            """SELECT k.id, k.topic, k.a_says, k.b_says,
                      da.filename, db.filename,
                      ca.content,  cb.content,
                      k.distance, k.status, k.created_at
                 FROM doc_conflicts k
                 JOIN chunks ca    ON ca.id = k.chunk_a_id
                 JOIN documents da ON da.id = ca.document_id
                 JOIN chunks cb    ON cb.id = k.chunk_b_id
                 JOIN documents db ON db.id = cb.document_id
                WHERE k.bot_id = %s AND k.status = %s
                ORDER BY k.distance NULLS LAST, k.created_at""",
            (bot_id, status),
        )
        rows = cur.fetchall()

    return [
        ConflictOut(
            id=r[0], topic=r[1], a_says=r[2], b_says=r[3],
            a_filename=r[4], b_filename=r[5],
            a_content=r[6], b_content=r[7],
            distance=r[8], status=r[9], created_at=r[10],
        )
        for r in rows
    ]


@app.patch("/internal/bots/{bot_id}/conflicts/{conflict_id}", response_model=ConflictOut)
def update_conflict_status(
    bot_id: UUID, conflict_id: UUID, req: ConflictStatusRequest
) -> ConflictOut:
    """충돌 1건의 상태를 바꾼다 (주로 오탐을 'ignored' 로 치우는 용도).

    🔴 경로에 bot_id 가 <반드시> 있어야 한다.
       conflict_id 만 받으면 Spring 이 "이게 누구 봇의 것인지" 를 알 수 없어
       소유권 확인(findOwnedBot)을 할 수가 없다. 그러면 남의 봇 충돌을
       id 만 알아내 치워버릴 수 있다. 아래 UPDATE 도 두 값으로 함께 좁힌다.

    ⚠️ 'ignored' 는 재스캔에서 되살아나면 안 된다 —
       conflicts.py 의 후보 질의가 NOT EXISTS 로 이미 걸러준다.
    """
    with cursor(commit=True) as cur:
        cur.execute(
            "UPDATE doc_conflicts SET status=%s WHERE id=%s AND bot_id=%s RETURNING id",
            (req.status, conflict_id, bot_id),
        )
        if cur.fetchone() is None:
            # 없는 id 와 <남의 봇 것>을 같은 404 로 답한다. 구분해주면
            # id 를 무작위로 던져 남의 충돌이 존재하는지 훑을 수 있다.
            # (BotService 가 남의 봇을 403 이 아니라 404 로 답하는 것과 같은 이유다)
            raise HTTPException(404, "해당 항목을 찾을 수 없습니다.")

    found = list_conflicts(bot_id, status=req.status)
    for c in found:
        if c.id == conflict_id:
            return c
    # UPDATE 는 됐는데 조회가 안 되는 경우 = 청크가 그 사이에 지워졌다(문서 삭제·재청킹).
    raise HTTPException(404, "해당 항목을 찾을 수 없습니다.")
