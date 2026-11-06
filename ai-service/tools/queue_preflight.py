"""종단 점검 전에 Redis 와 워커가 떠 있는지 확인한다.

왜 따로 있나: 워커가 없으면 업로드는 202 를 받고 pending 에 머문다. 점검은 그걸
120초 기다린 뒤에야 "ready 가 아니다" 로 실패하고, 원인(워커를 안 띄움)은 안 적힌다.
여기서 미리 묻고 바로 안내한다.
"""
from __future__ import annotations

import sys

from kombu.exceptions import OperationalError

from app.worker import celery_app


def require_worker() -> None:
    try:
        # control.ping: 브로커를 거쳐 떠 있는 워커들에게 "살아 있나" 를 묻는다. 답한 워커 목록이 온다.
        replies = celery_app.control.ping(timeout=2.0)
    except OperationalError:
        sys.exit("Redis 에 연결하지 못했습니다. 저장소 루트에서 `docker compose up -d` 를 먼저 실행하세요.")
    if not replies:
        sys.exit(
            "Celery 워커가 떠 있지 않습니다. 다른 터미널에서 먼저 띄우세요:\n"
            "  cd ai-service && .venv/bin/celery -A app.worker worker --pool=solo --loglevel=info"
        )
