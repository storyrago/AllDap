"""리랭커를 <이 컴퓨터에서> 돌리는 제공자 파일 (ONNX Runtime).

왜 별도 파일인가
─────────────────────────────────────────────────────────────────────────────
friendli.py 가 세워둔 규칙 그대로다. `cf.py` 는 <Cloudflare 를 어떻게 부르는가>만
아는 파일이고, 거기에 두 번째 제공자를 끼워 넣으면 "어느 분기가 어느 제공자였더라" 가
시작된다. 제공자마다 파일을 하나씩 두고, 부르는 쪽이 고른다.

출력 계약을 Cloudflare 와 <똑같이> 맞춘다
─────────────────────────────────────────────────────────────────────────────
    {"response": [{"id": <입력 인덱스>, "score": float}, ...]}   점수 내림차순

이 모양은 추측이 아니라 retriever._rerank 가 실제로 읽는 모양이다
(`order = [item["id"] for item in result["response"]]`). 지키면 _rerank 의 나머지
로직(실패 시 원래 순서 유지 · 빠진 인덱스 보전 · rerank_fusion)을 한 줄도 안 고쳐도 된다.

⚠️ 실패 모드가 Cloudflare 와 다르다
─────────────────────────────────────────────────────────────────────────────
Cloudflare 는 네트워크와 HTTP 오류뿐이지만 여기는 모델 파일 없음 · 의존성 없음 ·
메모리 부족 · 스레드 고갈이 있다. <새 실패 모드가 느는 것>이므로 부르는 쪽(_rerank)의
try/except 를 넓게 잡는다. 리랭커는 순서를 개선하는 부가 기능이고,
리랭커가 죽었다고 채팅이 죽으면 안 된다.

🔴 그러나 <조용히 Cloudflare 로 떨어지지는 않는다.> 로컬을 골랐는데 결과가 Cloudflare
   것이면 "무엇을 쟀는지" 를 잃는다. 그래서 평가는 preflight() 로 <시작 전에> 거절하고,
   운영 경로(채팅)만 벡터 순서로 살아남는다. 둘은 모순이 아니라 역할이 다른 것이다.

⚠️ onnxruntime · transformers 는 requirements-lab.txt 에만 있다. 그래서 import 를
   전부 함수 안에 둔다. 모듈 최상단에 두면 운영 이미지와 CI 가 import 하는 순간 죽는다.
   (export_reranker.py 가 세운 패턴 그대로다)
"""
from __future__ import annotations

import resource
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any

from .export_reranker import ONNX_FILENAME, artifact_status, missing_message, variant_dir

# 한 번에 넘기는 최대 토큰 수. bge-reranker-base 의 학습 길이가 512 다.
MAX_LENGTH = 512


class ModelUnavailable(RuntimeError):
    """모델 산출물이 없거나 실험 의존성이 안 깔린 상태."""


def preflight(variant: str, models_dir: Path | None = None) -> Path:
    """산출물이 <돌릴 수 있는 상태로> 있는지 확인하고 디렉터리를 돌려준다.

    없으면 ModelUnavailable 이다. 표식(None)이 아니라 예외인 이유는,
    분기를 빠뜨린 호출부가 조용히 지나가지 못하게 하려는 것이다
    (metrics 의 MetricUnreadable 과 같은 판단이다).
    """
    if not artifact_status(models_dir).get(variant, False):
        raise ModelUnavailable(missing_message(variant))
    return variant_dir(variant, models_dir)


def _to_response(scores: list[float]) -> dict:
    """점수 목록을 Cloudflare 와 같은 모양으로 바꾼다. 인덱스는 하나도 버리지 않는다."""
    ranked = sorted(enumerate(scores), key=lambda pair: pair[1], reverse=True)
    return {"response": [{"id": i, "score": float(s)} for i, s in ranked]}


# 변형별로 세션과 토크나이저를 한 번만 만든다. 매 호출 로드하면 큰 파일을 질문마다
# 다시 읽어 <측정이 로딩 시간을 재게> 된다.
_sessions: dict[str, tuple[Any, Any]] = {}


def _session(variant: str) -> tuple[Any, Any]:
    if variant in _sessions:
        return _sessions[variant]

    model_dir = preflight(variant)
    try:
        import onnxruntime as ort  # noqa: PLC0415 - 늦은 import 가 의도다
        from transformers import AutoTokenizer  # noqa: PLC0415
    except ImportError as e:
        # 의존성이 없는 것도 "이 제공자를 쓸 수 없다" 는 같은 사실이다.
        # 다만 안내 문구가 설치 방법을 담고 있어야 한다(missing_message 가 담고 있다).
        raise ModelUnavailable(missing_message(variant)) from e

    session = ort.InferenceSession(
        str(model_dir / ONNX_FILENAME[variant]),
        providers=["CPUExecutionProvider"],
    )
    tokenizer = AutoTokenizer.from_pretrained(str(model_dir))
    _sessions[variant] = (session, tokenizer)
    return _sessions[variant]


