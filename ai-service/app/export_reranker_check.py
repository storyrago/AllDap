"""내보내기 스크립트의 <순수 로직> 점검. 모델도 네트워크도 건드리지 않는다.

여기서 보는 것은 넷이다.
  ① 리비전이 못박혀 있는가 (안 박으면 나중에 다른 가중치가 와서
     "양자화 때문인가 모델이 바뀐 것인가" 를 구분할 수 없다)
  ② 산출물이 <부분적으로> 있을 때 "있다" 고 말하지 않는가
  ③ 변형(local · local_int8 · local_int8_pc)이 <빠짐없이> 등록돼 있는가
  ④ 없을 때 나가는 안내가 무엇을 어떻게 하면 되는지 말하는가
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from .export_reranker import (
    ONNX_FILENAME,
    QUANT_PER_CHANNEL,
    REPO_ID,
    REVISION,
    VARIANT_DIRS,
    artifact_status,
    missing_message,
)


def check_revision_is_pinned() -> None:
    """🔴 리비전이 커밋 해시로 못박혀 있어야 한다.

    `main` 같은 움직이는 이름이면 나중에 다른 가중치가 온다. 그러면
    B(로컬 원본)와 C(로컬 INT8)의 차이를 양자화 탓으로 읽을 수 없게 된다.
    """
    assert REPO_ID == "BAAI/bge-reranker-base", REPO_ID
    assert len(REVISION) == 40, f"리비전이 40자 커밋 해시가 아니다: {REVISION}"
    assert all(c in "0123456789abcdef" for c in REVISION), REVISION
    assert REVISION.strip("0") != "", "REVISION 이 아직 자리표시자다"


def check_missing_artifacts_are_not_reported_as_present() -> None:
    """산출물이 하나라도 빠지면 False 여야 한다.

    ⚠️ 디렉터리 존재만 보면 안 된다. 변환이 중간에 죽어 디렉터리만 남은 상태와
       정상 산출물을 <같은 값으로 뭉갠다.> 이 저장소가 여덟 번 낸 버그의 부류다.
    """
    with TemporaryDirectory() as tmp:
        models = Path(tmp)
        assert artifact_status(models) == dict.fromkeys(VARIANT_DIRS, False)

        # 디렉터리만 만든다 (변환이 죽은 상태)
        (models / VARIANT_DIRS["local"]).mkdir(parents=True)
        assert artifact_status(models)["local"] is False, "빈 디렉터리를 산출물로 셌다"

        # onnx 파일만 있고 토크나이저가 없는 상태도 False 다
        (models / VARIANT_DIRS["local"] / ONNX_FILENAME["local"]).write_bytes(b"x")
        assert artifact_status(models)["local"] is False, "토크나이저 없이 완성으로 셌다"

        (models / VARIANT_DIRS["local"] / "tokenizer.json").write_text("{}")
        (models / VARIANT_DIRS["local"] / "tokenizer_config.json").write_text("{}")
        assert artifact_status(models)["local"] is True


def check_every_variant_is_fully_registered() -> None:
    """🔴 변형을 하나 더할 때 <빠뜨리기 쉬운 자리들>을 여기서 한꺼번에 막는다.

    2026-09-17 에 local_int8_pc 를 더하면서 실제로 셋을 동시에 손봐야 했다:
    VARIANT_DIRS · ONNX_FILENAME · QUANT_PER_CHANNEL. 하나라도 빠지면 증상이 제각각이라
    (KeyError · 조용한 덮어쓰기 · 양자화 설정 누락) 원인을 찾는 데 시간이 든다.

    ⚠️ 특히 <디렉터리가 겹치는 것>을 본다. ORTQuantizer 는 변형과 무관하게
       model_quantized.onnx 라는 같은 이름으로 떨구므로, 두 변형이 같은 디렉터리를 쓰면
       뒤에 돌린 것이 앞의 것을 조용히 덮는다. 그러면 표의 두 줄이 사실은 같은 파일이 된다.
    """
    assert set(ONNX_FILENAME) == set(VARIANT_DIRS), (
        f"ONNX_FILENAME 과 VARIANT_DIRS 의 변형 목록이 다르다: "
        f"{sorted(ONNX_FILENAME)} != {sorted(VARIANT_DIRS)}"
    )
    dirs = list(VARIANT_DIRS.values())
    assert len(set(dirs)) == len(dirs), f"변형끼리 디렉터리가 겹친다(덮어쓴다): {dirs}"
    # 양자화 변형은 전부 per_channel 값이 정해져 있어야 한다. 빠지면 export 가 KeyError 다.
    assert set(QUANT_PER_CHANNEL) <= set(VARIANT_DIRS), sorted(QUANT_PER_CHANNEL)
    assert "local" not in QUANT_PER_CHANNEL, "fp32 원본은 양자화 대상이 아니다"
    # 🔴 per_channel 값이 서로 달라야 <비교>가 성립한다. 같으면 두 변형이 같은 실험이다.
    assert len(set(QUANT_PER_CHANNEL.values())) == len(QUANT_PER_CHANNEL), QUANT_PER_CHANNEL


def check_missing_message_tells_what_to_do() -> None:
    """안내는 <무엇을 어떻게 하면 되는지> 까지 말해야 한다(저장소 규칙)."""
    msg = missing_message("local_int8")
    assert "app.export_reranker" in msg, msg
    assert "requirements-lab.txt" in msg, msg
    assert "local_int8" in msg, msg


def main() -> None:
    checks = [
        check_revision_is_pinned,
        check_missing_artifacts_are_not_reported_as_present,
        check_every_variant_is_fully_registered,
        check_missing_message_tells_what_to_do,
    ]
    for fn in checks:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(checks)}가지 전부 통과.")


if __name__ == "__main__":
    main()
