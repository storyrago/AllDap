"""리랭커를 내려받아 ONNX 로 바꾸고 INT8 로 양자화한다.

    cd ai-service && .venv/bin/python -m app.export_reranker

한 번만 돌리면 된다. 산출물은 ai-service/models/ 아래에 남고 git 에는 올라가지 않는다.

🔴 리비전을 못박는 이유
─────────────────────────────────────────────────────────────────────────────
태그 없이 받으면 나중에 다른 가중치가 와서 <양자화 때문인가 모델이 바뀐 것인가> 를
구분할 수 없게 된다. 이 저장소가 여덟 번 낸 버그가 전부 "원인이 다른 사실들을
같은 값으로 뭉갠 것" 이었다. 같은 함정을 여기서 미리 가른다.

🔴 왜 동적(dynamic) 양자화인가
─────────────────────────────────────────────────────────────────────────────
가중치를 8비트 정수로 줄이고 활성값은 추론 중에 그때그때 양자화한다.
<보정 데이터(calibration set)가 필요 없다.> 정적 양자화는 대표 입력 표본이 필요한데,
그것을 고르는 순간 표본 선택이 결과에 섞인다. 변수를 하나만 바꾸려면 없는 쪽이 낫다.
BERT 계열 인코더에서 가장 많이 쓰이는 기본 경로이기도 하다.
정적 양자화 · INT4 는 이번 범위가 아니다(설계문서 §3-5).

🔴 왜 등가 검증(_verify_equivalence)을 하는가
─────────────────────────────────────────────────────────────────────────────
내보낸 ONNX 가 PyTorch 원본과 <같은 출력을 내는지> 를 먼저 못박아 둔다.
이게 없으면 나중에 A(Cloudflare)와 B(로컬)의 점수가 갈렸을 때
"Cloudflare 가 다른 모델을 쓴다" 와 "우리 변환이 틀어졌다" 를 구분할 수 없다.
이것도 <원인이 다른 사실을 뭉개지 않기> 위한 장치다.

📌 실측 기록 (2026-09-16, Python 3.13.9 / macOS arm64)
─────────────────────────────────────────────────────────────────────────────
등가 검증: fp32 ONNX vs PyTorch 최대 오차 1.431e-05 (허용 1e-4). 순위도 같다.
           INT8 ONNX vs PyTorch 최대 오차 1.158e+00 - 양자화라 <달라지는 것이 정상>이고,
           네 쌍의 순위는 그대로였다.
산출물 크기: fp32 1,112,400,634 바이트 · INT8 278,863,038 바이트 (약 4.0배 감소).
대조: 이 저장소가 이미 올려둔 onnx/model.onnx(1,112,459,588 바이트)와 크기가
      58,954 바이트 다르지만 같은 입력의 로짓 차이는 6.676e-06 이다.
      즉 <같은 모델이고 내보낸 도구의 그래프 메타데이터만 다르다.>
      그래도 우리가 직접 내보내는 이유는 리비전을 못박아 재현을 우리가 쥐기 위해서다.

⚠️ 이 파일은 requirements-lab.txt 를 설치한 환경에서만 <내보내기가> 돈다.
   무거운 import 는 전부 함수 안에 있다 (모듈 최상단에 두면 CI 가 그 자리에서 죽는다).
"""
from __future__ import annotations

import contextlib
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ID = "BAAI/bge-reranker-base"
# 🔴 huggingface API 로 확인한 실제 커밋 해시다(2024-06-24 시점의 main).
REVISION = "2cfc18c9415c912f9d8155881c133215df768a70"

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"

VARIANT_DIRS = {
    "local": "bge-reranker-base-onnx",
    "local_int8": "bge-reranker-base-onnx-int8",
}
ONNX_FILENAME = {
    "local": "model.onnx",
    "local_int8": "model_quantized.onnx",
}
# 토크나이저까지 있어야 <돌릴 수 있는> 산출물이다. onnx 파일만 보면
# 변환이 중간에 죽은 상태를 완성으로 착각한다.
_REQUIRED_EXTRA = ("tokenizer.json", "tokenizer_config.json")

