# 부하테스트 PR 3 (S2 breakpoint) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 관리자 채팅 경로에 계단식 부하(1→5→10→20→40→80 VU)를 걸어 **선형성이 깨지는 단계와 그때 포화된 자원**을 기록으로 남긴다. 고치지 않는다.

**Architecture:** Python 에 `/internal/metrics` 를 신설해 anyio 스레드풀 점유를 내보내고(1순위 가설), 로컬 `bootRun` 에 운영과 같은 힙 한도를 옵트인으로 씌워 힙 고갈을 링에 올린다(2순위 가설). k6 가 중단 없이 80 까지 밀고, 판정은 전부 사후에 파일과 Grafana 로 한다. 오염(fallback·경로 미탐)만 예비 실행 30초로 미리 거른다.

**Tech Stack:** FastAPI + `prometheus-client` 0.26.0 / Prometheus + Grafana(docker) / Gradle `bootRun` / k6 (`brew install k6`) / 자체 점검은 이 저장소 관례인 `*_check.py` 스크립트 (pytest 를 쓰지 않는다)

---

## Global Constraints

- **모든 경로는 저장소 루트 `/Users/cheonjamin/projects/AllDap` 기준.** Python 명령은 전부 `cd ai-service` 에서 `.venv/bin/python -m ...` 로 돈다.
- **브랜치는 `feat/loadtest-s2-breakpoint`** (이미 체크아웃돼 있다). `main` 에 직접 커밋하지 않는다.
- **커밋 메시지는 `<타입>: <한국어 요약>`** — feat / fix / refactor / test / docs / chore / review (AGENTS.md:282).
- **테스트 관례는 pytest 가 아니라 `*_check.py` 자체 점검 스크립트다.** `python -m` 으로 돌고, 각 항목을 `OK`/`FAIL` 로 찍고, 실패가 하나라도 있으면 종료코드 1 을 돌려준다. `app/evaluator_check.py`·`loadtest/fake_cf_check.py` 가 선례다.
- **가짜 CF 지연값은 이 PR 에서 바꾸지 않는다** — `loadtest/fake_cf.py:LATENCY_MS = {"embed": 235, "rerank": 414, "generate": 937}`.
- **계정**: 측정 전용 계정(기본 `loadtest@example.com`). 비밀번호는 저장소에 적지 않고 `LOADTEST_PASSWORD` 환경변수로만 넘긴다(이메일을 바꾸려면 `LOADTEST_EMAIL`).
  측정 전에 `cd ai-service && LOADTEST_PASSWORD='...' .venv/bin/python -m loadtest.account` 를 한 번 돌려 계정과 측정 봇 소유권을 맞춘다.
  ⚠️ 이 줄은 원래 `w2check@example.com` / 고정 비밀번호였다. PR #133(2026-09-11)이 그 손작업과 코드 기본값을 없앴으므로 옛 값으로 로그인하면 401 이다.
- **`botId` 를 코드에 하드코딩하지 않는다.** 로그인 뒤 봇 목록에서 골라 시작 조건 파일에 적고, k6 는 환경변수로 받는다.
- **개선하지 않는다.** 병목이 보여도 이 PR 에서는 고치지 않는다(PR 5 의 before 가 사라진다).
- **prometheus-client 버전은 `prometheus-client==0.26.0`.** `requirements.txt` 는 이 저장소에서 정확 버전 고정이 규칙이다(파일 상단 주석의 사고 기록 참고).

---

## File Structure

| 파일 | 책임 | 신규/수정 |
|---|---|---|
| `ai-service/requirements.txt` | `prometheus-client` 추가 | 수정 |
| `ai-service/app/metrics.py` | 지표 4개 정의 + anyio limiter 샘플링 + 렌더 | **신규** |
| `ai-service/app/metrics_check.py` | 위 모듈과 `/internal/metrics` 라우트 자체 점검 | **신규** |
| `ai-service/app/main.py` | `/internal/metrics` 라우트 1개 + `/internal/chat` 계측 | 수정 |
| `observability/prometheus.yml` | `alldap-ai` job 추가 | 수정 |
| `observability/grafana/dashboards/alldap-api.json` | 패널 3개 추가 | 수정 |
| `api/build.gradle` | `bootRun` 블록(`-Ploadtest`) | 수정 |
| `docker-compose.prod.yml` | `JAVA_OPTS` 옆에 상호 참조 주석 | 수정 |
| `ai-service/loadtest/s2_breakpoint.js` | k6 시나리오 6단계 | **신규** |
| `ai-service/loadtest/s2_context.py` | 시작 조건 파일 + 전후 cf-stats 대조 | **신규** |
| `ai-service/loadtest/results/` | 결과 JSON 3종 | 산출물 |
| `docs/superpowers/2026-09-10-loadtest-s2-result.md` | 결과 문서 | **신규** |

---

## 설계서에서 두 가지를 더 정했다 (실행 전에 읽을 것)

설계서(`docs/superpowers/specs/2026-09-10-loadtest-pr3-s2-breakpoint-design.md`)를 코드 수준으로
내리면서 **실측으로 확인해 바꾼 것이 둘** 있다. 둘 다 안 하면 측정이 조용히 거짓이 된다.

### ① `bootRun` 의 `-XX:TieredStopAtLevel=1` 을 꺼야 한다

설계서 §5③ 의 gradle 스니펫에는 없는 항목이다. Spring Boot Gradle 플러그인의 `BootRun` 은
`optimizedLaunch` 가 **기본 true** 이고, 그때 `-XX:TieredStopAtLevel=1` 을 붙인다
(플러그인 jar 4.0.7 의 `BootRun.class` 를 직접 열어 확인했다).

TieredStopAtLevel=1 은 JIT 을 C1 에서 멈춘다 — 기동을 1초쯤 줄이려는 옵션인데,
**12분 동안 수천 건을 처리하는 측정에서는 운영(C2 까지 컴파일)보다 훨씬 느린 JVM 을 재게 된다.**
그러면 "어디서 꺾이는가" 가 통째로 아래 단계로 밀리고, 이 PR 의 산출물이 정확히 그 숫자다.

→ `-Ploadtest` 블록 안에서 `optimizedLaunch = false` 를 함께 준다.

### ② `-XX:MaxMetaspaceSize=128m` 도 함께 씌운다

설계서 스니펫은 플래그 3개(`-Xms192m -Xmx256m -XX:+ExitOnOutOfMemoryError`)만 적었는데,
`docker-compose.prod.yml:54-56` 의 실제 운영 값은 **네 개**다.

```
-Xms192m -Xmx256m -XX:MaxMetaspaceSize=128m -XX:+ExitOnOutOfMemoryError
```

설계서 §2 가 내건 근거는 "로컬 `bootRun` 에 **운영과 같은** JVM 플래그를 씌운다" 이고,
메타스페이스 한도도 힙과 같은 부류의 **자원 한도**다. 셋만 베끼면 "운영과 같다" 는
전제가 처음부터 어긋나고, 그 어긋남은 나중에 아무도 못 찾는다.
→ 네 개를 그대로 쓴다.

### ③ anyio limiter 는 이벤트 루프 스레드에서만 읽을 수 있다 (실측)

`.venv/bin/python` 으로 직접 확인했다:

```
event loop: total 40 borrowed 0
during: borrowed 3
  worker-thread call FAILED: NoEventLoopError
--- outside any loop ---
FAILED: NoEventLoopError
```

`anyio.to_thread.current_default_thread_limiter()` 는 RunVar 라 **워커 스레드에서 부르면
`NoEventLoopError` 로 죽는다.** 그래서:

- `/internal/metrics` 라우트는 반드시 **`async def`** 여야 한다 (`def` 로 두면 FastAPI 가
  워커 스레드에서 부르고, 지표 엔드포인트가 500 을 낸다 — 부하 한가운데서)
- `/internal/chat` 계측(`def`, 워커 스레드에서 돈다)은 limiter 를 **건드리면 안 된다.**
  거기서는 Histogram·Gauge 만 쓴다 (`prometheus_client` 의 이 둘은 락으로 스레드 안전하다)

같은 실측에서 `total_tokens == 40` 도 확인했다(anyio 4.14.2 기본값).

---

## Task 1: Python 지표 모듈 (`app/metrics.py`)

**Files:**
- Modify: `ai-service/requirements.txt`
- Create: `ai-service/app/metrics.py`
- Create: `ai-service/app/metrics_check.py` (이 태스크에서는 **① 단위 검사 3건만**. 라우트 검사는 Task 2 에서 같은 파일에 덧붙인다)

**Interfaces:**
- Consumes: 없음 (첫 태스크)
- Produces:
  - `app.metrics.sample_anyio_threads() -> None`
  - `app.metrics.render() -> tuple[bytes, str]` (본문, Content-Type)
  - `app.metrics.CHAT_DURATION` — `prometheus_client.Histogram`, `.observe(seconds: float)`
  - `app.metrics.CHAT_INFLIGHT` — `prometheus_client.Gauge`, `.inc()` / `.dec()`
  - 지표 이름 4개: `alldap_anyio_threads_borrowed`, `alldap_anyio_threads_total`, `alldap_chat_duration_seconds`, `alldap_chat_inflight`

---

- [ ] **Step 1: `prometheus-client` 를 requirements 에 적고 설치한다**

`ai-service/requirements.txt` 의 `httpx==0.28.1` 줄 **바로 아래**에 다음을 덧붙인다:

```
# 부하테스트 S2 가 읽는 /internal/metrics 용.
# 🔴 prometheus-fastapi-instrumentator 를 <쓰지 않는다.> 정작 필요한 지표를 그 패키지가
#    주지 않는다 — anyio 스레드풀 점유(alldap_anyio_threads_borrowed)는 어느 범용 계측기에도
#    없고 limiter 를 직접 읽어야 한다. 핵심을 손으로 써야 하면 범용 패키지는 의존성만 늘린다.
prometheus-client==0.26.0
```

설치:

```bash
cd /Users/cheonjamin/projects/AllDap/ai-service && .venv/bin/pip install prometheus-client==0.26.0
```

기대: `Successfully installed prometheus-client-0.26.0`

- [ ] **Step 2: 실패하는 자체 점검을 먼저 쓴다**

`ai-service/app/metrics_check.py` 를 새로 만든다:

