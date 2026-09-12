# 5b 동일성 확인 결과: A판(S3) · F2판(S4) 재실행 (2026-09-12, 로컬)

설계서: `docs/superpowers/specs/2026-09-12-loadtest-pr5-remeasure-design.md` §2 "동일성 확인"
before 원본: `docs/superpowers/2026-09-11-loadtest-s3-result.md` §3 · `-s4-result.md` §4
돌리기 전에 못박은 판정 기준: `ai-service/loadtest/results/PRE-2026-09-12-identity-criteria.md`

**한 줄 결론: S3 는 완전히 같다(도구만 고쳐졌다). F2 는 구조 신호가 전부 같은데, <내가 실행 전에
못박은 기준 두 줄>을 어겼다. 어긴 두 줄은 전부 주입 순간의 경계 정렬에 딸린 값이고 그것이
원인임을 산술로 닫았지만, 기준을 본 뒤에 고치지 않는다는 규칙에 따라 "통과" 로 적지 않는다.**

🔴 **그래서 이 판의 관문 판정은 <멈춤·보고>다.** 파도 3(5c) 진행 여부는 취합 세션이 정한다.
아래 §4 가 "무엇을 보고 그렇게 판단했는가" 를 통째로 싣는다.

---

## 0. 이 판이 무엇이 아닌가

새 측정이 아니다. **도구를 고쳤는데 재는 대상은 안 바뀌었다** 를 보이는 것이 전부다.
그래서 숫자를 잘 뽑는 것이 목적이 아니라, **before 와 어느 축이 같아야 하고 어느 축은
원리적으로 같을 수 없는지를 먼저 가르는 것**이 목적이다. 그 가름은 실행 전에 적어뒀다
(위 PRE 파일). 이 문서는 그 기준에 실측을 대본 것이다.

## 1. 환경