# 등가 검증에 쓰는 입력쌍. 실제 이 제품이 던지는 모양(한국어 질문 + 사규 조각)으로 골랐다.
# 맞는 쌍과 틀린 쌍을 섞어 점수 범위 양쪽을 다 태운다.
_VERIFY_PAIRS = [
    ("정규직의 연차 휴가는 며칠인가요?", "제20조(연차유급휴가) 정규직 사원에게 연 15일의 연차유급휴가를 부여한다."),
    ("정규직의 연차 휴가는 며칠인가요?", "제4조(사내식당) 중식은 11시 30분부터 13시까지 제공한다."),
    ("업무용 컴퓨터 교체 주기", "제6조(비품) 노트북은 3년마다 교체하는 것을 원칙으로 한다."),
    ("사내 헬스장이 있나요?", "제12조(출장) 국내 출장비는 실비로 정산한다."),
]
# fp32 ONNX 와 PyTorch 원본의 로짓 차이 허용오차. 같은 연산을 다른 런타임으로 돌린
# 부동소수 오차 수준이면 1e-4 를 넘지 않는다. 넘으면 변환이 틀어진 것이다.
VERIFY_ATOL = 1e-4


def variant_dir(variant: str, models_dir: Path | None = None) -> Path:
    """변형 이름 → 산출물 디렉터리."""
    if variant not in VARIANT_DIRS:
        raise ValueError(f"모르는 리랭커 변형입니다: {variant}")
    return (models_dir or MODELS_DIR) / VARIANT_DIRS[variant]


def artifact_status(models_dir: Path | None = None) -> dict[str, bool]:
    """변형별로 <돌릴 수 있는 산출물이 다 있는가>. 디렉터리 존재만 보지 않는다."""
    out: dict[str, bool] = {}
    for variant in VARIANT_DIRS:
        d = variant_dir(variant, models_dir)
        needed = [ONNX_FILENAME[variant], *_REQUIRED_EXTRA]
        out[variant] = all((d / name).is_file() for name in needed)
    return out


def missing_message(variant: str) -> str:
    """모델이 없을 때 나가는 안내. <무엇을 어떻게 하면 되는지> 까지 적는다."""
    return (
        f"로컬 리랭커 모델({variant})이 없습니다. "
        f"ai-service 에서 `.venv/bin/pip install -r requirements-lab.txt` 로 실험 의존성을 설치한 뒤 "
        f"`.venv/bin/python -m app.export_reranker` 를 한 번 돌려 모델을 준비해주세요. "
        f"(운영 이미지에는 이 의존성이 없습니다. 기본값 reranker_provider=cloudflare 로 두세요.)"
    )


def _onnx_logits(onnx_path: Path, tokenizer_dir: Path) -> "list[float]":
    """ONNX Runtime 으로 _VERIFY_PAIRS 의 로짓을 뽑는다."""
    import numpy as np  # noqa: PLC0415 - 늦은 import 가 의도다
    import onnxruntime as ort  # noqa: PLC0415
    from transformers import AutoTokenizer  # noqa: PLC0415

    tok = AutoTokenizer.from_pretrained(tokenizer_dir)
    enc = tok(
        [q for q, _ in _VERIFY_PAIRS],
        [p for _, p in _VERIFY_PAIRS],
        padding=True,
        truncation=True,
        max_length=512,
        return_tensors="np",
    )
    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    # 모델마다 받는 입력 이름이 다르다(token_type_ids 가 없는 것도 있다). 세션이
    # 실제로 요구하는 이름만 골라 넣는다.
    wanted = {i.name for i in sess.get_inputs()}
    feed = {k: v.astype(np.int64) for k, v in enc.items() if k in wanted}
    logits = sess.run(None, feed)[0]
    return [float(x) for x in np.asarray(logits).reshape(-1)]


def _torch_logits(tokenizer_dir: Path) -> "list[float]":
    """PyTorch 원본으로 같은 입력의 로짓을 뽑는다. 이것이 비교의 기준선이다."""
    import torch  # noqa: PLC0415
    from transformers import AutoModelForSequenceClassification, AutoTokenizer  # noqa: PLC0415

    tok = AutoTokenizer.from_pretrained(tokenizer_dir)
    model = AutoModelForSequenceClassification.from_pretrained(REPO_ID, revision=REVISION)
    model.eval()
    enc = tok(
        [q for q, _ in _VERIFY_PAIRS],
        [p for _, p in _VERIFY_PAIRS],
        padding=True,
        truncation=True,
        max_length=512,
        return_tensors="pt",
    )
    with torch.no_grad():
        logits = model(**enc).logits
    return [float(x) for x in logits.reshape(-1)]


