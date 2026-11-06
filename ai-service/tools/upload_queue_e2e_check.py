"""문서 처리 큐 종단 점검 (스펙 6-2). 손으로 돌린다 - CI 에서는 못 돈다.

실행 (Redis 와 워커가 떠 있어야 한다. 없으면 바로 안내하고 끝난다):
    docker compose up -d                                                   # 저장소 루트
    cd ai-service && .venv/bin/celery -A app.worker worker --pool=solo     # 다른 터미널
    cd ai-service && .venv/bin/python -m tools.upload_queue_e2e_check

API 는 인프로세스(TestClient)로 부르고, 처리는 <진짜 워커>가 Redis 를 거쳐 한다.
DB·Redis·워커·Cloudflare 임베딩이 전부 진짜다.

이 점검이 보는 것
  ① 업로드 → 큐 → 워커 → ready, 처리 뒤에도 원본이 남는다(보존)
  ② 이미 ready 인 문서를 다시 처리하라고 해도 건너뛴다(상태 가드)
  ③ 없는 문서(워커가 꺼내기 전에 삭제된 문서)의 작업은 건너뛴다
     (가드의 bot_id 조건만 따로 재는 시나리오는 없다. pending 인 남의 문서를 만들어야 해서다)
  ④ 남의 bot_id 로 지우면 원본이 남고, 제 bot_id 로 지우면 행·청크·원본이 다 사라진다

②③ 은 작업 함수를 <이 프로세스에서 직접> 부른다(`process_document(...)`, .delay 가 아니다).
가드는 SQL 한 문장이라 어느 프로세스에서 부르든 같고, 직접 부르면 반환값("skipped")을
기다림 없이 확인할 수 있다. 큐를 지나는 경로는 ① 이 본다.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app import storage
from app.db import cursor
from app.main import app
from app.schemas import Id
from app.worker import process_document
from tools.queue_preflight import require_worker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from testdata.make_fixtures import FIXTURES, NAMES  # noqa: E402

SEED_BOT: Id = 1
OTHER_BOT: Id = 999_999  # 없는 봇. 격리 확인용이라 존재할 필요가 없다.
NAME = next(n for n in NAMES if n.endswith(".docx"))
READY_TIMEOUT_S = 120.0


def _purge() -> None:
    with cursor(commit=True) as cur:
        cur.execute(
            "DELETE FROM documents WHERE bot_id=%s AND filename=%s RETURNING id",
            (SEED_BOT, NAME),
        )
        ids = [r[0] for r in cur.fetchall()]
    for doc_id in ids:
        storage.delete(SEED_BOT, doc_id)


def _row(doc_id: Id) -> tuple[str, int | None] | None:
    with cursor() as cur:
        cur.execute("SELECT status, chunk_count FROM documents WHERE id=%s", (doc_id,))
        return cur.fetchone()


def _chunks(doc_id: Id) -> int:
    with cursor() as cur:
        cur.execute("SELECT count(*) FROM chunks WHERE document_id=%s", (doc_id,))
        return cur.fetchone()[0]


def main() -> None:
    require_worker()
    _purge()

    with TestClient(app) as client:
        try:
            # ① 업로드 → ready, 원본 보존
            r = client.post(
                f"/internal/bots/{SEED_BOT}/documents",
                files={"file": (NAME, (FIXTURES / NAME).read_bytes(), "application/octet-stream")},
            )
            assert r.status_code == 202, (r.status_code, r.text)
            doc_id = r.json()["id"]
            deadline = time.monotonic() + READY_TIMEOUT_S
            # `:=` (바다코끼리 연산자): 값을 변수에 넣으면서 그 값을 바로 조건에 쓴다.
            # row = _row(doc_id) 를 루프 위·안에 두 번 적지 않으려고 쓴다.
            while (row := _row(doc_id)) and row[0] in ("pending", "processing"):
                assert time.monotonic() < deadline, f"{READY_TIMEOUT_S}초 안에 끝나지 않았다: {row}"
                time.sleep(1.0)
            assert row and row[0] == "ready", row
            before = _chunks(doc_id)
            assert before > 0 and before == row[1], (before, row)
            assert storage.read(SEED_BOT, doc_id) == (FIXTURES / NAME).read_bytes()
            print(f"✅ ① 업로드 → 큐 → ready ({before}청크), 원본 보존")

            # ② 다시 처리하라고 해도 건너뛴다
            assert process_document(doc_id, SEED_BOT) == "skipped"
            assert _chunks(doc_id) == before, "가드를 지나 청크가 늘었다"
            print("✅ ② 이미 ready 인 문서는 건너뛴다 (청크 수 그대로)")

            # ③ 없는 문서
            # ⚠️ "다른 bot_id 면 건너뛴다" 는 여기서 재지 않는다. 이 문서는 이미 ready 라
            #    bot_id 가 맞아도 건너뛴다 - 통과해도 bot_id 조건 덕인지 증명하지 못한다.
            assert process_document(doc_id + 10_000_000, SEED_BOT) == "skipped"
            print("✅ ③ 없는 문서의 작업은 건너뛴다")

            # ④ 삭제
            assert client.delete(f"/internal/bots/{OTHER_BOT}/documents/{doc_id}").status_code == 204
            assert storage.read(SEED_BOT, doc_id), "남의 bot_id 로 원본이 지워졌다"
            assert client.delete(f"/internal/bots/{SEED_BOT}/documents/{doc_id}").status_code == 204
            assert _row(doc_id) is None and _chunks(doc_id) == 0
            try:
                storage.read(SEED_BOT, doc_id)
                raise AssertionError("문서를 지웠는데 원본이 남았다")
            except FileNotFoundError:
                pass
            print("✅ ④ 남의 봇으로는 안 지워지고, 제 봇으로 지우면 행·청크·원본이 사라진다")
        finally:
            _purge()

    print("\nupload_queue_e2e_check: 4가지 전부 통과.")


if __name__ == "__main__":
    main()
