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

from . import retriever
from .chunker import chunk_text
from .config import get_settings
from .db import close_pool, cursor
from .generator import generate
from .parsers import ParseError, extract_text
from .schemas import ChatRequest, ChatResponse, DocumentOut


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


@app.delete("/internal/documents/{doc_id}", status_code=204)
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
