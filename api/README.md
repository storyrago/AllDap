# api/ — Spring Boot API 계층 (W2)

외부에 노출되는 **유일한** 서비스. 인증·권한·봇/문서 메타·대화 로그를 담당하고,
AI 작업(파싱·임베딩·검색·생성·평가)은 직접 하지 않고 Python AI 서비스(:8001)에 REST로 위임한다.

```
브라우저 ──HTTPS──> [Spring :8080] ──REST(내부망)──> [Python :8001] ──> 외부 LLM API
                          │                              │
                          └────────── PostgreSQL :5432 ──┘  (같은 DB를 공유)
```

> **Python 서비스를 외부에 노출하면 안 된다.** `/internal/*` 에는 인증이 전혀 없다.
> 포트가 열려 있으면 누구나 남의 봇 문서를 조회·삭제할 수 있다.
> 외부 LLM API 키도 Python만 가진다. Spring은 키를 갖지 않는다.

---

## ✅ 현재 상태

**이 문서는 2026-07-31(W2 착수 전) 기준으로 굳어 있었다.** "아직 코드가 없다" 로 시작했고,
이미 만들어진 것을 여러 곳에서 "미정" 이라 말했다. 아래는 실제 코드에 맞춰 고친 판이다.

| 항목 | 상태 |
|---|---|
| Boot 4.0.7 / Java 21 골격 · Flyway | ✅ |
| 인증 (가입·로그인·JWT) | ✅ |
| 봇 CRUD + 소유권 격리 | ✅ |
| 문서 업로드·목록·삭제 (Python 위임) | ✅ |
| 관리자 테스트 채팅 · 대화 로그 · 피드백 | ✅ |
| 위젯 공개 API (`/api/w/*`) + Origin 검증 + rate limit | ✅ |
| 평가 API (질문 생성·수정·실행·결과·미답변) | ✅ |
| 문서 충돌 (`/api/bots/{botId}/conflicts`) | ✅ |
| 사용량 계량 · 결제 수단 · 요금제 | ✅ (🔴 **실제 청구는 아직 없다**. 루트 `AGENTS.md` 참고) |

아래 1장의 "프로젝트 생성" 은 **이미 지나간 절차의 기록**이다. 다시 생성할 일은 없지만
Boot 4 스타터 이름(1-2 절)처럼 지금도 예제를 붙여넣을 때 걸리는 함정이 있어 그대로 둔다.

---

## 1. 프로젝트 생성 (start.spring.io)

| 항목 | 값 |
|---|---|
| Project | **Gradle - Groovy** |
| Language | Java |
| Spring Boot | **4.0.7** (드롭다운의 최신 stable 을 그대로) |
| Group | `com.alldap` |
| Artifact / Name | `api` |
| Package name | **`com.alldap.api`** |
| Packaging | Jar |
| Java | **21** |

**Dependencies**: Spring Web, Spring Data JPA, PostgreSQL Driver, Spring Security, Validation, Lombok

### 1-1. Boot 버전 — 4.0.7 을 그대로 쓴다

이 README의 예전 버전에는 `Spring Boot 3.4.x` 라고 적혀 있었지만
**start.spring.io 에서 3.4.x 선택지가 내려갔다.** 현재 고를 수 있는 건 `4.1.0` / `4.0.7` 뿐이다.

한때 "4.0.7 로 생성한 뒤 3.5.3 으로 내린다"고 적었으나 **철회했다.**
국내 레퍼런스가 3.x 중심이라 자료가 많다는 이점은 있었지만, 내리는 비용이 예상보다 컸다.

### 1-2. ⚠️ Boot 4 는 스타터 이름이 Boot 3 과 다르다

이게 다운그레이드를 접은 직접적 이유이고, **검색해서 나온 예제를 붙여넣을 때도 걸리는 지점**이다.

| Boot 3 | Boot 4 (지금 우리) |
|---|---|
| `spring-boot-starter-web` | **`spring-boot-starter-webmvc`** |
| `spring-boot-starter-test` (통합 1개) | **`-webmvc-test`, `-data-jpa-test`, `-security-test`, `-validation-test`, `-actuator-test`** 로 분리 |

"한 줄만 바꾸면 된다"고 봤던 게 실제로는 7줄이었고, 내린 뒤 무엇이 더 깨질지 확인하는
시간까지 계산하면 이점이 상쇄된다. 참고 레포(`hwanh2/kcalog`)도 Boot 4.0.7 + Java 21 로
실제 굴러가는 것을 확인했다.
→ 결정 근거 전문은 `docs/decisions.md` 2026-07-31 항목.

**Boot 3 기준 예제를 그대로 붙여넣지 말 것.** 의존성이 안 찾아지면 먼저 스타터 이름부터 의심하라.

### 1-2. 로컬 JDK 가 17 이다 — Java 21 을 따로 깔아야 한다

이 맥에 설치된 JDK는 **17**이다. 위 설정은 Java 21이므로 그대로는 빌드가 안 된다.

```bash
brew install openjdk@21
/usr/libexec/java_home -V          # 21이 목록에 보이는지 확인
```

