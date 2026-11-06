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