def _verify_equivalence(fp32_dir: Path, int8_dir: Path) -> None:
    """내보낸 ONNX 가 PyTorch 원본과 같은 출력을 내는지 확인한다.

    fp32 는 <같아야 한다>(허용오차 VERIFY_ATOL). 어긋나면 변환이 틀어진 것이므로
    여기서 멈춘다. 측정을 시작한 뒤에 알면 A·B·C 어느 것도 해석할 수 없다.

    INT8 은 <달라지는 것이 정상>이다(그게 양자화다). 그래서 기준선을 걸지 않고
    실제 차이값만 찍는다. 이 숫자 자체가 C 설정의 해석 재료다.
    """
    import numpy as np  # noqa: PLC0415

    ref = np.asarray(_torch_logits(fp32_dir))
    fp32 = np.asarray(_onnx_logits(fp32_dir / ONNX_FILENAME["local"], fp32_dir))
    int8 = np.asarray(_onnx_logits(int8_dir / ONNX_FILENAME["local_int8"], int8_dir))

    fp32_diff = float(np.max(np.abs(fp32 - ref)))
    int8_diff = float(np.max(np.abs(int8 - ref)))

    print(f"   PyTorch  로짓: {np.round(ref, 4).tolist()}")
    print(f"   ONNX fp32 로짓: {np.round(fp32, 4).tolist()}  (최대 오차 {fp32_diff:.3e})")
    print(f"   ONNX INT8 로짓: {np.round(int8, 4).tolist()}  (최대 오차 {int8_diff:.3e})")

    if fp32_diff > VERIFY_ATOL:
        raise SystemExit(
            f"내보낸 fp32 ONNX 가 PyTorch 원본과 다릅니다(최대 오차 {fp32_diff:.3e} > "
            f"{VERIFY_ATOL:.0e}). 변환이 틀어진 것이므로 이 산출물로 측정하면 안 됩니다. "
            f"ai-service/models/ 를 지우고 `.venv/bin/python -m app.export_reranker` 를 "
            f"다시 돌려주세요. 그래도 같으면 requirements-lab.txt 의 버전 조합을 의심할 것."
        )
    # 순위가 뒤집혔는지도 본다. 리랭커가 하는 일은 <순서를 정하는 것>이라
    # 로짓이 조금 달라도 순서가 같으면 실무상 같은 동작이다.
    print(
        f"   순위 일치: fp32 {np.argsort(-fp32).tolist() == np.argsort(-ref).tolist()} · "
        f"INT8 {np.argsort(-int8).tolist() == np.argsort(-ref).tolist()}"
    )


def _pre_process(src: Path, dst: Path) -> None:
    """양자화 <전처리>. ONNX Runtime 공식 권장 경로다.

    하는 일은 셋이다: 심볼릭 shape 추론 · ONNX 자체 shape 추론 · 그래프 최적화.
    건너뛰면 양자화기가 텐서 모양을 몰라 융합하지 못하는 자리가 생기고, 그만큼
    정확도가 <필요 이상으로> 떨어진다. 즉 나중에 C(INT8)가 나빠 보일 때 그 원인이
    "양자화 자체" 인지 "전처리를 안 해서" 인지 구분할 수 없게 된다.

    ⚠️ 이 모델에서는 심볼릭 추론이 실패한다. position_ids 쪽에 Min(514, sequence_length)
       와 sequence_length 를 브로드캐스트하는 자리가 있는데 추론기가 그 조합을 모른다
       ("unsupported broadcast between Min(514, sequence_length) sequence_length").
       그래서 실패하면 그 단계만 끄고 나머지 둘로 다시 돌린다.
       🔴 조용히 건너뛰지 않고 <어느 경로로 돌았는지를 찍는다.> 전처리가 온전히 돈 것과
          한 단계 빠진 것은 다른 사실이고, 뭉개면 INT8 결과를 해석할 수 없다.
    """
    from onnxruntime.quantization.shape_inference import quant_pre_process  # noqa: PLC0415

    src, dst = src.resolve(), dst.resolve()
    # ⚠️ quant_pre_process 는 중간 산출물(sym_shape_infer_temp.onnx 와 1GB 짜리 .data)을
    #    <현재 작업 디렉터리에> 떨어뜨린다. 그대로 두면 ai-service/ 에 2GB 가 쌓이고
    #    git status 에 잡힌다(실제로 한 번 겪었다). 임시 디렉터리 안에서 돌려 같이 지운다.
    with TemporaryDirectory() as scratch, contextlib.chdir(scratch):
        try:
            quant_pre_process(
                input_model_path=str(src), output_model_path=str(dst), skip_symbolic_shape=False
            )
            print("   전처리: 심볼릭 shape 추론 + 그래프 최적화 (전체 경로)")
        except Exception as exc:  # noqa: BLE001 - 어떤 실패든 후퇴 경로가 같다
            print(f"   ⚠️ 심볼릭 shape 추론 실패({exc}). 그 단계만 끄고 나머지로 전처리한다.")
            quant_pre_process(
                input_model_path=str(src), output_model_path=str(dst), skip_symbolic_shape=True
            )
            print("   전처리: ONNX shape 추론 + 그래프 최적화 (심볼릭 단계 제외)")


