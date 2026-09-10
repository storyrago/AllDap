# 부하테스트 PR 3 설계: S2 breakpoint (2026-09-10)

부하테스트 시리즈 전체 설계는 `2026-09-10-loadtest-design.md` 에 있다.
이 문서는 그 §PR 3 을 실행 가능한 수준까지 내린 것이고, **설계서와 다르게 정한 것이
둘 있다**(§2, §4). 그 둘은 근거와 함께 아래에 적었다.

## 목적

**어디서 선형성이 깨지는가, 그때 무엇이 포화됐는가.** 이 둘만 본다.

개선은 하지 않는다(PR 5). SLO 도 정하지 않는다(설계서 결정 5).
여기서 고치면 before/after 의 before 가 사라진다.

---

## 1. 구성

```
 [k6] 맥 호스트
   │  POST /api/auth/login              (1회, JWT 재사용)
   │  POST /api/bots/{botId}/chat       ← 관리자 채팅. rate limit 없음
   ↓
 Spring :8080  (gradle bootRun, 운영과 같은 JVM 플래그 — §2)
   │   └ :8081/actuator/prometheus      (PR 1)
   ├─→ Postgres (docker, alldap-db)
   └─→ Python :8001
         ├ /internal/metrics            (이 PR 에서 신설 — §3)
         └─→ 가짜 CF :9001              (235 / 414 / 937ms, PR 2 의 S1 실측 p50)
 Prometheus :9090 → Grafana :3001       [타깃 2개: 8081, 8001]
```

로컬 전용이다. 운영 실행과 "동시 N명" 절대수치는 이 PR 의 범위가 아니다
(설계서 결정 2: 병목 찾기는 로컬, 절대수치는 운영).

## 2. 두 가설을 같은 링에 올린다

설계서 §PR 3 은 *"가설 두 개(Python 스레드풀 40 vs 힙 256m)가 여기서 판정된다"* 고
적어뒀다. **그런데 PR 1 이 세운 로컬 구성으로는 둘째 가설을 판정할 수 없다.**

실측 근거:

- `docker-compose.prod.yml:54-56` — 운영은 `-Xms192m -Xmx256m -XX:+ExitOnOutOfMemoryError`
- `docker-compose.yml` 의 서비스는 `db`·`prometheus`·`grafana` 셋뿐이다. **api 가 없다**
- `observability/prometheus.yml` 주석 — *"Spring 은 컨테이너 밖(맥 호스트)에서 gradle 로 돌린다"*

즉 로컬 Spring 은 JVM 기본 힙(맥 RAM 의 1/4, 기가 단위)으로 돌고
`ExitOnOutOfMemoryError` 도 없다. 그대로 돌리면 힙은 절대 안 마르고
**"Python 스레드풀이 먼저다" 라는 결론이 나온다 — 그게 사실이어서가 아니라
상대 가설을 링에 올리지도 않았기 때문이다.** 설계서 자신의 기준
("부하테스트의 목적은 맞히는 게 아니라 틀리는 걸 보는 것")에 걸린다.

설계서가 "병목 찾기는 로컬, 구조 문제라 사양과 무관" 이라고 한 것은 맞지만,
**힙 256m 은 구조가 아니라 자원 한도**라 그 예외에 들어가지 않는다.

→ **로컬 `bootRun` 에 운영과 같은 JVM 플래그를 씌운다.**

| | 가설 | 판정 신호 | 이 PR 이 붙여야 하는 것 |
|---|---|---|---|
| 1순위 | Python anyio 스레드풀 40 이 먼저 찬다 (`main.py:230` 의 `chat` 이 `def`) | `borrowed_tokens` 가 `total_tokens`(40)에 붙고 대기가 생긴다 | Python `/internal/metrics` 신설 |
| 2순위 | 그보다 힙 256m 이 먼저 마른다 | 느려지는 게 아니라 **끊기고 재시작**. `process_start_time_seconds` 가 점프 | `bootRun` JVM 플래그 |

