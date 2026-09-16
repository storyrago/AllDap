"""로컬 리랭커의 <계약> 점검. 모델도 onnxruntime 도 필요 없다.

CI 에서 도는 점검이다. 그래서 진짜 추론은 여기서 하지 않는다
(진짜 모델로 돌리는 것은 app/local_reranker_e2e_check.py 이고 사람이 손으로 돌린다).

여기서 보는 것은 다섯이다.
  ① 출력이 Cloudflare 와 <같은 모양> 인가. 다르면 retriever._rerank 가 조용히 망가진다
  ② 점수 내림차순이고 입력 인덱스를 하나도 잃지 않는가
  ③ 모델이 없을 때 <조용히 넘어가지 않고> 한국어 오류를 내는가
  ④ 모듈 최상단에서 onnxruntime 을 import 하지 않는가 (하면 운영 이미지와 CI 가 죽는다)
  ⑤ 그 오류가 <HTTP 응답으로도> 한국어 안내와 code 를 싣고 나가는가
"""
from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from . import local_reranker
from .export_reranker import artifact_status
from .local_reranker import ModelUnavailable, _to_response


def check_response_shape_matches_cloudflare() -> None:
    """Cloudflare 응답과 같은 모양이어야 한다.

    {"response": [{"id": <입력 인덱스>, "score": float}, ...]}  점수 내림차순.
    이 계약이 맞으면 retriever._rerank 의 나머지 로직을 한 줄도 안 고쳐도 된다.
    """
    out = _to_response([0.1, 0.9, 0.5])
    assert set(out) == {"response"}, out
    assert [item["id"] for item in out["response"]] == [1, 2, 0], out
    assert all(isinstance(item["score"], float) for item in out["response"]), out


def check_scores_are_descending() -> None:
    scores = [item["score"] for item in _to_response([-3.0, 2.0, 0.0, 7.5])["response"]]
    assert scores == sorted(scores, reverse=True), scores


def check_every_input_index_survives() -> None:
    """입력 인덱스가 하나도 사라지면 안 된다.

    _rerank 가 빠진 인덱스를 뒤에 붙여 보전하긴 하지만, 제공자가 <잃어버리는 것> 자체가
    버그다. 잃으면 "리랭커가 아래로 내렸다" 와 "제공자가 빠뜨렸다" 가 뭉개진다.
    """
    ids = sorted(item["id"] for item in _to_response([1.0] * 5)["response"])
    assert ids == [0, 1, 2, 3, 4], ids


def check_empty_input_is_empty_response() -> None:
    assert _to_response([]) == {"response": []}


def check_missing_model_raises_korean_error() -> None:
    """🔴 조용히 Cloudflare 로 떨어지지 않는다. 떨어지면 <무엇을 쟀는지> 를 잃는다."""
    with TemporaryDirectory() as tmp:
        try:
            local_reranker.preflight("local_int8", models_dir=Path(tmp))
        except ModelUnavailable as e:
            assert "app.export_reranker" in str(e), str(e)
            assert "requirements-lab.txt" in str(e), str(e)
        else:
            raise AssertionError("모델이 없는데 preflight 가 통과했다")


def check_rerank_without_model_raises_too() -> None:
    """🔴 rerank() 도 같은 자리에서 막혀야 한다.

    preflight 만 막고 rerank 가 다른 경로로 새면, 평가는 거절하는데 실제 호출은
    엉뚱한 예외(ImportError · FileNotFoundError)로 터진다. 그러면 부르는 쪽이
    "모델이 없다" 와 "런타임이 고장났다" 를 구분하지 못한다.
    빈 입력이 그보다 <먼저> 걸린다는 것도 같이 못박는다(모델 없이도 {"response": []}).
    """
    assert local_reranker.rerank("질문", [], variant="local_int8") == {"response": []}

    if artifact_status().get("local_int8", False):
        # 🔴 이 컴퓨터에 진짜 모델이 있으면 여기서 <실제로 모델을 로드하게> 된다.
        #    점검이 느려질 뿐 아니라 onnxruntime 이 올라와 위 ④ 항목의 전제가 흐려진다.
        #    건너뛰되 <건너뛰었다는 사실을 찍는다> - 조용히 통과하면 "통과했다" 와
        #    "안 재봤다" 가 뭉개진다. 판정이 나는 곳은 깨끗한 환경(CI · 임시 venv)이다.
        print("   ⏭  이 컴퓨터에는 산출물이 있어 모델 없음 경로를 못 태운다(깨끗한 환경에서 판정)")
        return
    try:
        local_reranker.rerank("질문", ["본문"], variant="local_int8")
    except ModelUnavailable:
        pass
    except ImportError as e:
        raise AssertionError(f"ModelUnavailable 이 아니라 ImportError 가 샜다: {e}") from e
    else:
        raise AssertionError("모델이 없는데 rerank 가 통과했다")