IntelliJ 에서는 `File → Project Structure → SDK` 를 21로,
`Settings → Build Tools → Gradle → Gradle JVM` 도 21로 맞춘다.

> Java 17로 낮춰도 동작은 하지만, 채용공고에서 17/21을 함께 요구하는 경우가 많고
> 21의 가상 스레드·패턴 매칭을 면접에서 언급할 여지가 생기므로 21을 권한다.

### 1-3. JWT(jjwt) 는 Initializr 목록에 없다 — 직접 추가한다

Spring Security 를 넣어도 **JWT 라이브러리는 안 딸려온다.** `build.gradle` 에 직접 적어야 한다.

```gradle
dependencies {
    implementation 'io.jsonwebtoken:jjwt-api:0.12.6'
    runtimeOnly    'io.jsonwebtoken:jjwt-impl:0.12.6'
    runtimeOnly    'io.jsonwebtoken:jjwt-jackson:0.12.6'
}
```

`api` 만 컴파일 시점에 쓰고 나머지 둘은 실행 시점에만 필요해서 `runtimeOnly` 로 나뉜다.
0.11.x 시절 예제(`Jwts.parser().setSigningKey(...)`)는 0.12 에서 API가 바뀌어 그대로 쓰면 컴파일이 안 된다.
검색해서 나온 코드가 안 되면 **먼저 버전부터 확인할 것.**

### 1-4. Flyway 를 도입했다 (2026-07-31)

처음에는 넣지 않기로 했다가 뒤집은 결정이다. 되돌린 이유가 면접 답변거리이므로 그대로 남긴다.

**원래 걱정**: 스키마의 주인은 하나여야 하는데, 두 서비스가 DB를 공유하는 상황에서
Flyway 까지 얹으면 *SQL 파일 / Flyway 이력 테이블 / Hibernate* 셋이 주장하게 된다.

**뒤집은 이유**: 그 걱정은 **데이터 쓰기 소유권과 스키마 소유권을 섞어서 본 것**이었다.
Flyway 로 **스키마는 Spring 이 단독 소유**하고 Python 은 데이터만 읽고 쓰면 주인은 여전히 하나다.
반대로 옛 방식(`docker-entrypoint-initdb.d`)은 스키마를 고칠 때마다 `docker compose down -v` 로
**데이터를 통째로 날려야** 해서, 파일럿이 시작되면 쓸 수 없는 방식이었다.

**그래서 생긴 제약 (반드시 지킬 것)**

1. `V1__init.sql` 을 수정하지 말 것. 적용된 마이그레이션을 고치면 체크섬 불일치로 기동이 실패한다.
   스키마 변경은 `V2__*.sql`, `V3__*.sql` 로만.
2. **스키마는 Spring 이 기동해야 생긴다.** 로컬 실행 순서가 `db → api → ai-service` 로 바뀌었다.
   Python 을 먼저 띄우면 테이블이 없어 실패한다.
3. 옛 방식으로 만들어진 볼륨이 남아 있으면
   `Found non-empty schema(s) "public" but no schema history table` 로 기동이 막힌다.
   `docker compose down -v` 로 비우고 다시 시작할 것.
4. ✅ **`V1__init.sql` 끝의 시드 INSERT 는 <그대로 둔다>** (2026-09-09 결정).
   "배포 전에 `dev` 프로파일로 분리할지 결정할 것 **[미정]**" 이라고 적어둔 채 2026-09-07 배포가
   지나갔고, 뒤늦게 따져보니 **지우면 안 되는 것**이었다.
   🔴 **이건 더 이상 "로컬 개발용" 이 아니라 <공개 데모 봇>이다.** 공개 `/demo` 화면이
   `NEXT_PUBLIC_DEMO_PUBLIC_KEY` 미설정 시 `pk_local_dev` 로 떨어지고, `api/` 통합 테스트
   (`UsageIntegrationTest`)도 이 봇이 있다고 전제한다. 지우면 운영의 `/demo` 가 전부 fallback 이 된다.
   - **로그인 가능한 계정은 들어 있지 않다.** 시드는 `bots` 한 행뿐이고 `users` 는 건드리지 않는다.
     비밀번호 해시도 소유자(`user_id`)도 없다. 즉 보안 사고가 아니다.
   - `allowed_origins` 가 `NULL` 이라 설정 조회는 Origin 을 보내는 모든 브라우저에 대해 차단된다
     (이 저장소 규칙: 빈 값 = 전부 차단).
   - ⚠️ 주인이 없는 봇이라 대시보드에 안 보이고 UI 로 지울 수 없다. 사용량 집계도 의도적으로 제외한다.
   → 근거 전문은 루트 `AGENTS.md` 의 Flyway 규칙 4번과 `docs/decisions.md` 2026-09-09 항목.

→ `docs/decisions.md` 참고.

---

## 2. Spring 공개 API → Python 내부 API 위임 매핑

Python 쪽 컨트랙트는 **`ai-service/app/main.py` 와 `schemas.py` 를 직접 읽어 확인한 것**이다.
추측이 아니라 실제 코드 기준이므로, Python을 고치면 이 표도 함께 고쳐야 한다.