```python
"""app/metrics.py 자체 점검. LLM 도 DB 도 없이 돈다.

실행:
    cd ai-service && .venv/bin/python -m app.metrics_check

무엇을 재나
─────────────────────────────────────────────────────────────────────────────
"지표가 나온다" 가 아니라 <숫자가 진짜 스레드풀 점유를 따라가는가> 를 잰다.
S2 의 1순위 가설(anyio 스레드풀 40 이 먼저 찬다)은 이 숫자 하나로 판정되므로,
이 숫자가 굳어 있으면 <가설이 틀린 것>과 <계측이 고장 난 것>이 같은 그림으로 보인다.
이 저장소가 반복해 걸린 부류다(원인이 다른 두 사실을 같은 값으로 뭉개는 것).
"""
from __future__ import annotations

import time

import anyio
import anyio.to_thread

from app import metrics

_failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK  ' if ok else 'FAIL'} {name} {detail}")
    if not ok:
        _failures.append(name)


def _value(name: str) -> float:
    """레지스트리에서 지표 하나의 현재 값을 읽는다."""
    from prometheus_client import REGISTRY

    got = REGISTRY.get_sample_value(name)
    return -1.0 if got is None else got


async def _scenario() -> None:
    # ① 아무도 안 쓸 때: borrowed 0, total 40
    metrics.sample_anyio_threads()
    check("유휴 borrowed == 0", _value("alldap_anyio_threads_borrowed") == 0.0,
          f"(={_value('alldap_anyio_threads_borrowed')})")
    total = _value("alldap_anyio_threads_total")
    # 🔴 40 은 <설정값이 아니라 anyio 기본값>이다. 버전이 올라가 이 값이 바뀌면
    #    Grafana 의 "40 에 붙었다" 판정이 조용히 거짓이 된다. 그래서 검사로 못 박는다.
    check("total_tokens == 40 (anyio 기본값)", total == 40.0, f"(={total})")

    # ② 스레드 3개를 점유한 상태: borrowed 가 따라 올라간다
    async def occupy() -> None:
        await anyio.to_thread.run_sync(lambda: time.sleep(0.5))

    async with anyio.create_task_group() as tg:
        for _ in range(3):
            tg.start_soon(occupy)
        await anyio.sleep(0.2)
        metrics.sample_anyio_threads()
        borrowed = _value("alldap_anyio_threads_borrowed")
        check("점유 중 borrowed == 3", borrowed == 3.0, f"(={borrowed})")


def main() -> int:
    print("app/metrics.py 자체 점검")
    anyio.run(_scenario)

    # ③ 루프 밖에서 부르면 <죽어야 한다>. 이 제약을 검사로 남기지 않으면
    #    나중에 누가 /internal/metrics 를 `def` 로 바꿔도 아무도 모르고,
    #    부하 한가운데서 지표 엔드포인트만 500 을 낸다.
    try:
        metrics.sample_anyio_threads()
        check("이벤트 루프 밖에서는 예외", False, "(예외가 안 났다)")
    except Exception as exc:  # noqa: BLE001
        check("이벤트 루프 밖에서는 예외", True, f"({type(exc).__name__})")

    print(f"\n{'실패 ' + ', '.join(_failures) if _failures else '전부 통과'}")
    return 1 if _failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: 점검이 실패하는 것을 확인한다**

```bash
cd /Users/cheonjamin/projects/AllDap/ai-service && .venv/bin/python -m app.metrics_check
```

기대: `ImportError: cannot import name 'metrics' from 'app'` (아직 모듈이 없다)

> ⚠️ `ModuleNotFoundError` 가 아니라 `ImportError` 다. 점검 파일이 `import app.metrics` 가 아니라
> `from app import metrics` 라, 패키지 `app` 자체는 있고 그 안의 이름만 없는 상황이기 때문이다.
> 어느 쪽이든 뜻은 같다(모듈이 아직 없다). 종료코드는 1 이다.

- [ ] **Step 4: `app/metrics.py` 를 쓴다**

```python
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

# 스레드풀 대기 큐 길이의 <대리 지표>다. borrowed 가 40 에 붙어 있는데 inflight 가
# 계속 늘면, 늘어난 만큼이 큐에서 기다리는 요청이다.
CHAT_INFLIGHT = Gauge("alldap_chat_inflight", "지금 /internal/chat 안에 있는 요청 수")


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
```

- [ ] **Step 5: 점검이 통과하는 것을 확인한다**

```bash
cd /Users/cheonjamin/projects/AllDap/ai-service && .venv/bin/python -m app.metrics_check
```

기대 출력:

```
app/metrics.py 자체 점검
  OK   유휴 borrowed == 0 (=0.0)
  OK   total_tokens == 40 (anyio 기본값) (=40.0)
  OK   점유 중 borrowed == 3 (=3.0)
  OK   이벤트 루프 밖에서는 예외 (NoEventLoopError)

전부 통과
```

종료코드 0 인 것도 확인:

```bash
cd /Users/cheonjamin/projects/AllDap/ai-service && .venv/bin/python -m app.metrics_check; echo "exit=$?"
```

기대: `exit=0`

- [ ] **Step 6: 커밋**

```bash
cd /Users/cheonjamin/projects/AllDap
git add ai-service/requirements.txt ai-service/app/metrics.py ai-service/app/metrics_check.py
git commit -m "feat: anyio 스레드풀 점유를 재는 지표를 만든다"
```

---

## Task 2: `/internal/metrics` 라우트 + `/internal/chat` 계측

**Files:**
- Modify: `ai-service/app/main.py` (import 블록 / `/internal/chat` 함수 `229-268` 근처 / 파일 끝에 라우트 추가)
- Modify: `ai-service/app/metrics_check.py` (라우트 검사 2건 추가)

**Interfaces:**
- Consumes: Task 1 의 `app.metrics.render()`, `CHAT_DURATION`, `CHAT_INFLIGHT`
- Produces: `GET /internal/metrics` → 200, `text/plain; version=0.0.4; charset=utf-8`, 본문에 지표 4개 이름이 모두 있다

---

- [ ] **Step 1: 라우트 검사를 먼저 쓴다 (실패하는 상태로)**

`ai-service/app/metrics_check.py` 의 `main()` 안, `③` 블록 **다음**·`print(f"\n{...}")` **앞**에 다음을 끼워 넣는다:

```python
    # ④ 라우트가 실제로 200 을 주고, 지표 이름 4개가 다 있는가.
    #    🔴 모듈 단위 검사만으로는 <라우트를 async def 로 뒀는가> 를 못 본다.
    #       그게 이 PR 에서 가장 조용히 깨지는 자리다.
    from fastapi.testclient import TestClient

    from app.main import app  # noqa: PLC0415  (지표 등록 뒤에 import 해야 한다)

    with TestClient(app) as client:
        resp = client.get("/internal/metrics")
        check("GET /internal/metrics == 200", resp.status_code == 200, f"({resp.status_code})")
        body = resp.text
        for name in (
            "alldap_anyio_threads_borrowed",
            "alldap_anyio_threads_total",
            "alldap_chat_duration_seconds",
            "alldap_chat_inflight",
        ):
            check(f"본문에 {name}", name in body)
```

- [ ] **Step 2: 검사가 실패하는 것을 확인한다**

```bash
cd /Users/cheonjamin/projects/AllDap/ai-service && .venv/bin/python -m app.metrics_check
```

기대: `FAIL GET /internal/metrics == 200 (404)` 와 그 아래 지표 이름 4건도 전부 FAIL, 종료코드 1

- [ ] **Step 3: `main.py` 에 import 를 추가한다**

`ai-service/app/main.py:16` 의

```python
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
```

을 다음으로 바꾼다:

```python
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Response, UploadFile
```

그리고 `main.py:18` 의

```python
from . import cf, conflicts, evaluator, evalrun, retriever
```

을 다음으로 바꾼다:

```python
from . import cf, conflicts, evaluator, evalrun, metrics, retriever
```

- [ ] **Step 4: `/internal/metrics` 라우트를 추가한다**

`main.py` 의 `cf_stats()` 함수가 끝나는 곳(`return stats` 다음 줄)과 `# ── 문서 처리 ───` 주석
**사이**에 다음을 끼워 넣는다:

```python
@app.get("/internal/metrics")
async def prometheus_metrics() -> Response:
    """Prometheus 스크레이프 엔드포인트. 부하테스트 S2 가 읽는다.

    🔴 <async def 여야 한다.> metrics.render() 안의 anyio limiter 조회는 이벤트 루프
       스레드에서만 되고, `def` 로 두면 FastAPI 가 워커 스레드로 넘겨 NoEventLoopError 로
       500 이 난다 — 하필 부하가 걸린 순간에만. app/metrics_check.py 가 이걸 검사한다.

    🔴 경로가 /metrics 가 아니라 <b>/internal/metrics</b> 인 이유.
       이 저장소는 "인증 없는 것은 /internal/* 아래에만 둔다" 와 "prod compose 가
       ai-service 에 ports: 를 안 써서 바깥에 안 열린다" 두 전제로 지탱한다
       (cf_stats docstring 이 같은 근거를 적어둔 자리). /metrics 를 루트에 두면
       그 규칙에서 혼자 벗어나고, 규칙에 예외가 하나 생기면 다음 예외는 근거 없이 생긴다.

    ⚠️ 여기서 나가는 것은 숫자뿐이다. 문서 내용도 봇 정보도 없다.
    """
    body, content_type = metrics.render()
    return Response(content=body, media_type=content_type)
```

- [ ] **Step 5: `/internal/chat` 을 계측한다**

`main.py` 의 `chat` 함수 전체(`@app.post("/internal/chat", ...)` 부터 `latency_ms=latency_ms,` 아래
`)` 까지)를 다음으로 **통째로 바꾼다.** 기존 주석은 한 줄도 지우지 않고 그대로 옮긴다 —
바뀌는 것은 `try/finally` 로 감싼 것과 들여쓰기뿐이다.

```python
@app.post("/internal/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    started = time.perf_counter()
    # 🔴 계측을 try/finally 로 감싼다. 아래 503(GenerationFailed) 경로도 <히스토그램에 들어가야>
    #    한다 — 30초 걸려 실패한 요청은 지연 통계에서 빠질 것이 아니라 거기 있어야 하는 사실이다.
    #    (cf._record_latency 가 raise_for_status 앞에 있는 것과 같은 이유)
    # ⚠️ 여기는 워커 스레드다. anyio limiter 를 건드리면 NoEventLoopError 로 죽는다.
    #    스레드풀 지표는 /internal/metrics(async) 가 스크레이프 시점에 읽는다.
    metrics.CHAT_INFLIGHT.inc()
    try:
        sources = retriever.search(req.bot_id, req.message)
        try:
            # 봇별 지침(PRD F-06). 없으면 기본 규칙만 쓴다.
            # ⚠️ 대체가 아니라 <덧붙임>이다 — build_system_prompt 주석 참고.
            answer, is_fallback = generate(
                req.message,
                sources,
                system_prompt=build_system_prompt(fetch_bot_prompt(req.bot_id)),
            )
        except GenerationFailed as e:
            # 🔴 fallback 으로 뭉개지 않는다. 근거는 찾았는데 <답변을 못 받은> 것이라
            #    "문서에서 답을 찾지 못했어요" 로 내보내면 제품이 거짓말을 한다.
            #    오류로 올려야 대화 로그에도 답변 행이 남지 않는다 — 그게 사실이다.
            #
            # ⚠️ 왜 로그를 남기나: 아래 message 는 사용자에게 그대로 닿지 않는다. Spring 이 자기
            #    ErrorCode 문구를 내보내기 때문이다. 원인(잘림인지 빈 응답인지, max_tokens 가
            #    얼마였는지)은 여기서만 볼 수 있다.
            _log.warning("답변 생성 실패 bot_id=%s: %s", req.bot_id, e)
            # 🔴 detail 을 <문자열이 아니라 객체>로 준다 (2026-09-09). Spring 이 이 실패를
            #    "Python 이 아프다"(재시도하면 된다)와 갈라야 하는데, 상태코드만으로는 못 가른다.
            #    503 이 지금은 이 자리 하나뿐이라 우연히 신호 노릇을 하지만, 여기 503 이 하나만 더
            #    생기는 순간 조용히 뭉개진다. 그래서 code 를 명시한다.
            #    ⚠️ 이건 API 컨트랙트다. 값을 바꾸면 AiServiceClient 도 함께 고칠 것.
            raise HTTPException(
                503,
                {
                    "code": "GENERATION_INCOMPLETE",
                    "message": "답변을 완성하지 못했습니다. 질문을 더 좁혀서 다시 물어봐 주세요.",
                },
            ) from e

        latency_ms = int((time.perf_counter() - started) * 1000)
        return ChatResponse(
            answer=answer,
            sources=sources,
            is_fallback=is_fallback,
            latency_ms=latency_ms,
        )
    finally:
        metrics.CHAT_INFLIGHT.dec()
        metrics.CHAT_DURATION.observe(time.perf_counter() - started)
```

- [ ] **Step 6: 검사가 통과하는 것을 확인한다**

```bash
cd /Users/cheonjamin/projects/AllDap/ai-service && .venv/bin/python -m app.metrics_check; echo "exit=$?"
```

기대: 앞의 4건 + 아래 5건이 전부 `OK`, `exit=0`

```
  OK   GET /internal/metrics == 200 (200)
  OK   본문에 alldap_anyio_threads_borrowed
  OK   본문에 alldap_anyio_threads_total
  OK   본문에 alldap_chat_duration_seconds
  OK   본문에 alldap_chat_inflight
```

