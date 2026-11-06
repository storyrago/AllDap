# 문서 처리 Celery 워커 분리 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ai-service 의 문서 처리를 FastAPI `BackgroundTasks` 에서 Celery 워커 + Redis 브로커로 옮긴다. 원본은 로컬 디스크에 두고 메시지에는 `doc_id`·`bot_id` 만 싣는다.

**Architecture:** 업로드 API 는 `documents` 행 INSERT 와 원본 저장을 한 트랜잭션에 묶고, 커밋 뒤에 `process_document.delay(doc_id, bot_id)` 로 Redis 에 메시지를 넣는다. 별도 프로세스인 Celery 워커가 메시지를 꺼내 상태 가드(`pending → processing`, 한 SQL 문장)를 통과한 경우에만 지금과 같은 파싱 → 청킹 → 임베딩을 돌린다. 저장은 `app/storage.py` 의 함수 셋 뒤에 숨긴다.

**Tech Stack:** Python 3.13(로컬) / 3.11(CI), FastAPI, Celery 5.7(Redis 브로커), Redis 7.4(docker), psycopg 3, PostgreSQL 16.

**설계 문서:** [`docs/superpowers/specs/2026-11-06-celery-document-worker-design.md`](../specs/2026-11-06-celery-document-worker-design.md) (이하 "스펙")

## Global Constraints

