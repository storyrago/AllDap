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
