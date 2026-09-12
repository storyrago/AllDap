"""S2 실행의 <시작 조건>을 파일로 찍고, 실행 뒤 <경로를 진짜 탔는지> 대조한다.

실행:
    # 실행 전: 봇을 고르고 조건을 남긴다. 인쇄된 두 줄을 k6 에 그대로 넘긴다.
    cd ai-service && .venv/bin/python -m loadtest.s2_context before \\
        --run-id 2026-09-10-1
    (계정은 LOADTEST_EMAIL·LOADTEST_PASSWORD 에서 온다. loadtest/account.py 가 먼저다)

    # 실행 후: 가짜 CF 호출 수를 요청 수와 맞춰본다.
    cd ai-service && .venv/bin/python -m loadtest.s2_context after \\
        --run-id 2026-09-10-1 --k6-summary loadtest/results/S2-2026-09-10-1.json

왜 이 파일이 있는가
─────────────────────────────────────────────────────────────────────────────
"그때 뭘로 쟀지" 를 못 답하는 측정은 재현할 수 없고, 재현할 수 없으면 측정이 아니다
(s1_baseline._conditions 와 같은 근거다).

S2 는 여기에 둘을 더 얹는다: <진짜 CF 를 태우고 있지 않은지>(실행 전)와
<경로를 진짜 탔는지>(실행 후).

🔴 실행 전 검사는 환경변수가 아니라 <뉴런>으로 한다. 환경변수는 드라이버 프로세스의
   것이라 요청을 처리하는 uvicorn 이 무엇을 보는지 말해주지 못한다. 가짜 서버는 뉴런을
   0 으로 주고 진짜 Cloudflare 는 호출마다 값을 준다. 그 차이는 <응답에서> 오므로
   uvicorn 을 통과해야만 보인다. 자세한 근거는 judge_fake_cf 주석에 있다.

실행 후 검사가 보는 것은 <경로를 진짜 탔는지>다. k6 가 200 을 받았다는 것만으로는
그 요청이 embed·rerank·generate 를 다 지났는지 알 수 없다. 캐시·조기 반환·설정 착오로
경로를 건너뛰어도 200 은 200 이다. 가짜 CF 의 호출 수를 실행 전후로 빼면 그게 드러난다.

🔴 기대 배수를 상수로 박지 않는다. reranker_enabled 가 켜져 있으면 요청당 3건
   (embed·rerank·generate), 꺼져 있으면 2건이다. 상수로 박으면 설정을 바꾼 날
   <정상 실행이 무효로 판정된다>. 그리고 그건 "경로를 안 탔다" 와 구분이 안 된다.

🔴 시작 조건은 되도록 <대상에게 물어본 값>으로 적는다. 드라이버 프로세스에서 얻은 값은
   요청을 처리하는 uvicorn 이나 가짜 CF 서버가 무엇으로 떠 있는지 말해주지 못한다.
   지금 어느 쪽인지는 이렇게 갈린다:

     대상에게 물어본 것 : bot(Spring) · fake_cf.latency_ms/vector_mode(가짜 서버 /stats)
                          · fake_cf.base_url(uvicorn /internal/debug/cf-config)
                          · warmup_models_called 와 그로부터 나온 expected_cf_calls_per_request
     드라이버에서 얻은 것 : commit(드라이버 체크아웃) · corpus(드라이버의 DATABASE_URL)
                          · settings 블록(드라이버의 app.config)

   드라이버 쪽 셋은 알고 남긴다. commit 은 앱이 자기 버전을 안 내보내고, corpus 는
   uvicorn 의 DB 접속 문자열을 물어볼 자리가 없다. settings 블록은 uvicorn 이 설정을
   내보내지 않아 통째로는 못 가져오지만, <사후 대조를 좌우하는> reranker 여부만은
   워밍업 관측으로 갈음하고 드라이버 값과 어긋나면 중단한다(cmd_before 참고).

⚠️ cf-stats 는 프로세스 시작 뒤 누적이고 리셋 API 가 없다(cf._latencies 주석이 근거를
   적어둔 자리). 여기서는 <전후 차이>만 쓰므로 문제되지 않는다. 백분위는
   _LATENCY_WINDOW=2000 창에 걸리지만 이 스크립트가 쓰는 것은 count 뿐이고,
   count 와 latency_window 는 cf_stats 가 이미 따로 내보낸다(cf.py:144).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import httpx

from .account import env_email, env_password
from .promtext import parse_prom_counter

RESULTS = Path(__file__).parent / "results"

# 사다리. loadtest/s2_breakpoint.js 의 STAGES·HOLD_S 와 같아야 한다.
# 🔴 2026-09-12 에 160 을 더했다. 근거는 s2_breakpoint.js 의 STAGES 주석에 있다
#    (새 천장 예측 47.6 req/s 에 닿으려면 동시 요청 80건이 필요한데, 옛 사다리의
#     마지막 칸이 그 벽과 정확히 겹친다).
STAGES = [1, 5, 10, 20, 40, 80, 160]
HOLD_SECONDS = 120
WARMUP_DISCARD_SECONDS = 20


def _context_path(run_id: str) -> Path:
    return RESULTS / f"S2-{run_id}-context.json"


def _verdict_path(run_id: str) -> Path:
    return RESULTS / f"S2-{run_id}-verdict.json"


def _cf_stats(ai_base: str) -> dict[str, dict]:
    """cf-stats 원본을 그대로 읽는다. 호출 수도 뉴런도 여기서 갈라 쓴다."""
    resp = httpx.get(f"{ai_base}/internal/debug/cf-stats", timeout=30.0)
    resp.raise_for_status()
    return resp.json()


def _counts_of(stats: dict[str, dict]) -> dict[str, int]:
    return {model: int(row.get("count", 0)) for model, row in stats.items()}


def _neurons_of(stats: dict[str, dict]) -> dict[str, float]:
    return {model: float(row.get("neurons", 0.0)) for model, row in stats.items()}


def _cf_counts(ai_base: str) -> dict[str, int]:
    """모델별 <호출 수>만 뽑는다. 사후 대조가 쓴다."""
    return _counts_of(_cf_stats(ai_base))


# 워밍업 질문. 코퍼스 어디에도 없는 낱말로 짓는다.
#
# 🔴 이유는 <진짜 CF 였을 때의 비용>이다. 이 질문은 어떤 청크와도 멀어
#    answerable_max_distance 게이트에 걸리므로, 진짜 CF 를 보고 있었다면 임베딩 1회
#    (약 0.024 뉴런, 하루 한도 10,000 의 0.0002%)에서 멈춘다. 게이트가 어쩌다 통과해
#    생성까지 가더라도 1건은 약 25 뉴런, 0.25% 다. 어느 쪽이든 12분 실행이 날려버리는
#    하루치와는 비교가 안 된다.
#    반대로 가짜 CF 는 <진짜 청크 벡터>를 돌려주므로 거리가 0 이라 게이트를 통과하고
#    embed·rerank·generate 를 다 태운다. 즉 이 한 건으로 세 모델을 한꺼번에 검사한다.
WARMUP_QUESTION = "부하테스트 사전 점검용 질문 zzqq (코퍼스에 없는 말입니다)"


def _called_models(before: dict[str, dict], after: dict[str, dict]) -> dict[str, int]:
    """워밍업 사이에 <실제로 호출이 늘어난> 모델. judge 와 기대 배수 산출이 같이 쓴다."""
    b, a = _counts_of(before), _counts_of(after)
    delta = {m: a.get(m, 0) - b.get(m, 0) for m in set(a) | set(b)}
    return {m: d for m, d in delta.items() if d > 0}


def read_fake_cf_stats(cf_base_url: str) -> dict:
    """<실제로 도는> 가짜 CF 서버에게 자기 설정을 물어본다.

    🔴 여기서 loadtest.fake_cf 의 상수를 import 해 대신하면 안 된다. 그건 드라이버
       프로세스가 읽은 코드일 뿐이라, 다른 지연값으로 떠 있는 서버를 상대로도 그대로
       통과한다. 그러면 시작 조건 파일이 <사실이 아닌 값>을 사실이라고 적는다.
       (같은 부류를 cf_base_url 가드에서 이미 한 번 겪었다. 이 파일 위쪽 주석 참고)

    🔴 못 읽으면 <중단>한다. 되돌아갈 import 값을 쓰지 않는 이유는 그게 고치기 전과
       똑같아지기 때문이고, "못 읽었다" 를 파일에 적고 계속 가지 않는 이유는 12분을
       돌린 뒤에 조건을 모르는 실행이 하나 남을 뿐이기 때문이다. 어차피 버릴 측정이면
       시작하기 전에 멈추는 편이 싸다. judge_fake_cf 의 ①(판정 불가 → 중단)과 같은 판단이다.
    """
    try:
        resp = httpx.get(f"{cf_base_url.rstrip('/')}/stats", timeout=10.0)
        resp.raise_for_status()
        stats = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        raise SystemExit(
            f"중단: 가짜 CF 서버({cf_base_url})의 /stats 를 못 읽었다 ({e}). "
            f"시작 조건을 <추측으로> 적을 바에는 재지 않는다. "
            f"가짜 서버가 그 주소에 떠 있는지 확인하고(cd ai-service && "
            f".venv/bin/python -m loadtest.fake_cf), 그 주소가 맞는지는 "
            f"ai-service 의 /internal/debug/cf-config 로 확인할 것."
        )

    missing = [k for k in ("latency_ms", "vector_mode", "counts") if k not in stats]
    if missing:
        raise SystemExit(
            f"중단: {cf_base_url}/stats 응답에 {missing} 가 없다. 그 주소에 떠 있는 것이 "
            f"loadtest/fake_cf.py 가 맞는지 확인할 것. 다른 서버라면 이 측정의 시작 조건을 "
            f"기록할 수 없다."
        )
    return stats


def _uvicorn_cf_base_url(ai_base: str) -> str:
    """요청을 처리하는 uvicorn 이 <실제로 보는> CF 주소. 드라이버의 환경변수가 아니다."""
    try:
        resp = httpx.get(f"{ai_base}/internal/debug/cf-config", timeout=10.0)
        resp.raise_for_status()
        return str(resp.json()["cf_base_url"])
    except (httpx.HTTPError, ValueError, KeyError) as e:
        raise SystemExit(
            f"중단: {ai_base}/internal/debug/cf-config 를 못 읽었다 ({e}). "
            f"ai-service 가 이 엔드포인트를 가진 버전인지 확인할 것."
        )


def judge_fake_cf(before: dict[str, dict], after: dict[str, dict]) -> tuple[bool, str]:
    """워밍업 전후의 cf-stats 로 <요청을 처리하는 프로세스>가 가짜 CF 를 보는지 판정한다.

    왜 뉴런인가
    ─────────────────────────────────────────────────────────────────────
    가짜 서버는 뉴런을 0 으로 준다(loadtest/fake_cf.py). 진짜 Cloudflare 는 호출마다
    0 이 아닌 값을 준다(cf._record_neurons 의 세 경로 중 하나로 반드시 들어온다).
    그리고 이 숫자는 <드라이버가 아니라 uvicorn 이 실제로 받은 응답>에서 나온다.
    환경변수는 그것을 말해주지 못한다: 드라이버 셸에 가짜 값이 있어도 uvicorn 이 진짜
    Cloudflare 를 보고 있을 수 있고, 그게 위험한 방향의 오탐이다.

    🔴 세 결과를 <세 값으로> 가른다. 뭉치면 원인이 다른 사실이 같은 실패가 된다.
       ① 호출이 안 늘었다  → 판정 불가(가짜라는 뜻이 아니다). 그래도 중단한다,
                             모르는 채로 12분을 돌릴 수는 없다.
       ② 뉴런이 늘었다    → 진짜 CF 다. 중단.
       ③ 호출만 늘었다    → 가짜 CF 다. 진행.
    """
    b_neuron, a_neuron = _neurons_of(before), _neurons_of(after)
    called = _called_models(before, after)
    if not called:
        return False, (
            "중단: 워밍업 요청이 Cloudflare 호출을 하나도 늘리지 않았다. "
            "가짜/진짜를 <판정하지 못한> 것이지 가짜라는 뜻이 아니다. "
            "ai-service 가 그 주소에 떠 있는지, 봇에 임베딩된 청크가 있는지 확인할 것."
        )

    burned = {
        m: round(a_neuron.get(m, 0.0) - b_neuron.get(m, 0.0), 6)
        for m in called
        if a_neuron.get(m, 0.0) - b_neuron.get(m, 0.0) > 0
    }
    if burned:
        return False, (
            f"중단: 요청을 처리하는 ai-service 가 <진짜 Cloudflare> 를 보고 있다. "
            f"워밍업 1건에 뉴런이 늘었다({burned}). 이대로 12분을 돌리면 하루 한도"
            f"(10,000 뉴런)가 날아가고 24~33시간 기다려야 한다. "
            f"가짜 서버를 띄우고(cd ai-service && .venv/bin/python -m loadtest.fake_cf) "
            f"CF_BASE_URL=http://127.0.0.1:9001 로 uvicorn 을 <다시> 띄운 뒤 이 명령을 다시 실행할 것."
        )

    return True, f"OK   가짜 CF 확인: 워밍업 호출 {called}, 뉴런 증가 0"


def _assert_fake_cf(ai_base: str, bot_id: str) -> dict[str, int]:
    """측정을 시작하기 <전에> 실제로 도는 ai-service 를 상대로 확인한다.

    ⚠️ 사후 대조가 아니라 여기여야 한다. 다 돌리고 나서 알아봐야 뉴런은 이미 탔다.

    통과하면 <워밍업 1건이 실제로 부른 모델>을 돌려준다. 기대 배수를 드라이버의
    설정이 아니라 이 관측값에서 뽑기 위해서다(cmd_before 주석 참고).
    """
    before = _cf_stats(ai_base)
    try:
        # ⚠️ 200 이 아니어도 된다. 게이트에 걸리면 fallback(200)이고, 생성이 잘리면 503 이다.
        #    둘 다 CF 호출은 이미 일어났으므로 판정 재료로는 충분하다.
        #    막힌 것은 호출 수가 안 늘어난 경우이고 그건 judge_fake_cf 가 ①로 잡는다.
        httpx.post(
            f"{ai_base}/internal/chat",
            json={"bot_id": bot_id, "message": WARMUP_QUESTION, "session_id": "s2-guard"},
            timeout=120.0,
        )
    except httpx.HTTPError as e:
        raise SystemExit(f"중단: 워밍업 요청이 실패했다 ({e}). ai-service 가 {ai_base} 에 떠 있는가?")

    after = _cf_stats(ai_base)
    ok, message = judge_fake_cf(before, after)
    print(message)
    if not ok:
        raise SystemExit(1)
    return _called_models(before, after)


def _prom(url: str, name: str, labels: dict[str, str] | None = None) -> float | None:
    """Prometheus 노출에서 값 하나. 못 읽으면 None, 값이 NaN·Inf 면 MetricUnreadable."""
    try:
        resp = httpx.get(url, timeout=10.0)
        resp.raise_for_status()
    except httpx.HTTPError:
        return None
    return parse_prom_counter(resp.text, name, labels or {})


def _runtime_snapshot(ai_base: str, spring_metrics: str) -> dict:
    """<측정 대상 프로세스들에게 물어본> 런타임 조건.

    🔴 이 블록이 있는 이유가 이 판의 전부다. 이 판이 재려는 변수는 anyio 스레드 상한
       하나이고, 그 값이 실제로 80 인지를 <설정값>으로 확인하면 아무것도 확인한 것이
       아니다. app/metrics_check.py ⑤ 는 로컬 TestClient 의 lifespan 을 본 것이지
       <요청을 처리하는 uvicorn>을 본 것이 아니다. 그걸 안 가르면
       "80 으로 올리고 쟀다" 가 <틀린 문장으로 리포트에 남는다>.

    🔴 그래서 설정값과 실측값을 <따로> 적는다. 한 칸에 합치면 어긋났다는 사실 자체가
       사라진다. 이 저장소가 여덟 번 낸 부류(원인이 다른 사실을 같은 값으로 뭉개기)를
       미리 막는 자리다.

    Spring 쪽은 힙과 기동 시각을 적는다. 힙은 설계서 §5 가 "OOM 이면 결과, 그 외 사유면
    오염" 으로 가르기로 한 축이고, 그 판정은 <힙이 실제로 제한돼 있었는가> 를 아는
    상태에서만 성립한다(안 씌우면 기가 단위라 "안 말랐다" 가 아무 정보도 아니다).
    """
    py_metrics = f"{ai_base.rstrip('/')}/internal/metrics"
    return {
        "python": {
            "metrics_url": py_metrics,
            # 🔴 이것이 이 판의 유효성 장치 1번이다. 80 이 아니면 그 판은 폐기다.
            "anyio_threads_total_measured": _prom(py_metrics, "alldap_anyio_threads_total"),
            "anyio_threads_borrowed_at_start": _prom(py_metrics, "alldap_anyio_threads_borrowed"),
            # psycopg 풀. before 의 병목 판정에 이 풀은 <아예 후보로 들어 있지 않았다>
            # (후보가 Tomcat · Hikari · anyio 셋뿐이었고, hikaricp_* 는 Spring 의 풀이다).
            # 스레드 80개가 커넥션 10개를 두고 경쟁하므로 이번에는 후보다.
            "db_pool_max_measured": _prom(py_metrics, "alldap_db_pool_max"),
            "db_pool_open_measured": _prom(py_metrics, "alldap_db_pool_open"),
            # ⚠️ timeout·max_waiting 은 지표로 안 나온다. psycopg_pool 기본값이고
            #    app/db.py 가 넘기지 않는다. 값을 <추측해서> 적지 않고 출처를 적는다.
            "db_pool_timeout_seconds": 30,
            "db_pool_max_waiting": 0,
            "db_pool_params_source": (
                "max_size 는 app/db.py:get_pool 이 명시(10). timeout 30초와 "
                "max_waiting 0(무제한)은 psycopg_pool 기본값이며 app/db.py 가 넘기지 않는다. "
                "PR #134 가 <일부러> 안 바꿨다: 한 번에 한 변수."
            ),
        },
        "spring": {
            "metrics_url": spring_metrics,
            "heap_max_bytes": _prom(spring_metrics, "jvm_memory_max_bytes",
                                    {"area": "heap", "id": "G1 Old Gen"}),
            "process_start_time_seconds": _prom(spring_metrics, "process_start_time_seconds"),
            "tomcat_max_threads": _prom(spring_metrics, "tomcat_threads_config_max_threads",
                                        {"name": "http-nio-8080"}),
            "circuit_state_at_start": _prom(spring_metrics, "alldap_ai_circuit_state"),
            "jvm_args": _spring_jvm_args(),
        },
    }


def _spring_jvm_args() -> list[str] | None:
    """도는 Spring 프로세스의 JVM 플래그. ps 로 실제 명령줄을 읽는다.

    🔴 build.gradle 을 읽어서 적으면 안 된다. -Ploadtest 는 옵트인이라, 플래그 없이 띄운
       프로세스를 상대로도 "붙어 있다" 고 적게 된다. 실제로 파도 2 가 그 상태였다
       (로컬 bootRun 에 -XX:+ExitOnOutOfMemoryError 가 없었다).
       그 플래그가 없으면 설계서 §5 의 "OOM 이면 결과, 그 외 사유면 오염" 규칙이
       <성립하지 않는다> - 힙이 말라도 JVM 이 안 죽으니 가를 사건 자체가 안 생긴다.

    None 은 "못 읽었다" 다. 빈 목록("플래그가 없다")과 다른 사실이라 섞지 않는다.
    """
    try:
        out = subprocess.run(["pgrep", "-f", "com.alldap.api.ApiApplication"],
                             capture_output=True, text=True, timeout=10)
        pids = [x for x in out.stdout.split() if x.isdigit()]
        if not pids:
            return None
        cmd = subprocess.run(["ps", "-o", "command=", "-p", pids[0]],
                             capture_output=True, text=True, timeout=10).stdout
    except (subprocess.SubprocessError, OSError):
        return None
    if not cmd.strip():
        return None
    return [tok for tok in cmd.split() if tok.startswith("-X") or tok.startswith("-D")]


def _pick_bot(bots: list[dict]) -> dict:
    """봇을 <규칙으로> 고른다. 사람이 고르면 다음 실행에서 다른 봇을 고를 수 있다.

    🔴 문서가 가장 많은 봇을 쓴다. 부하테스트가 재려는 것은 <실제 코퍼스를 가진 봇>의
       검색·생성 경로이고, 문서 0건 봇을 고르면 게이트에서 막혀 전부 fallback 이 난다.
       동점이면 먼저 만들어진 쪽: 규칙에 임의성이 남으면 재현이 안 된다.
    """
    if not bots:
        raise SystemExit("중단: 이 계정에 봇이 없다.")
    return sorted(bots, key=lambda b: (-b["documentCount"], b["createdAt"]))[0]


def _corpus(bot_id: str) -> dict:
    """코퍼스 크기. API 가 아니라 DB 에서 직접 센다. 청크 수는 API 가 안 준다."""
    from app.db import cursor

    with cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM documents WHERE bot_id=%s AND status='ready'", (bot_id,)
        )
        docs = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM chunks WHERE bot_id=%s", (bot_id,))
        chunks = cur.fetchone()[0]
    return {"documents_ready": docs, "chunks": chunks}


def _settings_snapshot() -> dict:
    from app.config import get_settings

    s = get_settings()
    return {
        "reranker_enabled": s.reranker_enabled,
        "hybrid_enabled": s.hybrid_enabled,
        "answerable_max_distance": s.answerable_max_distance,
        "max_distance": s.max_distance,
        "top_k": s.top_k,
        "chat_model": s.chat_model,
        "embedding_model": s.embedding_model,
        "reranker_model": s.reranker_model,
        # 🔴 <드라이버 셸이 읽은 설정값>이다. 실측값은 runtime.python 에 따로 있다.
        #    두 칸인 것이 요점이다: 어긋나면 그 판은 80 을 잰 것이 아니다.
        "anyio_max_threads": s.anyio_max_threads,
        # 🔴 이 값들은 <드라이버 프로세스>가 읽은 것이지 요청을 처리한 uvicorn 의 것이 아니다.
        #    둘이 다른 환경변수로 떠 있으면 이 파일은 거짓 조건을 남긴다.
        #    특히 cf_base_url: 이건 <기록용>이지 판정 근거가 아니다.
        #    uvicorn 이 무엇을 보는지는 judge_fake_cf 가 뉴런으로 판정한다.
        "cf_base_url": s.cf_base_url,
    }


def cmd_before(args) -> int:
    settings = _settings_snapshot()

    # 🔴 이 값으로 <막지> 않는다. 예전에는 여기서 중단시켰는데, 그 검사는 드라이버
    #    프로세스의 환경변수만 봐서 양쪽으로 다 틀렸다:
    #      · 드라이버만 가짜 값 → 통과시킨다. uvicorn 이 진짜 CF 여도 통과한다(위험한 오탐).
    #      · 드라이버만 진짜 값 → 중단시킨다. uvicorn 이 가짜여도 중단한다(2026-09-10 실제로 겪었다).
    #    진짜 판정은 아래 _assert_fake_cf 가 <도는 프로세스>를 상대로 한다.
    #    값을 계속 찍는 이유는 두 프로세스의 설정이 어긋났다는 <단서>로는 쓸모가 있어서다.
    if "cloudflare.com" in settings["cf_base_url"]:
        print(f"경고: 이 셸의 CF_BASE_URL 이 진짜 Cloudflare 다 ({settings['cf_base_url']}). "
              f"uvicorn 이 무엇을 보는지는 이 값으로 알 수 없어 아래 워밍업 검사로 판정한다.")

    client = httpx.Client(timeout=60.0)
    resp = client.post(f"{args.api}/api/auth/login",
                       json={"email": args.email, "password": args.password})
    resp.raise_for_status()
    token = resp.json()["token"]

    resp = client.get(f"{args.api}/api/bots", headers={"Authorization": f"Bearer {token}"})
    resp.raise_for_status()
    bot = _pick_bot(resp.json())

    # 🔴 여기서 막는다. k6 를 띄우기 <전>이자 봇을 고른 <뒤>다.
    #    측정이 실제로 두드릴 봇으로 같은 경로를 한 번 태워야 판정에 뜻이 있다.
    warmup_called = _assert_fake_cf(args.ai, bot["id"])

    # 가짜 CF 의 설정은 <그 서버에게 물어본다.> 예전에는 loadtest.fake_cf 의 상수를
    # import 해서 적었는데, 그건 드라이버가 읽은 코드일 뿐이라 다른 지연값으로 떠 있는
    # 서버를 상대로도 그대로 통과했다(read_fake_cf_stats 주석에 근거).
    uvicorn_cf_base_url = _uvicorn_cf_base_url(args.ai)
    if uvicorn_cf_base_url != settings["cf_base_url"]:
        print(f"참고: 드라이버의 CF_BASE_URL({settings['cf_base_url']})과 uvicorn 의 것"
              f"({uvicorn_cf_base_url})이 다르다. 아래 기록은 <uvicorn 의 것>을 따른다.")
    fake_cf_stats = read_fake_cf_stats(uvicorn_cf_base_url)

    # 🔴 기대 배수도 <관측>에서 뽑는다. 예전에는 드라이버가 읽은 reranker_enabled 로
    #    정했는데, 그러면 uvicorn 이 다른 설정으로 떠 있을 때 사후 대조가 <정상 실행을
    #    무효로> 판정한다. 그리고 그건 "경로를 안 탔다" 와 구분이 안 된다
    #    (cmd_after 가 원인 후보로 적어둔 바로 그 항목이다).
    #    워밍업 1건이 부른 모델 수가 곧 요청당 CF 호출 수다(embed·rerank·generate).
    expected = len(warmup_called)
    expected_from_settings = 3 if settings["reranker_enabled"] else 2
    if expected != expected_from_settings:
        raise SystemExit(
            f"중단: 워밍업이 부른 모델은 {expected}종({sorted(warmup_called)})인데 "
            f"드라이버가 읽은 설정으로는 {expected_from_settings}종이다"
            f"(reranker_enabled={settings['reranker_enabled']}). "
            f"두 프로세스가 다른 설정으로 떠 있다는 뜻이라, 이 파일의 settings 블록 전체를 "
            f"믿을 수 없다. 같은 환경변수로 uvicorn 을 다시 띄우고 다시 실행할 것."
        )

    runtime = _runtime_snapshot(args.ai, args.spring_metrics)
    measured = runtime["python"]["anyio_threads_total_measured"]
    configured = settings["anyio_max_threads"]
    print(f"anyio 스레드 상한: 드라이버 설정값 {configured} / 대상 프로세스 실측값 {measured}")
    if measured is None:
        raise SystemExit(
            f"중단: {runtime['python']['metrics_url']} 에서 alldap_anyio_threads_total 을 "
            f"읽지 못했다. 이 판의 변수가 바로 그 값이라, 못 읽은 채로 도는 것은 "
            f"<무엇을 쟀는지 모르는 측정>을 하나 남기는 것뿐이다. "
            f"uvicorn 이 {args.ai} 에 떠 있는지 확인할 것."
        )
    if measured != configured:
        print(f"경고: 드라이버 설정값({configured})과 대상 프로세스 실측값({measured})이 다르다. "
              f"아래 기록과 판정은 <실측값>을 따른다.")
    # 🔴 절차가 아니라 코드가 막는다. "80 으로 돌리기로 했다" 를 사람이 기억하는 것으로
    #    지키면 빠뜨려도 아무 일이 안 일어나고, 그 판은 <다른 값을 잰 채> 80 이라고 적힌다.
    #    봇 소유권을 findByIdAndUserId 로 못박은 것과 같은 판단이다.
    if args.expect_anyio_threads is not None and measured != args.expect_anyio_threads:
        raise SystemExit(
            f"중단: alldap_anyio_threads_total 실측값이 {measured} 인데 "
            f"--expect-anyio-threads {args.expect_anyio_threads} 로 요구했다. "
            f"이 판은 {args.expect_anyio_threads} 를 잰 것이 아니므로 폐기 대상이다. "
            f"ANYIO_MAX_THREADS={args.expect_anyio_threads} 로 uvicorn 을 다시 띄울 것."
        )

    context = {
        "run_id": args.run_id,
        "commit": subprocess.run(["git", "rev-parse", "HEAD"],
                                 capture_output=True, text=True).stdout.strip(),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "api_base": args.api,
        "ai_base": args.ai,
        "bot": {
            "id": bot["id"],
            "name": bot["name"],
            "document_count": bot["documentCount"],
        },
        "corpus": _corpus(bot["id"]),
        "settings": settings,
        # 🔴 <도는 서버에게 물어본> 값이다. 드라이버가 import 한 상수가 아니다.
        "fake_cf": {
            "base_url": uvicorn_cf_base_url,
            "latency_ms": fake_cf_stats["latency_ms"],
            "vector_mode": fake_cf_stats["vector_mode"],
            "vector_bot_id": fake_cf_stats.get("vector_bot_id"),
        },
        "warmup_models_called": warmup_called,
        "expected_cf_calls_per_request": expected,
        # ⚠️ 워밍업 <뒤>의 값이다. 앞에서 찍으면 워밍업 3건이 사후 대조의 배수에 섞여
        #    "경로를 더 탔다" 로 읽힌다(요청 수에는 안 잡히므로 배수가 위로 튄다).
        "cf_stats_before": _cf_counts(args.ai),
        # 🔴 <측정 대상 프로세스들에게 물어본> 값. settings 블록(드라이버 셸)과 따로 둔다.
        "runtime": runtime,
        # 측정 계정. 🔴 이메일만 적는다. 비밀번호를 적으면 그 파일이 곧 커밋된 비밀번호다.
        "loadtest_email": args.email,
        "stages": STAGES,
        "hold_seconds": HOLD_SECONDS,
        "warmup_discard_seconds": WARMUP_DISCARD_SECONDS,
    }

    RESULTS.mkdir(exist_ok=True)
    _context_path(args.run_id).write_text(
        json.dumps(context, ensure_ascii=False, indent=2, default=str)
    )
    print(json.dumps(context, ensure_ascii=False, indent=2, default=str))
    print(f"\n저장: {_context_path(args.run_id)}")
    # 아래 두 줄을 k6 실행 명령에 그대로 넣는다.
    print(f"\nBOT_ID={bot['id']}")
    print(f"RUN_ID={args.run_id}")
    return 0


def cmd_after(args) -> int:
    context = json.loads(_context_path(args.run_id).read_text())
    summary = json.loads(Path(args.k6_summary).read_text())

    def metric_count(key: str) -> int:
        m = summary.get("metrics", {}).get(key) or {}
        return int((m.get("values") or {}).get("count", 0))

    after = _cf_counts(context["ai_base"])
    before = context["cf_stats_before"]
    delta = {model: after.get(model, 0) - before.get(model, 0)
             for model in set(after) | set(before)}
    total_delta = sum(delta.values())

    ok_2xx = metric_count("chat_status{status:200}")
    fallbacks = metric_count("chat_fallback")
    expected = context["expected_cf_calls_per_request"]
    actual_ratio = round(total_delta / ok_2xx, 3) if ok_2xx else None

    verdicts: list[str] = []

    # ① fallback 이 하나라도 있으면 그 실행은 무효다.
    if fallbacks == 0:
        verdicts.append("OK   fallback 0건: 생성 경로를 탔다")
    else:
        verdicts.append(
            f"무효 fallback {fallbacks}건. 그 요청들은 LLM 을 안 타 0.1초에 끝났고, "
            f"재려던 곡선이 그만큼 아래로 끌려갔다. 질문·게이트 설정을 확인하고 다시 잰다."
        )

    # ② 가짜 CF 호출 수가 요청 수와 맞는가.
    #    🔴 pass/fail 로만 내지 않고 <실제 배수>를 함께 적는다. 기대와 다를 때 그 값이
    #       2 인지 3 인지 0 인지에 따라 원인이 전혀 다르다(리랭커 꺼짐 / 경로 미탐 /
    #       드라이버와 uvicorn 의 설정 불일치). 하나의 FAIL 로 뭉개면 그 구분이 사라진다.
    if ok_2xx == 0:
        verdicts.append("무효 2xx 가 0건이다. 실행이 시작조차 못 했다.")
    elif actual_ratio is None:
        verdicts.append("무효 배수를 계산할 수 없다.")
    elif abs(actual_ratio - expected) <= 0.05:
        verdicts.append(f"OK   가짜 CF 호출 배수 {actual_ratio} ≈ 기대 {expected}")
    else:
        verdicts.append(
            f"무효 가짜 CF 호출 배수가 {actual_ratio} 다 (기대 {expected}). "
            f"모델별 증가분={delta}. 2 면 리랭커가 꺼진 채 돌았고(시작 조건 파일의 "
            f"reranker_enabled 와 대조할 것), 0 에 가까우면 그 경로를 아예 안 탔다."
        )

    result = {
        "run_id": args.run_id,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "cf_stats_before": before,
        "cf_stats_after": after,
        "cf_delta": delta,
        "cf_delta_total": total_delta,
        "requests_2xx": ok_2xx,
        "expected_cf_calls_per_request": expected,
        "actual_cf_calls_per_request": actual_ratio,
        "fallbacks": fallbacks,
        "verdicts": verdicts,
        "valid": all(v.startswith("OK") for v in verdicts),
        # 🔴 "유효" 는 <오염이 없다> 는 뜻이지 <결과가 좋다> 는 뜻이 아니다.
        #    5xx 와 재시작은 여기서 판정하지 않는다. 그건 S2 가 찾으려는 결과 그 자체이고,
        #    재시작 경계는 Grafana 패널을 눈으로 보고 사람이 표에 옮긴다.
        "valid_means": (
            "오염(fallback·경로 미탐)이 없다는 뜻이다. 5xx·재시작은 여기서 판정하지 않는다."
        ),
    }

    _verdict_path(args.run_id).write_text(
        json.dumps(result, ensure_ascii=False, indent=2)
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n저장: {_verdict_path(args.run_id)}")
    for v in verdicts:
        print(f"  {v}")
    return 0 if result["valid"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="S2 시작 조건 · 사후 대조")
    parser.add_argument("phase", choices=["before", "after"])
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--api", default="http://localhost:8080")
    parser.add_argument("--ai", default="http://localhost:8001")
    # 🔴 계정은 <측정 전용>이고 기본값은 환경변수에서 온다. 예전에는 w2check@example.com
    #    이 박혀 있었는데, 그건 W2 검증에 쓰던 계정이라 측정이 끝날 때마다 비밀번호를
    #    되돌렸고 그래서 다음 측정이 매번 401 이었다(loadtest/account.py 참고).
    parser.add_argument("--email", default=env_email())
    parser.add_argument("--password", default=env_password())
    parser.add_argument("--k6-summary")
    parser.add_argument("--spring-metrics", default="http://localhost:8081/actuator/prometheus")
    # 🔴 기본값을 두지 않는다. 기본 80 을 박으면 다른 상한을 재려는 판이 <조용히 막히고>,
    #    기본 None 만 두면 아무도 안 넘겨 검사가 죽은 채로 남는다. 그래서 넘기게 한다.
    parser.add_argument("--expect-anyio-threads", type=int, default=None,
                        help="alldap_anyio_threads_total 실측값이 이 값이 아니면 중단한다")
    args = parser.parse_args()

    if args.phase == "before":
        if not args.password:
            print("중단: before 에는 비밀번호가 필요하다. "
                  "LOADTEST_PASSWORD 를 넣거나 --password 로 넘길 것.")
            return 1
        return cmd_before(args)

    if not args.k6_summary:
        print("중단: after 에는 --k6-summary 가 필요하다.")
        return 1
    return cmd_after(args)


if __name__ == "__main__":
    sys.exit(main())