- [ ] **Step 7: 기존 자체 점검이 안 깨졌는지 확인한다**

`chat` 함수를 통째로 다시 쓴 자리라 fallback 경로가 그대로인지 본다.

```bash
cd /Users/cheonjamin/projects/AllDap/ai-service && .venv/bin/python -m loadtest.fake_cf_check; echo "exit=$?"
```

기대: 전부 `OK`, `exit=0`

- [ ] **Step 8: 커밋**

```bash
cd /Users/cheonjamin/projects/AllDap
git add ai-service/app/main.py ai-service/app/metrics_check.py
git commit -m "feat: /internal/metrics 를 내보내고 채팅 처리시간을 계측한다"
```

---

## Task 3: Prometheus 타깃 + Grafana 패널

**Files:**
- Modify: `observability/prometheus.yml`
- Modify: `observability/grafana/dashboards/alldap-api.json`

**Interfaces:**
- Consumes: Task 2 의 `GET /internal/metrics` 와 지표 이름 4개
- Produces: Prometheus job `alldap-ai`(라벨 `job="alldap-ai"`), 대시보드 uid `alldap-api` 에 패널 id 6·7·8

---

- [ ] **Step 1: Prometheus 에 Python 타깃을 추가한다**

`observability/prometheus.yml` 파일 끝(`- targets: ['host.docker.internal:8081']` 다음)에 덧붙인다:

```yaml

  - job_name: alldap-ai
    metrics_path: /internal/metrics
    static_configs:
      # 🔴 여기도 host.docker.internal 이다. Python(uvicorn)도 컨테이너 밖(맥 호스트)에서
      #    돌기 때문에 위 alldap-api 와 <같은 이유>로 localhost 가 아니다.
      #
      # 🔴 경로가 /metrics 가 아니라 /internal/metrics 인 것은 오타가 아니다.
      #    이 저장소는 인증 없는 것을 /internal/* 아래에만 둔다(app/main.py 의
      #    prometheus_metrics docstring 참고).
      - targets: ['host.docker.internal:8001']
```

- [ ] **Step 2: 대시보드에 패널 3개를 추가한다**

`observability/grafana/dashboards/alldap-api.json` 의 `"panels"` 배열에서 `"id": 5` 인 패널의
닫는 `}` **다음**에 쉼표를 두고 아래 셋을 이어 붙인다(배열의 마지막 원소가 된다):

```json
    {
      "id": 6,
      "type": "timeseries",
      "title": "1순위 가설 — anyio 스레드풀 (Python)",
      "description": "borrowed 가 total(40)에 붙고 inflight 가 그 위로 계속 늘면, 늘어난 만큼이 스레드를 못 받고 큐에서 기다리는 요청이다. total 을 함께 그리는 이유: 40 은 우리 설정값이 아니라 anyio 기본값이라 라이브러리를 올리면 조용히 바뀐다.",
      "gridPos": {
        "h": 8,
        "w": 12,
        "x": 0,
        "y": 24
      },
      "targets": [
        {
          "refId": "A",
          "expr": "alldap_anyio_threads_borrowed",
          "legendFormat": "borrowed (쓰는 중)"
        },
        {
          "refId": "B",
          "expr": "alldap_anyio_threads_total",
          "legendFormat": "total (상한)"
        },
        {
          "refId": "C",
          "expr": "alldap_chat_inflight",
          "legendFormat": "inflight (안에 있는 요청)"
        }
      ]
    },
    {
      "id": 7,
      "type": "timeseries",
      "title": "Python 몫 지연 p50 / p95 / p99 (초)",
      "description": "왼쪽 위 Spring 지연 패널과 나란히 읽는다. 둘의 차이가 Spring 왕복(직렬화·Hikari·톰캣 대기)의 몫이다. 이게 없으면 '느린 게 Spring 인가 Python 인가' 를 못 가른다.",
      "gridPos": {
        "h": 8,
        "w": 12,
        "x": 12,
        "y": 24
      },
      "targets": [
        {
          "refId": "A",
          "expr": "histogram_quantile(0.50, sum(rate(alldap_chat_duration_seconds_bucket[1m])) by (le))",
          "legendFormat": "p50"
        },
        {
          "refId": "B",
          "expr": "histogram_quantile(0.95, sum(rate(alldap_chat_duration_seconds_bucket[1m])) by (le))",
          "legendFormat": "p95"
        },
        {
          "refId": "C",
          "expr": "histogram_quantile(0.99, sum(rate(alldap_chat_duration_seconds_bucket[1m])) by (le))",
          "legendFormat": "p99"
        }
      ]
    },
    {
      "id": 8,
      "type": "timeseries",
      "title": "🔴 재시작 경계 — Spring 살아 있은 시간 (초)",
      "description": "process_start_time_seconds 에서 유도한 값이다. 이 선이 0 으로 떨어진 순간이 재시작이고, 2순위 가설(힙 256m + ExitOnOutOfMemoryError)이 맞았다는 뜻이다. 판정 절차: 떨어진 시각이 걸친 단계는 결과 표에 '측정 불가' 로 적고 숫자를 싣지 않는다. 그 단계의 숫자는 '포화' 가 아니라 '재시작 중' 을 잰 것이라, 나란히 놓으면 원인이 다른 두 사실이 같은 값으로 뭉개진다.",
      "gridPos": {
        "h": 8,
        "w": 24,
        "x": 0,
        "y": 32
      },
      "targets": [
        {
          "refId": "A",
          "expr": "time() - process_start_time_seconds{job=\"alldap-api\"}",
          "legendFormat": "Spring uptime (초)"
        }
      ]
    }
```

> **왜 `process_start_time_seconds` 를 그대로 안 그리나.** 그 값은 1.7e9 짜리 유닉스 시각이라
> 12분 창에서는 완전히 평평한 직선으로 보이고, 재시작해도 눈으로 구분이 안 된다.
> `time() - start` 는 <같은 사실>을 쓰면서 재시작을 톱니 모양으로 드러낸다.
> `job="alldap-api"` 라벨을 붙이는 이유: Python 타깃도 같은 이름의 지표를 낼 수 있어
> 필터가 없으면 두 프로세스의 선이 겹쳐 어느 쪽이 죽었는지 못 가른다.

- [ ] **Step 3: JSON 이 깨지지 않았는지 확인한다**

```bash
cd /Users/cheonjamin/projects/AllDap && python3 -c "
import json
d = json.load(open('observability/grafana/dashboards/alldap-api.json'))
ids = [p['id'] for p in d['panels']]
print('panel ids:', ids)
assert ids == [1,2,3,4,5,6,7,8], ids
print('OK')
"
```

기대: `panel ids: [1, 2, 3, 4, 5, 6, 7, 8]` 다음 `OK`

- [ ] **Step 4: Prometheus YAML 이 유효한지 확인한다**

```bash
cd /Users/cheonjamin/projects/AllDap && python3 -c "
import yaml
d = yaml.safe_load(open('observability/prometheus.yml'))
jobs = [j['job_name'] for j in d['scrape_configs']]
print('jobs:', jobs)
assert jobs == ['alldap-api', 'alldap-ai'], jobs
print('OK')
"
```

기대: `jobs: ['alldap-api', 'alldap-ai']` 다음 `OK`

(`yaml` 이 없으면 `python3 -m pip install --user pyyaml` 대신
`cd ai-service && .venv/bin/python` 으로 같은 코드를 돌린다 — pydantic-settings 가 pyyaml 을 끌고 온다.)

- [ ] **Step 5: 살아 있는 스택에 붙여 타깃 2개가 UP 인 것을 확인한다**

터미널 4개가 필요하다. 각각 따로 띄운다.

터미널 A — 관측 스택과 DB:

```bash
cd /Users/cheonjamin/projects/AllDap && docker compose up -d db prometheus grafana && docker compose restart prometheus
```

터미널 B — 가짜 CF:

```bash
cd /Users/cheonjamin/projects/AllDap/ai-service && .venv/bin/python -m loadtest.fake_cf
```

터미널 C — uvicorn (가짜 CF 를 보게 한다):

```bash
cd /Users/cheonjamin/projects/AllDap/ai-service && \
  CF_BASE_URL=http://127.0.0.1:9001 .venv/bin/uvicorn app.main:app --port 8001
```

터미널 D — Spring:

```bash
cd /Users/cheonjamin/projects/AllDap/api && ./gradlew bootRun
```

넷이 다 뜨면 확인한다:

```bash
curl -s http://localhost:9090/api/v1/targets | python3 -c "
import json,sys
d = json.load(sys.stdin)
for t in d['data']['activeTargets']:
    print(t['labels']['job'], t['scrapeUrl'], t['health'], t.get('lastError',''))
"
```

기대:

```
alldap-api http://host.docker.internal:8081/actuator/prometheus up
alldap-ai http://host.docker.internal:8001/internal/metrics up
```

- [ ] **Step 6: 패널에 실제로 값이 들어오는지 본다**

```bash
curl -s 'http://localhost:9090/api/v1/query?query=alldap_anyio_threads_total' | python3 -c "
import json,sys; d=json.load(sys.stdin)
print([ (r['metric'].get('job'), r['value'][1]) for r in d['data']['result'] ])
"
```

기대: `[('alldap-ai', '40')]`

브라우저로 `http://localhost:3001` → 대시보드 **AllDap API** 를 열어 패널 6·7·8 이
에러 없이 그려지는지 본다(부하 전이라 6 은 0, 7 은 비어 있는 것이 정상이고,
**8 은 Spring uptime 이 우상향하는 선이어야 한다** — 여기가 비면 뒤의 판정 절차가 아예 안 돈다).

`/targets` 화면(`http://localhost:9090/targets`) 스크린샷을 찍어 둔다 — Task 7 의 산출물이다.

- [ ] **Step 7: 커밋**

```bash
cd /Users/cheonjamin/projects/AllDap
git add observability/prometheus.yml observability/grafana/dashboards/alldap-api.json
git commit -m "feat: Python 지표를 스크레이프하고 두 가설을 같은 시간축에 올린다"
```

---

## Task 4: 로컬 JVM 을 운영과 맞춘다 (`-Ploadtest`)

**Files:**
- Modify: `api/build.gradle` (파일 끝 `processResources { ... }` 블록 다음)
- Modify: `docker-compose.prod.yml:50-56` 근처 (상호 참조 주석)

**Interfaces:**
- Consumes: 없음
- Produces: `./gradlew bootRun -Ploadtest` 로 띄운 JVM 의 힙 상한이 256MB (`jvm_memory_max_bytes{area="heap"}` 합이 약 2.68e8)

---

- [ ] **Step 1: 플래그 없이 지금 힙이 얼마인지 먼저 잰다 (before 를 남긴다)**

> 🔴 **`/actuator/metrics/...` 로는 못 읽는다 — 인증이 걸려 있다.** 이 저장소의 SecurityConfig 가
> actuator 중 `/actuator/prometheus` 와 `/actuator/health` 만 열어두고 나머지는 잠근다.
> `curl .../actuator/metrics/jvm.memory.max` 를 치면 숫자가 아니라
> `{"error":{"code":"AUTHENTICATION_REQUIRED",...}}` 가 온다(실측). 그래서 힙은 **Prometheus 에
> 질의해서** 읽는다. 그 대신 Prometheus 가 한 번은 긁은 뒤여야 하므로, 기동 직후면 15초 기다린다.

Task 3 Step 5 의 터미널 D 에서 돌던 `bootRun` 을 그대로 두고:

```bash
curl -s --get http://localhost:9090/api/v1/query \
  --data-urlencode 'query=sum(jvm_memory_max_bytes{area="heap",job="alldap-api"})' | python3 -c "
import json,sys; r = json.load(sys.stdin)['data']['result']
print(f"heap max = {float(r[0]['value'][1])/1024/1024:.0f} MB" if r else 'FAIL — Prometheus 가 아직 안 긁었다(15초 기다릴 것)')
"
```