Spring 쪽 기존 지표(`hikaricp.pending`, 톰캣 스레드, 힙 사용량)는 PR 1 이 깔아놨다.

## 3. 부하 프로파일

| 단계 | VU | 유지 | 예상 표본 |
|---|---|---|---|
| 1 | 1 | 2분 | 약 75건 |
| 2 | 5 | 2분 | 약 370건 |
| 3 | 10 | 2분 | 약 750건 |
| 4 | 20 | 2분 | 약 1,500건 |
| 5 | 40 | 2분 | 수천 (상한에 걸리면 정체) |
| 6 | 80 | 2분 | 수천 (같음) |

- **계단식 전환.** 램프를 두지 않는다. 꺾이는 지점이 단계 경계에 맞아떨어져야
  "20 은 버텼고 40 에서 깨졌다" 를 표로 읽을 수 있다. 램프를 두면 꺾임이
  두 단계 사이로 번지고, 이 PR 의 산출물이 정확히 그 숫자다
- **think time 없는 closed loop.** 설계서의 "동시 사용자 N" 을 항상 N건 in-flight
  으로 읽는다. 생각시간을 넣으면 breakpoint 탐색에서 부하가 흐려진다
- **각 단계 앞 20초는 집계에서 잘라낸다.** 계단식이라 전환 순간 폭주가 있고
  Prometheus scrape 이 15초라 점 1~2개 분량이다. 잘라내지 않으면
  "20 단계 p99" 에 전환 충격이 섞인다
- 총 12분

### 알려진 한계

요청 한 건의 하한이 **1.586초**(235+414+937)라 1 VU 단계는 2분에 약 75건뿐이다.
설계서의 "단계당 수천 건" 은 20 이상 단계에만 해당하고 **1 VU·5 VU 단계의 p99 는 표본이 얇다.**
낮은 단계를 더 오래 유지해 표본을 맞추는 선택도 있으나, 꺾임은 위쪽 단계에서 나므로
실행시간을 늘리지 않고 **한계로 남긴다.** 결과 문서의 "못 잰 것" 에 적는다.

## 4. 실행은 중단하지 않는다

PR 2 의 S1 드라이버(`s1_baseline.py:42`)는 *"429·503·비200 이 하나라도 나오면 즉시
멈추고 'N건에서 중단됨' 으로 표시한다"* 는 규칙을 갖고 있다. 평가 16문항이 전부 429 로
죽었는데 실행이 `completed` 로 남은 사고에서 나온 규칙이고, S1 에서는 옳다.

**S2 에 그대로 물려주면 정확히 반대로 작동한다.** S2 는 깨지는 지점을 찾는 시나리오라
5xx·타임아웃·연결끊김이 찾으려는 결과 그 자체다. 특히 2순위 가설이 맞으면 증상이
"끊기고 30초쯤 뒤 돌아온다" 인데, S1 규칙이면 **가설이 맞는 순간 드라이버가 자살하고
그 뒤를 못 본다.**

→ **80 까지 끝까지 민다. 판정은 전부 사후에 한다.**

그래서 아래 §6 의 장치들은 모두 "실행 뒤에 파일만 보고 가려낼 수 있는가" 를 기준으로
배치했다. 다만 오염(fallback·경로 미탐)은 사후에야 드러나 12분을 통째로 버리게 되므로
**본 실행 앞에 30초 예비 실행(1 VU)** 을 둔다. 예비 실행은 그 낭비만 막는 것이고
본 실행의 중단 규칙과는 무관하다.

## 5. 코드 변경

### ① Python 관측 — `/internal/metrics` 신설

```
ai-service/requirements.txt      + prometheus-client
ai-service/app/metrics.py        신규
ai-service/app/main.py           라우트 1개 + /internal/chat 계측
```

`prometheus-fastapi-instrumentator` 를 쓰지 않는다. **정작 필요한 지표를 그 패키지가
주지 않는다** — anyio 스레드풀 점유는 어느 범용 계측기에도 없고 직접 읽어야 한다.
핵심을 손으로 써야 하면 범용 패키지는 의존성만 늘린다.

