"""부하테스트 S2(breakpoint) 가 읽는 Prometheus 지표.

이 모듈이 존재하는 이유는 하나다 — <어느 자원이 먼저 차는가> 를 가리는 것.
Spring 쪽 지표(Hikari·Tomcat·힙)는 PR 1 이 깔아놨고, 여기 없는 것은 Python 몫이다.

🔴 prometheus-fastapi-instrumentator 를 쓰지 않는다. 근거는 requirements.txt 주석 참고.

⚠️ 멀티프로세스 주의 — 지금은 안전하지만 <PR 5 에서 깨진다>
─────────────────────────────────────────────────────────────────────────────
prometheus_client 의 기본 레지스트리는 <프로세스 안의> 카운터다. 워커가 여럿이면
스크레이프가 그중 <아무 워커 하나>에 닿아 그 워커의 숫자만 돌려주고, 나머지는 사라진다.
지금은 Dockerfile:34 의 uvicorn 이 워커 1개라 문제가 없다.
🔴 그런데 PR 5 의 개선 후보가 정확히 "워커 수를 늘리기" 다. 그때 이 파일을
   multiprocess 모드(PROMETHEUS_MULTIPROC_DIR + MultiProcessCollector)로 함께 고치지 않으면
   지표는 <에러를 내지 않고> 조용히 1/N 로 줄어들고, 그 그래프는 "개선됐다" 로 읽힌다.
"""
from __future__ import annotations

import anyio.to_thread
from prometheus_client import CONTENT_TYPE_LATEST, Gauge, Histogram, generate_latest

# ── 1순위 가설: anyio 스레드풀이 먼저 찬다 ──────────────────────────────
#
# main.py 의 `chat` 이 `async def` 가 아니라 `def` 라, FastAPI 는 그 요청을
# anyio 의 <기본 스레드풀>에서 처리한다. 그 풀의 상한이 40 이고, 한 요청이
# 최소 1.586초(embed 235 + rerank 414 + generate 937) 걸린다.
# 즉 동시 40건을 넘기는 순간 41번째부터는 <일을 시작조차 못 하고> 큐에서 기다린다.
ANYIO_THREADS_BORROWED = Gauge(
    "alldap_anyio_threads_borrowed",
    "anyio 기본 스레드풀에서 지금 쓰이고 있는 스레드 수",
)

# 🔴 상한을 <같이> 내보낸다. 40 은 우리가 설정한 값이 아니라 anyio 기본값이라,
#    라이브러리를 올리면 조용히 바뀔 수 있다. borrowed 만 그리면 "40 에 붙었다" 를
#    사람이 기억한 40 과 비교하게 되고, 그 기억이 틀린 날 그래프가 거짓말을 한다.
ANYIO_THREADS_TOTAL = Gauge(
    "alldap_anyio_threads_total",
    "anyio 기본 스레드풀의 상한 (설정값이 아니라 anyio 기본값이다)",
)

# ── Spring 왕복에서 Python 몫을 분리한다 ────────────────────────────────
#
# 이게 없으면 k6 가 보는 종단 지연이 느려졌을 때 <Spring 인가 Python 인가> 를 못 가른다.
# 버킷은 가짜 CF 기준 하한 1.586초를 가운데 두고 잡았다. 기본 버킷(최대 10초)은
# 포화 구간에서 전부 +Inf 로 몰려 p99 를 못 준다.
CHAT_DURATION = Histogram(
    "alldap_chat_duration_seconds",
    "/internal/chat 처리 시간 (Python 몫)",
    buckets=(0.1, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 8.0, 13.0, 21.0, 34.0, 60.0, 120.0),
)

# 🔴 이 지표는 <대기 큐 길이가 아니다>. 2026-09-10 S2 실측에서 드러났다.
#
# 애초에는 "스레드풀 대기 큐 길이의 대리 지표" 로 뒀는데(설계서 §5①), 원리적으로
# 그 역할을 못 한다. inc() 가 main.chat 함수 <안>에 있고 그 함수는 anyio 워커 스레드를
# 이미 얻은 뒤에야 실행되므로, <기다리는> 요청은 inc() 에 도달조차 못 한다.
# 즉 inflight 는 구조적으로 ANYIO_THREADS_BORROWED 를 넘을 수 없다.
# 80 VU 실측이 그대로 보여준다: tomcat_busy=80 인데 inflight=40 이었다.
#
# ⚠️ 값이 틀린 게 아니라 <약속이 틀렸던> 것이다. "지금 Python 이 실제로 처리 중인 건수"
#    로는 여전히 옳다. 그래서 이름도 바꾸지 않는다(이미 쌓인 S1·S2 측정 기록과
#    Prometheus 시계열의 연속성이 끊긴다).
#
# 🔴 실제 대기 큐 길이는 <뺄셈>으로 읽는다:
#       tomcat_threads_busy_threads - alldap_anyio_threads_borrowed
#    Spring 이 붙잡고 있는 요청 수에서 Python 이 실제로 돌리는 수를 뺀 것이다.
#    S2 실측에서는 80 - 40 = 40 이었다. PR 5 의 개선 전후 비교는 이 식으로 한다.
#    (Grafana 패널 id 6 이 이 식을 시리즈로 그린다)
#
# ⚠️ 뺄셈 식은 Spring 이 Python 을 <동기로 1:1 호출한다>는 전제 위에 선다. 그 전제가
#    깨지면(비동기 큐 도입 등) 이 식도 함께 무효다.
CHAT_INFLIGHT = Gauge(
    "alldap_chat_inflight",
    "지금 /internal/chat 을 실제로 처리 중인 요청 수 (대기 큐 아님. 큐는 "
    "tomcat_threads_busy_threads - alldap_anyio_threads_borrowed 로 읽을 것)",
)


def sample_anyio_threads() -> None:
    """anyio 스레드풀 점유를 지금 값으로 갱신한다.

    🔴 <이벤트 루프 스레드에서만> 부를 수 있다. current_default_thread_limiter() 는
       RunVar 라 워커 스레드나 루프 밖에서 부르면 NoEventLoopError 로 죽는다(실측).
       그래서 이걸 부르는 /internal/metrics 라우트는 반드시 `async def` 여야 한다.
       `def` 로 두면 FastAPI 가 워커 스레드로 넘기고, 지표 엔드포인트만 500 을 낸다 —
       하필 <부하 한가운데서>, 즉 그 숫자가 가장 필요한 순간에.
       app/metrics_check.py 가 이 제약을 검사로 못 박아둔다.

    ⚠️ 스크레이프 시점의 <순간값>이다. 15초 간격 사이에 40 에 붙었다 떨어지면 못 본다.
       S2 는 단계를 2분씩 유지하므로 단계마다 점이 8개 찍혀 그 한계에 걸리지 않는다.
    """
    limiter = anyio.to_thread.current_default_thread_limiter()
    ANYIO_THREADS_TOTAL.set(limiter.total_tokens)
    ANYIO_THREADS_BORROWED.set(limiter.borrowed_tokens)


def render() -> tuple[bytes, str]:
    """스크레이프 응답 본문과 Content-Type. 이벤트 루프에서만 부를 것."""
    sample_anyio_threads()
    return generate_latest(), CONTENT_TYPE_LATEST