기대: 맥 RAM 의 1/4 (기가 단위, 예: `heap max = 8192 MB`).
**이 숫자를 적어둔다** — 결과 문서에 "고치기 전에는 이랬다" 로 들어간다.

이 값이 256MB 근처면 뭔가 이미 걸려 있는 것이다. 그 원인을 찾기 전에는 다음으로 가지 않는다
(뭐가 힙을 정하고 있는지 모르는 채로 재면 2순위 가설을 못 판정한다).

- [ ] **Step 2: `api/build.gradle` 에 블록을 추가한다**

파일 맨 끝(`processResources { ... }` 블록 다음)에 덧붙인다:

```gradle

/*
 * 부하테스트용: 로컬 bootRun 을 <운영과 같은 자원 한도>로 돌린다.
 *
 * 왜 필요한가 — 이게 없으면 가설 하나가 링에 오르지도 못한다
 * ─────────────────────────────────────────────────────────────────────────
 * S2(breakpoint)가 판정해야 하는 가설은 둘이다:
 *   1순위 — Python anyio 스레드풀 40 이 먼저 찬다
 *   2순위 — 그보다 Spring 힙 256m 이 먼저 마른다
 * 그런데 로컬 Spring 은 컨테이너 밖(맥 호스트)에서 gradle 로 돈다
 * (observability/prometheus.yml 주석 참고). 즉 JVM 기본 힙 = 맥 RAM 의 1/4 로,
 * 기가 단위다. 그대로 재면 힙은 <절대 안 마르고> 결론은 언제나 "Python 이 먼저다" 가 된다 —
 * 그게 사실이어서가 아니라 <상대 가설을 링에 올리지도 않았기> 때문에.
 * 부하테스트의 목적은 맞히는 게 아니라 틀리는 걸 보는 것이다.
 *
 * 🔴 -Ploadtest 옵트인이다. 무조건 걸면 평소 개발에서도 힙이 256m 이 되어
 *    문서 업로드·임베딩이 엉뚱하게 죽는다. 측정을 위한 제약이 일상을 망가뜨리는 자리라
 *    조건을 붙인다.
 *
 * 실행: ./gradlew bootRun -Ploadtest
 */
tasks.named('bootRun') {
	if (project.hasProperty('loadtest')) {
		// 🔴 docker-compose.prod.yml 의 JAVA_OPTS 와 <반드시 같은 값이어야 한다.>
		//    한쪽만 바뀌면 로컬이 운영을 대변하지 못하게 되는데, 그게 <조용히> 일어난다
		//    (provenance: false 를 같은 방식으로 처리한 선례가 있다).
		//    거기를 고치는 사람이 여기를 보게 하려고 양쪽에 서로를 가리키는 주석을 뒀다.
		jvmArgs = [
			'-Xms192m',
			'-Xmx256m',
			'-XX:MaxMetaspaceSize=128m',
			'-XX:+ExitOnOutOfMemoryError',
		]

		// 🔴 optimizedLaunch 를 끈다. bootRun 은 기본으로 -XX:TieredStopAtLevel=1 을 붙여
		//    JIT 을 C1 에서 멈춘다(기동을 1초쯤 줄이려는 옵션이다. 플러그인 4.0.7 의
		//    BootRun.class 를 열어 확인했다).
		//    12분 동안 수천 건을 처리하는 측정에서 이걸 켜두면 <운영보다 훨씬 느린 JVM>을 재게 되고,
		//    "어디서 꺾이는가" 가 통째로 아래 단계로 밀린다. 그 숫자가 이 PR 의 산출물이다.
		//    측정에서는 기동 1초보다 정확한 곡선이 중요하다.
		optimizedLaunch = false
	}
}
```

- [ ] **Step 3: 운영 쪽에 되가리키는 주석을 남긴다**

`docker-compose.prod.yml` 에서 `JAVA_OPTS: >-` 바로 **위** 줄
(`#    restart 정책이 다시 띄우는 편이 <반쯤 죽은 채로 응답하는 것>보다 낫다.` 다음)에
다음 두 줄을 끼워 넣는다:

```yaml
      #    ⚠️ api/build.gradle 의 bootRun(-Ploadtest) 블록이 <이 네 값을 그대로> 복제한다.
      #       부하테스트가 운영을 대변하려면 둘이 같아야 한다. 여기를 바꾸면 거기도 바꿀 것.
```

- [ ] **Step 3b: 서버를 띄우기 전에, 설정된 값을 gradle 에게 직접 물어본다**

🔴 **`./gradlew help -Ploadtest` 나 `tasks --dry-run` 으로는 이 블록을 검증할 수 없다.**
gradle 은 configuration avoidance 라 `tasks.named('bootRun') { ... }` 안이 **bootRun 이 실제로
realize 될 때까지 한 줄도 실행되지 않는다.** 즉 블록 안에 `optimizedLaunche = false` 같은 오타를
넣어도 `help` 는 `BUILD SUCCESSFUL` 을 낸다(실측 확인: 아래 명령의 PROBE 줄이 `help` 에서는 0줄이다).
**이 저장소가 이미 두 번 걸린 부류다 — 검사를 안 짠 것이 아니라 짜둔 검사가 아무 데서도 안 돈 것**
(오픈 리다이렉트, 배포 rate limit 점검 명령).

읽기 전용 init script 로 **실제 설정된 값**을 찍는다. 저장소 파일은 건드리지 않는다.

```bash
cat > /tmp/probe-bootrun.gradle <<'EOF'
gradle.projectsEvaluated {
    rootProject.tasks.named('bootRun').configure { t ->
        println "PROBE optimizedLaunch=" + t.optimizedLaunch.get()
        println "PROBE jvmArgs=" + t.jvmArgs
    }
}
EOF
cd /Users/cheonjamin/projects/AllDap/api
echo "--- with -Ploadtest ---"
./gradlew -q -I /tmp/probe-bootrun.gradle bootRun --dry-run -Ploadtest 2>&1 | grep -E "PROBE|bootRun"
echo "--- without flag ---"
./gradlew -q -I /tmp/probe-bootrun.gradle bootRun --dry-run 2>&1 | grep -E "PROBE|bootRun"
```

기대:

```
--- with -Ploadtest ---
PROBE optimizedLaunch=false
PROBE jvmArgs=[-Xms192m, -Xmx256m, -XX:MaxMetaspaceSize=128m, -XX:+ExitOnOutOfMemoryError]
:bootRun SKIPPED
--- without flag ---
PROBE optimizedLaunch=true
PROBE jvmArgs=[]
:bootRun SKIPPED
```

`--dry-run` 이라 **bootRun 은 `SKIPPED` 다 — 서버가 뜨지 않는다.** 그래서 이 검사는 스택을
띄우기 전에 돌릴 수 있고, 오타를 여기서 잡으면 아래 Step 4~6 의 왕복을 통째로 아낀다.

운영 값과 글자까지 같은지도 여기서 대조한다:

```bash
cd /Users/cheonjamin/projects/AllDap && python3 -c "
import yaml
d = yaml.safe_load(open('docker-compose.prod.yml'))
opts = d['services']['api']['environment']['JAVA_OPTS'].split()
expected = ['-Xms192m', '-Xmx256m', '-XX:MaxMetaspaceSize=128m', '-XX:+ExitOnOutOfMemoryError']
print('JAVA_OPTS =', opts)
assert opts == expected, f'운영과 다르다: {opts} != {expected}'
print('OK — build.gradle 의 jvmArgs 네 개와 같아야 한다(위 PROBE 줄과 눈으로 대조)')
"
```

- [ ] **Step 4: 플래그가 실제로 먹는지 실행해서 확인한다**

Task 3 의 터미널 D 에서 돌던 `bootRun` 을 `Ctrl+C` 로 끄고, 플래그를 붙여 다시 띄운다:

```bash
cd /Users/cheonjamin/projects/AllDap/api && ./gradlew bootRun -Ploadtest
```

기동이 끝나면 다른 터미널에서:

```bash
curl -s --get http://localhost:9090/api/v1/query \
  --data-urlencode 'query=sum(jvm_memory_max_bytes{area="heap",job="alldap-api"})' | python3 -c "
import json,sys; r = json.load(sys.stdin)['data']['result']
mb = float(r[0]['value'][1])/1024/1024 if r else -1
print(f'heap max = {mb:.0f} MB')
print('OK' if 200 <= mb <= 280 else 'FAIL — 플래그가 안 먹었다')
"
```

기대: `heap max = 256 MB` (G1 이 영역을 잘라 248~256 사이로 나올 수 있다) 다음 `OK`

> 🔴 여기서 `FAIL` 이 나면 **다음 태스크로 가지 않는다.** 플래그가 안 먹은 채로 측정하면
> 2순위 가설이 조용히 링에서 빠지고, 결과 문서는 "Python 이 먼저다" 라고 <틀리게> 적힌다.

- [ ] **Step 5: TieredStopAtLevel 이 실제로 빠졌는지 확인한다**

```bash
ps -Ao pid,command | grep -i "[A]llDap\|[b]ootRun\|[c]om.alldap" | grep java | head -3
```

나온 PID 로:

```bash
jcmd <PID> VM.flags | tr ' ' '\n' | grep -i "TieredStopAtLevel\|MaxHeapSize\|ExitOnOutOfMemory\|MaxMetaspaceSize"
```

기대:
- `-XX:MaxHeapSize=268435456` 가 있다
- `-XX:+ExitOnOutOfMemoryError` 가 있다
- `-XX:MaxMetaspaceSize=134217728` 이 있다
- **`TieredStopAtLevel` 은 없다** (있으면 `optimizedLaunch = false` 가 안 먹은 것이다)

- [ ] **Step 6: 플래그 없이 띄우면 원래대로인지 확인한다 (옵트인이 옵트인인가)**

`bootRun` 을 끄고 플래그 없이 다시 띄운다:

```bash
cd /Users/cheonjamin/projects/AllDap/api && ./gradlew bootRun
```

```bash
curl -s --get http://localhost:9090/api/v1/query \
  --data-urlencode 'query=sum(jvm_memory_max_bytes{area="heap",job="alldap-api"})' | python3 -c "
import json,sys; r = json.load(sys.stdin)['data']['result']
mb = float(r[0]['value'][1])/1024/1024 if r else -1
print(f'heap max = {mb:.0f} MB')
print('OK — 옵트인이 지켜진다' if mb > 500 else 'FAIL — 플래그가 무조건 걸리고 있다')
"
```

기대: Step 1 에서 적어둔 기가 단위 값 그대로, `OK — 옵트인이 지켜진다`

그다음 **다시 `-Ploadtest` 로 띄워둔다** (Task 7 의 실행이 이 상태를 전제한다).

- [ ] **Step 7: 커밋**

```bash
cd /Users/cheonjamin/projects/AllDap
git add api/build.gradle docker-compose.prod.yml
git commit -m "feat: 부하테스트에서만 로컬 힙을 운영과 같게 맞춘다"
```

---

## Task 5: k6 시나리오 (`s2_breakpoint.js`)

**Files:**
- Create: `ai-service/loadtest/s2_breakpoint.js`

**Interfaces:**
- Consumes: 환경변수 `BOT_ID`·`RUN_ID` (Task 6 의 `s2_context.py before` 가 인쇄한다), `API`·`EMAIL`·`PASSWORD`·`OUT`·`DRYRUN`
- Produces: `OUT` 이 가리키는 k6 summary JSON. Task 6 의 `after` 와 이 파일의 `handleSummary` 가 다음 키를 읽는다(전부 `metrics[<키>].values.<필드>` 모양이다):
  - `metrics["chat_status{status:200}"].values.count` — 전체 2xx 건수 (`cmd_after` 가 쓴다)
  - `metrics["chat_fallback"].values.count` — fallback 총계 (`cmd_after` 가 쓴다)
  - `metrics["chat_duration{stage:<VU>,phase:measure}"].values` — 단계별 `count`·`min`·`med`·`p(95)`·`p(99)`·`max`·`avg`
  - `metrics["chat_status{stage:<VU>,status:<code>}"].values.count` — 단계별 상태코드
  - 🔴 이 서브지표 이름들은 `options.thresholds` 에 등록해야만 summary 에 생긴다. 임계값을 지우면 Task 6 이 조용히 0 을 읽는다.

