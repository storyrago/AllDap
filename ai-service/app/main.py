"""AllDap AI 서비스 (내부 API).

이 서비스는 외부에 직접 노출하지 않는다.
W2부터 Spring Boot API 서버가 앞단에서 인증·권한·트랜잭션을 처리하고,
AI 관련 작업만 이 서비스로 위임(REST)한다.
그래서 엔드포인트 경로를 모두 /internal/* 로 둔다.
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile

from . import evaluator, evalrun, retriever
from .chunker import chunk_text
from .config import get_settings
from .db import close_pool, cursor
from .generator import generate
from .parsers import ParseError, extract_text
from .schemas import (
    ChatRequest,
    ChatResponse,
    DocumentOut,
    EvalQuestionOut,
    EvalResultOut,
    EvalRunOut,
    GenerateQuestionsRequest,
)


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

        chunks = chunk_text(text)
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
    answer, is_fallback = generate(req.message, sources)

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