| 지표 | 출처 | 무엇을 판정 |
|---|---|---|
| `alldap_anyio_threads_borrowed` | `anyio.to_thread.current_default_thread_limiter().borrowed_tokens` | **1순위 가설.** 40 에 붙는 순간 |
| `alldap_anyio_threads_total` | 같은 limiter 의 `total_tokens` | 40 은 설정값이 아니라 anyio **기본값**이다. 버전이 바뀌면 그래프가 조용히 거짓이 되는 것을 막는다 |
| `alldap_chat_duration_seconds` (histogram) | `/internal/chat` 처리시간 | Spring 왕복에서 **Python 몫을 분리.** 없으면 "느린 게 Spring 인가 Python 인가" 를 못 가른다 |
| `alldap_chat_inflight` (gauge) | 진입/이탈 | 스레드풀 대기 큐 길이의 대리 지표 |

**경로를 `/internal/metrics` 로 두는 이유.** 이 저장소는 인증 없는 것을 `/internal/*`
아래에만 두고, prod compose 가 ai-service 에 `ports:` 를 안 써서 외부에 안 열린다는
전제로 지탱한다(`cf_stats` docstring 이 같은 근거를 적어둔 자리). `/metrics` 를 루트에
두면 그 규칙에서 혼자 벗어난다.

⚠️ `prometheus-client` 는 워커가 여럿이면 멀티프로세스 모드가 필요하다. `Dockerfile:34`
의 uvicorn 워커가 **1개**라 지금은 불필요하다. **워커를 늘리는 순간 이 지표가 프로세스
마다 갈라진다** — PR 5 의 개선 후보가 정확히 "워커 수 늘리기" 라서, 그때 함께 손대야
한다는 주석을 코드에 남긴다.

### ② Prometheus 타깃 + Grafana 패널

```
observability/prometheus.yml                     job 1개 추가
observability/grafana/dashboards/alldap-api.json  패널 추가
```

**대시보드 패널이 이 PR 의 산출물이다.** §8 이 요구하는 "부하 곡선과 내부 지표를
같은 시간축에" 는 지표를 내보내는 것만으로는 안 되고, `alldap_anyio_threads_borrowed`
/`_total` 과 `process_start_time_seconds` 를 Spring 쪽 기존 패널과 같은 대시보드에
올려야 한다. 특히 **재시작 경계(§6 마지막 항목)** 는 눈으로 보는 것이 판정 절차라
패널이 없으면 그 규칙을 실행할 수 없다.

`host.docker.internal:8001` 이다. Python 도 컨테이너 밖(호스트 uvicorn)에서 돌아
기존 Spring 타깃과 같은 이유로 `localhost` 가 아니다. PR 1 이 그 주석을 남겨놨으니
같은 근거를 가리킨다.

### ③ 로컬 JVM 을 운영과 맞춤

```
api/build.gradle                 bootRun 블록 추가
```

```gradle
tasks.named('bootRun') {
    if (project.hasProperty('loadtest')) {
        jvmArgs = ['-Xms192m', '-Xmx256m', '-XX:+ExitOnOutOfMemoryError']
    }
}
```

**`-Ploadtest` 로 옵트인이다.** 무조건 걸면 평소 개발에도 힙 256m 이 적용돼 문서
업로드·임베딩에서 엉뚱하게 죽는다. 측정을 위한 제약이 일상을 망가뜨리는 자리라
조건을 붙인다.

`docker-compose.prod.yml:54` 와 **서로를 가리키는 주석을 양쪽에 남긴다.** 한쪽만
바뀌면 로컬이 운영을 대변하지 못하게 되는데, 그것이 조용히 일어난다
(`provenance: false` 를 같은 방식으로 처리한 선례가 있다).

### ④ k6 시나리오

```
ai-service/loadtest/s2_breakpoint.js     신규
```

`brew install k6` 가 선행된다(현재 `k6 not found`).

- 로그인 1회 → JWT 재사용. `w2check@example.com` / `S1loadtest!2026`
  (비밀번호는 S1 측정 때 바꿔둔 것이다. 원래 해시는 `AllDap-pr2/.s1-old-hash.txt`)