---

- [ ] **Step 1: k6 를 설치한다**

```bash
brew install k6 && k6 version
```

기대: `k6 v2.2.0 (commit/devel, go1.26.5, darwin/arm64)` 같은 줄 (설치 전에는 `k6 not found` 다).

> ⚠️ **brew 가 주는 것은 v0.5x 가 아니라 v2.x 다.** 이 계획서는 **v2.2.0 에서 실측 확인**했다.
> v2 에서 이 PR 에 영향을 주는 차이는 둘뿐이다:
> - `k6 inspect` 가 시스템 환경변수를 기본으로 안 넘긴다 (Step 3b 참고). `k6 run` 은 기본 넘긴다.
> - `--new-machine-readable-summary` 라는 **다른 모양의 summary** 가 플래그로 있다.
>   🔴 **본 실행에서 그 플래그를 붙이지 말 것.** 붙이면 `metrics[키].values.필드` 구조가 바뀌어
>   `s2_context.py after` 가 키를 못 찾고 **에러 없이 0 을 읽는다.** 기본값이 옛 모양이고,
>   Task 6 이 그 모양을 전제한다.

- [ ] **Step 2: 시나리오를 쓴다**

`ai-service/loadtest/s2_breakpoint.js` 를 새로 만든다:

```javascript
// S2 breakpoint — 어디서 선형성이 깨지는가, 그때 무엇이 포화됐는가.
//
// 실행 (직접 부르지 말고 s2_context.py 가 인쇄한 값을 넣는다):
//   cd ai-service && \
//     BOT_ID=<...> RUN_ID=<...> OUT=loadtest/results/S2-<runId>.json \
//     k6 run loadtest/s2_breakpoint.js
//
// 🔴 <중단하지 않는다.> S1 드라이버(s1_baseline.py:42)는 비200 이 하나라도 나오면
//    즉시 멈추지만, S2 에 그 규칙을 물려주면 정확히 반대로 작동한다. S2 는 깨지는
//    지점을 찾는 시나리오라 5xx·타임아웃·연결끊김이 <찾으려는 결과 그 자체>다.
//    특히 2순위 가설(힙 256m + ExitOnOutOfMemoryError)이 맞으면 증상이 "끊기고
//    30초쯤 뒤 돌아온다" 인데, S1 규칙이면 <가설이 맞는 순간 드라이버가 자살하고
//    그 뒤를 못 본다.> 80 까지 끝까지 밀고, 판정은 전부 사후에 파일로 한다.

import http from 'k6/http';
import exec from 'k6/execution';
import { Counter, Trend } from 'k6/metrics';

const API      = __ENV.API      || 'http://localhost:8080';
const EMAIL    = __ENV.EMAIL    || __ENV.LOADTEST_EMAIL    || 'loadtest@example.com';
const PASSWORD = __ENV.PASSWORD || __ENV.LOADTEST_PASSWORD;
const BOT_ID   = __ENV.BOT_ID;
const RUN_ID   = __ENV.RUN_ID;
const OUT      = __ENV.OUT || 'loadtest/results/S2-unnamed.json';

// 🔴 예비 실행 스위치. k6 는 options.scenarios 가 있으면 --vus/--duration/--stage 를
//    <조용히 무시한다> — 명령줄로 30초 예비 실행을 만들려다 12분을 돌리게 되는 자리다.
//    그래서 스위치를 스크립트 안에 둔다. 본 실행과 <같은 파일·같은 코드경로>를 타야
//    예비 실행이 본 실행의 오염을 대신 걸러줄 수 있다.
const DRYRUN = __ENV.DRYRUN === '1';

// 계단식 6단계. 램프를 두지 않는다 — 꺾이는 지점이 단계 경계에 맞아떨어져야
// "20 은 버텼고 40 에서 깨졌다" 를 표로 읽을 수 있다. 램프를 두면 꺾임이 두 단계
// 사이로 번지고, 이 PR 의 산출물이 정확히 그 숫자다.
const STAGES = DRYRUN ? [1] : [1, 5, 10, 20, 40, 80];
const HOLD_S = DRYRUN ? 30 : 120;

// 🔴 각 단계 앞 20초는 집계에서 잘라낸다. 계단식이라 전환 순간 폭주가 있고
//    Prometheus scrape 이 15초라 점 1~2개 분량이다. 잘라내지 않으면
//    "20 단계 p99" 에 전환 충격이 섞인다.
//    ⚠️ 예비 실행은 0 이다. 30초 중 20초를 버리면 표본이 6건쯤 남아 표가 비어 보이는데,
//       예비 실행이 보려는 것은 지연이 아니라 <오염>(fallback·경로 미탐)이라 버릴 이유가 없다.
const WARMUP_MS = DRYRUN ? 0 : 20000;

// 🔴 상태코드별로 <따로> 센다. 처리량 곡선은 2xx 만이다.
//    5xx 를 처리량에 섞으면 "빨라졌다"(빨리 실패한 것)가 개선으로 보인다.
const WATCHED_STATUS = [200, 0, 429, 500, 502, 503, 504];  // 0 = 연결 실패·타임아웃

// 🔴 질문은 S1 이 쓴 5개를 <그대로> 쓴다. eval_questions 테이블 원문이다.
//    S1 은 손으로 적었다가 테이블 문항과 16건 중 완전 일치 0건이었고, 5건 예행에서
//    2건이 fallback 났다 — 회귀가 아니라 <다른 질문을 던진 것>이었다.
//    fallback 은 LLM 을 안 타 0.1초에 끝나므로, 섞이면 재려던 곡선이 통째로 거짓이 된다.
//    (리랭커가 정답 청크를 밀어내는 알려진 2건과 코퍼스에 정답이 없는 1건은
//     S1 이 근거를 적어 빼놨다. 여기서 새로 적으면 그 판단이 사라진다.)
const QUESTIONS = [
  '정규직으로 새로 들어온 직원의 시용 기간은 얼마나 되나요?',
  '정규직의 업무용 컴퓨터를 바꿀 수 있는 주기는 얼마나 되나요?',
  '정규직이 결혼할 때 쉴 수 있는 날이 며칠인가요?',
  '정규직 기준으로 회사의 플라스틱 카드는 어떤 직급부터 쓸 수 있나요?',
  '정규직이 쌍둥이를 낳았을 때 아빠가 쓸 수 있는 휴가는 며칠인가요?',
];

const chatDuration  = new Trend('chat_duration', true);
const chatStatus    = new Counter('chat_status');
const chatFallback  = new Counter('chat_fallback');

// ── 시나리오와 임계값을 프로그램으로 만든다 ────────────────────────────
//
// ⚠️ thresholds 는 <판정용이 아니다.> k6 는 서브지표(chat_duration{stage:20,...})를
//    summary 에 넣어주지 않는데, 임계값을 걸어두면 그 이름이 summary 에 생긴다.
//    그래서 항상 참인 식(`p(99)>=0`)을 건다. 이 PR 은 SLO 를 정하지 않으므로
//    <실패할 수 있는 임계값은 하나도 두지 않는다> — 두면 k6 가 종료코드로 판정을
//    내리게 되고, 판정은 전부 사후에 사람이 하는 것이 이 PR 의 규칙이다.
const scenarios = {};
const thresholds = {
  'chat_status{status:200}': ['count>=0'],
  'chat_fallback': ['count>=0'],
};

STAGES.forEach((vus, i) => {
  scenarios[`vu${vus}`] = {
    executor: 'constant-vus',
    vus: vus,
    duration: `${HOLD_S}s`,
    // startTime 이 <절대 시각>이라 단계가 밀리지 않는다. 앞 단계가 늦게 끝나도
    // 다음 단계는 정해진 초에 시작한다 — 결과 표의 "몇 분대가 몇 VU 였나" 가 어긋나면
    // Grafana 시간축과 대조할 수 없다.
    startTime: `${i * HOLD_S}s`,
    exec: 'chat',
    // think time 없는 closed loop. 설계서의 "동시 사용자 N" 을 항상 N건 in-flight 으로
    // 읽는다. 생각시간을 넣으면 breakpoint 탐색에서 부하가 흐려진다.
    tags: { stage: String(vus) },
  };
  thresholds[`chat_duration{stage:${vus},phase:measure}`] = ['p(99)>=0'];
  thresholds[`chat_duration{stage:${vus},phase:warmup}`]  = ['p(99)>=0'];
  thresholds[`chat_fallback{stage:${vus}}`] = ['count>=0'];
  WATCHED_STATUS.forEach((code) => {
    thresholds[`chat_status{stage:${vus},status:${code}}`] = ['count>=0'];
  });
});

export const options = {
  scenarios: scenarios,
  thresholds: thresholds,
  // 🔴 기본 요약은 p90·p95 만 보여주고 p99 가 안 나온다. 이 PR 의 판정 근거가 p95·p99 다.
  //    avg 는 표에 싣되 판정에 쓰지 않는다(평균은 느린 꼬리를 감춘다).
  summaryTrendStats: ['min', 'med', 'p(95)', 'p(99)', 'max', 'avg'],
  // 응답 본문을 버리지 않는다 — isFallback 을 읽어야 한다.
  discardResponseBodies: false,
};

export function setup() {
  // 🔴 하드코딩된 기본값을 두지 않는다. 봇을 지우고 다시 만들면 id 가 바뀌는데,
  //    기본값이 있으면 그때 <다른 코퍼스를 가진 봇>을 조용히 재게 되고
  //    "그때 뭘로 쟀지" 를 못 답한다. 없으면 죽는다.
  if (!BOT_ID) {
    throw new Error('BOT_ID 가 없다. s2_context.py before 가 인쇄한 값을 넣을 것.');
  }
  // 🔴 RUN_ID 가 없으면 세션 id 가 실행끼리 섞인다. S1 이 s1-{i} 를 재사용해
  //    집계가 LIKE 67건 / 시각 66건으로 갈렸다. S2 는 단계당 수천 건이라
  //    같은 구조면 <단계 경계가 뭉개진다>.
  if (!RUN_ID) {
    throw new Error('RUN_ID 가 없다. s2_context.py before 가 인쇄한 값을 넣을 것.');
  }

  // 로그인 1회. 토큰을 재사용한다 — 로그인에도 분당 제한이 있다.
  const res = http.post(
    `${API}/api/auth/login`,
    JSON.stringify({ email: EMAIL, password: PASSWORD }),
    { headers: { 'Content-Type': 'application/json' } },
  );
  if (res.status !== 200) {
    throw new Error(`로그인 실패 ${res.status}: ${String(res.body).slice(0, 200)}`);
  }
  return { token: res.json('token') };
}

export function chat(data) {
  const stage = exec.scenario.name.slice(2);   // 'vu20' → '20'
  const elapsed = Date.now() - exec.scenario.startTime;
  const phase = elapsed < WARMUP_MS ? 'warmup' : 'measure';

  const question = QUESTIONS[exec.scenario.iterationInTest % QUESTIONS.length];
  // 🔴 세션 id 는 실행·VU·반복이 전부 들어가야 한다. 하나라도 빠지면 다른 단계의
  //    대화가 같은 세션으로 합쳐진다.
  const sessionId = `s2-${RUN_ID}-${exec.vu.idInTest}-${exec.vu.iterationInScenario}`;

  const res = http.post(
    `${API}/api/bots/${BOT_ID}/chat`,
    JSON.stringify({ message: question, sessionId: sessionId }),
    {
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${data.token}`,
      },
      // 🔴 기본 60초로 두면 2순위 가설의 증상("끊기고 30초쯤 뒤 돌아온다")이
      //    타임아웃에 잘려 <연결 실패>로만 보인다. 넉넉히 준다.
      timeout: '120s',
      tags: { stage: stage, phase: phase, name: 'chat' },
    },
  );

  chatStatus.add(1, { stage: stage, status: String(res.status) });

  if (res.status === 200) {
    chatDuration.add(res.timings.duration, { stage: stage, phase: phase });
    // 🔴 fallback 이 0 이 아니면 그 요청들은 LLM 경로를 안 탄 것이고, 그 실행은 무효다.
    //    어느 질문이 걸렸는지까지 남긴다 — 개수만으로는 못 고친다.
    let isFallback = false;
    try {
      isFallback = res.json('isFallback') === true;
    } catch (e) {
      isFallback = false;   // 본문이 JSON 이 아니면 fallback 판정을 할 수 없다
    }
    if (isFallback) {
      chatFallback.add(1, { stage: stage, question: question });
    }
  }
}

