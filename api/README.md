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

## ⚠️ 현재 상태

**이 디렉터리에는 아직 코드가 없다.** Spring Initializr로 프로젝트를 생성하는 중이다.
아래는 "무엇을 어떻게 만들 것인가"에 대한 설계 문서이지, 만들어진 것에 대한 설명이 아니다.

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
4. **`V1__init.sql` 끝의 시드 INSERT 가 이제 운영에도 적용된다.** initdb 시절엔 로컬 전용이었다.
   배포 전에 `dev` 프로파일로 분리할지 결정할 것. **[미정]**

→ `docs/decisions.md` 참고.

---

## 2. Spring 공개 API → Python 내부 API 위임 매핑

Python 쪽 컨트랙트는 **`ai-service/app/main.py` 와 `schemas.py` 를 직접 읽어 확인한 것**이다.
추측이 아니라 실제 코드 기준이므로, Python을 고치면 이 표도 함께 고쳐야 한다.

| Spring 공개 API (PRD §10.1) | → Python 내부 API | 비고 |
|---|---|---|
| `POST /api/bots/{botId}/documents` | `POST /internal/bots/{botId}/documents` | multipart, **필드명 `file`**. 202 + `DocumentOut` |
| `GET /api/bots/{botId}/documents` | `GET /internal/bots/{botId}/documents` | `DocumentOut[]` |
| `DELETE /api/documents/{docId}` | `DELETE /internal/documents/{docId}` | 204 (본문 없음) |
| `POST /api/bots/{botId}/chat` (테스트 채팅) | `POST /internal/chat` | `ChatResponse` |
| `POST /api/w/{publicKey}/chat` (위젯) | `POST /internal/chat` | publicKey → botId 로 바꿔 호출 |
| `POST/GET /api/bots/{botId}/eval/*` | `POST /internal/eval/*` | ❌ **아직 존재하지 않음 (W3에서 구현)** |
| `POST /api/auth/*`, `/api/bots`, `/api/messages/{id}/feedback`, `/api/bots/{botId}/logs`, `GET /api/w/{publicKey}/config` | — | 위임 없음. Spring이 DB로 직접 처리 |
| — | `GET /health` | 헬스체크. 기동 확인·장애 감지용 |

> **`/internal/eval/*` 은 Python 에 아직 없다.** PRD §10.2 에 적혀 있지만 W3 예정이다.
> 지금 Spring 에 평가 관련 호출 코드를 만들면 404 만 받는다. W3에서 Python부터 만들 것.

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
- `DELETE /api/documents/{docId}` → ⚠️ **Python 의 삭제 API 는 `doc_id` 만 받고 봇 소유권을 안 본다.**
  Spring 이 먼저 `documents.bot_id` 를 읽어(Spring은 documents 읽기 권한 있음)
  → `bots.user_id` 가 요청자와 같은지 확인 → 그 다음 위임.
  이 검사를 빠뜨리면 **남의 문서를 id만 알면 지울 수 있다.**
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
# application.yml — 절대 이렇게 하지 말 것
spring:
  jackson:
    property-naming-strategy: SNAKE_CASE
```

이건 **전역 설정**이라 Python 호출뿐 아니라 **브라우저에 주는 공개 API 응답까지 snake_case가 된다.**
프론트(Next.js·위젯)가 갑자기 `is_fallback` 을 받게 되고, PRD의 공개 API 규약이 깨진다.

### ✅ 권장: 변환은 `client` 패키지 **경계 한 곳**에서만

Python 통신용 DTO는 `client` 패키지 안에만 두고, 필드마다 `@JsonProperty` 로 이름을 명시한다.

- 어느 필드가 Python의 어느 필드인지 **파일 하나만 열면 다 보인다** (초보자가 읽기 좋다)
- 전역 설정이 아니라 그 DTO에만 적용되므로 공개 API는 영향이 없다
- 필드가 많아져 `@JsonProperty` 가 지겨워지면, 그때 **RestClient 전용 ObjectMapper** 에만
  `SNAKE_CASE` 전략을 주는 방식으로 바꾼다 (여전히 전역 설정은 아니다)

`client` 패키지 밖(도메인 서비스·컨트롤러)은 **camelCase 만 안다.**
`ChatAiResponse`(snake) → `ChatResponse`(camel) 변환도 이 경계에서 끝낸다.
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

### 엔드포인트마다 타임아웃을 다르게

| 호출 | connect | read | 근거 |
|---|---|---|---|
| `GET /health` | 1s | 2s | 살았는지만 본다. 느리면 죽은 것으로 친다 |
| `GET .../documents` | 3s | 10s | 단순 조회 |
| `POST .../documents` | 3s | 30s | 파일 전송 시간 포함 (처리는 Python이 백그라운드로 하므로 202는 금방 온다) |
| `POST /internal/chat` | 3s | 60s | 검색 + LLM 생성. 여기서 짧게 잡으면 정상 답변을 끊어먹는다 |

> 위 숫자는 **가정**이다. W2에서 실제로 재보고 조정한 뒤 이 표를 갱신할 것.

### 재시도는 아무 데나 걸면 안 된다

```
✅ 재시도해도 되는 것 : GET (문서 목록, health) — 여러 번 불러도 결과가 같다
⚠️ 조심해야 하는 것   : POST /internal/chat — 재시도 = LLM 중복 호출 = 비용 2배
🚫 하면 안 되는 것    : POST .../documents 를 응답 못 받았다고 재시도
                       → documents 행이 2개 생기고 임베딩도 2번 돈다 (돈이 두 배로 나간다)