- **`botId` 는 하드코딩하지 않는다.** 로그인 뒤 그 계정의 봇 목록에서 집어
  **시작 조건 파일에 기록한다.** 봇을 지우고 다시 만들면 id 가 바뀌는데, 하드코딩하면
  그때 실행이 404 로 죽거나 <다른 코퍼스를 가진 봇>을 재게 된다. 어느 쪽이든
  "그때 뭘로 쟀지" 를 못 답한다
- `stages` 계단식 6단계, `summaryTrendStats: ['min','med','p(95)','p(99)','max','avg']`
  (기본 요약은 p90·p95 만 보여주고 p99 가 안 나온다)
- **질문은 S1 의 5개를 그대로 쓴다.** `eval_questions` 테이블 원문이고, 리랭커가 정답
  청크를 밀어내는 알려진 2건과 코퍼스에 정답이 없는 1건은 S1 이 근거를 적어 빼놨다.
  **여기서 새로 적으면 fallback 이 섞여 실행이 무효가 된다**
  (S1 이 "손으로 적었다가 테이블 문항과 16건 중 완전 일치 0건" 으로 데인 자리)
- **세션 id 는 `s2-<runId>-<vu>-<iter>`.** S1 이 `s1-{i}` 를 재사용해 집계가
  `LIKE` 67건 / 시각 66건으로 갈렸다. S2 는 단계당 수천 건이라 같은 구조면
  **단계 경계가 뭉개진다**
- 상태코드와 `isFallback` 을 **단계 태그와 함께 따로 집계.** 처리량은 2xx 만
- 중단 없이 80 까지 끝까지 민다

### ⑤ 실행 절차와 산출물 스크립트

```
ai-service/loadtest/s2_context.py        신규 (시작 조건 파일 + 전후 cf-stats)
ai-service/loadtest/results/             결과 JSON
```

시작 조건으로 커밋 SHA·설정값(`reranker_enabled`, `hybrid_enabled`,
`answerable_max_distance`, `max_distance`)·코퍼스 크기·가짜 CF 지연값·실행 시각을
파일로 찍고, `cf-stats` 의 `count` 를 실행 전후로 비교한다.

`cf-stats` 는 프로세스 시작 뒤 누적이고 리셋 API 가 없다. 실행 **전후 차이**로 쓰므로
문제되지 않는다. 백분위는 `_LATENCY_WINDOW = 2000` 창에 걸리지만 이 PR 이 `cf-stats`
에서 쓰는 것은 `count` 뿐이고, `count` 와 `latency_window` 는 `cf_stats` 가 이미
따로 내보낸다(`cf.py:144`, "둘은 다른 사실이라 따로 내보낸다").

**uvicorn 로그를 파일로 받는다.** 핸드오프 §5-ⓐ 가 "다음 측정부터" 로 남긴 것이다.
S1 에서 `ANSWER_INCOMPLETE` 의 원인이 잘림인지 빈 응답인지 못 가른 이유가 로그를
안 남긴 것이었고, 12분 실행에서 같은 일이 나면 또 못 가른다.

## 6. 측정을 무효로 만들지 않기 위한 장치

| 장치 | 어디서 | 무효/유효를 어떻게 가르나 |
|---|---|---|
| 상태코드별 따로 집계 | k6 단계 태그 | 처리량 곡선은 **2xx 만**. 5xx·연결실패는 별 계열로 겹쳐 그린다 |
| `isFallback` 카운트 | k6 응답 파싱 | **0 이 아니면 그 실행은 무효.** 예비 실행에서 한 번, 본 실행 결과에서 다시 |
| 가짜 CF 호출 수 전후 비교 | `s2_context.py` | `count` 증가분을 2xx 요청 수와 맞춘다. 기대값은 요청당 3건(embed·rerank·generate)이고 **`reranker_enabled` 가 꺼져 있으면 2건**이다 — 그래서 기대 배수를 상수로 박지 않고 시작 조건 파일의 설정값에서 정한다. 안 맞으면 그 경로를 안 탄 것 |
| 시작 조건 파일 | `s2_context.py` | 커밋 SHA·설정 4개·코퍼스 크기·지연값·시각 |
| 판정은 p95·p99 | k6 `summaryTrendStats` | 평균은 표에 싣되 판정 근거로 쓰지 않는다 |
| **재시작 경계** | `process_start_time_seconds` | 점프한 시각을 기록한다. **재시작이 있었던 단계는 "측정 불가" 로 표시하고 숫자를 싣지 않는다** |