// 사후 판정에 쓸 표를 stdout 으로도 찍는다. 12분을 기다린 사람이 파일을 열기 전에
// "몇 단계에서 꺾였나" 를 먼저 보게 하려는 것이다.
export function handleSummary(data) {
  const num = (v) => (typeof v === 'number' ? v.toFixed(0) : '-');
  const lines = [
    '',
    `S2 breakpoint — runId=${RUN_ID}  botId=${BOT_ID}`,
    '단계  표본   p50      p95      p99      max      2xx     비2xx   fallback',
  ];
  STAGES.forEach((vus) => {
    const t = (data.metrics[`chat_duration{stage:${vus},phase:measure}`] || {}).values || {};
    let ok = 0;
    let bad = 0;
    WATCHED_STATUS.forEach((code) => {
      const m = data.metrics[`chat_status{stage:${vus},status:${code}}`];
      const c = m && m.values ? (m.values.count || 0) : 0;
      if (code === 200) { ok += c; } else { bad += c; }
    });
    const fb = data.metrics[`chat_fallback{stage:${vus}}`];
    const fbc = fb && fb.values ? (fb.values.count || 0) : 0;
    lines.push(
      `${String(vus).padStart(3)}  ` +
      `${String(num(t.count)).padStart(5)}  ` +
      `${String(num(t.med)).padStart(7)}  ` +
      `${String(num(t['p(95)'])).padStart(7)}  ` +
      `${String(num(t['p(99)'])).padStart(7)}  ` +
      `${String(num(t.max)).padStart(7)}  ` +
      `${String(ok).padStart(6)}  ` +
      `${String(bad).padStart(6)}  ` +
      `${String(fbc).padStart(8)}`,
    );
  });
  lines.push('');
  lines.push('🔴 위 숫자는 아직 <판정이 아니다.> s2_context.py after 로 가짜 CF 호출 수를');
  lines.push('   대조하고, Grafana 재시작 경계 패널을 본 뒤에야 표로 옮길 수 있다.');
  lines.push('');

  const out = {};
  out.stdout = lines.join('\n');
  out[OUT] = JSON.stringify(data, null, 2);
  return out;
}
```

- [ ] **Step 3: 문법과 시나리오 배치를 실행 없이 확인한다**

```bash
cd /Users/cheonjamin/projects/AllDap/ai-service && \
  k6 inspect loadtest/s2_breakpoint.js | python3 -c "
import json, re, sys

def secs(v):
    'k6 가 120s 로도 2m0s 로도 인쇄할 수 있어 둘 다 받는다.'
    total = 0
    for n, unit in re.findall(r'(\d+(?:\.\d+)?)(h|m|s|ms)', str(v)):
        total += float(n) * {'h': 3600, 'm': 60, 's': 1, 'ms': 0.001}[unit]
    return total

sc = json.load(sys.stdin)['scenarios']
rows = sorted(((secs(s['startTime']), name, s['vus'], secs(s['duration']), s['tags']['stage'])
               for name, s in sc.items()))
for start, name, vus, dur, tag in rows:
    print(f'{name:5} vus={vus:<3} start={start:>4.0f}s dur={dur:>4.0f}s stage={tag}')

assert [r[2] for r in rows] == [1, 5, 10, 20, 40, 80], '단계 순서가 다르다'
assert all(r[3] == 120 for r in rows), '유지 시간이 120초가 아니다'
assert [r[0] for r in rows] == [0, 120, 240, 360, 480, 600], '단계가 겹치거나 벌어졌다'
assert [r[4] for r in rows] == ['1', '5', '10', '20', '40', '80'], 'stage 태그가 VU 와 다르다'
print('OK — 총 12분, 단계가 겹치지 않는다')
"
```

기대:

```
vu1   vus=1   start=   0s dur= 120s stage=1
vu5   vus=5   start= 120s dur= 120s stage=5
vu10  vus=10  start= 240s dur= 120s stage=10
vu20  vus=20  start= 360s dur= 120s stage=20
vu40  vus=40  start= 480s dur= 120s stage=40
vu80  vus=80  start= 600s dur= 120s stage=80
OK — 총 12분, 단계가 겹치지 않는다
```

- [ ] **Step 3b: `DRYRUN=1` 이 단계 하나로 줄어드는지 확인한다**

🔴 **`--include-system-env-vars` 를 빼면 안 된다.** k6 v2 의 `inspect` 는 시스템 환경변수를
기본으로 **넘기지 않는다**(`run` 은 기본 true 인데 `inspect` 만 다르다). 빼고 치면 `DRYRUN=1` 이
조용히 무시돼 6단계가 그대로 나오고, 어서션이 `dict_keys(['vu1','vu10',...])` 로 깨진다.
`k6 inspect -e DRYRUN=1 ...` 도 같은 효과다(둘 중 아무거나).

```bash
cd /Users/cheonjamin/projects/AllDap/ai-service && \
  DRYRUN=1 k6 inspect --include-system-env-vars loadtest/s2_breakpoint.js | python3 -c "
import json, sys
sc = json.load(sys.stdin)['scenarios']
print(sorted(sc.keys()), [s['vus'] for s in sc.values()], [s['duration'] for s in sc.values()])
assert len(sc) == 1, sc.keys()
print('OK')
"
```

기대: `['vu1'] [1] ['30s']` 다음 `OK`

> 🔴 이 검사가 있어야 하는 이유: k6 는 `options.scenarios` 가 있으면 `--vus`·`--duration`·
> `--stage` 를 **경고 없이 무시한다.** 명령줄로 예비 실행을 만들려고 하면 30초를 기대하고
> 12분을 돌리게 되고, 그 12분은 <오염된 채로> 돌아간 본 실행이 되어 버린다.

- [ ] **Step 4: 환경변수 가드가 실제로 죽는지 확인한다**

```bash
cd /Users/cheonjamin/projects/AllDap/ai-service && \
  k6 run --quiet loadtest/s2_breakpoint.js > /tmp/s2-guard.log 2>&1; \
  echo "exit=$?"; grep -o 'BOT_ID 가 없다.*' /tmp/s2-guard.log