| Spring 공개 API (PRD §10.1) | → Python 내부 API | 비고 |
|---|---|---|
| `POST /api/bots/{botId}/documents` | `POST /internal/bots/{botId}/documents` | multipart, **필드명 `file`**. 202 + `DocumentOut` |
| `GET /api/bots/{botId}/documents` | `GET /internal/bots/{botId}/documents` | `DocumentOut[]` |
| `DELETE /api/documents/{docId}` | `DELETE /internal/bots/{botId}/documents/{docId}` | 204 (본문 없음) |
| `POST /api/bots/{botId}/chat` (테스트 채팅) | `POST /internal/chat` | `ChatResponse` |
| `POST /api/w/{publicKey}/chat` (위젯) | `POST /internal/chat` | publicKey → botId 로 바꿔 호출 |
| `GET/POST/PATCH /api/bots/{botId}/eval/questions*` | 같은 경로의 `/internal/bots/{botId}/eval/questions*` | 질문 목록·생성(동기 200)·수정 |
| `POST/GET /api/bots/{botId}/eval/runs` | `POST/GET /internal/bots/{botId}/eval/runs` | 실행은 **202 + 폴링** (`eval_runs.status` 가 있어 202 가 성립한다) |
| `GET /api/bots/{botId}/eval/runs/{runId}/results` | 같은 경로의 `/internal/...` | 질문별 채점 결과 |
| `GET /api/bots/{botId}/eval/unanswered` | — | 위임 없음. **Spring 이 `messages` 를 직접 집계**한다 |
| `GET/POST/PATCH /api/bots/{botId}/conflicts*` | 같은 경로의 `/internal/bots/{botId}/conflicts*` | 문서 충돌 스캔·목록·상태 변경 (`doc_conflicts`, V4) |
| `POST /api/auth/*`, `/api/bots`, `/api/messages/{id}/feedback`, `/api/bots/{botId}/logs`, `GET /api/w/{publicKey}/config`, `/api/usage`, `/api/plan`, `/api/billing/methods*` | — | 위임 없음. Spring이 DB로 직접 처리 |
| — | `GET /health` | 헬스체크. 기동 확인·장애 감지용 |

