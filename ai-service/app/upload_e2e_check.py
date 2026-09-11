"""업로드 파이프라인 종단 점검 - PDF·DOCX·HWPX 를 <status=ready 까지> 태운다.

실행 (둘 중 하나):
    # ① 인프로세스: 서버를 띄우지 않고 ASGI 앱을 직접 태운다. DB·Cloudflare 는 진짜다.
    cd ai-service && .venv/bin/python -m app.upload_e2e_check

    # ② 진짜 HTTP: uvicorn 을 띄워두고 밖에서 두드린다. 폴링도 실제로 돈다.
    cd ai-service && .venv/bin/uvicorn app.main:app --port 8001   # 다른 터미널
    cd ai-service && .venv/bin/python -m app.upload_e2e_check --base-url http://localhost:8001

🔴 이 파일이 생긴 이유 - "파서가 된다" 와 "업로드가 된다" 는 다른 사실이다
────────────────────────────────────────────────────────────────────
`app/parsers_check.py` 는 파일 → 텍스트만 본다. 그 뒤의 청킹·임베딩·상태 전이는
한 줄도 안 지난다. 그런데 PDF·DOCX 로 <업로드부터 ready 까지> 돌린 기록이
이 저장소에 없었다. W1 종단 실측은 전부 텍스트 코퍼스 기준이었다.

간접 증거는 있었다(`docs/decisions.md` 2026-08-05 의 "실제 PDF 51쌍 0 오탐" -
쌍이 생기려면 그 PDF 의 청크와 임베딩이 DB 에 있었어야 한다). 하지만
**"거기까지는 돌았을 것" 은 추론이고 `ready` 전이를 본 것과 다르다.** DOCX 는 그 추론조차 없었다.

이 점검이 닫는 축 / 안 닫는 축
────────────────────────────────────────────────────────────────────
  ✅ 업로드 파이프라인 종단 (업로드 → 파싱 → 청킹 → 임베딩 → ready)
  ❌ 대용량 문서                 fixture 는 수 KB 다. pymupdf OOM 구간에 못 간다.

🔴 Spring 을 거치는 경로는 <여기서 돌지 않는다> - 손으로 한 번 돌렸다
────────────────────────────────────────────────────────────────────
이 파일은 Python `/internal` 직행이다. Spring 을 거치는 것은 다른 사실이라
(HTTP/2 multipart 사고가 정확히 그 경계에서 났다) 2026-09-11 에 curl 로 따로 돌렸다:
가입 → 봇 생성 → 세 파일 업로드 → `pending` → `processing` → `ready` 까지 봤고
camelCase 변환(`fileType` · `charCount` · `chunkCount`)과 한글 파일명도 그대로였다.

자동화하지 않은 이유는 <봇 주인> 이다. Spring 은 `findOwnedBot(userId, botId)` 로
조회하는데 시드 데모 봇은 `user_id IS NULL` 이라 누구의 것도 아니다(404). 태우려면
이 스크립트가 계정을 만들고 봇을 만들어야 하는데, `users`·`bots` 쓰기는 Spring 소유라
(AGENTS.md 테이블 소유권) Python 점검이 할 일이 아니다.
→ Spring 쪽 회귀는 `api/` 통합 테스트가 맡는 것이 맞다. 그 경로를 다시 재려면
   `docs/` 의 절차대로 손으로 돌릴 것.

🔴 왜 인프로세스(①)를 기본으로 두는가
────────────────────────────────────────────────────────────────────
②가 더 강한 증거다. 그래서 지울 수 없게 옵션으로 남겼다. 그런데 ②만 두면
"서버가 안 떠 있어서 안 돌렸다" 가 일상이 되고, 안 도는 점검은 없는 것과 같다
(오픈 리다이렉트 때 겪었다 - 검사를 안 짠 것이 아니라 짜둔 검사가 아무 데서도 안 돌았다).
①도 진짜 ASGI 스택·진짜 DB·진짜 Cloudflare 를 지난다. 가짜인 것은 소켓 하나뿐이다.

⚠️ 어느 쪽이든 <진짜 Cloudflare 임베딩>을 부른다. fixture 3개 = 청크 10개 남짓이라
   비용은 평가 1회(804 뉴런)의 1%도 안 되지만, 한도가 소진된 상태면 여기서 멈춘다.

⚠️ 봇은 시드 데모 봇(pk_local_dev)을 빌려 쓰고 <끝나면 지운다>. `bots` 쓰기는
   Spring 소유라(AGENTS.md 테이블 소유권) 봇을 새로 만들지 않는다.
   시작할 때도 같은 이름의 잔재를 먼저 지운다 - 중간에 죽어도 다음 실행이 깨끗하다.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from uuid import UUID

import httpx

from .config import get_settings
from .db import cursor

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from testdata.make_fixtures import FIXTURES, NAMES  # noqa: E402

# V1__init.sql 의 시드 봇. 주인이 없는 공개 데모 봇이라 사람의 데이터가 아니다.
SEED_BOT = UUID("00000000-0000-0000-0000-000000000001")

MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "hwpx": "application/hwp+zip",
}

READY_TIMEOUT_S = 120.0
POLL_INTERVAL_S = 1.0


def _client(base_url: str | None) -> httpx.Client:
    if base_url:
        return httpx.Client(base_url=base_url, timeout=60.0)
    # TestClient 는 앱을 그대로 호출한다(httpx.Client 를 상속하므로 아래 코드가 같다).
    # Starlette 가 응답을 낸 뒤 BackgroundTasks 를 같은 호출 안에서 끝내므로,
    # 인프로세스에서는 첫 폴링에 이미 ready 다.
    #
    # ⚠️ httpx.ASGITransport 를 쓰려다 접었다. 그쪽은 async 전용이라
    #    동기 Client 에 못 물린다(`__enter__` 가 없다). TestClient 가 그 포털을 대신 판다.
    from fastapi.testclient import TestClient

    from .main import app

    return TestClient(app)


def _purge(bot_id: UUID, names: list[str]) -> int:
    """같은 이름의 잔재를 지운다(중간에 죽은 앞 실행 대비).

    chunks 는 documents 에 ON DELETE CASCADE 로 딸려 있다(V1__init.sql).
    """
    with cursor(commit=True) as cur:
        cur.execute(
            "DELETE FROM documents WHERE bot_id = %s AND filename = ANY(%s) RETURNING id",
            (bot_id, names),
        )
        return len(cur.fetchall())


def _chunk_stats(doc_id: UUID) -> tuple[int, int, int]:
    """(청크 수, 임베딩이 있는 청크 수, 벡터 차원).

    🔴 chunk_count 컬럼만 보면 안 된다. 그 값은 <INSERT 하려던 개수>고,
       임베딩이 실제로 들어갔는지는 다른 사실이다. 여기서 직접 센다.
    """
    with cursor() as cur:
        cur.execute(
            """SELECT count(*),
                      count(embedding),
                      coalesce(max(vector_dims(embedding)), 0)
               FROM chunks WHERE document_id = %s""",
            (doc_id,),
        )
        return cur.fetchone()


def run_one(client: httpx.Client, bot_id: UUID, name: str, verbose: bool) -> None:
    path = FIXTURES / name
    ftype = path.suffix.lstrip(".")
    data = path.read_bytes()

    # ── 업로드: 202 + pending ───────────────────────────────────────
    r = client.post(
        f"/internal/bots/{bot_id}/documents",
        files={"file": (name, data, MIME[ftype])},
    )
    assert r.status_code == 202, (r.status_code, r.text)
    doc = r.json()
    assert doc["status"] == "pending", doc
    assert doc["file_type"] == ftype, doc
    # 한글 파일명이 multipart 를 건너 그대로 살아 있어야 한다.
    # 깨지면 목록 화면에서 사용자가 자기 파일을 못 알아본다.
    assert doc["filename"] == name, doc
    doc_id = UUID(doc["id"])

    # ── 폴링: ready 로 <전이하는 것>을 본다 ─────────────────────────
    deadline = time.monotonic() + READY_TIMEOUT_S
    status, row = None, None
    while time.monotonic() < deadline:
        lr = client.get(f"/internal/bots/{bot_id}/documents")
        assert lr.status_code == 200, (lr.status_code, lr.text)
        row = next((d for d in lr.json() if d["id"] == str(doc_id)), None)
        assert row is not None, f"{name}: 업로드한 문서가 목록에 없다"
        status = row["status"]
        if status in ("ready", "failed"):
            break
        time.sleep(POLL_INTERVAL_S)

    assert status == "ready", f"{name}: status={status} error={row and row.get('error_message')}"

    # ── ready 가 <무엇을 뜻하는지>까지 확인한다 ─────────────────────
    # "상태가 ready 다" 와 "검색 가능한 청크가 생겼다" 는 다른 사실이다.
    assert row["char_count"] and row["char_count"] > 0, row
    assert row["chunk_count"] and row["chunk_count"] > 0, row

    # 🔴 청킹이 <돌았는가> 와 <청크가 1개 나왔는가> 는 다른 사실이다.
    #    fixture 셋은 전부 chunk_size 보다 길게 써뒀다(testdata/make_fixtures.py 참고).
    #    그런데도 1개면 청킹 단계가 통째로 건너뛰어진 것이다.
    #    설정을 바꿔 chunk_size 가 문서보다 커지면 이 단언은 스스로 비켜난다.
    settings = get_settings()
    if row["char_count"] > settings.chunk_size:
        assert row["chunk_count"] > 1, (
            f"{name}: {row['char_count']}자인데 청크가 1개다 "
            f"(chunk_size={settings.chunk_size})"
        )

    total, embedded, dims = _chunk_stats(doc_id)
    assert total == row["chunk_count"], (total, row["chunk_count"])
    assert embedded == total, f"{name}: 임베딩이 빈 청크가 {total - embedded}개"
    assert dims == settings.embedding_dim, (dims, settings.embedding_dim)

    if verbose:
        print(
            f"  ok  {name}: {row['char_count']}자 → {total}청크 "
            f"(임베딩 {embedded}/{total}, {dims}차원)"
        )

    # ── 삭제까지 태운다(정리이자 점검이다) ──────────────────────────
    dr = client.delete(f"/internal/bots/{bot_id}/documents/{doc_id}")
    assert dr.status_code == 204, (dr.status_code, dr.text)
    left, _, _ = _chunk_stats(doc_id)
    assert left == 0, f"{name}: 문서를 지웠는데 청크가 {left}개 남았다"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--base-url",
        default=None,
        help="비우면 인프로세스 ASGI. 예: http://localhost:8001 (진짜 HTTP)",
    )
    ap.add_argument("--bot-id", default=str(SEED_BOT))
    ap.add_argument("--only", default=None, help="pdf | docx | hwpx")
    args = ap.parse_args()

    bot_id = UUID(args.bot_id)
    names = [n for n in NAMES if args.only is None or n.endswith(f".{args.only}")]
    assert names, f"--only {args.only} 에 해당하는 fixture 가 없다"

    purged = _purge(bot_id, list(NAMES))
    if purged:
        print(f"앞 실행의 잔재 {purged}건을 지웠다")

    mode = args.base_url or "인프로세스 ASGI"
    print(f"대상 봇: {bot_id}  경로: {mode}\n")

    with _client(args.base_url) as client:
        try:
            for name in names:
                run_one(client, bot_id, name, verbose=True)
        finally:
            _purge(bot_id, list(NAMES))

    print(f"\nupload_e2e_check: {len(names)}개 형식이 ready 까지 통과")


if __name__ == "__main__":
    main()