- 브랜치는 `feat/celery-document-worker`. 커밋 메시지는 `<타입>: <한국어 요약>` 이고 끝에 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` 를 붙인다.
- 로컬 전용이다. 운영(EC2)은 고려하지 않는다(사용자 결정). 다만 `deploy.yml` 이 남아 있으므로 머지 시 배포가 시도될 수 있다는 사실은 PR 본문에 한 줄 적는다.
- 메시지에는 `doc_id`, `bot_id` 만. 경로·파일명·바이트를 싣지 않는다.
- 경로 규칙은 `{upload_dir}/{bot_id}/{doc_id}`. 원본 파일명을 경로에 쓰지 않는다.
- `task_acks_late=False`, 자동 재시도 없음. `DELETE FROM chunks` 는 이번에 넣지 않는다.
- 처리 성공 후 원본을 지우지 않는다. 문서 삭제 때만 지운다.
- `/internal/*` 오류 본문은 FastAPI 기본값 `detail`. 사용자에게 보이는 문구는 한국어로 "무엇을 하면 되는지"까지 쓴다.
- Spring(`api/`) 코드는 바꾸지 않는다. 마이그레이션은 없다.
- 코드 주석은 한국어. Python 문법·관용구가 처음 나오는 곳에는 왜 그렇게 쓰는지 짧게 설명한다(AGENTS.md).
- 이 저장소는 pytest 가 아니라 `python -m tools.<이름>_check` 점검 스크립트를 쓴다. 실패하면 `assert` 로 비정상 종료한다.
- 명령은 별도 표시가 없으면 `ai-service/` 에서 실행한다. 파이썬은 `.venv/bin/python`.

## 파일 구조

| 파일 | 책임 | 새로/수정 |
|---|---|---|
| `docker-compose.yml` | `redis` 서비스 | 수정 |
| `ai-service/requirements.txt` | `celery[redis]` 고정 | 수정 |
| `ai-service/app/config.py` | `upload_dir`, `broker_url` | 수정 |
| `ai-service/app/storage.py` | 원본 저장·읽기·삭제와 경로 규칙, 기동 시 폴더 검사 | 새로 |
| `ai-service/tools/storage_check.py` | storage 의 순수 점검 (CI) | 새로 |
| `ai-service/app/worker.py` | Celery 앱, `process_document` 작업, 처리 본문 | 새로 |
| `ai-service/app/main.py` | 업로드·삭제 경로, lifespan, `_process_document` 제거 | 수정 |
| `ai-service/tools/queue_preflight.py` | "Redis·워커가 떠 있는가" 사전 확인 (e2e 점검 공용) | 새로 |
| `ai-service/tools/upload_queue_e2e_check.py` | 큐 경로 종단 점검 (손으로) | 새로 |
| `ai-service/tools/upload_e2e_check.py` | 워커 전제로 수정, 잔재 정리 시 원본도 삭제 | 수정 |
| `.github/workflows/ci.yml` | storage_check 추가, 못 태우는 점검 목록 갱신 | 수정 |
| `AGENTS.md`, `docs/BACKLOG.md`, `docs/decisions.md`, `docs/실측-기록.md`, `tools/eval_set_check.py`·`tools/parsers_check.py` docstring | 문서 | 수정 |

---

### Task 1: Redis·Celery 의존성과 설정

**Files:**
- Modify: `docker-compose.yml` (db 서비스 다음, `prometheus` 앞)
- Modify: `ai-service/requirements.txt`
- Modify: `ai-service/app/config.py:371` 부근 (`upload_max_bytes` 아래)

**Interfaces:**
- Produces: `Settings.upload_dir: str`, `Settings.broker_url: str`. Redis 가 `127.0.0.1:6380` 에서 뜬다(호스트 6379 는 다른 Redis 가 쓰고 있어 피했다).

- [ ] **Step 1: compose 에 redis 추가**

`docker-compose.yml` 의 `db:` 서비스 블록이 끝나는 곳(`retries: 10` 다음 빈 줄)과 `# ── 로컬 관측 스택` 주석 사이에 넣는다.

```yaml
  # ── Celery 브로커 (2026-11-06, 문서 처리 워커 분리) ───────────────────
  # 문서 처리 작업 메시지를 보관한다. 메시지에는 doc_id·bot_id 만 들어간다(원본은 디스크).
  # profiles 없이 둔다: 이제 업로드가 이것 없이는 503 이 된다. db 와 같이 늘 떠 있어야 한다.
  redis:
    image: redis:7.4-alpine
    container_name: alldap-redis
    # appendonly: 메시지를 디스크에도 적는다. 끄면 Redis 를 재시작할 때 대기 중인 메시지가 사라진다.
    #   "브로커가 작업을 잃지 않는다" 를 이 조각에서 직접 확인하려고 켠다.
    command: ["redis-server", "--appendonly", "yes"]
    ports:
      # db 와 같은 이유로 127.0.0.1 에만 연다. 인증이 없는 Redis 를 사내망에 열면 누구나 작업을 넣는다.
      - "127.0.0.1:6380:6379"
    volumes:
      - alldap-redis:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10
```

맨 아래 `volumes:` 에 한 줄 추가:

```yaml
  # Redis 의 appendonly 파일. 지우면 대기 중이던 작업 메시지가 사라진다.
  alldap-redis:
```

- [ ] **Step 2: Redis 기동 확인**

Run (저장소 루트): `docker compose up -d redis && docker exec alldap-redis redis-cli ping`
Expected: `PONG`

- [ ] **Step 3: celery 설치와 버전 고정**

Run: `.venv/bin/pip install "celery[redis]==5.7.0" && .venv/bin/pip show celery redis kombu | grep -E "^(Name|Version)"`
Expected: celery 5.7.0, 그리고 실제로 깔린 redis·kombu 버전이 출력된다.

`requirements.txt` 맨 아래에 추가한다. `<redis 버전>` 자리는 **Step 3 출력의 실제 값**으로 적는다(이 저장소는 파일에 적힌 버전과 실제 버전이 어긋나 깨끗한 환경에서 resolve 가 안 된 적이 있다. pydantic 주석 참고).

```text
# 문서 처리 워커 (2026-11-06). Redis 를 브로커로 쓴다.
# 🔴 RQ 가 아니라 Celery 인 이유는 docs/decisions.md 2026-11-06 항목.
celery[redis]==5.7.0
# celery[redis] 가 끌어오지만 버전을 못박는다(실제 설치된 값).
redis==<redis 버전>
```

- [ ] **Step 4: 설정 두 개 추가**

`app/config.py` 맨 위 import 에 `from pathlib import Path` 를 추가하고, `upload_max_bytes` 줄 바로 아래에 넣는다.

```python
    # ── 문서 처리 워커 (2026-11-06) ─────────────────────────────────────
    # 업로드 원본을 두는 폴더. 경로 규칙은 app/storage.py 만 안다.
    # 기본값을 <ai-service/uploads> 로 고정한다. 상대경로("uploads")로 두면 uvicorn 과 워커를
    # 서로 다른 폴더에서 띄웠을 때 둘이 <다른 폴더를 보고> 워커가 파일을 못 찾는다.
    # 🔴 루트 .gitignore 의 `uploads/` 가 이 폴더를 막는다. 이름을 바꾸면 고객 문서가 커밋될 수 있다.
    #
    # Path(__file__) 는 "이 파일(config.py)의 경로" 다. .resolve() 로 절대경로로 바꾸고
    # .parent 를 두 번 올라가면 app/ → ai-service/ 다.
    upload_dir: str = str(Path(__file__).resolve().parent.parent / "uploads")

    # Celery 브로커. 끝의 /0 은 Redis 의 0번 DB 라는 뜻이다.
    broker_url: str = "redis://localhost:6380/0"
```

- [ ] **Step 5: 설정이 읽히는지 확인**

Run: `.venv/bin/python -c "from app.config import get_settings as g; s=g(); print(s.upload_dir, s.broker_url)"`
Expected: `/Users/.../AllDap/ai-service/uploads redis://localhost:6380/0`

- [ ] **Step 6: Commit**

```bash
cd /Users/cheonjamin/projects/AllDap
git add docker-compose.yml ai-service/requirements.txt ai-service/app/config.py
git commit -m "chore: Celery 브로커로 쓸 Redis 와 업로드 폴더 설정을 더한다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: 원본 저장소 `storage.py` 와 CI 점검

**Files:**
- Create: `ai-service/app/storage.py`
- Create: `ai-service/tools/storage_check.py`
- Modify: `.github/workflows/ci.yml` (자체 점검 `run:` 목록)

**Interfaces:**
- Consumes: `Settings.upload_dir` (Task 1)
- Produces:
  - `storage.save(bot_id: int, doc_id: int, data: bytes, *, root: Path | None = None) -> None`
  - `storage.read(bot_id: int, doc_id: int, *, root: Path | None = None) -> bytes` (없으면 `FileNotFoundError`)
  - `storage.delete(bot_id: int, doc_id: int, *, root: Path | None = None) -> None` (없어도 예외 없음)
  - `storage.ensure_upload_dir(*, root: Path | None = None) -> Path` (만들 수 없거나 쓸 수 없으면 `RuntimeError`, 한국어)

- [ ] **Step 1: 실패하는 점검을 먼저 쓴다**

`ai-service/tools/storage_check.py`:

```python
"""원본 저장소(app/storage.py) 자체 점검. DB·Redis·외부 API 를 쓰지 않는다.

왜 이 검사가 있나
─────────────────────────────────────────────────────────────────────────────
워커는 메시지의 doc_id·bot_id 만으로 원본을 찾는다(claim check, 스펙 2절).
그래서 <경로 규칙>이 곧 계약이다. 규칙이 흔들리면 업로드는 성공하는데
워커가 "원본 파일을 찾지 못했습니다" 로 떨어진다.

🔴 특히 둘을 본다.
   ① 경로에 사용자가 보낸 값(파일명)이 들어가지 않는다 - `../` 로 폴더 밖에 쓰는 것을 막는다.
   ② 다른 bot_id 로는 읽지 못한다 - /internal/* 에는 인증이 없어 경로가 마지막 격리선이다.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from app import storage


def check_path_is_bot_then_doc(root: Path) -> None:
    """경로는 {root}/{bot_id}/{doc_id} 이고 그 밖의 것은 들어가지 않는다."""
    storage.save(7, 42, b"x", root=root)
    assert (root / "7" / "42").read_bytes() == b"x"
    assert sorted(p.relative_to(root).as_posix() for p in root.rglob("*")) == ["7", "7/42"]


def check_rejects_non_int_ids(root: Path) -> None:
    """id 자리에 문자열이 오면 거절한다. "../x" 가 경로가 되는 길을 막는다.

    bool 도 거절한다: 파이썬에서 True 는 int 의 하위 타입이라 isinstance 로는 통과한다.
    """
    for bad in ("../etc", "1", 1.0, True, None):
        try:
            storage.save(bad, 1, b"x", root=root)  # type: ignore[arg-type]
        except TypeError:
            continue
        raise AssertionError(f"bot_id={bad!r} 를 받아들였다")
    for bad in ("../etc", True):
        try:
            storage.read(1, bad, root=root)  # type: ignore[arg-type]
        except TypeError:
            continue
        raise AssertionError(f"doc_id={bad!r} 를 받아들였다")


def check_roundtrip(root: Path) -> None:
    """저장한 바이트가 그대로 돌아온다. 0바이트가 아닌 바이너리로 본다."""
    data = bytes(range(256)) * 10
    storage.save(1, 1, data, root=root)
    assert storage.read(1, 1, root=root) == data


def check_read_missing_raises(root: Path) -> None:
    """없는 원본은 FileNotFoundError. 워커가 이 예외로 "원본 없음" 을 판정한다."""
    try:
        storage.read(1, 999, root=root)
    except FileNotFoundError:
        return
    raise AssertionError("없는 원본을 읽었는데 예외가 나지 않았다")


def check_delete_is_idempotent(root: Path) -> None:
    """두 번 지워도 예외가 없다. 삭제 API 가 두 번 불려도 204 여야 한다."""
    storage.save(1, 2, b"x", root=root)
    storage.delete(1, 2, root=root)
    storage.delete(1, 2, root=root)
    assert not (root / "1" / "2").exists()


def check_other_bot_cannot_read(root: Path) -> None:
    """같은 doc_id 라도 bot_id 가 다르면 못 읽는다."""
    storage.save(1, 3, b"secret", root=root)
    try:
        storage.read(2, 3, root=root)
    except FileNotFoundError:
        return
    raise AssertionError("다른 봇의 원본을 읽었다")


def check_ensure_upload_dir_creates(root: Path) -> None:
    """폴더가 없으면 만든다."""
    target = root / "new" / "uploads"
    assert storage.ensure_upload_dir(root=target) == target
    assert target.is_dir()


def check_ensure_upload_dir_rejects_file(root: Path) -> None:
    """같은 이름의 <파일>이 있으면 폴더를 만들 수 없다. 한국어 RuntimeError 로 기동을 막는다."""
    target = root / "occupied"
    target.write_bytes(b"")
    try:
        storage.ensure_upload_dir(root=target)
    except RuntimeError as e:
        assert "UPLOAD_DIR" in str(e), e
        return
    raise AssertionError("폴더를 만들 수 없는데 통과했다")


def main() -> None:
    checks = [
        check_path_is_bot_then_doc,
        check_rejects_non_int_ids,
        check_roundtrip,
        check_read_missing_raises,
        check_delete_is_idempotent,
        check_other_bot_cannot_read,
        check_ensure_upload_dir_creates,
        check_ensure_upload_dir_rejects_file,
    ]
    for fn in checks:
        # 점검마다 빈 임시 폴더를 준다. 앞 점검이 남긴 파일이 뒤 점검을 통과시키지 않게.
        # `with ... as d:` 블록을 벗어나면 폴더가 통째로 지워진다(try/finally 를 대신 써 주는 문법).
        with tempfile.TemporaryDirectory() as d:
            fn(Path(d))
        print(f"✅ {fn.__name__}")
    print(f"\n{len(checks)}가지 전부 통과.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 실패를 확인한다**

Run: `.venv/bin/python -m tools.storage_check`
Expected: `ImportError: cannot import name 'storage' from 'app'`

- [ ] **Step 3: `storage.py` 를 쓴다**

`ai-service/app/storage.py`:

```python
"""업로드 원본 저장소. 경로 규칙을 아는 곳은 이 파일 하나다.

왜 이 파일이 있나 (스펙 2절, 3-3절)
─────────────────────────────────────────────────────────────────────────────
Celery 워커는 API 와 <다른 프로세스>다. 그래서 파일 바이트를 함수 인자로 넘길 수 없고,
메시지에는 doc_id·bot_id 만 싣는다(claim check). 워커는 이 파일의 read() 로 원본을 찾는다.

지금은 로컬 디스크다. 다음 조각에서 MinIO 를 붙일 때 <이 파일의 안쪽만> 바꾼다.
그래서 호출하는 쪽(main.py, worker.py)은 경로를 직접 만들지 않는다.

경로: {upload_dir}/{bot_id}/{doc_id}
  · 원본 파일명을 쓰지 않는다. 파일명은 사용자가 보낸 값이라 `../` 가 들어올 수 있다.
  · 봇 단위 폴더다. 봇이 지워지면 고아가 한 폴더에 모인다(스펙 7절 4번).

`root` 인자는 점검(tools/storage_check.py)이 임시 폴더를 넘기려고 있다. 앱 코드는 비워 둔다.
`*,` 뒤의 인자는 <이름을 붙여서만> 넘길 수 있다(키워드 전용). save(1, 2, data, root=...) 처럼.
"""
from __future__ import annotations

from pathlib import Path

from .config import get_settings


def _root(root: Path | None) -> Path:
    return root if root is not None else Path(get_settings().upload_dir)


def _check_id(name: str, value: object) -> int:
    # `type(x) is int` 로 본다. isinstance(True, int) 는 True 라서 bool 이 통과해 버린다.
    if type(value) is not int:
        raise TypeError(f"{name} 는 정수여야 한다: {value!r}")
    return value


def _path(bot_id: int, doc_id: int, root: Path | None) -> Path:
    return _root(root) / str(_check_id("bot_id", bot_id)) / str(_check_id("doc_id", doc_id))


def save(bot_id: int, doc_id: int, data: bytes, *, root: Path | None = None) -> None:
    path = _path(bot_id, doc_id, root)
    # parents=True: 중간 폴더(bot_id)가 없으면 같이 만든다. exist_ok=True: 이미 있어도 괜찮다.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def read(bot_id: int, doc_id: int, *, root: Path | None = None) -> bytes:
    """없으면 FileNotFoundError. 워커가 이 예외로 "원본 없음" 을 판정한다(스펙 5-2)."""
    return _path(bot_id, doc_id, root).read_bytes()


def delete(bot_id: int, doc_id: int, *, root: Path | None = None) -> None:
    """없어도 예외가 없다. 삭제가 두 번 불려도 안전해야 한다."""
    _path(bot_id, doc_id, root).unlink(missing_ok=True)


def ensure_upload_dir(*, root: Path | None = None) -> Path:
    """기동 시 한 번 부른다. 폴더가 없으면 만들고, 쓸 수 없으면 기동을 막는다(스펙 5-4).

    업로드를 받아 놓고 나중에 저장에서 실패하는 것보다 처음부터 안 뜨는 편이 낫다.
    """
    target = _root(root)
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".write-probe"
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as e:
        raise RuntimeError(
            f"업로드 폴더를 쓸 수 없습니다: {target} ({e.strerror}). "
            "UPLOAD_DIR 환경변수로 쓸 수 있는 폴더를 지정하거나, 그 경로의 권한을 확인해주세요."
        ) from e
    return target
```

- [ ] **Step 4: 통과를 확인한다**

Run: `.venv/bin/python -m tools.storage_check`
Expected: `✅` 8줄과 `8가지 전부 통과.`

- [ ] **Step 5: CI 목록에 추가**

`.github/workflows/ci.yml` 의 `- name: 자체 점검 (DB·외부 API 없이 도는 것만)` 블록에서 `python -m tools.chunker_check` 다음 줄에 추가:

```yaml
          python -m tools.storage_check
```

같은 블록 위 주석의 `✅ tools.import_boundary_check ...` 줄 바로 앞에 한 줄 추가:

```yaml
      #    ✅ tools.storage_check 는 업로드 원본의 경로 규칙을 임시 폴더에서만 본다. Redis 도 DB 도 안 쓴다.
```

- [ ] **Step 6: Commit**

```bash
cd /Users/cheonjamin/projects/AllDap
git add ai-service/app/storage.py ai-service/tools/storage_check.py .github/workflows/ci.yml
git commit -m "feat: 업로드 원본을 봇·문서 번호 경로로 저장하는 storage 모듈을 더한다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Celery 워커와 `process_document` 작업

**Files:**
- Create: `ai-service/app/worker.py`

**Interfaces:**
- Consumes: `storage.read`, `storage.ensure_upload_dir` (Task 2), `Settings.broker_url` (Task 1)
- Produces:
  - `worker.celery_app: celery.Celery`
  - `worker.process_document` — Celery 작업. `process_document.delay(doc_id: int, bot_id: int)` 로 큐에 넣고, `process_document(doc_id, bot_id)` 로 부르면 현재 프로세스에서 바로 실행된다. 반환값 `"ready" | "failed" | "skipped"`.

이 Task 는 main.py 를 아직 건드리지 않는다. 업로드는 여전히 `BackgroundTasks` 로 돈다(Task 4 에서 바꾼다).

- [ ] **Step 1: `worker.py` 를 쓴다**

처리 본문(`_run_pipeline`)은 `app/main.py` 의 `_process_document` 에서 **`status='processing'` UPDATE 한 줄만 빼고** 그대로 옮긴 것이다. 그 줄은 상태 가드(`_claim`)가 대신한다.

`ai-service/app/worker.py`:

```python
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
        _log.exception("문서 처리 실패 doc_id=%s", doc_id)
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
```

- [ ] **Step 2: import 가 되는지, 그리고 Redis 없이도 되는지 확인**

Run: `docker compose stop redis && .venv/bin/python -c "from app.worker import celery_app, process_document; print(process_document.name)"; docker compose start redis`
Expected: `documents.process` (Redis 가 꺼져 있어도 import 는 성공한다)

- [ ] **Step 3: 워커가 뜨는지 확인**

Run (다른 터미널): `.venv/bin/celery -A app.worker worker --pool=solo --loglevel=info`
Expected: 배너의 `[tasks]` 아래 `. documents.process` 가 보이고 `celery@... ready.` 가 찍힌다. 확인 후 Ctrl+C.

- [ ] **Step 4: 기존 CI 점검이 깨지지 않았는지 확인**

Run: `.venv/bin/python -m tools.import_boundary_check && .venv/bin/python -m tools.openapi_check`
Expected: 둘 다 통과.

- [ ] **Step 5: Commit**

```bash
cd /Users/cheonjamin/projects/AllDap
git add ai-service/app/worker.py
git commit -m "feat: 문서 처리 작업을 Celery 워커 모듈로 옮기고 상태 가드를 더한다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: 업로드 경로를 큐로 바꾼다

**Files:**
- Modify: `ai-service/app/main.py` — import 블록(15~22행), `lifespan`(84~88행), `_process_document`(삭제), `upload_document`(시그니처·docstring·본문)

**Interfaces:**
- Consumes: `storage.save`, `storage.delete`, `storage.ensure_upload_dir` (Task 2), `process_document` (Task 3)
- Produces: `POST /internal/bots/{bot_id}/documents` 가 202 + `pending` 을 돌려주고 처리는 워커가 한다. 저장 실패 → 503(행 없음), 브로커 실패 → 503 + 행 `failed`.

- [ ] **Step 1: import 와 lifespan**

`from fastapi import BackgroundTasks, ...` 줄은 그대로 둔다(평가 실행이 아직 쓴다). 아래를 추가한다.

```python
from kombu.exceptions import OperationalError as BrokerUnavailable

from . import storage
from .worker import process_document
```

`from .parsers import ParseError, extract_text` 줄은 `upload_document` 가 `detect_type` 을 지연 import 하고 `ParseError` 를 잡으므로 `ParseError` 는 남긴다. `extract_text` 를 main.py 의 다른 곳이 쓰는지 `grep -n "extract_text" app/main.py` 로 확인하고, 업로드 처리 말고 쓰는 곳이 없으면 import 에서 뺀다. `chunk_text`·`retriever`·`json` 도 같은 방식으로 확인한다.

`lifespan` 을 바꾼다:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    _apply_thread_limit()
    # 업로드 폴더를 못 쓰면 여기서 기동을 막는다. 업로드를 받고 나서 실패하는 것보다 낫다(스펙 5-4).
    storage.ensure_upload_dir()
    yield
    close_pool()
```

- [ ] **Step 2: `_process_document` 를 지운다**

`# ── 문서 처리 ───` 아래의 `def _process_document(...)` 함수 전체를 지운다(본문은 Task 3 에서 `worker._run_pipeline` 으로 옮겼다). 구획 주석 한 줄은 남긴다.

- [ ] **Step 3: `upload_document` 를 바꾼다**

시그니처에서 `background: BackgroundTasks,` 를 지운다.

docstring 의 `나머지를 \`BackgroundTasks\` 로 넘긴다.` 를 `나머지는 Celery 워커가 한다(app/worker.py).` 로 바꾸고, `🔴 <b>대가가 있다. 알고 남긴 한계다:</b>` 문단 전체를 아래로 바꾼다.

```text
    🔴 <b>순서가 계약이다 (스펙 4-1):</b> 행 INSERT 와 원본 저장을 <한 트랜잭션>에 넣고,
    메시지는 <커밋 뒤에> 보낸다. 커밋 전에 보내면 워커가 아직 안 보이는 행을 찾다가
    "없는 문서" 로 건너뛴다. 저장이 실패하면 커밋이 안 되어 "행은 있는데 원본이 없는" 문서가 없다.

    🔴 <b>알고 남긴 한계 (스펙 7절):</b> 워커가 처리 중에 죽으면 문서는 processing 에 멈춘다
    (acks_late 를 껐다). 커밋과 delay() 사이에 이 프로세스가 죽으면 pending 이 남는다.
```

함수 본문에서 `s = get_settings()` 부터 끝까지를 아래로 바꾼다(파일 검사 세 개는 그대로다).

```python
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

    # ── ① 행과 원본을 한 트랜잭션에 ────────────────────────────────────
    # `with cursor(commit=True)` 블록이 <예외 없이> 끝나야 커밋된다. 저장이 예외를 내면
    # 커밋을 건너뛰고 연결이 롤백되므로 행도 사라진다.
    doc_id: Id | None = None
    try:
        with cursor(commit=True) as cur:
            cur.execute(
                """INSERT INTO documents (bot_id, filename, file_type, status)
                   VALUES (%s, %s, %s, 'pending') RETURNING id""",
                (bot_id, filename, ftype),
            )
            doc_id = cur.fetchone()[0]
            storage.save(bot_id, doc_id, data)
    except Exception as e:
        # 행은 롤백됐다. 쓰다 만 원본이 있으면 지운다(없어도 예외 없음).
        if doc_id is not None:
            storage.delete(bot_id, doc_id)
        # OSError: 디스크 꽉 참, 권한 등 <파일 쪽> 실패. 사용자 잘못이 아니다 → 503.
        # 그 밖(DB 오류)은 지금까지처럼 그대로 올린다.
        if isinstance(e, OSError):
            _log.exception("업로드 원본 저장 실패 bot_id=%s", bot_id)
            raise HTTPException(
                503, "업로드한 파일을 저장하지 못했습니다. 잠시 후 다시 올려주세요."
            ) from e
        raise

    # ── ② 커밋 뒤에 메시지 ────────────────────────────────────────────
    # .delay(...) 는 "지금 실행" 이 아니라 "Redis 에 쪽지를 넣는다" 다. 실행은 워커가 한다.
    try:
        process_document.delay(doc_id, bot_id)
    except BrokerUnavailable as e:
        # Redis 가 꺼져 있다. 그대로 두면 이 문서는 pending 에 영원히 멈춘다(쪽지가 없으니까).
        # failed 로 바꿔 목록에서 보이게 한다. 원본은 남긴다(보존 원칙, 스펙 5-1).
        reason = "작업 대기열에 연결하지 못했습니다. 잠시 후 다시 올려주세요."
        with cursor(commit=True) as cur:
            cur.execute(
                "UPDATE documents SET status='failed', error_message=%s WHERE id=%s",
                (reason, doc_id),
            )
        _log.error("브로커 연결 실패로 문서를 failed 로 바꿨다 doc_id=%s: %s", doc_id, e)
        raise HTTPException(503, reason) from e

    return DocumentOut(id=doc_id, filename=filename, file_type=ftype, status="pending")
```

`_log` 가 main.py 에 이미 있는지 `grep -n "^_log" app/main.py` 로 확인한다. 없으면 `logging.getLogger(__name__)` 로 모듈 상단에 둔다.

- [ ] **Step 4: 정적 확인**

Run: `.venv/bin/python -m compileall -q app && .venv/bin/python -m tools.openapi_check && .venv/bin/python -m tools.import_boundary_check`
Expected: 오류 없음, 두 점검 통과.

- [ ] **Step 5: 손으로 한 번 태운다 (정상 경로)**

터미널 셋: ① `docker compose up -d`(루트) ② `.venv/bin/uvicorn app.main:app --port 8001` ③ `.venv/bin/celery -A app.worker worker --pool=solo --loglevel=info`

Run:
```bash
curl -s -F "file=@testdata/fixtures/$(ls testdata/fixtures | grep docx | head -1)" localhost:8001/internal/bots/1/documents
sleep 15
curl -s localhost:8001/internal/bots/1/documents | .venv/bin/python -c "import json,sys; [print(d['id'], d['status'], d['chunk_count']) for d in json.load(sys.stdin)[:3]]"
ls uploads/1/
```
Expected: 업로드 응답 `"status":"pending"`, 워커 로그에 `documents.process[...] succeeded`, 목록에서 그 문서가 `ready`, `uploads/1/` 에 그 doc_id 파일이 있다. (fixture 가 없으면 `.venv/bin/python -m testdata.make_fixtures` 로 먼저 만든다.)

이 문서는 Task 5 Step 3 에서 지운다.

- [ ] **Step 6: Commit**

```bash
cd /Users/cheonjamin/projects/AllDap
git add ai-service/app/main.py
git commit -m "feat: 업로드가 원본을 저장하고 커밋 뒤에 Celery 로 처리를 넘긴다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: 삭제 시 원본 정리

**Files:**
- Modify: `ai-service/app/main.py` — `delete_document` 본문과 docstring

**Interfaces:**
- Consumes: `storage.delete` (Task 2)
- Produces: `DELETE /internal/bots/{bot_id}/documents/{doc_id}` 가 DB 에서 실제로 1행을 지웠을 때만 원본을 지운다. 응답은 언제나 204.

- [ ] **Step 1: 본문을 바꾼다**

```python
    with cursor(commit=True) as cur:
        # RETURNING id: 지운 행이 있으면 그 id 를 돌려준다. 0행이면 fetchone() 이 None 이다.
        cur.execute(
            "DELETE FROM documents WHERE id=%s AND bot_id=%s RETURNING id", (doc_id, bot_id)
        )
        deleted = cur.fetchone() is not None

    # 🔴 DB 가 "네 봇의 문서가 맞다" 고 확인해 준 경우에만 원본을 지운다(스펙 4-3).
    #    /internal/* 에는 인증이 없다. 남의 bot_id 로 부르면 위 DELETE 는 0행인데,
    #    파일 삭제가 그와 무관하게 돌면 격리가 깨진다.
    # 🔴 DB 먼저, 파일 나중. 반대면 "행은 있는데 원본이 없는" 문서가 생길 수 있다.
    #    이 순서의 최악은 고아 파일이고, 고아는 다음 조각의 스위퍼가 치운다.
    if deleted:
        try:
            storage.delete(bot_id, doc_id)
        except OSError:
            # 사용자 입장에서 문서는 이미 지워졌다. 204 를 그대로 주고 로그만 남긴다(스펙 5-4).
            _log.exception("원본 삭제 실패(고아 파일) bot_id=%s doc_id=%s", bot_id, doc_id)
```

docstring 첫 줄 `문서 1건을 지운다. 청크는 CASCADE 로 함께 사라진다.` 아래에 한 줄 추가:

```text
    업로드 원본(uploads/{bot_id}/{doc_id})도 지운다. 단 DB 에서 1행이 지워졌을 때만이다.
```

- [ ] **Step 2: 정적 확인**

Run: `.venv/bin/python -m compileall -q app && .venv/bin/python -m tools.openapi_check`
Expected: 통과.

- [ ] **Step 3: 손으로 확인 (Task 4 Step 5 의 문서로)**

Task 4 Step 5 에서 만든 문서 id 를 `<ID>` 로 쓴다(uvicorn 은 띄운 채).

Run:
```bash
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE localhost:8001/internal/bots/999/documents/<ID>
ls uploads/1/<ID>
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE localhost:8001/internal/bots/1/documents/<ID>
ls uploads/1/<ID>
```
Expected: `204` → 파일 있음(남의 봇으로는 안 지워진다) → `204` → `No such file or directory`.

- [ ] **Step 4: Commit**

```bash
cd /Users/cheonjamin/projects/AllDap
git add ai-service/app/main.py
git commit -m "feat: 문서를 지우면 DB 에서 지워진 경우에만 업로드 원본도 지운다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: 종단 점검 — 새 점검, 기존 점검 수정, CI 주석

**Files:**
- Create: `ai-service/tools/queue_preflight.py`
- Create: `ai-service/tools/upload_queue_e2e_check.py`
- Modify: `ai-service/tools/upload_e2e_check.py` (docstring 실행 방법, `_client` 주석, `_purge`, `main`)
- Modify: `.github/workflows/ci.yml` (못 태우는 점검 목록 주석)

**Interfaces:**
- Consumes: `worker.celery_app`, `worker.process_document` (Task 3), `storage.read` (Task 2), 업로드·삭제 API (Task 4, 5)
- Produces: `queue_preflight.require_worker() -> None` — Redis 나 워커가 없으면 한국어 안내와 함께 `SystemExit(1)`.

- [ ] **Step 1: 사전 확인 모듈**

`ai-service/tools/queue_preflight.py`:

```python
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
```

- [ ] **Step 2: 새 종단 점검**

`ai-service/tools/upload_queue_e2e_check.py`:

```python
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
```

- [ ] **Step 3: 새 점검을 돌린다**

Run (Redis·워커 떠 있는 상태): `.venv/bin/python -m tools.upload_queue_e2e_check`
Expected: `✅` 4줄과 `4가지 전부 통과.`

워커를 끄고 한 번 더 돌린다.
Expected: `Celery 워커가 떠 있지 않습니다. ...` 로 바로 끝난다(120초를 기다리지 않는다).

- [ ] **Step 4: 기존 `upload_e2e_check.py` 를 고친다**

(a) docstring 맨 위 실행 방법 블록을 아래로 바꾼다.

```text
실행 (둘 다 Redis 와 Celery 워커가 떠 있어야 한다 - 2026-11-06 부터 처리는 워커가 한다):
    docker compose up -d                                                   # 저장소 루트
    cd ai-service && .venv/bin/celery -A app.worker worker --pool=solo     # 다른 터미널

    # ① 인프로세스: API 는 ASGI 앱을 직접 태운다. DB·Redis·워커·Cloudflare 는 진짜다.
    cd ai-service && .venv/bin/python -m tools.upload_e2e_check

    # ② 진짜 HTTP: uvicorn 도 띄워두고 밖에서 두드린다.
    cd ai-service && .venv/bin/uvicorn app.main:app --port 8001   # 또 다른 터미널
    cd ai-service && .venv/bin/python -m tools.upload_e2e_check --base-url http://localhost:8001

🔴 Celery eager 모드(큐 없이 delay() 자리에서 바로 실행)를 쓰지 않는다(스펙 6-3).
   이 점검이 지나야 할 바로 그 경로(큐)를 건너뛰고 초록불을 준다.
```

(b) `_client` 안의 주석 세 줄(`# Starlette 가 응답을 낸 뒤 BackgroundTasks 를 ...` 부터 `... 첫 폴링에 이미 ready 다.`)을 지우고 아래로 바꾼다.

```python
    # 처리는 워커가 한다. 인프로세스여도 폴링이 실제로 돈다(2026-11-06 전에는 첫 폴링에 이미 ready 였다).
```

(c) `_purge` 를 원본까지 지우도록 바꾼다.

```python
def _purge(bot_id: Id, names: list[str]) -> int:
    """같은 이름의 잔재를 지운다(중간에 죽은 앞 실행 대비).

    chunks 는 documents 에 ON DELETE CASCADE 로 딸려 있다(V9__bigint_ids.sql).
    DB 를 직접 지우므로 업로드 원본도 여기서 함께 지운다(삭제 API 를 안 거치니까).
    """
    with cursor(commit=True) as cur:
        cur.execute(
            "DELETE FROM documents WHERE bot_id = %s AND filename = ANY(%s) RETURNING id",
            (bot_id, names),
        )
        ids = [r[0] for r in cur.fetchall()]
    for doc_id in ids:
        storage.delete(bot_id, doc_id)
    return len(ids)
```

import 블록에 `from app import storage` 와 `from tools.queue_preflight import require_worker` 를 추가한다.

(d) `main()` 의 `bot_id = args.bot_id` 바로 앞에 `require_worker()` 를 넣는다.

- [ ] **Step 5: 기존 점검을 돌린다**

Run: `.venv/bin/python -m tools.upload_e2e_check`
Expected: `upload_e2e_check: 3개 형식이 ready 까지 통과`. 그 뒤 `ls uploads/1/` 에 이 점검이 남긴 파일이 없다.

- [ ] **Step 6: CI 주석 갱신**

`.github/workflows/ci.yml` 의 못 태우는 점검 목록에서:

- `#    🔴 여기 없는 점검 8개는` → `#    🔴 여기 없는 점검 9개는`
- `#       마지막 하나를 뺀 일곱은` → `#       마지막 하나를 뺀 여덟은`
- `#         · tools.upload_e2e_check     DB(cursor) + 실제 임베딩 호출` 를 아래 두 줄로 바꾼다.

```yaml
      #         · tools.upload_e2e_check     DB(cursor) + 실제 임베딩 호출 + Redis·Celery 워커
      #         · tools.upload_queue_e2e_check  DB(cursor) + 실제 임베딩 호출 + Redis·Celery 워커
```

- [ ] **Step 7: Commit**

```bash
cd /Users/cheonjamin/projects/AllDap
git add ai-service/tools/queue_preflight.py ai-service/tools/upload_queue_e2e_check.py ai-service/tools/upload_e2e_check.py .github/workflows/ci.yml
git commit -m "test: 문서 처리 큐 종단 점검을 더하고 업로드 점검을 워커 전제로 바꾼다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: 손으로 재는 실험 (PR 에 붙일 결과)

**Files:**
- Modify: `docs/실측-기록.md` (맨 끝에 절 추가)

코드를 바꾸지 않는다. 결과를 기록한다. 각 실험의 **실제 출력**을 그대로 붙인다("돌려봤다" 가 아니라 결과).

- [ ] **Step 1: 메시지에 ID 만 있는가 (claim check 확인)**

워커를 끄고(Ctrl+C) uvicorn 만 띄운 채:

```bash
curl -s -F "file=@testdata/fixtures/$(ls testdata/fixtures | grep docx | head -1)" localhost:8001/internal/bots/1/documents
docker exec alldap-redis redis-cli KEYS '*'
docker exec alldap-redis redis-cli LRANGE celery 0 -1 > /tmp/msg.json
.venv/bin/python -c "
import base64, json
m = json.loads(open('/tmp/msg.json').read().splitlines()[0])
print('headers.task =', m['headers']['task'])
print('body =', base64.b64decode(m['body']).decode())
print('메시지 크기(바이트) =', len(open('/tmp/msg.json','rb').read()))
"
```
Expected: 큐 키 `celery` 가 보이고, `headers.task = documents.process`, `body` 에 `[[<doc_id>, 1], {}, {...}]` 처럼 번호 둘만 있다. 크기는 수백 바이트~1KB 대. (`KEYS` 에 `celery` 가 없으면 나온 키 이름으로 `LRANGE` 를 다시 한다. Celery 의 Redis 메시지 형식은 버전에 따라 다를 수 있으므로, 출력 모양이 다르면 그대로 기록한다.)

- [ ] **Step 2: 워커 없이 올린 문서가 나중에 처리되는가**

Step 1 의 문서는 `pending` 이다. 워커를 띄우고 15초 뒤 목록을 본다.
Expected: 그 문서가 `ready`. 쪽지가 Redis 에 남아 있었다는 뜻이다.

- [ ] **Step 3: Redis 가 꺼져 있으면**

```bash
docker compose stop redis
time curl -s -w "\n%{http_code}\n" -F "file=@testdata/fixtures/$(ls testdata/fixtures | grep docx | head -1)" localhost:8001/internal/bots/1/documents
curl -s localhost:8001/internal/bots/1/documents | .venv/bin/python -c "import json,sys; d=json.load(sys.stdin)[0]; print(d['status'], d.get('error_message'))"
docker compose start redis
```
Expected: `503`, 본문에 "작업 대기열에 연결하지 못했습니다...", 마지막 문서가 `failed` 에 같은 사유. **`real` 시간을 기록한다.** 5초를 넘으면 `worker.py` 의 `broker_connection_timeout` 과 `task_publish_retry` 가 실제로 먹는지 확인하고, 고친 값과 다시 잰 시간을 함께 기록한다.

- [ ] **Step 4: 처리 중 워커를 kill -9 (다음 조각의 before)**

워커를 띄운 채 PDF fixture 를 올리고 **곧바로** 워커 프로세스를 죽인다.

```bash
curl -s -F "file=@testdata/fixtures/$(ls testdata/fixtures | grep pdf | head -1)" localhost:8001/internal/bots/1/documents
pkill -9 -f "celery -A app.worker"
sleep 2
curl -s localhost:8001/internal/bots/1/documents | .venv/bin/python -c "import json,sys; d=json.load(sys.stdin)[0]; print(d['id'], d['status'])"
docker exec alldap-redis redis-cli LLEN celery
```
Expected: 문서가 `processing`(이미 가드를 지났으면) 또는 `pending`(아직 안 꺼냈으면)이다. **둘 중 무엇이 나왔는지, 그리고 `LLEN` 값을 그대로 기록한다.** `processing` 이면 워커를 다시 띄워도 그대로 멈춰 있는 것까지 확인한다(이 조각의 한계, 스펙 7절 1번). `pending` 이 나오면 처리가 늦게 시작되도록 더 큰 문서로 다시 한 번 시도하고, 두 결과를 모두 적는다.

- [ ] **Step 5: git 과 회귀**

```bash
cd /Users/cheonjamin/projects/AllDap
git status --porcelain | grep uploads || echo "uploads 없음"
cd api && ./gradlew test
```
Expected: `uploads 없음`, `BUILD SUCCESSFUL`.

Spring 을 거친 업로드는 `ai-service/tools/upload_e2e_check.py` docstring 의 "Spring 을 거치는 경로" 문단이 가리키는 절차(가입 → 봇 생성 → 업로드 → 폴링)로 한 번 돌리고 `ready` 까지 본다.

- [ ] **Step 6: 남긴 문서를 정리하고 실측 기록에 적는다**

이 Task 에서 만든 문서는 `DELETE /internal/bots/1/documents/<id>` 로 지운다(원본도 같이 지워진다). `processing` 에 멈춘 문서도 같은 방법으로 지운다.

`docs/실측-기록.md` 맨 끝에 추가한다. `<...>` 는 위 Step 들의 실제 출력으로 채운다.

```markdown
### 🔧 문서 처리 Celery 워커 분리 (2026-11-06) — 메시지에는 번호 둘만 간다

스펙: `docs/superpowers/specs/2026-11-06-celery-document-worker-design.md`. 로컬 전용이다.

| 실험 | 결과 |
|---|---|
| Redis 메시지 내용 | `<body 출력>`, 크기 `<N>` 바이트. 원본은 `uploads/1/<id>` |
| 워커 없이 업로드 → 나중에 기동 | `<pending → ready 여부>` |
| Redis 를 끄고 업로드 | `<HTTP 코드>`, `<status / error_message>`, 응답까지 `<real 시간>` |
| 처리 중 kill -9 | `<processing 또는 pending>`, `LLEN celery = <값>`. 워커 재기동 후 `<상태>` |

🔴 마지막 줄이 이 조각의 한계다. `acks_late` 를 껐으므로 꺼낸 메시지는 Redis 에서 이미 사라졌다.
다음 조각(유실 방지)의 완료 조건은 이 실험에서 `ready` 가 나오는 것이다.
```

- [ ] **Step 7: Commit**

```bash
cd /Users/cheonjamin/projects/AllDap
git add docs/실측-기록.md
git commit -m "docs: Celery 워커 분리의 실측 결과를 남긴다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: 설명하는 자리 고치기

**Files:**
- Modify: `AGENTS.md` (로컬 실행 순서 블록, "알려진 한계" 의 625·640행)
- Modify: `docs/BACKLOG.md` (3-5 절)
- Modify: `docs/decisions.md` (맨 끝에 두 항목)
- Modify: `ai-service/tools/eval_set_check.py:29`, `ai-service/tools/parsers_check.py:81` (docstring 의 `_process_document` 언급)

- [ ] **Step 1: 옛 이름을 찾는다**

Run (저장소 루트): `grep -rn "_process_document\|Redis + RQ\|BackgroundTasks" --include=*.py --include=*.md . | grep -v node_modules | grep -v "docs/superpowers/"`
Expected: 이 Task 의 Files 목록과 `app/main.py`(평가 실행 쪽 `BackgroundTasks`, 이건 그대로 둔다)가 나온다. 목록에 없는 곳이 더 나오면 그 자리도 함께 고친다.

- [ ] **Step 2: tools docstring 두 곳**

- `tools/eval_set_check.py` 의 `` (`app/main.py` 의 `_process_document`) `` → `` (`app/worker.py` 의 `process_document`) ``
- `tools/parsers_check.py` 의 `` `_process_document` 의 `` → `` `app/worker.py` 의 `process_document` 의 ``

- [ ] **Step 3: AGENTS.md**

로컬 실행 순서 블록의 `cd ai-service && .venv/bin/uvicorn app.main:app --port 8001` 줄 바로 아래에 추가:

```text
cd ai-service && .venv/bin/celery -A app.worker worker --pool=solo --loglevel=info   # 다른 터미널. 없으면 업로드가 pending 에 머문다
```

블록 위 문장 `**로컬 실행 순서**` 뒤 괄호 설명 끝에 `` `docker compose up -d` 가 이제 Redis 도 띄운다(2026-11-06). `` 를 덧붙인다.

625행을 바꾼다:

```text
- 문서 처리는 Celery 워커(로컬 전용, 2026-11-06)지만 `acks_late` 를 꺼서 처리 중 워커가 죽으면 문서가 `processing` 에 멈춘다. 평가 실행은 여전히 `BackgroundTasks` 다. 스펙 `docs/superpowers/specs/2026-11-06-celery-document-worker-design.md` 7절.
```

640행의 `업로드 상한 10MB 는` 을 `업로드 상한(운영 10MB, 로컬 기본값 20MB)은` 으로 바꾼다.

- [ ] **Step 4: BACKLOG 3-5 절**

`Redis + RQ 로 교체해야 한다. **트리거는 실사용 트래픽이다.**` 를 아래로 바꾼다.

```text
**문서 처리는 2026-11-06 에 Celery 워커로 옮겼다(로컬 전용).** 다만 `acks_late` 를 꺼서
처리 중 워커가 죽으면 여전히 `processing` 에 멈춘다. 다음 조각: `acks_late` + 청크 멱등화,
완료 조건은 "처리 중 kill -9 를 해도 ready". 평가 실행(`evalrun.execute`)은 아직 `BackgroundTasks` 다.
```

- [ ] **Step 5: decisions.md 두 항목**

맨 끝에 추가한다(형식은 바로 앞 항목들과 같다).

```markdown
## 2026-11-06 | 문서 처리를 Celery 워커로 옮기고, 업로드 원본은 로컬 디스크에 두며 메시지에는 번호 둘만 싣는다

**무엇을**: `_process_document` 를 `app/worker.py` 의 Celery 작업으로 옮겼다. 원본은 `uploads/{bot_id}/{doc_id}` 에 저장하고(`app/storage.py`), Redis 메시지에는 `doc_id`·`bot_id` 만 싣는다. 로컬 전용이다. 설계 `docs/superpowers/specs/2026-11-06-celery-document-worker-design.md`.

**왜 그렇게**
- 워커는 API 와 다른 프로세스라 바이트를 인자로 못 넘긴다. 큰 데이터는 저장소에, 메시지에는 열쇠만 두는 것이 통용 관행이다(claim check).
- 세 관점(학습자·기술·면접관)의 분석 팀이 3라운드 교차 검증 끝에 전원 조건부 인정했다(18·17·18 / 20).
- 이번 조각은 "워커 분리" 까지다. `acks_late` 를 꺼서 처리 중 워커가 죽으면 여전히 멈춘다. 켜면 지금 처리 함수는 청크를 두 벌 만든다. 다음 조각에서 그것을 먼저 재현한 뒤 고친다.

**검토한 대안**
① MinIO(S3 호환)에 저장 → 다음 조각. Celery 와 S3 SDK 를 한 PR 에서 함께 배우게 된다. 저장 함수의 두 번째 구현으로 붙인다.
② 메시지에 바이트를 직접 → 기각. 로컬 상한 20MB 가 base64 로 약 27MB 메시지가 된다.
③ PostgreSQL `bytea` 자식 테이블 → 기각(차점). 행·원본이 한 트랜잭션에 묶이고 봇 삭제 CASCADE 로 원본도 사라지는 이점이 있지만, 학습 초점이 "DB 에 파일을 넣어도 되나" 로 옮겨 가고 V10 이 따라온다.

## 2026-11-06 | 작업 큐를 RQ 가 아니라 Celery 로 고른다

**무엇을**: BACKLOG 와 코드 주석에 적혀 있던 "Redis + RQ" 대신 Celery 를 썼다.

**왜 그렇게**
- RQ 를 적었던 기준은 "1인 개발에서 운영할 것을 최소화한다" 였다. 이번 작업의 기준은 "실무에서 마주칠 도구를 직접 다뤄 본 경험" 이고, 운영에는 올리지 않는다.
- 브로커는 둘 다 Redis 라 인프라는 같다. 달라지는 것은 라이브러리의 설정 표면(acks_late, 직렬화, 시그널 등)이고, 그것이 배우려는 대상이다.

**검토한 대안**
① RQ → 기각. 구조가 단순해 브로커·큐·워커를 따라가기는 쉽지만, 이번 기준(경험)에서 우선순위가 낮다.
```

- [ ] **Step 6: 로컬 검사 후 Commit**

Run: `cd ai-service && .venv/bin/python -m compileall -q app tools && .venv/bin/python -m tools.storage_check && .venv/bin/python -m tools.openapi_check && .venv/bin/python -m tools.import_boundary_check`
Expected: 전부 통과.

```bash
cd /Users/cheonjamin/projects/AllDap
git add AGENTS.md docs/BACKLOG.md docs/decisions.md ai-service/tools/eval_set_check.py ai-service/tools/parsers_check.py
git commit -m "docs: Celery 워커 분리를 실행 순서·한계·결정 로그에 반영한다

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## PR (모든 Task 뒤)

`.github/PULL_REQUEST_TEMPLATE.md` 를 채운다. 제목: `feat: 문서 처리를 Celery 워커로 분리한다 (로컬 디스크 claim check)`.

- **어떻게 해결했나요**: Task 6 Step 3·5 와 Task 7 의 실제 출력.
- **한계 & 트레이드오프**: 스펙 7절 여섯 줄을 그대로 옮기고, `deploy.yml` 이 남아 있어 머지 시 배포가 시도될 수 있다는 한 줄을 더한다.
- **검토한 대안**: decisions.md 2026-11-06 두 항목.