```

원칙: **"서버에 닿지도 못한 실패"(연결 거부·연결 타임아웃)만 재시도**하고,
**"요청은 갔는데 응답을 못 받은 실패"(읽기 타임아웃)는 재시도하지 않는다.**
후자는 서버가 이미 일을 했을 수 있기 때문이다.

- TODO(W2): 재시도는 `spring-retry` 를 쓸지 직접 구현할지 정할 것 (Initializr에 없어 의존성 추가 필요)
- TODO(W2): 서킷브레이커(Resilience4j)는 **일단 보류.** 타임아웃 + 좁은 범위의 재시도부터 넣고,
  Python이 실제로 자주 죽는지 본 뒤에 판단한다. 안 겪은 문제를 미리 막느라 복잡도를 올리지 말 것.
- 채팅이 실패하면 사용자에게는 PRD §10.3 포맷의 한국어 안내를 준다.
  이때 **봇의 `fallback_message` 를 쓰면 안 된다.** "문서에 답이 없음"과 "서버 장애"는 다른 사건이고,
  둘을 같은 문구로 뭉개면 품질 대시보드의 미답변 통계가 오염된다.

---

## 5. ⚠️ 알려진 갭 — 봇별 설정이 Python까지 전달되지 않는다

**W2에서 반드시 부딪힐 문제이므로 미리 적어둔다.**

`bots` 테이블에는 `system_prompt` 와 `fallback_message` 컬럼이 있고 PRD F-06은 봇별 설정을 요구한다.
그런데 Python의 `POST /internal/chat` 요청 스키마(`ChatRequest`)는
**`bot_id` · `message` · `session_id` 세 개만 받는다.** 봇 설정을 넘길 자리가 없다.

| 설정 | 지금 가능한가 | 방법 |
|---|---|---|
| `fallback_message` | ✅ 우회 가능 | Spring이 응답의 `is_fallback == true` 를 보고 `answer` 를 그 봇의 문구로 **치환** |
| `system_prompt` | ❌ **반영 불가** | Python의 `ChatRequest` 와 `generator.py` 를 고쳐야 한다 |

**그래서 지금은 모든 봇이 같은 시스템 프롬프트로 동작한다.**
고치기로 결정하기 전까지 "봇마다 말투·역할을 설정할 수 있다"고 문서·화면·면접에서 말하면 안 된다.

TODO(W2 또는 W3): Python `ChatRequest` 에 `system_prompt` 를 선택 필드로 추가할지 결정.
추가한다면 Python이 `bots` 를 직접 읽는 방식(테이블 읽기 권한은 있다)과
Spring이 요청에 실어 보내는 방식 중 후자가 낫다 — **설정의 주인은 Spring**이고,
Python이 봇 설정까지 읽기 시작하면 소유권 경계가 흐려진다.

### 그 밖의 갭

- **`messageId` 가 없다.** `ChatResponse` 에 id가 없어서 👍/👎(`POST /api/messages/{msgId}/feedback`)
  를 붙일 수 없다. `messages` 테이블은 Spring이 쓰므로 **Spring이 로그를 저장하며 만든 id** 를
  채팅 응답에 넣어줘야 한다. 위젯이 이 값을 기다리고 있다 (`widget/README.md` 참고).
- **`bots` 에 색상 컬럼이 없다.** PRD F-04는 "브랜드 색상 1종 커스텀"을 요구하는데
  `api/src/main/resources/db/migration/V1__init.sql` 에 해당 컬럼이 없다. `GET /api/w/{publicKey}/config` 를 만들 때 결정할 것.
  (`ddl-auto` 로 컬럼을 만들면 안 된다. 스키마는 Flyway 마이그레이션이 주인이다)
- **`allowed_origins` 검증 미정.** 컬럼은 있으나 검증 로직이 없다 (PRD 부록A #3, 결정 시점 W2).
  검증 전까지는 `public_key` 만 알면 누구나 남의 봇을 자기 사이트에 붙일 수 있다.

---

## 6. 패키지 구조 제안 (`com.alldap.api`)

계층(controller/service/repository)으로 먼저 나누지 않고 **도메인으로 먼저 나눈다.**
"봇 기능이 어디 있지?" 를 폴더 하나에서 찾을 수 있고, 도메인이 커지면 그 폴더만 들여다보면 된다.
계층은 각 도메인 폴더 **안에서** 나눈다.

```
com.alldap.api
├── common/          전 계층 공통. PRD §10.3 에러 포맷과 공통 예외를 여기 한 곳에 둔다
│   └── error/         ErrorCode(코드 enum) · ErrorResponse(응답 DTO) · GlobalExceptionHandler
├── config/          설정 클래스 모음. SecurityConfig · RestClientConfig · CorsConfig
├── security/        JWT 발급·검증 필터, 인증 주체(로그인한 사용자를 컨트롤러에 넘겨주는 것)
├── client/          ★ Python AI 서비스 호출 전담. snake_case ↔ camelCase 변환이 여기서 끝난다
│                      AiClient(호출) + snake_case DTO. 밖에서는 Python의 존재를 몰라도 되게 한다
└── domain/
    ├── user/        가입·로그인·비밀번호 해시 (users 테이블)
    ├── bot/         봇 CRUD, public_key 발급, 소유권 검사 (bots 테이블) ★ 격리의 기준점
    ├── document/    문서 업로드·목록·삭제. 권한 검사 후 client 로 위임 (documents 읽기 전용)
    ├── chat/        테스트 채팅 + 대화 로그 저장 + 피드백 (conversations, messages 쓰기)
    ├── eval/        평가 질문·실행·이력 조회 (eval_* 읽기). W3에서 채운다
    └── widget/      공개 엔드포인트 /api/w/*. 인증 없음 → rate limit·Origin 검증이 여기 붙는다
```

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
| `users`, `bots` | **Spring** | Python | Spring이 주인. 자유롭게 CRUD |
| `documents` | **Python** | Spring | ⚠️ 조회만. `status` 는 Python이 갱신한다. Spring이 UPDATE 하면 안 됨 |
| `chunks` | **Python** | — | ⚠️ **JPA 엔티티를 만들지 말 것.** Spring은 이 테이블을 아예 건드리지 않는다 |
| `conversations`, `messages` | **Spring** | — | 대화 로그·피드백은 Spring이 저장 |
| `eval_*` | **Python** | Spring | 실행은 Python, 조회·표시는 Spring |

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

**스키마의 단일 진실 공급원은 `api/src/main/resources/db/migration/V1__init.sql` 이다.**
컬럼이 필요하면 엔티티가 아니라 **새 마이그레이션(`V2__*.sql`)** 을 추가한다. `V1__init.sql` 은 수정 금지.

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

DB명·계정·비밀번호 전부 `alldap`. 로컬 개발용 시드 봇이 하나 들어 있다.

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

TODO(W2): 파일을 어떻게 가져올지(직접 복사 / Gradle 복사 태스크 / 리소스 핸들러 매핑) 결정.
`/api/w/*` 의 **CORS 허용**도 함께 필요하다 — 남의 도메인에서 호출되므로 없으면 무조건 막힌다.
자세한 내용은 `widget/README.md`.

---

## 10. W2 체크리스트

- [x] Initializr 생성 (Boot 4.0.7 유지) → `./gradlew compileJava` 통과
- [x] JDK 21(Temurin) 설치 — IntelliJ Project SDK 지정은 남음
- [x] `ddl-auto: validate` 로 기동 성공 (= 엔티티가 실제 스키마와 맞는다는 뜻). Flyway V1 적용 + `/actuator/health` 200 확인
- [ ] `common/error` 에러 포맷 + `GlobalExceptionHandler`
- [ ] 인증 (가입·로그인·JWT 필터)
- [ ] 봇 CRUD + **소유권 검사** (봇 간 격리의 기준점)
- [ ] `client` 패키지 — Python 호출 + 타임아웃 + snake_case 변환
- [ ] 문서 업로드·목록·삭제 위임 (삭제 시 소유권 검사 빠뜨리지 말 것)
- [ ] 테스트 채팅 + 대화 로그 저장 + `messageId` 응답에 포함
- [ ] 위젯 공개 API (`/api/w/{publicKey}/config`, `/chat`) + CORS + rate limit
- [ ] **봇 간 데이터 격리 테스트** — 다른 사용자의 botId·docId 로 호출하면 막히는지 (NFR 확정 항목)

---

## 참고 파일

| 파일 | 내용 |
|---|---|
| `AGENTS.md` | 아키텍처 원칙, 테이블 소유권, 작업 규칙 (`CLAUDE.md` 는 이 파일을 가리키는 포인터) |
| `docs/PRD_v0.3.md` | §7 사이트맵 · §10 API 설계 · 부록A 미정 항목 |
| `docs/decisions.md` | 설계 결정 로그 (Boot 4.0.7, Flyway 도입 등의 근거 전문) |
| `api/src/main/resources/db/migration/V1__init.sql` | **스키마의 단일 진실 공급원** |
| `ai-service/app/main.py`, `schemas.py` | Python 내부 API 의 실제 컨트랙트 |
| `widget/README.md` | 임베드 위젯 구조와 Spring 이 만들어줘야 할 것 |