def check_eval_run_rejection_reaches_http_as_korean_error() -> None:
    """🔴 거절이 <밖으로 나갈 때도> 한국어 안내여야 한다.

    2026-09-16 실측에서 여기가 뚫려 있었다: create_run 은 제대로 거절하는데
    ModelUnavailable 을 HTTP 계층에서 잡는 곳이 없어 맨 500 평문이 나갔고,
    "무엇을 어떻게" 는 서버 로그에만 남았다. 즉 <거절한다> 와 <거절을 설명한다> 가
    서로 다른 사실인데 앞쪽만 검사가 있었다.

    왜 create_run 을 가짜로 바꾸는가
    ─────────────────────────────────────────────────────────────────────────
    진짜 경로를 태우려면 로컬 제공자 설정 + 산출물 없는 models 디렉터리가 필요한데,
    models 디렉터리 위치를 이 경로로는 주입할 수 없고(설정이 아니라 모듈 상수다)
    이 컴퓨터에 진짜 산출물이 있으면 거절이 아예 안 난다. 여기서 못박는 계약은
    "ModelUnavailable 이 올라오면 main 이 어떤 응답으로 바꾸는가" 하나다.
    DB 도 모델도 onnxruntime 도 필요 없다.
    """
    from fastapi.testclient import TestClient  # noqa: PLC0415 - 점검 안에서만 필요하다

    from . import evalrun, main  # noqa: PLC0415
    from .export_reranker import missing_message  # noqa: PLC0415

    def boom(_bot_id):
        raise ModelUnavailable(missing_message("local_int8"))

    original = evalrun.create_run
    evalrun.create_run = boom
    try:
        # ⚠️ with 로 감싸지 않는다. TestClient 의 컨텍스트 진입이 lifespan 을 돌려
        #    DB 풀을 여는데, 이 점검은 DB 없이 돌아야 한다.
        res = TestClient(main.app).post("/internal/bots/1/eval/runs")
    finally:
        evalrun.create_run = original

    assert res.status_code == 503, res.status_code
    detail = res.json()["detail"]
    assert detail["code"] == "RERANKER_MODEL_UNAVAILABLE", detail
    # 맨 500 평문이었을 때 빠져 있던 바로 그것: <무엇을 어떻게 하면 되는지>.
    assert "requirements-lab.txt" in detail["message"], detail
    assert "app.export_reranker" in detail["message"], detail
    # 🔴 재시도로 안 풀리는 실패에 "잠시 후 다시 시도" 라고 안내하지 않는다
    #    (ANSWER_INCOMPLETE · BILLING_METHOD_UNREADABLE 이 세운 원칙이다).
    assert "잠시 후" not in detail["message"], detail


def check_latency_percentiles_shape_matches_cf() -> None:
    """🔴 cf.latency_percentiles() 와 <키가 같아야> 비교가 성립한다.

    한쪽에만 있는 키가 있으면 표를 만들 때 그 칸이 비고, 비어 있는 칸은
    "안 쟀다" 와 "0 이다" 를 뭉갠다. cf 를 import 해 키 집합을 직접 대조한다.
    """
    from . import cf  # noqa: PLC0415 - 점검 안에서만 필요하다

    local_reranker._record_latency("local_int8", 12.5)
    mine = local_reranker.latency_percentiles()["local_int8"]

    cf._record_latency("_check_only", 12.5)
    theirs = cf.latency_percentiles()["_check_only"]
    cf._latencies.pop("_check_only", None)
    cf._call_counts.pop("_check_only", None)

    assert set(mine) == set(theirs), f"{sorted(mine)} != {sorted(theirs)}"
    assert mine["count"] == 1 and mine["latency_window"] == 1, mine
    assert mine["p50"] == mine["p95"] == mine["p99"] == 12.5, mine

    local_reranker._latencies.pop("local_int8", None)
    local_reranker._call_counts.pop("local_int8", None)


def check_max_rss_is_plausible() -> None:
    """🔴 단위가 OS 마다 다르다(macOS 바이트 · 리눅스 킬로바이트).

    나누는 수를 하나로 두면 1024배 틀린 값이 조용히 표에 실린다. 파이썬 인터프리터
    하나가 10MB 미만일 수도, 20GB 일 수도 없으므로 그 사이인지만 본다.
    """
    rss = local_reranker.max_rss_mb()
    assert 10.0 < rss < 20000.0, f"단위 환산이 틀린 것 같다: {rss} MB"


def check_onnxruntime_is_not_imported_at_module_load() -> None:
    """🔴 무거운 의존성은 <함수 안에서> 늦게 import 한다.

    모듈 최상단에서 import 하면 requirements.txt 만 깔린 CI 와 운영 이미지가
    이 파일을 import 하는 순간 죽는다.
    """
    assert "onnxruntime" not in sys.modules, "import 만 했는데 onnxruntime 이 올라왔다"
    assert "torch" not in sys.modules, "import 만 했는데 torch 가 올라왔다"


def main() -> None:
    checks = [
        # 🔴 맨 앞이어야 한다. 뒤에 두면 앞선 항목이 올린 모듈을 보고 판정하게 된다.
        check_onnxruntime_is_not_imported_at_module_load,
        check_response_shape_matches_cloudflare,
        check_scores_are_descending,
        check_every_input_index_survives,
        check_empty_input_is_empty_response,
        check_missing_model_raises_korean_error,
        check_rerank_without_model_raises_too,
        check_eval_run_rejection_reaches_http_as_korean_error,
        check_latency_percentiles_shape_matches_cf,
        check_max_rss_is_plausible,
    ]
    for fn in checks:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(checks)}가지 전부 통과.")


if __name__ == "__main__":
    main()