| | 값 |
|---|---|
| 커밋 | `28b5495` (PR #136 · #137 머지 직후) |
| Spring | `./gradlew bootRun` 기본 설정. **두 판 내내 재기동 없음** (`process_start_time_seconds` 1.789192110022E9 불변, `Started ApiApplication` 1회) |
| JVM | Temurin 21, `-XX:TieredStopAtLevel=1`, 힙 상한 기본값(G1 Old Gen 6.44GB). 🔴 **`-XX:+ExitOnOutOfMemoryError` 는 안 붙어 있다** (설계서 §5 의 "OOM 이면 결과" 규칙은 이 판에서 쓸 일이 없었다. 재기동 자체가 없다) |
| Python (F2 판만) | `ANYIO_MAX_THREADS=40 CF_BASE_URL=http://127.0.0.1:9001 uvicorn app.main:app --port 8001` |
| **`alldap_anyio_threads_total`** | **40.0 (실측).** 설정값이 아니라 측정 대상 프로세스의 지표를 읽었다. §2-3 참고 |
| psycopg 풀 | `max=10` · `open=1` · `requests_waiting` 최종 0.0 |
| 가짜 CF (F2 판만) | `fake_cf --port 9001 --vector db` (embed 235 / rerank 414 / generate 937ms) |
| k6 | v2.2.0 (darwin/arm64) |
| 측정 계정 | **`loadtest2@example.com`** (아래 §5-ⓐ 가 이유다. 기본값 `loadtest@example.com` 이 아니다) |
| 봇 | `628d2785-...` `W2 검증 봇`, 문서 50건 |

🔴 **S3 A판에는 Python 도 가짜 CF 도 안 띄웠다.** 형식만 맞는 가짜 `pk_` 키라 Spring 에서
404 로 끝난다. 따라서 A판에는 `ANYIO_MAX_THREADS` 가 적용될 프로세스가 아예 없다.
"40 으로 쟀다" 는 **F2 판에만** 해당한다.

---

## 2. S3 A판: 완전히 같다

### 2-1. 상태코드 히스토그램

| 상태 | before (2026-09-11-A) | **after (2026-09-12-A)** | 판정 |
|---|---|---|---|
| 404 | 20 | **20** | 일치 |
| 429 | 80 | **80** | 일치 |
| 400 / 200 / 0 / 500 / 503 | 0 | **0** | 일치 |
| 합계 | 100 | **100** | 일치 |

지연은 밴드로만 봤다(기준 파일 §1-3): `http_req_duration` max 21.2ms → **25.7ms**,
실행 시간 26.3ms → **31.2ms**. 둘 다 밴드 안이다.

### 2-2. 교차 검증 축 (#137 이 옮긴 축)

| 축 | 값 |
|---|---|
| k6 가 센 429 | 80 |
| `alldap_ratelimit_rejected_total{bucket="widget-chat",mode="check"}` 증가분 | **80** |
| 두 값의 차 | **0** (옛 ±1 여유 없이 정확히 일치) |
| `mode="blocked"` | 시계열 없음 (= 로그인 버킷을 안 건드렸다) |

### 2-3. ①이 고쳐졌다

- `valid`: **`false` → `true`**, `after` 의 종료코드 **1 → 0**
- 무효 사유였던 `alldap_ratelimit_recorded_total{bucket="widget-chat"}` 부재가
  이제 **"이것이 정상이다" 라는 OK 사유**로 판정문에 남는다

🔴 **그 부재가 정상이라는 것을 이 실행이 <음성 대조로> 확인해줬다.** 같은 스크레이프에
`alldap_ratelimit_recorded_total{bucket="login-failure"} 1.0` 이 있다(§5-ⓐ 의 로그인 401 이
남긴 것이다). 즉 **그 카운터 자체는 살아 있고, widget-chat 라벨만 없다.**
"계측이 안 붙었다" 와 "이 버킷은 원리적으로 안 쌓인다" 가 한 화면에서 갈렸다.

---

## 3. S4 F2판: 구조는 같고, 경계에 딸린 두 줄이 다르다

### 3-1. 정확히 일치해야 한다고 못박은 것

| 축 | before | **after** | 판정 |
|---|---|---|---|
| 정상 구간 상태코드 | 200 만 | **200 701 + 503 7** | 🔴 **어긋남** (§4) |
| 주입 구간 상태코드 | 503 만 | **503 만** (243,453) | 일치 |
| `alldap_ai_retry_total` 증가분 | **0** | **0** (시계열 자체가 없다) | 일치 |
| `circuit_transition_total{to="open"}` 증가분 | 4 | **3** | 🔴 **어긋남** (§4) |
| `python_5xx` : 가짜 CF 임베딩 결함 : `fault.injected` | 73:73:73 | **64:57+7:64** | §4-2 가 정산한다 |
| fallback | 0 | **0** | 일치 |
| `verdict.valid` | true | **true** | 일치 |

### 3-2. ②가 고쳐졌다 (이 판의 본래 목적)

| | 값 |
|---|---|
| `alldap_ai_call_seconds_count{outcome="success"}` 증가분 | **701** |
| k6 가 센 200 (정상 구간) | **701** |
| **차** | **0** |

**옛 순서(`recover → after`)였다면 702 였다.** `recover` 가 서킷을 닫으려고 직접 만드는 성공
1건이 스냅샷에 섞이기 때문이고, before 의 F3 가 1,800 이 아니라 1,801 이었던 것이 그것이다.

🔴 **같은 오염이 <다른 축에도> 있었다는 것이 이번에 드러났다.**
`circuit_transition_total{to="closed"}` 증가분이 before 는 **+2** 인데 이번에는 **0** 이다.
`recover` 의 성공 1건은 열린 서킷을 닫으므로 `to=closed` 전이를 하나 만든다. 설계서 §2-② 가
*"원리적으로는 to=closed 전이도 한 건 섞일 수 있다"* 고 예측해둔 자리이고, **예측이 맞았다.**
순서를 고친 효과가 success 한 축이 아니라 최소 두 축에 걸쳐 있었다.

### 3-3. 순서를 코드가 지키는지 (실측)

verdict 파일을 잠시 치우고 `recover` 를 돌렸다.

```
중단: 2026-09-12-F2 의 verdict 파일이 없다. recover 보다 after 를 먼저 돌려야 한다.
  이유: recover 는 서킷을 닫으려고 채팅 성공 1건을 직접 만든다. ...
  할 일: `s4_context after --run-id 2026-09-12-F2 --k6-summary ...` 를 먼저 돌린 뒤 ...
종료코드 1
```

**절차가 아니라 코드가 막는다.** 다만 한계가 하나 보였다: **context 파일조차 없는 run-id** 로
부르면 이 안내가 아니라 `FileNotFoundError` 트레이스백이 난다. 가드는 "context 는 있는데
verdict 가 없는" 경우에만 돈다. 실제로 사람이 저지르는 실수가 그 경우이므로 판정을 뒤집지는
않지만, 적어둔다.

### 3-4. 규모 축 (밴드로만 본 것)

| 축 | before | after | 밴드(±20%) |
|---|---|---|---|
| 정상 구간 총 요청 | 720 | 708 | 576~864 안 |
| 주입 구간 503 | 235,700 | 243,453 | 안 |
| `python_5xx` | 73 | 64 | 58~88 안 |
| 정상 구간 avg 지연 | 1676.8ms | 1718.3ms | 안 |
| `circuit_open` 급속 거절 | 235,627 | 243,396 | (= 주입 503 의 99.97%, before 와 같은 비율) |

---

## 4. 🔴 어긋난 두 줄: 무엇이 원인인가

### 4-1. 원인은 하나다. 주입 시각이 k6 의 구간 경계보다 약 0.6초 <앞섰다>

`s4_faults.js` 는 요청을 **보내기 시작한 시각**으로 `phase` 태그를 붙인다
(`elapsed = Date.now() - exec.scenario.startTime`). 드라이버는 k6 프로세스를 띄운 뒤 60초를
센다. 그런데 k6 는 부팅과 `setup()` 로그인에 시간을 쓰므로 **시나리오 시계는 그만큼 늦게
0초가 된다.** 이번 판에서는 그 차이가 약 0.6초였고, 그래서 주입이 k6 기준 59.4초에 켜졌다.

정상 구간 요청 처리량은 708건 / 60초 ≈ 11.8건/초다. **0.6초 × 11.8 ≈ 7.1건.**
관측된 정상 구간 503 이 **정확히 7건**이다.

⚠️ 드라이버 스스로가 이 어긋남을 인정하고 있다:
*"경계 몇 초의 어긋남은 어차피 생기므로, 사후 판정은 '정확히 언제' 가 아니라 구간별 총량으로
한다"* (`s4_faults.js` `chat()` 주석). **before 가 0 이었던 것이 운이고, 7 이 결함이 아니다.**

### 4-2. 그 7건이 주입 때문이라는 것을 산술로 닫았다

503 을 만들 수 있는 원인은 둘뿐이다: 서킷 급속 거절, Python 5xx.
연결 실패·읽기 타임아웃 시계열은 **아예 없다**(그런 일이 없었다).

```
k6 가 받은 503 전체 = 7(정상 태그) + 243,453(주입 태그) = 243,460
Spring 이 센 503   = circuit_open 243,396 + python_5xx 64 = 243,460
                                                             ↑ 정확히 같다
```

가짜 CF 호출 수로 파이프라인 단계까지 갈라진다(성공 1건 = embed·rerank·generate 3콜).

```
embed 766 · rerank 709 · generate 709 · injected 64 · 성공 702(= k6 701 + recover 1)

embed 에서 실패      = 766 - 709 = 57
rerank 에서 실패     = 709 - 709 = 0
generate 에서 실패   = 709 - 702 = 7
                       57 + 0 + 7 = 64 = injected  ✅ 정산이 맞는다
```

**generate 단계에서 실패한 7건이 곧 정상 태그 503 7건이다.** 주입이 켜진 순간 이미
embed·rerank 를 지나 generate 를 부르려던 요청들이고, 이들은 k6 기준 59.4초 이전에
<시작>했으므로 정상으로 태깅됐다. 지연 1.59초 파이프라인에서 generate 구간 비중이
937/1586 = 59% 이므로, 경계에 걸린 요청이 대부분 generate 자리에 있는 것도 맞는 그림이다.

🔴 **이 정산은 성공 경로의 호출 배수 3 도 함께 확인한다**(설계서 §5 의 폐기 조건):
702×3 + 57(embed 만) + 7×3(embed·rerank·generate 전부 세어짐) = 2,184 = 766+709+709.

### 4-3. `to=open` 이 4 가 아니라 3 인 것도 같은 경계 문제다

서킷은 열린 뒤 30초마다 HALF_OPEN 이 되고, 주입 중에는 다시 열린다. 90초 주입이면
**열리는 횟수는 3 이냐 4 냐가 마지막 톱니가 창 안에 들어오느냐로 갈린다.**
이번 판은 `clear` 직후 `after` 시점의 상태가 **`half_open`(1.0)** 이었다. 즉 네 번째
HALF_OPEN 까지는 갔는데 그때 주입이 이미 꺼져 있어 **다시 열리지 않았다.**
`recover` 를 돌리자 곧바로 200 이 나고 `closed`(0.0) 가 됐다.

**"30초 톱니가 있다" 는 사실은 그대로다**(90초에 3회 = 30초 주기). 바뀐 것은 창의 끝이
톱니의 어느 위상에 걸렸느냐다.

### 4-4. 닫지 못한 것 하나

before 는 **73건이 전부 embed 에서 실패**했다(rerank·generate 증가 0). 위 4-2 의 논리대로면
before 도 경계에 걸린 요청이 rerank·generate 에서 몇 건 실패했어야 한다. **왜 0 이었는지는
이 판의 자료로 설명하지 못한다.** 추정하지 않고 모른다고 적는다. 판정을 뒤집는 축은 아니다
(before 의 `python_5xx` 73 = 가짜 CF 임베딩 증가 73 = injected 73 으로 그쪽도 정산은 맞았다).

---

## 5. 실행 중에 드러난 것

### ⓐ 측정 계정 `loadtest@example.com` 은 **이미 있는데 비밀번호를 아무도 모른다**

PR #133 이 만든 계정이 2026-09-11 22:53 에 DB 에 생겼다. 그런데 비밀번호는 환경변수로만
받으므로 **저장소 어디에도 없고**, 세션이 바뀌면 알 길이 없다.
`account.py` 는 이 상황을 정확히 안내한다(401 에 "값을 찍어 맞히려 하지 말 것" 까지).
안내대로 `LOADTEST_EMAIL='loadtest2@example.com'` 으로 새로 만들어 썼다.

🔴 **이건 결함이 아니라 설계대로다.** 다만 **기록해야 하는 사실이 하나 생겼다**:
봇 `628d2785-...` 의 주인이 `loadtest@example.com` → `loadtest2@example.com` 로 옮겨졌다.
다음 세션이 기본값으로 돌리면 "봇이 없다" 로 멈춘다. **`LOADTEST_EMAIL` 를 반드시 넘길 것.**
(비밀번호를 아는 사람이 없으므로 `loadtest@example.com` 은 되살릴 수 없다)

### ⓑ `s3_ratelimit.js` 의 기본 출력 파일 이름에 `RUN_ID` 가 안 들어간다

핸드오프 §3-ⓑ 의 명령에는 `-e OUT=` 이 없는데, 기본값이
`loadtest/results/S3-unnamed-${ROUND}.json` 이다. 그대로 돌리면 `after` 가
`S3-<run-id>-<round>.json` 을 못 찾아 **`FileNotFoundError` 트레이스백**으로 죽는다.
(`s4_faults.js` 는 이미 `S4-${RUN_ID}.json` 이라 이 문제가 없다)

이번에는 손으로 파일 이름을 바꿔 이어붙였다. **고치지 않았다** 이 PR 의 경계가
"도구 수정" 이 아니라 "동일성 확인" 이기 때문이다. 파도 3·4 에서 정할 것.
`-e OUT=` 을 명령에 적어 넣거나, 기본값을 `S3-${RUN_ID}-${ROUND}` 로 바꾸는 두 갈래다.

### ⓒ 🔴 주입 시각을 k6 시계에 맞추는 장치가 없다 (§4 의 뿌리)

지금은 드라이버가 **자기 시계로** 60초를 센다. k6 의 시나리오 시계는 부팅·로그인만큼 늦다.
그 차이가 판마다 달라지므로 **"정상 구간에 503 이 몇 건 섞이나" 가 판마다 달라진다.**
이번 판과 before 가 갈린 두 줄이 정확히 그것이다.

없애려면 둘 중 하나다: ① k6 가 구간 경계에서 `/fault` 를 직접 부르게 한다(시계가 하나가 된다),
② 드라이버가 k6 요약의 시나리오 시작 시각을 읽어 사후에 구간을 다시 태깅한다.
**①이 낫다.** ②는 사후 보정이라 "언제 켰나" 를 여전히 모른다.

---

## 6. 원본 파일

```
ai-service/loadtest/results/PRE-2026-09-12-identity-criteria.md     실행 전에 못박은 판정 기준
ai-service/loadtest/results/S3-2026-09-12-A-{context,verdict}.json  S3 시작 조건 · 판정
ai-service/loadtest/results/S3-2026-09-12-A.json                    k6 원본
ai-service/loadtest/results/S3-2026-09-12-A-k6.txt                  k6 콘솔
ai-service/loadtest/results/S3-2026-09-12-A-prom-after.txt          판 직후 지표 원본
ai-service/loadtest/results/S4-2026-09-12-F2-{context,verdict}.json S4 시작 조건 · 판정
ai-service/loadtest/results/S4-2026-09-12-F2.json                   k6 원본
ai-service/loadtest/results/S4-2026-09-12-F2-k6.txt                 k6 콘솔 (구간별 표)
ai-service/loadtest/results/S4-2026-09-12-F2-uvicorn-summary.txt    uvicorn 로그 요약 (ASGI 예외 64건 = 주입 64건 · '리랭킹 실패' 0줄)
                                                                   🔴 원본 .log 는 .gitignore 의 *.log 에 걸려 안 올라간다(787KB)
ai-service/loadtest/results/S4-2026-09-12-F2-prom-after.txt         Spring 지표 원본
ai-service/loadtest/results/S4-2026-09-12-F2-python-metrics-after.txt  Python 지표 원본 (anyio · 풀)
ai-service/loadtest/results/S4-2026-09-12-F2-cfstats-final.json     가짜 CF 최종 카운터
```
