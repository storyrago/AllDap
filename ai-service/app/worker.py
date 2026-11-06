"""문서 처리 워커 (2026-11-06). 스펙: docs/superpowers/specs/2026-11-06-celery-document-worker-design.md

띄우는 법 (uvicorn 과 다른 터미널에서):
    cd ai-service && .venv/bin/celery -A app.worker worker --pool=solo --loglevel=info

왜 이 파일이 main.py 와 따로 있나 (스펙 3-1)
─────────────────────────────────────────────────────────────────────────────
워커는 이 모듈을 import 해서 뜬다. 처리 코드가 main.py 에 있으면 워커가 FastAPI 앱 전체
(라우트, 미들웨어, 지표)를 만들어야 한다. 의존 방향은 main → worker 하나다.
🔴 이 파일에서 `from .main import ...` 를 하지 말 것. 순환 import 가 되고, 워커가 API 를 품는다.

왜 --pool=solo 인가
─────────────────────────────────────────────────────────────────────────────
기본 풀(prefork)은 자식 프로세스를 fork 한다. 이 조각에서는
  ① 동시 처리 1건이면 충분하고(로컬, 학습용),
  ② 처리 중 kill -9 실측(스펙 6-4)을 할 때 죽일 프로세스가 하나라 결과가 분명하다.
동시 처리를 늘리는 것은 이 조각의 범위가 아니다.

🔴 이 조각의 한계 (스펙 7절)
─────────────────────────────────────────────────────────────────────────────
task_acks_late=False 다. Celery 는 메시지를 <꺼내자마자> 브로커에서 지운다. 그래서 처리 중에
워커가 죽으면 그 문서는 processing 에 멈춘다. 이 조각은 "유실 해결" 이 아니라 "워커 분리" 다.
"""
from __future__ import annotations

import json
import logging

from celery import Celery
from celery.signals import worker_init

from . import retriever, storage
from .chunker import chunk_text
from .config import get_settings
from .db import cursor
from .parsers import ParseError, extract_text
from .schemas import Id

_log = logging.getLogger(__name__)

# Celery("이름", broker=...) 는 <연결하지 않는다>. 메시지를 실제로 보낼 때 연결한다.
# 그래서 Redis 가 꺼져 있어도 이 줄은 성공하고, main.py 가 이 모듈을 import 해도 안전하다.
celery_app = Celery("alldap", broker=get_settings().broker_url)
celery_app.conf.update(
    # 메시지를 JSON 으로만 주고받는다. pickle 은 메시지를 열면 임의 코드가 실행될 수 있다.
    task_serializer="json",
    accept_content=["json"],
    # 결과 저장소(result backend)를 두지 않는다. 결과는 documents.status 가 이미 말한다.
    task_ignore_result=True,
    # 🔴 끈다. 처리 함수가 아직 두 번 돌면 안전하지 않다(청크 중복, LLM 이중 과금).
    #    다음 조각에서 청크 중복을 재현한 뒤 켠다(스펙 2-3, 8절).
    task_acks_late=False,
    # delay() 가 Redis 연결에 실패하면 <스스로 재시도하지 않고> 바로 예외를 낸다.
    # 재시도하는 동안 업로드 요청이 매달린다. 실제 소요 시간은 Task 7 에서 잰다.
    task_publish_retry=False,
    broker_connection_timeout=2.0,
    # 워커 기동 시 Redis 가 아직 안 떴으면 기다린다(Celery 6 에서 기본값이 바뀐다는 경고를 끈다).
    broker_connection_retry_on_startup=True,
)


@worker_init.connect
def _check_upload_dir(**_: object) -> None:
    """워커가 뜰 때 업로드 폴더를 확인한다. 못 쓰면 기동을 막는다(스펙 5-4).

    @worker_init.connect 는 "워커가 초기화될 때 이 함수를 불러 달라" 는 등록이다(시그널).
    **_ 는 Celery 가 넘기는 키워드 인자를 전부 받아 버린다는 뜻이다. 여기서는 쓰지 않는다.
    """
    storage.ensure_upload_dir()


