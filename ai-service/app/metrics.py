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

✅ 2026-09-11(PR 5a): 동시 처리를 <워커 수가 아니라 스레드 상한>으로 올렸다
   (config.anyio_max_threads). 한 프로세스 안에서 스레드만 느는 것이라 위 함정은
   아직 발현하지 않는다. 워커를 늘리는 날 이 경고는 그대로 유효하다.
"""
from __future__ import annotations

import anyio.to_thread
from prometheus_client import CONTENT_TYPE_LATEST, Gauge, Histogram, generate_latest

from . import db

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

# 🔴 상한을 <같이> 내보낸다. borrowed 만 그리면 "상한에 붙었다" 를 사람이 기억한
#    숫자와 비교하게 되고, 그 기억이 틀린 날 그래프가 거짓말을 한다.
#
# ⚠️ 2026-09-11 에 이 값의 <출처>가 바뀌었다. 예전에는 anyio 기본값 40 이었고,
#    이제는 config.anyio_max_threads(기본 80)를 main.lifespan 이 적용한 결과다.
#    값을 채우는 코드는 그대로다 — sample_anyio_threads() 가 limiter 에게 직접
#    물어보기 때문에 <설정을 바꾸면 게이지가 따라온다>. 설정값을 여기 따로 적어
#    넣지 않는 이유가 그것이다: 두 군데에 적으면 언젠가 어긋나고, 어긋난 쪽이
#    계기판이면 그래프가 거짓말을 한다.
ANYIO_THREADS_TOTAL = Gauge(
    "alldap_anyio_threads_total",
    "anyio 기본 스레드풀의 상한 (config.anyio_max_threads 를 lifespan 이 적용한 값)",
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


# ── 다음 벽 후보: psycopg 커넥션 풀 ─────────────────────────────────────
#
# 🔴 이 지표가 없으면 <스레드 상한을 올린 뒤 다음 벽을 힙과 구분할 수 없다.>
#    S2(2026-09-10)는 경쟁 후보 셋 중 Tomcat(busy 80 / max 200)과
#    Hikari(pending 0)를 배제하고 병목을 anyio 스레드풀로 좁혔다. 그 판정에
#    <이 풀은 아예 들어 있지 않았다> — hikaricp_* 는 Spring 의 풀이고 이건
#    Python 의 다른 풀이다. 스레드를 40 -> 80 으로 올리면 80개가 커넥션 10개를
#    두고 경쟁하므로, 다음 측정에서 처리량이 예측(48 req/s)에 못 미칠 때
#    "Spring 힙이 말랐다" 와 "커넥션을 기다렸다" 가 <같은 그림>으로 보인다.
#    그 둘을 가르는 것이 아래 requests_waiting 이다.
#
# 🔴 네 값을 따로 내보내는 이유: 전부 다른 사실이다. 하나로 뭉치면 이 저장소가
#    일곱 번 낸 그 버그가 된다.
#      size      지금 <만들어져 있는> 커넥션 수. 풀은 min_size=1 로 시작해 필요할 때 는다
#      max       상한. size 와 같아지는 것이 곧 포화는 아니다(놀고 있을 수 있다)
#      available 지금 <아무도 안 쓰는> 커넥션 수. max - waiting 으로 유도할 수 없다
#      waiting   지금 커넥션을 <기다리는> 요청 수. 이것만이 "풀이 벽이다" 의 증거다
#    특히 size == max 와 waiting > 0 은 다른 사실이다. 앞은 "다 만들었다",
#    뒤는 "부족하다" 이고, 둘을 뭉치면 넉넉한 풀을 병목으로 오진한다.
DB_POOL_SIZE = Gauge(
    "alldap_db_pool_size",
    "psycopg 풀에 지금 만들어져 있는 커넥션 수 (상한이 아니라 실제 생성된 수)",
)
DB_POOL_MAX = Gauge(
    "alldap_db_pool_max",
    "psycopg 풀의 커넥션 상한 (db.get_pool 의 max_size)",
)
DB_POOL_AVAILABLE = Gauge(
    "alldap_db_pool_available",
    "psycopg 풀에서 지금 아무도 안 쓰는 커넥션 수",
)
DB_POOL_WAITING = Gauge(
    "alldap_db_pool_requests_waiting",
    "지금 psycopg 커넥션을 기다리는 요청 수 (이 값이 0 이 아니면 풀이 벽이다)",
)

# 🔴 "풀이 아직 없다" 와 "풀이 있는데 전부 0 이다" 는 다른 사실이다.
#    풀은 첫 DB 사용 때 만들어지므로 기동 직후 스크레이프에는 없는 것이 정상인데,
#    그때 위 네 게이지는 <생성 기본값 0> 을 내보낸다. 그 0 을 "상한이 0" 이나
#    "커넥션이 없다" 로 읽으면 안 된다. 이 게이지가 그 둘을 갈라준다.
DB_POOL_OPEN = Gauge(
    "alldap_db_pool_open",
    "psycopg 풀이 만들어져 있으면 1, 아직 없으면 0 (0 이면 위 풀 지표는 의미가 없다)",
)


def sample_db_pool() -> None:
    """psycopg 풀 상태를 지금 값으로 갱신한다.

    ⚠️ 이벤트 루프를 막지 않는다. db.pool_stats() 는 이미 만들어진 풀에게만 묻고
       (풀을 만들지 않는다), psycopg_pool 의 get_stats() 는 잠금 없이 deque 길이와
       dict 복사만 한다. 이 두 전제가 깨지면 /internal/metrics 가 <부하 한가운데서>
       루프를 붙잡게 되고, 그 순간이 하필 이 숫자가 가장 필요한 때다.

    ⚠️ 스크레이프 시점의 순간값이다. 15초 간격 사이에 찼다 빠지면 못 본다
       (sample_anyio_threads 와 같은 한계, 같은 이유로 S2 는 단계를 2분씩 유지한다).
    """
    stats = db.pool_stats()
    if stats is None:
        DB_POOL_OPEN.set(0)
        return
    DB_POOL_OPEN.set(1)
    # ⚠️ 누적 카운터(requests_num 등)는 값이 0 이면 키 자체가 없다(psycopg 가
    #    defaultdict 로 모으기 때문). 순간값 네 개는 항상 오지만 .get 으로 받는다.
    DB_POOL_SIZE.set(stats.get("pool_size", 0))
    DB_POOL_MAX.set(stats.get("pool_max", 0))
    DB_POOL_AVAILABLE.set(stats.get("pool_available", 0))
    DB_POOL_WAITING.set(stats.get("requests_waiting", 0))


def render() -> tuple[bytes, str]:
    """스크레이프 응답 본문과 Content-Type. 이벤트 루프에서만 부를 것."""
    sample_anyio_threads()
    sample_db_pool()
    return generate_latest(), CONTENT_TYPE_LATEST