def export() -> None:
    """내려받기 → ONNX 변환 → 등가 검증 → INT8 양자화. 무거운 import 는 전부 여기 안에 있다."""
    from optimum.onnxruntime import (  # noqa: PLC0415 - 늦은 import 가 의도다
        AutoQuantizationConfig,
        ORTModelForSequenceClassification,
        ORTQuantizer,
    )
    from transformers import AutoTokenizer  # noqa: PLC0415

    fp32_dir = variant_dir("local")
    int8_dir = variant_dir("local_int8")
    fp32_dir.mkdir(parents=True, exist_ok=True)
    int8_dir.mkdir(parents=True, exist_ok=True)

    print(f"① 내려받기 + ONNX 변환: {REPO_ID}@{REVISION[:8]}")
    model = ORTModelForSequenceClassification.from_pretrained(
        REPO_ID, revision=REVISION, export=True
    )
    model.save_pretrained(fp32_dir)
    AutoTokenizer.from_pretrained(REPO_ID, revision=REVISION).save_pretrained(fp32_dir)

    print("② 동적 INT8 양자화")
    # 🔴 quantize 앞에 quant_pre_process 를 둔다(ONNX Runtime 공식 권장 경로).
    #    하는 일은 심볼릭 shape 추론 + 그래프 최적화다. 이걸 건너뛰면 양자화기가
    #    텐서 모양을 몰라 융합하지 못하는 자리가 생기고, 그만큼 정확도가
    #    <필요 이상으로> 떨어진다. 즉 나중에 C 가 나빠 보일 때 그 원인이
    #    "양자화 자체" 인지 "전처리를 안 해서" 인지 구분할 수 없게 된다.
    #
    # ⚠️ 전처리 결과를 fp32_dir 에 덮어쓰지 않고 별도 임시 디렉터리에 만든다.
    #    fp32_dir 은 B(로컬 원본) 설정이 그대로 쓰는 산출물이라, 최적화된 그래프로
    #    바꿔버리면 B 가 <원본이 아니게> 된다. 변수를 하나만 바꾸려는 것이 이 실험의 전부다.
    with TemporaryDirectory() as tmp:
        prep_dir = Path(tmp) / "prep"
        shutil.copytree(fp32_dir, prep_dir)
        _pre_process(fp32_dir / ONNX_FILENAME["local"], prep_dir / ONNX_FILENAME["local"])
        quantizer = ORTQuantizer.from_pretrained(prep_dir)
        # avx512_vnni 는 x86 가속 힌트일 뿐이고, 양자화된 가중치 자체는 어느 CPU 에서도 돈다.
        # ⚠️ 그래서 <속도>는 아키텍처마다 다르다. M4 Pro(ARM)에서 잰 속도를 EC2(x86_64)의
        #    속도라고 말하면 안 된다(설계문서 §5).
        qconfig = AutoQuantizationConfig.avx512_vnni(is_static=False, per_channel=False)
        quantizer.quantize(save_dir=int8_dir, quantization_config=qconfig)
    AutoTokenizer.from_pretrained(REPO_ID, revision=REVISION).save_pretrained(int8_dir)

    print("③ 등가 검증 (내보낸 ONNX 가 PyTorch 원본과 같은 출력을 내는가)")
    _verify_equivalence(fp32_dir, int8_dir)


def _report() -> None:
    for variant, ok in artifact_status().items():
        d = variant_dir(variant)
        if not ok:
            print(f"❌ {variant}: 산출물이 완전하지 않다 ({d})")
            continue
        onnx = d / ONNX_FILENAME[variant]
        print(f"✅ {variant}: {onnx} ({onnx.stat().st_size / 1024 / 1024:.1f} MB)")


def main() -> None:
    if REVISION.strip("0") == "":
        print(
            "REVISION 이 비어 있습니다. 아래로 실제 커밋 해시를 얻어 "
            "app/export_reranker.py 의 REVISION 에 박아주세요.\n"
            '  .venv/bin/python -c "from huggingface_hub import HfApi; '
            f"print(HfApi().model_info('{REPO_ID}').sha)\"",
            file=sys.stderr,
        )
        raise SystemExit(1)
    export()
    _report()


if __name__ == "__main__":
    main()