마지막 항목이 이 PR 에서 새로 필요해진 것이다. 끝까지 미는 실행이라 Spring 이 OOM 으로
죽으면 그 뒤 단계의 숫자는 **"포화" 가 아니라 "재시작 중"** 을 잰 것이고, 둘을 같은 표에
나란히 놓으면 이 저장소가 반복해 걸린 뭉개기 — 원인이 다른 두 사실을 같은 값으로
합치는 것 — 가 된다.

## 7. 새로 붙인 코드의 검증

측정 도구가 틀리면 측정이 통째로 거짓이 된다. PR 2 가 `fake_cf_check.py` 로 한 것과
같은 방식을 쓴다.

| 대상 | 어떻게 |
|---|---|
| `metrics.py` 의 anyio 지표 | 단위 테스트 — limiter 를 점유한 상태에서 `borrowed_tokens` 가 올라가는 것, `total_tokens` 가 40 인 것 |
| `/internal/metrics` 노출 | 기존 ai-service 테스트에 라우트 200 + 지표명 존재 확인 |
| `-Ploadtest` 플래그 | 붙였을 때 `Runtime.maxMemory()` 가 256m 근처인 것을 **실행해서** 확인. 플래그가 안 먹으면 2순위 가설이 조용히 링에서 빠진다 |
| Prometheus 타깃 | `/targets` 에서 job 2개가 `UP` 인 것을 확인하고 스크린샷 |

## 8. 산출물

PR 3 이 내는 것은 **측정 기록**이다. 최종 리포트(`docs/부하테스트-리포트.md`)는
before/after 까지 모이는 PR 5 에서 쓴다.

```
docs/superpowers/2026-09-10-loadtest-s2-result.md   (S1 결과 문서와 같은 자리)
ai-service/loadtest/results/S2-<날짜>.json
Grafana 스크린샷 (부하 곡선 + 내부 지표를 같은 시간축에)
```

결과 문서에 반드시 들어갈 것:

- **꺾인 단계와 그때 벽에 닿은 신호**
- 두 가설 중 어느 것이 맞았는지, **또는 둘 다 아니었는지**
- **못 잰 것** — 1 VU·5 VU 단계 p99 표본 부족(§3), 맥 CPU·메모리 대역이 t3.micro 가 아니므로
  **"동시 N명" 절대수치는 이 실행으로 말할 수 없다**는 것

## 9. 범위 밖

- **개선.** 병목이 보여도 고치지 않는다(PR 5). 여기서 손대면 before 가 사라진다
- **SLO 확정** — 설계서 결정 5
- **운영 실행** — PR 3 은 로컬 전용. 절대수치는 별도
- **S3·S4** (rate limit 정확성·장애 주입) — PR 4
- **미세 탐색** (20→25→30→35 로 꺾인 구간을 좁히는 것) — 이번 결과를 보고 필요하면 추가
- **핸드오프 §5-ⓒ** (`fake_cf_check.py:75` 의 `expected + 300` 절대 허용창을 비율
  기준으로) — 이 PR 은 지연값을 바꾸지 않으므로 물리지 않는다
- **설계서·PR1·PR2 계획서를 `main` 에 올리는 것** — 아직 `docs/loadtest-design`
  브랜치에만 있다(`f1c22a4`, `2d84558`, `fb9a519`). 이 PR 에 끼워 넣으면 측정 PR 에
  문서 3건이 섞인다. **별 슬라이스로 두는 것을 권한다**