> ⚠️ **평가·충돌 경로는 `/internal/eval/*` 이 아니라 `/internal/bots/{bot_id}/eval/*` 이다.**
> `/internal/*` 에는 인증이 전혀 없어서 **경로의 `bot_id` 가 격리의 전부**다.
> 실제로 문서 삭제 API 가 `doc_id` 만 받던 것을 `bot_id` 를 받도록 고친 적이 있다(PR #46).
> 경로에서 `bot_id` 를 빼는 방향의 제안은 하지 말 것.

### 2-1. Python 스키마 (JSON은 전부 snake_case — FastAPI/Pydantic 기본값)

```
DocumentOut  = { id, filename, file_type, status, error_message, char_count, chunk_count }
                 status ∈ pending | processing | ready | failed

ChatRequest  = { bot_id, message, session_id }
                 message    : 1 ~ 2000자   (넘으면 422)
                 session_id : 최대 64자    (기본값 "local-test")

ChatResponse = { answer, sources[], is_fallback, latency_ms }
Source       = { chunk_id, document_id, filename, score, preview }
                 score   : 0~1 (1 - 코사인거리). 높을수록 관련성 높음
                 preview : 청크 본문 앞 200자
```

### 2-2. 위임할 때 Spring 이 반드시 해야 하는 일

**Python 은 권한을 전혀 검사하지 않는다.** `bot_id` 를 주면 그냥 처리한다.
따라서 아래는 "하면 좋은 것"이 아니라 **안 하면 뚫리는 것**이다.

- `POST/GET /api/bots/{botId}/documents` → 그 봇이 **JWT 사용자 소유인지** 확인 후 위임
- `DELETE /api/documents/{docId}` → Spring 이 먼저 `documents.bot_id` 를 읽어
  (Spring은 documents 읽기 권한 있음) → `bots.user_id` 가 요청자와 같은지 확인 → 그 다음 위임.
  이 검사를 빠뜨리면 **남의 문서를 id만 알면 지울 수 있다.**
  ✅ Python 쪽도 경로가 `DELETE /internal/bots/{bot_id}/documents/{doc_id}` 로 바뀌어
  **두 겹이 됐다**(PR #46). 예전엔 `doc_id` 만 받아 봇을 보지 않았다.
- `POST /api/w/{publicKey}/chat` → `public_key` 로 봇을 찾고, `bot_id` 를 **서버가** 채운다.
  클라이언트가 보낸 `botId` 를 믿으면 봇 간 격리가 깨진다.
- 업로드 크기: Python은 20MB 초과 시 413을 준다. Spring 도 `spring.servlet.multipart.max-file-size`
  를 맞춰두면 파일을 다 받아 Python에 넘긴 뒤 실패하는 대신, 앞에서 한국어로 안내할 수 있다.

---

## 3. snake_case ↔ camelCase 를 어디서 바꾸나

- **Python 내부 API**: `snake_case` (`is_fallback`, `latency_ms`, `chunk_id`)
- **Spring 공개 API / 브라우저 / 위젯**: `camelCase` (`isFallback`, `latencyMs`, `chunkId`)

### 🚫 하면 안 되는 것

```yaml
# application.yaml — 절대 이렇게 하지 말 것
spring:
  jackson:
    property-naming-strategy: SNAKE_CASE
```

이건 **전역 설정**이라 Python 호출뿐 아니라 **브라우저에 주는 공개 API 응답까지 snake_case가 된다.**
프론트(Next.js·위젯)가 갑자기 `is_fallback` 을 받게 되고, PRD의 공개 API 규약이 깨진다.

### ✅ 실제: 변환은 `global/client` 패키지 **경계 한 곳**에서만

Python 통신용 DTO는 `global/client/dto` 안에만 두고(전부 `Ai*` 접두사),
필드마다 `@JsonProperty` 로 이름을 명시한다.

- 어느 필드가 Python의 어느 필드인지 **파일 하나만 열면 다 보인다** (초보자가 읽기 좋다)
- 전역 설정이 아니라 그 DTO에만 적용되므로 공개 API는 영향이 없다
- 필드가 많아져 `@JsonProperty` 가 지겨워지면, 그때 **RestClient 전용 ObjectMapper** 에만
  `SNAKE_CASE` 전략을 주는 방식으로 바꾼다 (여전히 전역 설정은 아니다)

`global/client` 밖(도메인 서비스·컨트롤러)은 **camelCase 만 안다.**
`AiChatResponse`(snake) → `ChatResponse`(camel) 변환도 이 경계에서 끝낸다.
이렇게 해두면 나중에 Python 필드명이 바뀌어도 고칠 파일이 한 곳이다.

### 에러 응답도 번역해야 한다

FastAPI 의 에러 포맷은 우리 규약과 **다르다.**

| Python 이 주는 것 | Spring 이 브라우저에 줘야 하는 것 (PRD §10.3) |
|---|---|
| `{"detail": "파일이 너무 큽니다 (최대 20MB)"}` | `{"error": {"code": "...", "message": "..."}}` |
| 422 검증 실패: `{"detail": [ {...}, {...} ]}` (배열) | 같은 위 포맷 |

`detail` 이 **문자열일 때와 배열일 때가 둘 다 있다**는 점에 주의.
Python 응답을 브라우저에 그대로 흘려보내지 말고 반드시 변환할 것.
(내부 서비스의 구조가 밖으로 새는 것 자체가 문제이기도 하다)

---

## 4. RestClient — 타임아웃과 재시도

Spring 6의 `RestClient` 를 쓴다(Boot 3.2+ 포함). `RestTemplate` 은 유지보수 모드다.

### 왜 반드시 설정해야 하나

- **임베딩·LLM 생성은 느리다.** 채팅 한 번에 수 초, 업로드 처리는 수십 초가 걸릴 수 있다.
- **Spring이 Python을 동기 호출하므로 Python이 죽으면 채팅이 죽는다.**
  타임아웃이 없으면 Python이 멈춘 동안 요청 스레드가 계속 쌓여
  **Python 하나 때문에 Spring 전체가 응답 불능이 된다.** 이게 진짜 이유다.

### 실제로 쓰는 값: 엔드포인트별이 아니라 **한 벌**이다

이 README 의 예전 판은 엔드포인트마다 다른 타임아웃(`/health` 1s/2s, 채팅 3s/60s …)을
제안했지만, **그렇게 만들지 않았다.** Python 호출은 전부 같은 `RestClient` 하나를 쓴다.

| 대상 | connect | read | 설정 위치 |
|---|---|---|---|
| **Python AI 서비스 전체** | **3s** | **120s** | `application.yaml` 의 `alldap.ai-service.*` (근거는 `RestClientConfig` 주석) |
| 토스 결제 API | 3s | 10s | `alldap.toss.*` (AI 와 **일부러 다르다**. 외부 결제 API 는 느릴 이유가 없다) |

- **connect 3s** : 같은 내부망이라 TCP 연결은 밀리초 단위로 끝나야 정상이다. 3s 를 넘겼다는 건
  "느린 것"이 아니라 "Python 이 떠 있지 않은 것"에 가깝다.
- **read 120s** : 여기는 반대로 길게 잡는다. Python 이 외부 LLM API 를 부르므로 수십 초가 걸릴 수 있고,
  흔한 기본값(5~10초)으로 두면 **정상 동작 중인 요청을 우리가 끊는다.** 이미 과금된 LLM 호출을
  버리는 셈이라 손해가 두 배다.

호출별로 나누지 않은 이유: 긴 읽기 타임아웃이 실제로 필요한 쪽은 `POST /internal/chat` 하나인데,
나머지를 짧게 잡아 얻는 이득보다 **값이 여러 벌이 되어 어긋나는 비용**이 크다고 봤다.
필요해지면 `RestClient` 를 용도별로 나누면 된다(토스 쪽이 이미 그 예다).

### 재시도는 아무 데나 걸면 안 된다

가르는 기준은 **HTTP 메서드가 아니라 "요청이 Python 에 닿았는가"** 다.

```
✅ 재시도한다      : 연결 자체가 안 됨 (연결 거부·연결 타임아웃)
                     → 요청이 닿지 않았으니 부작용이 남을 수 없다
🚫 재시도하지 않음 : 읽기 타임아웃 · 5xx · 4xx
                     → 전부 "요청은 갔다" 는 뜻이다. documents 행이 2개 생기고
                       임베딩도 2번 돈다 (돈이 두 배로 나간다)
```

⚠️ 이 README 의 예전 판은 "GET 은 재시도해도 된다" 고 적었지만, 그 기준으로는
**읽기 타임아웃 난 GET 도 재시도 대상**이 된다. 실제 구현은 메서드를 보지 않는다.

✅ **재시도·서킷브레이커는 2026-08-17 에 붙였다.** 둘 다 `AiServiceClient.call()` 안에 있고,
`spring-retry` 도 Resilience4j 도 쓰지 않았다. Boot 4 호환이 미확인이었고, 필요한 게
상태 3개짜리 카운터뿐이라 직접 만들었다(`AiServiceCircuitBreaker`).

🔴 **재시도는 <연결 실패에만> 한다. 여기가 이 기능의 전부다.**
재시도의 전제는 "직전 시도가 **아무 일도 하지 않았다**" 인데, 그게 보장되는 실패는
**연결 자체가 안 된 경우뿐**이다. 요청이 Python 에 닿지 않았으니 부작용이 남을 수 없다.

- 🚫 **5xx 는 재시도하지 않는다.** Python 이 응답했다는 건 **요청이 도달했다**는 뜻이다.
  재시도하면 documents 행이 중복되거나 LLM 이 두 번 과금된다.
  ⚠️ `RestClientConfig` 에 있던 옛 TODO 가 5xx 를 "요청이 처리되지 않은 게 확실한 경우" 로
  분류했는데 **그 분류가 틀렸다.** 정정해뒀다.
- 🚫 4xx 도 재시도하지 않는다. 같은 요청은 같은 이유로 또 거절된다.
- ✅ 연결 실패로 좁히면 **업로드도 재시도 대상이 된다.** 예전엔 "업로드는 제외" 라는 예외를 뒀지만,
  요청이 안 갔으니 중복될 행이 없다. 오히려 업로드야말로 재시도가 고마운 경로다.

**서킷은 4xx 와 DTO 불일치를 실패로 세지 않는다.** 그건 Python 장애가 아니라 우리 잘못이라,
세면 **우리 버그로 멀쩡한 Python 을 차단**하게 된다. (답변 잘림 `ANSWER_INCOMPLETE` 도 같은 이유로
세지 않는다. Python 은 멀쩡히 판단해서 응답했다)

⚠️ **상태를 가진 싱글턴이라 통합 테스트마다 `circuitBreaker.reset()` 이 필요하다.**
안 하면 5xx 테스트가 누적돼 서킷이 열리고, 실행 순서에 따라 나타났다 사라지는 실패가 난다.

값(재시도 2회 · 200ms · 서킷 임계 5회 · 30초)의 근거는 **실측이 아니라 판단**이다.
`application.yaml` 주석에 그렇게 적어뒀다.
- 채팅이 실패하면 사용자에게는 PRD §10.3 포맷의 한국어 안내를 준다.
  이때 **봇의 `fallback_message` 를 쓰면 안 된다.** "문서에 답이 없음"과 "서버 장애"는 다른 사건이고,
  둘을 같은 문구로 뭉개면 품질 대시보드의 미답변 통계가 오염된다.

---

## 5. 봇별 설정: 두 개가 서로 <다른 경로>로 반영된다

Python 의 `POST /internal/chat` 요청 스키마(`ChatRequest`)는 지금도
**`bot_id` · `message` · `session_id` 세 개뿐**이다. 그런데 봇별 설정 둘 다 실제로 반영된다.

| 설정 | 반영 경로 |
|---|---|
| `fallback_message` | **Spring** 이 응답의 `is_fallback == true` 를 보고 `answer` 를 봇 문구로 **치환** (`ChatService`) |
| `system_prompt` | ✅ **Python 이 `bots` 테이블에서 직접 읽는다** (2026-08-13, `generator.fetch_bot_prompt`) |

🔴 **왜 Spring 이 실어 보내지 않는가.** 성능이 아니라 **평가** 때문이다.
평가 실행(`evalrun`)은 Spring 을 거치지 않으므로, Spring 이 실어 보내는 방식이면
**평가만 기본 프롬프트로 돌아** "평가에서는 좋았는데 실사용은 다르다" 가 된다.
부수 효과로 Spring 은 한 줄도 고치지 않았다.
→ **`AiChatRequest` 에 `system_prompt` 필드를 추가하지 말 것.** 반영 경로가 둘이 되면
어느 쪽이 이겼는지 알 수 없어지고 평가와 실사용이 다시 갈라진다.

결합은 **대체가 아니라 덧붙임**이다(기본 규칙을 앞에 두고 "충돌하면 위가 우선").
대체하면 `NO_ANSWER` 규칙이 사라져 환각 억제가 설정 하나로 뚫린다.
🔴 **다만 프롬프트로 프롬프트를 막는 데는 한계가 있고, 실측으로 뚫렸다.**
막지 못하므로 대신 잰다. `ai-service/app/bot_prompt_check.py` 가 그것이다. 자세한 내용은 루트 `AGENTS.md`.

### 그 밖의 갭

- ✅ **`messageId` 는 있다.** Python `ChatResponse` 에는 여전히 id 가 없지만,
  **Spring 이 `messages` 행을 저장하며 만든 id** 를 자기 응답(`ChatResponse.messageId`)에
  실어 내려준다. 프론트·위젯이 그 값으로 `POST /api/messages/{msgId}/feedback` 을 부른다.
- **`bots` 에 색상 컬럼이 없다.** PRD F-04는 "브랜드 색상 1종 커스텀"을 요구하는데
  `api/src/main/resources/db/migration/` 의 마이그레이션 전부를 확인해도 없다(V8 까지 없다).
  그래서 `WidgetConfigResponse.themeColor` 는 **항상 null 로 나간다.** 위젯은 설치 코드의
  `data-primary-color` 속성으로 우회한다.
  (`ddl-auto` 로 컬럼을 만들면 안 된다. 스키마는 Flyway 마이그레이션이 주인이다)
- ✅ **`allowed_origins` 검증은 켜져 있다** (PR #11). 옛 서술("검증 로직이 없어 public_key 만
  알면 누구나 남의 봇을 자기 사이트에 붙일 수 있다")은 **지금과 정반대**다.
  - **빈 `allowed_origins` 는 "전부 허용" 이 아니라 "전부 차단" 이다.** 그렇게 두지 않으면
    모든 신규 봇이 무방비로 태어난다. `public_key` 는 고객 사이트 HTML 에 그대로 노출되므로 비밀이 아니다.
  - **Origin 비교는 정확히 일치만** (`Bot.isOriginAllowed`). 접미사 비교를 쓰면
    `evil-example.com` 이 `example.com` 으로 통과한다.
  - 🔴 **검증은 설정 조회(`GET /api/w/{publicKey}/config`)에만 걸린다.** 채팅은 iframe 안에서
    나가므로 고객 사이트가 아니라 **우리 앱의 Origin** 이 실린다. 구조적 한계다
    (2026-08-02 에 이걸 모르고 검증을 걸었다가 위젯이 반드시 403 이 나는 버그를 냈다).
    **채팅의 실질 방어선은 rate limit** 이다(IP + publicKey 분당 20건, 인메모리).
  - Origin 은 브라우저가 붙이는 값이라 curl 로는 얼마든지 위조된다. **CORS 를 인가 수단으로 쓰지 말 것.**

---

## 6. 패키지 구조 (`com.alldap.api`): 실제로 이렇게 됐다

계층(controller/service/repository)으로 먼저 나누지 않고 **도메인으로 먼저 나눈다.**
"봇 기능이 어디 있지?" 를 폴더 하나에서 찾을 수 있고, 도메인이 커지면 그 폴더만 들여다보면 된다.
계층은 각 도메인 폴더 **안에서** 나눈다.

⚠️ **예전 판의 "제안" 과 실제가 다르다.** 공통 코드는 최상위 `common/`·`config/`·`security/`·`client/`
넷으로 흩어지지 않고 **`global/` 하나 아래로** 모였다. 아래가 실제 트리다.

```
com.alldap.api
├── global/
│   ├── common/       BaseEntity · PageResponse
│   ├── exception/    ★ PRD §10.3 에러 포맷. ErrorCode · ErrorResponse · GlobalExceptionHandler
│   │                   + 인증 실패용 EntryPoint/AccessDeniedHandler (필터 단계는 @ControllerAdvice 가 못 잡는다)
│   ├── config/       SecurityConfig · RestClientConfig · TossClientConfig · JpaConfig · *Properties
│   ├── client/       ★ Python AI 서비스 호출 전담. snake_case ↔ camelCase 변환이 여기서 끝난다
│   │                   AiServiceClient · AiServiceCircuitBreaker · AiServiceMetrics · dto/Ai*
│   ├── crypto/       빌링키 앱 레벨 AES-256-GCM (이 저장소의 첫 암호화)
│   ├── ratelimit/    RateLimiter. 위젯 공개 엔드포인트용. 인메모리다
│   └── validation/
└── domain/
    ├── auth/         가입·로그인·JWT 발급/검증 필터
    ├── user/         users 테이블
    ├── bot/          봇 CRUD, public_key 발급, 소유권 검사 ★ 격리의 기준점
    ├── document/     업로드·목록·삭제. 권한 검사 후 client 로 위임 (documents 읽기 전용)
    ├── chat/         테스트 채팅 + 대화 로그 저장 + 피드백 (conversations, messages 쓰기)
    ├── eval/         평가 질문·실행·결과·미답변 집계 (eval_* 읽기)
    ├── conflict/     문서 충돌 (doc_conflicts 읽기, V4)
    ├── usage/        사용량 원장 조회·메꾸기 (usage_events, V5)
    ├── billing/      토스 빌링키 등록·조회·삭제 (billing_methods, V6/V7) + client/Toss*
    ├── plan/         요금제 선택 (users.plan, V8)
    └── widget/       공개 엔드포인트 /api/w/*. 인증 없음 → rate limit·Origin 검증이 여기 붙는다
```

JWT 필터가 `security/` 가 아니라 `domain/auth/filter/` 에 있는 이유: 발급과 검증이 같은 도메인의
앞뒷면이라 한 폴더에서 같이 읽히는 편이 낫다고 봤다.

각 도메인 폴더 안: `controller / service / repository / entity / dto`

**`widget` 을 따로 뺀 이유**: `/api/w/*` 는 **인증이 없는 공개 엔드포인트**다.
`bot` 패키지에 섞어두면 "이건 인증이 필요한가?"가 헷갈리고, 언젠가 인증이 필요한 코드를
실수로 공개 경로에 붙이게 된다. 폴더로 갈라두면 보안 검토할 곳이 명확해진다.

**`client` 를 따로 뺀 이유**: Python 서비스는 언제든 바뀔 수 있는 외부 시스템이다.
호출 코드가 도메인 서비스 곳곳에 흩어지면 Python API가 바뀔 때 고칠 곳이 흩어진다.

---

## 7. DB — 테이블 소유권 (어기면 데이터가 깨진다)

Python 서비스와 **같은 PostgreSQL 을 공유**한다. 누가 어느 테이블을 쓰는지 반드시 지킬 것.

| 테이블 | 쓰기(owner) | 읽기 | Spring 쪽 주의 |
|---|---|---|---|
| `users`, `bots` | **Spring** | Python | Spring이 주인. `users.plan`(V8)은 요금제이고 **아직 아무것도 청구하지 않는다**. `bots.system_prompt` 는 Python 이 읽는다(5장) |
| `documents` | **Python** | Spring | ⚠️ 조회만. `status` 는 Python이 갱신한다. Spring이 UPDATE 하면 안 됨 |
| `chunks` | **Python** | — | ⚠️ **JPA 엔티티를 만들지 말 것.** Spring은 이 테이블을 아예 건드리지 않는다 |
| `conversations`, `messages` | **Spring** | — | 대화 로그·피드백은 Spring이 저장 |
| `eval_*` | **Python** | Spring | 실행은 Python, 조회·표시는 Spring |
| `doc_conflicts` (V4) | **Python** | Spring | 문서끼리 어긋나는 곳. `eval_*` 과 같은 패턴 |
| `usage_events` (V5) | **Spring** | — | 과금 원장. **append-only.** 평가 실행분도 Python 이 아니라 **Spring 이 조회 직전에 멱등하게 메꾼다** |
| `billing_methods` (V6·V7) | **Spring** | — | 토스 빌링키. Python 은 건드리지 않는다. `billing_key_enc` 는 **암호문**이라 SQL 로 읽어도 못 쓴다 |

### `ddl-auto` 는 반드시 `validate` 또는 `none`

```yaml
spring:
  jpa:
    hibernate:
      ddl-auto: validate    # update / create 로 두면 Python 쪽이 즉시 깨진다
```

`update` 로 두면 Hibernate 가 엔티티에 맞춰 스키마를 **멋대로 바꾼다.**
`chunks.embedding` 같은 pgvector 컬럼이나 `bots.allowed_origins` 같은 배열 타입은
Hibernate가 제대로 인식하지 못해 컬럼이 추가되거나 타입이 어긋날 수 있고, 그 순간 Python이 죽는다.

**스키마의 단일 진실 공급원은 `api/src/main/resources/db/migration/` 의 마이그레이션 전부다**
(지금 V1~V8). 컬럼이 필요하면 엔티티가 아니라 **새 마이그레이션**을 추가한다.
**이미 적용된 파일은 주석 한 글자도 고치지 말 것**. Flyway 체크섬이 깨져 기동이 막힌다.

> `validate` 로 두면 엔티티와 실제 스키마가 어긋날 때 **기동 시점에** 에러가 난다.
> 런타임에 이상하게 동작하는 것보다 훨씬 낫다. 그게 `validate` 를 쓰는 이유다.

### 접속 정보 (로컬)

```yaml
spring:
  datasource:
    url: jdbc:postgresql://localhost:5432/alldap
    username: alldap
    password: alldap
```

DB명·계정·비밀번호 전부 `alldap`. 시드 봇이 하나 들어 있는데 **이제 로컬 전용이 아니라
공개 데모 봇이다**(위 1-4 절 4번 참고). 주인이 없어(`user_id IS NULL`) 대시보드에 안 보인다.

```
bot_id     = 00000000-0000-0000-0000-000000000001
public_key = pk_local_dev
```

---

## 8. 공통 에러 포맷 (PRD §10.3)

```json
{ "error": { "code": "DOCUMENT_TOO_LARGE",
             "message": "파일이 20MB를 넘습니다. 문서를 나눠서 올려주세요." } }
```

- **전 계층 공통**이다. Spring·Python·Next.js 모두 이 포맷을 쓴다.
- `message` 는 한국어로, **"무엇을 어떻게 하면 되는지"까지** 담는다.
  - ❌ `"잘못된 요청입니다"`
  - ✅ `"구버전 .hwp 는 지원하지 않습니다. .hwpx 로 저장한 뒤 다시 올려주세요."`
- 구현은 `common/error/GlobalExceptionHandler` 한 곳에 모은다.
  컨트롤러마다 try-catch 를 흩뿌리면 포맷이 금방 어긋난다.
- 스택트레이스·SQL·Python 내부 경로가 `message` 에 섞여 나가지 않게 할 것.

---

## 9. 위젯 정적 파일 서빙

임베드 위젯(`widget/alldap-widget.js`)은 **Spring이 정적 파일로** 서빙한다.

```
api/src/main/resources/static/widget/alldap-widget.js
   → http://localhost:8080/widget/alldap-widget.js
```

설치 코드 한 줄에 들어가는 도메인이 API 도메인과 같아져 관리자가 복사할 게 하나뿐이고,
위젯 JS는 `public_key` 검증·CORS 정책과 수명주기를 같이 하므로 API와 함께 배포되는 게 자연스럽다.

✅ **가져오는 방법은 Gradle 복사 태스크로 정해져 있다.** `api/build.gradle` 의 `processResources` 가
빌드할 때 `widget/alldap-widget.js` 를 `static/widget/` 으로 담는다. **원본은 `widget/` 하나뿐이다**
(소스에 사본을 두면 반드시 한쪽만 고쳐져 어긋난다).

> ⚠️ **그래서 빌드를 안 하면 `http://localhost:8080/widget/alldap-widget.js` 가 안 나온다.**

✅ `/api/w/*` 의 **CORS 허용**도 들어가 있다(`SecurityConfig` · `CorsProperties`).
남의 도메인에서 호출되므로 없으면 무조건 막힌다.
⚠️ 다만 **CORS 는 인가 수단이 아니다.** CORS 필터가 먼저 끊으면 응답 본문이 `Invalid CORS request`
평문이 되어 우리 한국어 안내를 사용자가 못 읽는다. `/api/w/**` 는 CORS 로는 열고 **판단은 컨트롤러가** 한다.
자세한 내용은 `widget/README.md`.

---

## 10. W2 체크리스트: 전부 끝났다

- [x] Initializr 생성 (Boot 4.0.7 유지) → `./gradlew compileJava` 통과
- [x] JDK 21(Temurin) 설치
- [x] `ddl-auto: validate` 로 기동 성공 (= 엔티티가 실제 스키마와 맞는다는 뜻) + Flyway 적용
- [x] `global/exception` 에러 포맷 + `GlobalExceptionHandler`
- [x] 인증 (가입·로그인·JWT 필터)
- [x] 봇 CRUD + **소유권 검사** (봇 간 격리의 기준점)
- [x] `global/client` : Python 호출 + 타임아웃 + snake_case 변환 (+ 재시도·서킷브레이커, 4장)
- [x] 문서 업로드·목록·삭제 위임 (삭제는 Spring·Python 양쪽에서 봇을 본다)
- [x] 테스트 채팅 + 대화 로그 저장 + `messageId` 응답에 포함
- [x] 위젯 공개 API (`/api/w/{publicKey}/config`, `/chat`) + CORS + rate limit
- [x] **봇 간 데이터 격리 테스트** : 다른 사용자의 botId·docId 로 호출하면 막히는지 (통합 테스트에 있다)

그 뒤에 더해진 것: 평가 API · 문서 충돌 · 사용량 계량 · 결제 수단 · 요금제.
🔴 **요금제는 "무엇을 골랐나" 를 기억할 뿐이고 실제 청구는 아직 없다.**

> ⚠️ **밖에서 `/actuator/*` 는 안 열린다** (2026-09-10). actuator 는 8081 포트로 옮겼고
> Caddy 는 8080 만 프록시한다. 옛 안내(`curl https://<도메인>/actuator/health`)를 되살리지 말 것.

> **소유권 검사는 새로 짜지 말고 `BotService.findOwnedBot(userId, botId)` 와 같은 방식을 따를 것.**
> 검사를 조회 쿼리에 못박고(`findByIdAndUserId`), **남의 봇은 403 이 아니라 404** 로 답한다
> (403 은 "그 봇은 존재한다" 를 알려주는 셈이다). `userId` 는 `@AuthenticationPrincipal` 로만 받는다.

---

## 참고 파일

| 파일 | 내용 |
|---|---|
| `AGENTS.md` | 아키텍처 원칙, 테이블 소유권, 작업 규칙 (`CLAUDE.md` 는 이 파일을 가리키는 포인터) |
| `docs/PRD_v0.4.md` | §7 사이트맵 · §10 API 설계 · 부록A 미정 항목 |
| `docs/decisions.md` | 설계 결정 로그 (Boot 4.0.7, Flyway 도입 등의 근거 전문) |
| `api/src/main/resources/db/migration/V1__init.sql` | **스키마의 단일 진실 공급원** |
| `ai-service/app/main.py`, `schemas.py` | Python 내부 API 의 실제 컨트랙트 |
| `widget/README.md` | 임베드 위젯 구조와 Spring 이 만들어줘야 할 것 |