```

기대: `exit=` 가 0 이 아니고(k6 는 setup 예외에 107 을 준다), 그 아래
`BOT_ID 가 없다. s2_context.py before 가 인쇄한 값을 넣을 것.` 이 보인다.
setup() 에서 죽으므로 12분을 기다릴 일은 없다 — 몇 초 안에 끝난다.

> 이 검사가 중요한 이유: 가드가 없으면 `undefined` 가 URL 에 박혀 12분 내내 404 를 재고,
> 그 실행은 파일만 보면 "전부 실패" 로 남아 원인을 못 가른다.

- [ ] **Step 5: 커밋**

```bash
cd /Users/cheonjamin/projects/AllDap
git add ai-service/loadtest/s2_breakpoint.js
git commit -m "feat: 계단식 6단계 S2 시나리오를 중단 없이 끝까지 민다"
```

---

## Task 6: 시작 조건 파일과 사후 대조 (`s2_context.py`)

**Files:**
- Create: `ai-service/loadtest/s2_context.py`

**Interfaces:**
- Consumes: Task 5 의 k6 summary JSON 키 (위 Task 5 Interfaces 참고), `app.config.get_settings()`, `app.db.cursor`, `loadtest.fake_cf.LATENCY_MS`
- Produces:
  - `loadtest/results/S2-<runId>-context.json` — `{commit, started_at, run_id, bot, corpus, settings, fake_cf_latency_ms, cf_stats_before, expected_cf_calls_per_request}`
  - `loadtest/results/S2-<runId>-verdict.json` — `{cf_delta, requests_2xx, actual_calls_per_request, expected_calls_per_request, fallbacks, verdicts: [...], valid: bool}`
  - stdout 에 `BOT_ID=<uuid>` 와 `RUN_ID=<runId>` 한 줄씩 (실행 절차가 그대로 복사한다)

---

- [ ] **Step 1: 스크립트를 쓴다**

`ai-service/loadtest/s2_context.py` 를 새로 만든다:

```python
"""S2 실행의 <시작 조건>을 파일로 찍고, 실행 뒤 <경로를 진짜 탔는지> 대조한다.

실행:
    # 실행 전 — 봇을 고르고 조건을 남긴다. 인쇄된 두 줄을 k6 에 그대로 넘긴다.
    cd ai-service && .venv/bin/python -m loadtest.s2_context before \\
        --run-id 2026-09-10-1
    (계정은 LOADTEST_EMAIL·LOADTEST_PASSWORD 에서 온다. loadtest/account.py 가 먼저다)

    # 실행 후 — 가짜 CF 호출 수를 요청 수와 맞춰본다.
    cd ai-service && .venv/bin/python -m loadtest.s2_context after \\
        --run-id 2026-09-10-1 --k6-summary loadtest/results/S2-2026-09-10-1.json

왜 이 파일이 있는가
─────────────────────────────────────────────────────────────────────────────
"그때 뭘로 쟀지" 를 못 답하는 측정은 재현할 수 없고, 재현할 수 없으면 측정이 아니다
(s1_baseline._conditions 와 같은 근거다).

S2 는 여기에 하나를 더 얹는다 — <경로를 진짜 탔는지>. k6 가 200 을 받았다는 것만으로는
그 요청이 embed·rerank·generate 를 다 지났는지 알 수 없다. 캐시·조기 반환·설정 착오로
경로를 건너뛰어도 200 은 200 이다. 가짜 CF 의 호출 수를 실행 전후로 빼면 그게 드러난다.

🔴 기대 배수를 상수로 박지 않는다. reranker_enabled 가 켜져 있으면 요청당 3건
   (embed·rerank·generate), 꺼져 있으면 2건이다. 상수로 박으면 설정을 바꾼 날
   <정상 실행이 무효로 판정된다> — 그리고 그건 "경로를 안 탔다" 와 구분이 안 된다.

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

RESULTS = Path(__file__).parent / "results"


def _context_path(run_id: str) -> Path:
    return RESULTS / f"S2-{run_id}-context.json"


def _verdict_path(run_id: str) -> Path:
    return RESULTS / f"S2-{run_id}-verdict.json"


def _cf_counts(ai_base: str) -> dict[str, int]:
    """모델별 <호출 수>만 뽑는다. 백분위·뉴런은 이 PR 이 쓰지 않는다."""
    resp = httpx.get(f"{ai_base}/internal/debug/cf-stats", timeout=30.0)
    resp.raise_for_status()
    return {model: int(row.get("count", 0)) for model, row in resp.json().items()}


def _pick_bot(bots: list[dict]) -> dict:
    """봇을 <규칙으로> 고른다. 사람이 고르면 다음 실행에서 다른 봇을 고를 수 있다.

    🔴 문서가 가장 많은 봇을 쓴다. 부하테스트가 재려는 것은 <실제 코퍼스를 가진 봇>의
       검색·생성 경로이고, 문서 0건 봇을 고르면 게이트에서 막혀 전부 fallback 이 난다.
       동점이면 먼저 만들어진 쪽 — 규칙에 임의성이 남으면 재현이 안 된다.
    """
    if not bots:
        raise SystemExit("중단: 이 계정에 봇이 없다.")
    return sorted(bots, key=lambda b: (-b["documentCount"], b["createdAt"]))[0]


def _corpus(bot_id: str) -> dict:
    """코퍼스 크기. API 가 아니라 DB 에서 직접 센다 — 청크 수는 API 가 안 준다."""
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
        # 🔴 이 값들은 <드라이버 프로세스>가 읽은 것이지 요청을 처리한 uvicorn 의 것이 아니다.
        #    둘이 다른 환경변수로 떠 있으면 이 파일은 거짓 조건을 남긴다.
        #    특히 cf_base_url — 가짜 서버를 띄웠던 셸에서 uvicorn 을 재시작하면 그대로 남는다.
        #    진짜 주소면 그 측정은 <진짜 CF 를 태운 것>이고, 하루 한도가 12분에 날아간다.
        "cf_base_url": s.cf_base_url,
    }


def cmd_before(args) -> int:
    from loadtest.fake_cf import LATENCY_MS

    settings = _settings_snapshot()

    # 🔴 가짜 서버를 안 보고 있으면 여기서 멈춘다. 이건 이 PR 에서 <유일하게> 실행 전에
    #    막는 자리다 — 진짜 CF 로 12분을 돌리면 하루 한도가 날아가고 24~33시간 기다린다.
    if "cloudflare.com" in settings["cf_base_url"]:
        print(f"중단: CF_BASE_URL 이 진짜 Cloudflare 다 ({settings['cf_base_url']}). "
              f"가짜 서버(http://127.0.0.1:9001)를 보게 하고 uvicorn 을 다시 띄울 것.")
        return 1

    client = httpx.Client(timeout=60.0)
    resp = client.post(f"{args.api}/api/auth/login",
                       json={"email": args.email, "password": args.password})
    resp.raise_for_status()
    token = resp.json()["token"]

    resp = client.get(f"{args.api}/api/bots", headers={"Authorization": f"Bearer {token}"})
    resp.raise_for_status()
    bot = _pick_bot(resp.json())

    # 리랭커가 꺼져 있으면 rerank 를 안 부른다. 기대 배수를 여기서 <설정으로부터> 정한다.
    expected = 3 if settings["reranker_enabled"] else 2

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
        # 가짜 CF 의 고정 지연. S1 실측 p50 이고 이 PR 은 이 값을 바꾸지 않는다.
        "fake_cf_latency_ms": dict(LATENCY_MS),
        "expected_cf_calls_per_request": expected,
        "cf_stats_before": _cf_counts(args.ai),
        "stages": [1, 5, 10, 20, 40, 80],
        "hold_seconds": 120,
        "warmup_discard_seconds": 20,
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
        verdicts.append("OK   fallback 0건 — 생성 경로를 탔다")
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
        #    5xx 와 재시작은 여기서 판정하지 않는다 — 그건 S2 가 찾으려는 결과 그 자체이고,
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
    # 🔴 계정 기본값은 환경변수에서 온다(loadtest/account.py 의 env_email·env_password).
    #    비밀번호 기본값을 코드에 박으면 그 값이 곧 저장소에 커밋된 비밀번호다.
    parser.add_argument("--email", default=env_email())
    parser.add_argument("--password", default=env_password())
    parser.add_argument("--k6-summary")
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
```

- [ ] **Step 2: `before` 가 도는지 확인한다 (스택이 떠 있는 상태에서)**

Task 3 Step 5 의 터미널 A~D 가 다 떠 있어야 한다(Spring 은 Task 4 대로 `-Ploadtest`).

```bash
cd /Users/cheonjamin/projects/AllDap/ai-service && \
  .venv/bin/python -m loadtest.s2_context before \
    --run-id smoke
```

기대: JSON 이 찍히고 맨 아래 두 줄이

```
BOT_ID=628d2785-a128-486c-a1ac-556f19f06de3
RUN_ID=smoke
```

**그리고 JSON 안에서 다음 셋을 눈으로 확인한다:**
- `settings.cf_base_url` 이 `http://127.0.0.1:9001` (진짜 Cloudflare 면 스크립트가 이미 멈췄어야 한다)
- `corpus.chunks` 가 300 근처 (평가 봇은 50문서 306청크다)
- `expected_cf_calls_per_request` 가 `3` (리랭커 기본 ON)

- [ ] **Step 3: 진짜 CF 가드가 도는지 확인한다**

```bash
cd /Users/cheonjamin/projects/AllDap/ai-service && \
  CF_BASE_URL=https://api.cloudflare.com/client/v4 .venv/bin/python -m loadtest.s2_context before \
    --run-id guard-check; echo "exit=$?"
```

기대: `중단: CF_BASE_URL 이 진짜 Cloudflare 다 ...` 와 `exit=1`

> 이 가드가 이 PR 에서 유일하게 실행 전에 막는 자리인 이유: 진짜 CF 로 12분을 돌리면
> 하루 한도가 날아가고 24~33시간 기다려야 한다. 나머지 오염은 전부 사후에 판정한다.

- [ ] **Step 4: `after` 를 가짜 summary 로 돌려본다**

k6 를 아직 안 돌렸으므로 최소 모양의 summary 를 만들어 대조 논리만 확인한다.

```bash
cd /Users/cheonjamin/projects/AllDap/ai-service && python3 -c "
import json, pathlib
p = pathlib.Path('loadtest/results/S2-smoke.json')
p.write_text(json.dumps({'metrics': {
  'chat_status{status:200}': {'values': {'count': 0}},
  'chat_fallback': {'values': {'count': 0}},
}}))
print('wrote', p)
"
cd /Users/cheonjamin/projects/AllDap/ai-service && \
  .venv/bin/python -m loadtest.s2_context after \
    --run-id smoke --k6-summary loadtest/results/S2-smoke.json; echo "exit=$?"
```

기대: `무효 2xx 가 0건이다. 실행이 시작조차 못 했다.` 와 `exit=1`
(요청을 하나도 안 보냈으니 이게 옳은 판정이다)

- [ ] **Step 5: 연습 결과 파일을 지운다**

```bash
cd /Users/cheonjamin/projects/AllDap/ai-service && \
  rm -f loadtest/results/S2-smoke.json loadtest/results/S2-smoke-context.json \
        loadtest/results/S2-smoke-verdict.json loadtest/results/S2-guard-check-context.json
```

- [ ] **Step 6: 커밋**

```bash
cd /Users/cheonjamin/projects/AllDap
git add ai-service/loadtest/s2_context.py
git commit -m "feat: S2 시작 조건을 남기고 경로를 진짜 탔는지 사후 대조한다"
```

---

## Task 7: 예비 실행 → 본 실행 → 결과 문서

**Files:**
- Create: `docs/superpowers/2026-09-10-loadtest-s2-result.md`
- 산출물: `ai-service/loadtest/results/S2-<날짜>.json`, `-context.json`, `-verdict.json`, `ai-service/loadtest/results/S2-<날짜>-uvicorn.log`, Grafana 스크린샷

**Interfaces:**
- Consumes: Task 1~6 전부
- Produces: PR 3 의 산출물 — 측정 기록

---

- [ ] **Step 1: 스택 5개를 띄운다**

각각 별도 터미널이다. 전부 뜬 뒤 다음 단계로 간다.

터미널 A — DB·Prometheus·Grafana:

```bash
cd /Users/cheonjamin/projects/AllDap && docker compose up -d db prometheus grafana
```

터미널 B — 가짜 CF:

```bash
cd /Users/cheonjamin/projects/AllDap/ai-service && .venv/bin/python -m loadtest.fake_cf
```

터미널 C — uvicorn. **로그를 파일로 받는다:**

```bash
cd /Users/cheonjamin/projects/AllDap/ai-service && \
  CF_BASE_URL=http://127.0.0.1:9001 .venv/bin/uvicorn app.main:app --port 8001 \
  2>&1 | tee "loadtest/results/S2-$(date +%Y-%m-%d)-uvicorn.log"
```

> 🔴 로그 파일이 이 PR 에서 새로 생긴 것이다. 핸드오프 §5-ⓐ 가 "다음 측정부터" 로 남긴 자리다.
> S1 에서 `ANSWER_INCOMPLETE` 의 원인이 <잘림>인지 <빈 응답>인지 못 가른 이유가 로그를
> 안 남긴 것이었고, 12분 실행에서 같은 일이 나면 또 못 가른다.

터미널 D — Spring. **`-Ploadtest` 를 반드시 붙인다:**

```bash
cd /Users/cheonjamin/projects/AllDap/api && ./gradlew bootRun -Ploadtest
```

터미널 E — 확인용(아래 단계들을 여기서 돈다).

- [ ] **Step 2: 타깃 2개가 UP 인지, 힙이 256m 인지 다시 확인한다**

```bash
curl -s http://localhost:9090/api/v1/targets | python3 -c "
import json,sys
for t in json.load(sys.stdin)['data']['activeTargets']:
    print(t['labels']['job'], t['health'])
"
curl -s --get http://localhost:9090/api/v1/query \
  --data-urlencode 'query=sum(jvm_memory_max_bytes{area="heap",job="alldap-api"})' | python3 -c "
import json,sys; print(f\"heap max = {json.load(sys.stdin)['measurements'][0]['value']/1024/1024:.0f} MB\")
"
```

기대: `alldap-api up` · `alldap-ai up` · `heap max = 256 MB`

> 🔴 `heap max` 가 기가 단위면 **여기서 멈춘다.** `-Ploadtest` 없이 12분을 돌리면
> 2순위 가설이 링에서 빠지고, 결과 문서가 "Python 이 먼저다" 라고 <틀리게> 적힌다.

- [ ] **Step 3: 시작 조건을 찍는다**

```bash
RUN_ID=$(date +%Y-%m-%d)
cd /Users/cheonjamin/projects/AllDap/ai-service && \
  .venv/bin/python -m loadtest.s2_context before --run-id "$RUN_ID"
```

인쇄된 `BOT_ID=` 값을 복사한다.

- [ ] **Step 4: 예비 실행 — 1 VU 30초**

`DRYRUN=1` 이면 스크립트가 1 VU · 30초 단계 하나만 돈다(Task 5 Step 3b 에서 확인한 것).
본 실행과 **같은 파일·같은 코드경로**를 타므로, 여기서 안 걸린 오염은 본 실행에서도 안 걸린다.

```bash
cd /Users/cheonjamin/projects/AllDap/ai-service && \
  DRYRUN=1 k6 run \
    --env BOT_ID=<복사한 값> \
    --env RUN_ID=dryrun \
    --env OUT=loadtest/results/S2-dryrun.json \
    loadtest/s2_breakpoint.js
```

기대: 약 30초 뒤 표가 한 줄(`  1  ...`) 찍히고 k6 가 스스로 끝난다.
(12분이 지나도 안 끝나면 `DRYRUN=1` 이 안 먹은 것이다. `Ctrl+C` 로 끄고 Task 5 Step 3b 를 다시 본다.)

- [ ] **Step 5: 예비 실행에서 오염이 없는지 본다**

k6 stdout 표에서 **1 단계 행의 `fallback` 열이 `0`** 인지 확인한다.
그리고 가짜 CF 호출이 요청 수의 3배인지 본다:

```bash
curl -s http://localhost:8001/internal/debug/cf-stats | python3 -c "
import json,sys
d = json.load(sys.stdin)
print({m: r['count'] for m, r in d.items()})
"
```

기대: `embed`·`rerank`·`generate` 세 모델의 count 가 서로 비슷하고, 각각 예비 실행 요청 수와 같다.

> 🔴 fallback 이 0 이 아니거나 세 모델 중 하나라도 0 이면 **본 실행을 시작하지 않는다.**
> 예비 실행이 막으려는 것이 정확히 이것이다 — 오염은 사후에야 드러나고, 그때는 12분을
> 통째로 버리게 된다. 예비 실행은 그 낭비만 막는 것이고 본 실행의 <중단 안 함> 규칙과는 무관하다.

- [ ] **Step 6: 측정 구간을 깨끗하게 만든다 (uvicorn·Spring 재시작)**

예비 실행이 cf-stats 누적과 히스토그램에 섞여 있다. 터미널 C 와 D 를 `Ctrl+C` 로 끄고
**같은 명령으로 다시 띄운다** (Step 1 의 C·D). 그다음 시작 조건을 다시 찍는다:

```bash
RUN_ID=$(date +%Y-%m-%d)
cd /Users/cheonjamin/projects/AllDap/ai-service && \
  .venv/bin/python -m loadtest.s2_context before --run-id "$RUN_ID"
```

> cf-stats 에 리셋 API 가 없는 것은 일부러다(`cf._latencies` 주석). 측정 구간의 시작은
> <프로세스를 다시 띄우는 것>으로 만든다.

- [ ] **Step 7: 본 실행 — 12분. 중단하지 않는다**

```bash
cd /Users/cheonjamin/projects/AllDap/ai-service && \
  k6 run \
    --env BOT_ID=<복사한 값> \
    --env RUN_ID=$(date +%Y-%m-%d) \
    --env OUT=loadtest/results/S2-$(date +%Y-%m-%d).json \
    loadtest/s2_breakpoint.js
```

> 🔴 5xx 가 쏟아져도, 연결이 끊겨도, Spring 이 죽었다 살아나도 **끄지 않는다.**
> 그게 찾으려는 결과다. 12분을 기다린다.

돌아가는 동안 Grafana(`http://localhost:3001`, 대시보드 **AllDap API**)를 열어둔다.

- [ ] **Step 8: 사후 대조**

```bash
RUN_ID=$(date +%Y-%m-%d)
cd /Users/cheonjamin/projects/AllDap/ai-service && \
  .venv/bin/python -m loadtest.s2_context after \
    --run-id "$RUN_ID" --k6-summary "loadtest/results/S2-$RUN_ID.json"; echo "exit=$?"
```

`verdicts` 를 읽는다. `무효` 가 하나라도 있으면 **그 실행은 결과 문서에 숫자로 싣지 않는다** —
"이런 이유로 무효였다" 를 적고 원인을 고친 뒤 Step 6 부터 다시 한다.

- [ ] **Step 9: 재시작 경계를 확인하고 시각을 적는다**

Grafana 패널 **"🔴 재시작 경계 — Spring 살아 있은 시간"** 을 실행 구간(12분)으로 좁혀 본다.

```bash
curl -s --get http://localhost:9090/api/v1/query_range \
  --data-urlencode 'query=changes(process_start_time_seconds{job="alldap-api"}[1m])' \
  --data-urlencode "start=$(date -v-15M +%s)" \
  --data-urlencode "end=$(date +%s)" \
  --data-urlencode 'step=15' | python3 -c "
import json, sys, datetime
d = json.load(sys.stdin)['data']['result']
jumps = [datetime.datetime.fromtimestamp(float(t)).strftime('%H:%M:%S')
         for r in d for t, v in r['values'] if float(v) > 0]
print('재시작 감지 시각:', jumps if jumps else '없음')
"
```

- 결과가 `없음` 이면 **2순위 가설은 이번 실행에서 발현하지 않았다.**
- 시각이 나오면 그 시각이 걸친 단계를 적어둔다. **그 단계는 결과 표에 "측정 불가" 로 적고 숫자를 싣지 않는다** —
  그 숫자는 "포화" 가 아니라 "재시작 중" 을 잰 것이고, 둘을 같은 표에 나란히 놓으면
  원인이 다른 두 사실을 같은 값으로 합치는 것이 된다.

- [ ] **Step 10: Grafana 스크린샷을 찍는다**

시간 범위를 실행 12분으로 맞춘 뒤, **부하 곡선과 내부 지표가 같은 시간축에 있는 화면**을 찍는다.
최소 두 장:

1. 패널 1(처리량)·2(지연) + 패널 6(anyio 스레드풀) 이 한 화면에 보이는 것
2. 패널 5(힙)·8(재시작 경계) 가 한 화면에 보이는 것

Task 3 Step 6 에서 찍어둔 `/targets` 스크린샷도 함께 보관한다.

- [ ] **Step 11: 결과 문서를 쓴다**

`docs/superpowers/2026-09-10-loadtest-s2-result.md` 를 만든다. **아래 골격을 그대로 쓰고
`<>` 자리를 실측으로 채운다.** 못 채운 칸은 비워두지 말고 "왜 못 채웠는가" 를 적는다.

````markdown
# 부하테스트 S2 (breakpoint) 결과 — <실행 날짜>

설계는 `docs/superpowers/specs/2026-09-10-loadtest-pr3-s2-breakpoint-design.md`,
계획은 `docs/superpowers/plans/2026-09-10-loadtest-pr3-s2-breakpoint.md` 에 있다.
이 문서는 <측정 기록>이다. 최종 리포트는 before/after 가 모이는 PR 5 에서 쓴다.

## 시작 조건

`ai-service/loadtest/results/S2-<날짜>-context.json` 전문이 근거다. 요약:

| | 값 |
|---|---|
| 커밋 | `<sha>` |
| 봇 | `<name>` (`<id>`) · 문서 <n>건 · 청크 <n>개 |
| 리랭커 / 하이브리드 | `<reranker_enabled>` / `<hybrid_enabled>` |
| `answerable_max_distance` / `max_distance` | `<...>` / `<...>` |
| 가짜 CF 지연 | embed 235 · rerank 414 · generate 937 ms |
| Spring JVM | `-Xms192m -Xmx256m -XX:MaxMetaspaceSize=128m -XX:+ExitOnOutOfMemoryError` (`-Ploadtest`) |
| 힙 상한 실측 | `<n>` MB (플래그 없이는 `<n>` MB 였다) |

## 유효성

| 장치 | 결과 |
|---|---|
| fallback | `<n>` 건 — <0 이면 "생성 경로를 탔다", 아니면 "이 실행은 무효"> |
| 가짜 CF 호출 배수 | 실측 `<x>` / 기대 `<n>` |
| 재시작 | `<없음 / HH:MM:SS>` |

## 단계별 (앞 20초를 잘라낸 구간)

**판정은 p95·p99 로 한다. avg 는 참고용이다.**

| VU | 표본 | p50 | p95 | p99 | max | 2xx | 비2xx | 비고 |
|---|---|---|---|---|---|---|---|---|
| 1 | | | | | | | | 표본 얇음(§못 잰 것) |
| 5 | | | | | | | | 표본 얇음(§못 잰 것) |
| 10 | | | | | | | | |
| 20 | | | | | | | | |
| 40 | | | | | | | | |
| 80 | | | | | | | | |

## 꺾인 단계와 그때 벽에 닿은 신호

<VU N 에서 꺾였다. 그때 무엇이 포화였나 — anyio borrowed 가 40 에 붙었는지,
 힙이 말랐는지, Hikari pending 이 섰는지, 톰캣 스레드가 찼는지를 그래프로 말한다.>

## 두 가설의 판정

| | 가설 | 판정 | 근거 |
|---|---|---|---|
| 1순위 | Python anyio 스레드풀 40 이 먼저 찬다 | <맞음/틀림> | `alldap_anyio_threads_borrowed` <...> |
| 2순위 | Spring 힙 256m 이 먼저 마른다 | <맞음/틀림> | `process_start_time_seconds` <...> |

🔴 **둘 다 아니었다면 그렇게 적는다.** 부하테스트의 목적은 맞히는 게 아니라 틀리는 걸 보는 것이다.
그때는 실제로 포화된 것이 무엇이었는지를 적고, 다음 측정에서 볼 지표를 남긴다.

## 못 잰 것

- **1 VU·5 VU 단계의 p99 는 표본이 얇다.** 요청 한 건의 하한이 1.586초(235+414+937)라
  1 VU 는 2분에 약 75건뿐이다. 낮은 단계를 더 오래 유지해 표본을 맞추는 선택도 있었으나,
  꺾임은 위쪽 단계에서 나므로 실행시간을 늘리지 않고 한계로 남겼다.
- **"동시 N명" 절대수치는 이 실행으로 말할 수 없다.** 맥의 CPU·메모리 대역이 t3.micro 가 아니다.
  여기서 얻은 것은 <어느 자원이 먼저 차는가> 이고, 그건 구조라 사양과 무관하다.
  절대수치는 운영 실행이 따로 필요하다(범위 밖).
- **가짜 CF 는 고정 지연이다.** S1 실행 중 종단 p50 이 단조 상승했는데(20건째 1,676ms →
  320건째 1,779ms) 가짜 서버는 몇 건을 돌리든 같은 시간을 잔다. 장시간 부하에서 진짜 CF 와
  수치가 벌어지면 버그가 아니라 이것일 수 있다.
- <재시작이 있었다면: VU <n> 단계는 "재시작 중" 을 잰 것이라 숫자를 싣지 않았다.>

## 파일

- `ai-service/loadtest/results/S2-<날짜>.json` — k6 원본
- `ai-service/loadtest/results/S2-<날짜>-context.json` — 시작 조건
- `ai-service/loadtest/results/S2-<날짜>-verdict.json` — 사후 대조
- `ai-service/loadtest/results/S2-<날짜>-uvicorn.log` — Python 로그
- Grafana 스크린샷 <경로>
````

- [ ] **Step 12: 커밋**

```bash
cd /Users/cheonjamin/projects/AllDap
git add docs/superpowers/2026-09-10-loadtest-s2-result.md ai-service/loadtest/results/
git commit -m "docs: S2 breakpoint 측정 결과를 남긴다"
```

- [ ] **Step 13: PR 을 연다**

```bash
cd /Users/cheonjamin/projects/AllDap
git push -u origin feat/loadtest-s2-breakpoint
gh pr create --title "feat: S2 breakpoint — 어디서 깨지는가를 잰다" --body "$(cat <<'EOF'
설계: `docs/superpowers/specs/2026-09-10-loadtest-pr3-s2-breakpoint-design.md`
결과: `docs/superpowers/2026-09-10-loadtest-s2-result.md`

## 무엇을 했나
- Python `/internal/metrics` 신설 — anyio 스레드풀 점유·채팅 처리시간·in-flight
- Prometheus 타깃 + Grafana 패널 3개 (두 가설을 같은 시간축에)
- `bootRun -Ploadtest` 로 로컬 힙을 운영과 같게 (2순위 가설을 링에 올린다)
- k6 계단식 6단계 시나리오 — 중단 없이 80 까지
- 시작 조건 파일 + 가짜 CF 호출 수 전후 대조

## 개선은 없다
병목이 보여도 고치지 않았다. 고치면 PR 5 의 before 가 사라진다.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_0186BrHnQWLnTEcaRG8TVFHP
EOF
)"
```

---

## 부록: 설계서 §6 장치가 어디에 구현됐는가

| 장치 | 구현 |
|---|---|
| 상태코드별 따로 집계 | Task 5 — `chat_status` Counter + `{stage,status}` 서브지표 임계값 |
| `isFallback` 카운트 | Task 5 `chat_fallback` / Task 6 `cmd_after` 판정 ① / Task 7 Step 5·8 |
| 가짜 CF 호출 수 전후 비교 | Task 6 `_cf_counts` + `cmd_after` 판정 ② (기대 배수를 설정에서 정한다) |
| 시작 조건 파일 | Task 6 `cmd_before` |
| 판정은 p95·p99 | Task 5 `summaryTrendStats` / 결과 문서 표 |
| 재시작 경계 | Task 3 패널 8 / Task 7 Step 9 |
| 앞 20초 잘라내기 | Task 5 `WARMUP_MS` + `phase` 태그 |
| 예비 실행 | Task 7 Step 4·5 |
| uvicorn 로그 파일 | Task 7 Step 1 터미널 C |
| 새 코드 검증 (§7) | Task 1 Step 5 · Task 2 Step 6 · Task 4 Step 4·5 · Task 3 Step 5 |