def _fail(doc_id: Id, reason: str) -> None:
    with cursor(commit=True) as cur:
        cur.execute(
            "UPDATE documents SET status='failed', error_message=%s WHERE id=%s",
            (reason, doc_id),
        )


def _claim(doc_id: Id, bot_id: Id) -> str | None:
    """상태 가드. pending 인 문서만 processing 으로 바꾸고 파일명을 돌려준다. 아니면 None.

    🔴 한 SQL 문장이어야 한다(스펙 4-2). SELECT 로 상태를 읽고 if 로 판단하면, 두 워커가
       같은 문서를 동시에 읽고 둘 다 "pending 이네" 하고 통과한다. UPDATE ... WHERE 는
       DB 가 행을 잠그고 판단하므로 둘 중 하나만 1행을 바꾼다.
    🔴 bot_id 도 조건에 넣는다. 메시지의 두 값이 같은 문서를 가리킬 때만 처리한다.

    None 이 되는 경우: 이미 처리됨(ready/failed/processing), 워커가 꺼내기 전에 삭제됨.
    ⚠️ 다음 조각(acks_late)에서 이 가드를 다시 설계해야 한다. 워커가 죽어 processing 에
       남은 문서의 재배달이 여기서 막힌다(스펙 7절 2번).
    """
    with cursor(commit=True) as cur:
        cur.execute(
            """UPDATE documents SET status='processing'
               WHERE id=%s AND bot_id=%s AND status='pending'
               RETURNING filename""",
            (doc_id, bot_id),
        )
        row = cur.fetchone()
    return row[0] if row else None


def _run_pipeline(doc_id: Id, bot_id: Id, filename: str, data: bytes) -> str:
    """파싱 → 청킹 → 임베딩 → 저장. 옛 main._process_document 본문 그대로다(스펙 4-2 의 4번)."""
    s = get_settings()
    try:
        try:
            _, text = extract_text(filename, data)
        except ParseError as e:
            _fail(doc_id, str(e))
            return "failed"

        chunks = chunk_text(
            text,
            size=s.chunk_size,
            overlap=s.chunk_overlap,
            split_headings=s.chunk_split_headings,
        )
        if not chunks:
            _fail(doc_id, "문서에서 유효한 내용을 찾지 못했습니다.")
            return "failed"

        vectors = retriever.embed([c.content for c in chunks])

        with cursor(commit=True) as cur:
            cur.executemany(
                """INSERT INTO chunks (document_id, bot_id, chunk_index, content, embedding, meta)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                [
                    (doc_id, bot_id, c.index, c.content, v, json.dumps(c.meta))
                    for c, v in zip(chunks, vectors)
                ],
            )
            cur.execute(
                """UPDATE documents
                   SET status='ready', char_count=%s, chunk_count=%s, error_message=NULL
                   WHERE id=%s""",
                (len(text), len(chunks), doc_id),
            )
        return "ready"
    except Exception as e:  # noqa: BLE001 - 어떤 실패든 상태로 남겨야 한다
        _fail(doc_id, f"처리 중 오류가 발생했습니다: {type(e).__name__}")
        return "failed"


# name= 을 못박는다. 안 적으면 "app.worker.process_document" 처럼 모듈 경로가 이름이 되어,
# 파일을 옮기는 순간 Redis 에 쌓여 있던 메시지를 워커가 못 알아본다.
@celery_app.task(name="documents.process")
def process_document(doc_id: Id, bot_id: Id) -> str:
    """메시지 하나 = 문서 하나. 인자는 번호 둘뿐이다(claim check, 스펙 2절).

    원본은 처리 뒤에도 지우지 않는다(스펙 2-3). 문서 삭제 API 만 지운다.
    """
    filename = _claim(doc_id, bot_id)
    if filename is None:
        _log.info("건너뜀: pending 이 아니거나 없는 문서 doc_id=%s bot_id=%s", doc_id, bot_id)
        return "skipped"

    try:
        data = storage.read(bot_id, doc_id)
    except FileNotFoundError:
        _fail(doc_id, "원본 파일을 찾지 못했습니다. 다시 올려주세요.")
        return "failed"

    return _run_pipeline(doc_id, bot_id, filename, data)