def rerank(query: str, texts: list[str], *, variant: str) -> dict:
    """(질문, 청크) 쌍마다 점수를 매겨 Cloudflare 와 같은 모양으로 돌려준다.

    ⚠️ texts 는 preview(앞 200자)가 아니라 <전체 본문>이어야 한다.
       덜 보여주고 "못 맞힌다" 고 판정하면 그건 모델이 아니라 우리 잘못이다
       (retriever._rerank 주석의 교훈).
    """
    if not texts:
        # 모델을 건드리기 <전에> 돌려준다. 빈 입력은 모델이 없어도 답이 정해져 있고,
        # 여기서 1GB 를 로드하면 그 자체가 낭비다.
        return {"response": []}

    session, tokenizer = _session(variant)
    started = time.perf_counter()
    encoded = tokenizer(
        [query] * len(texts),
        texts,
        padding=True,
        truncation=True,
        max_length=MAX_LENGTH,
        return_tensors="np",
    )
    # 모델이 실제로 받는 입력 이름만 넘긴다. token_type_ids 가 없는 그래프도 있다.
    # dtype 을 못박는 이유: 토크나이저가 int32 를 주면 ONNX 그래프가 int64 를 요구해
    # 런타임에서 터진다. export_reranker._onnx_logits 도 같은 이유로 못박는다.
    wanted = {i.name for i in session.get_inputs()}
    feed = {k: v.astype("int64") for k, v in encoded.items() if k in wanted}
    logits = session.run(None, feed)[0]
    _record_latency(variant, (time.perf_counter() - started) * 1000)

    # 교차 인코더라 출력이 (N, 1) 이다. 첫 열이 관련성 점수다.
    return _to_response([float(row[0]) for row in logits])


# ── 지연 계측 (cf._record_latency 와 같은 모양을 일부러 맞춘다) ──────────
#
# 같은 모양으로 두는 이유: A(Cloudflare)와 B·C(로컬)의 지연을 <같은 방식으로> 읽어야
# 비교가 성립한다. 한쪽은 p50, 한쪽은 평균이면 표가 거짓말을 한다.
# 키 집합이 어긋나는 것도 같은 부류라, local_reranker_check 가 cf 와 직접 대조한다.
# ⚠️ 스레드 안전하지 않다. cf.py 와 같은 한계이고 같은 이유로 괜찮다(측정용 근사치).
_LATENCY_WINDOW = 2000
_latencies: dict[str, deque[float]] = {}
_call_counts: dict[str, int] = {}


def _record_latency(variant: str, ms: float) -> None:
    if variant not in _latencies:
        _latencies[variant] = deque(maxlen=_LATENCY_WINDOW)
    _latencies[variant].append(ms)
    _call_counts[variant] = _call_counts.get(variant, 0) + 1


def latency_percentiles() -> dict[str, dict[str, float]]:
    """변형별 호출 수와 p50/p95/p99(ms). 평균은 주지 않는다(느린 꼬리를 감춘다).

    🔴 `count` 는 프로세스가 뜬 뒤의 <전체 호출 수>이고 `latency_window` 는 그중
       백분위에 실제로 쓰인 최근 건수다. cf.latency_percentiles 와 키가 같다.
    """
    out: dict[str, dict[str, float]] = {}
    for variant, values in _latencies.items():
        ordered = sorted(values)

        def pct(p: float, ordered: list[float] = ordered) -> float:
            # nearest-rank. cf.latency_percentiles 와 같은 식이어야 비교가 성립한다.
            idx = max(0, min(len(ordered) - 1, int(-(-len(ordered) * p // 100)) - 1))
            return ordered[idx]

        out[variant] = {
            "count": _call_counts.get(variant, len(ordered)),
            "latency_window": len(ordered),
            "latency_window_max": _LATENCY_WINDOW,
            "p50": pct(50),
            "p95": pct(95),
            "p99": pct(99),
        }
    return out


def max_rss_mb() -> float:
    """이 프로세스가 지금까지 쓴 <최대> 상주 메모리(MB).

    🔴 단위가 OS 마다 다르다. macOS 는 바이트, 리눅스는 킬로바이트다.
       나누는 수를 하나로 두면 1024배 틀린 값이 조용히 표에 실린다.
       ("원인이 다른 사실을 같은 값으로 뭉개지 말 것" 과 같은 부류다.)

    ⚠️ 프로세스 전체의 최대치라 <리랭커만의 사용량이 아니다.> t3.micro 판단의
       재료로 쓰되, 이 값으로 "들어간다" 를 주장하지 말 것(설계문서 §5).
    """
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return raw / (1024 * 1024) if sys.platform == "darwin" else raw / 1024
