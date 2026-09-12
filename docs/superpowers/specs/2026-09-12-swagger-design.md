# Swagger (OpenAPI) 문서화 설계

날짜: 2026-09-12
대상: `api/` (Spring Boot 4.0.7)
목적: 포트폴리오 전시용 API 문서. 로컬에서만 열린다.

---

## 1. 배경과 전제

### 왜 Spring 만인가

`ai-service/` (FastAPI) 는 **이미 Swagger 를 갖고 있다.** `FastAPI(title=..., version=...)` 한 줄로
`/docs`, `/redoc`, `/openapi.json` 이 자동 생성되고, docstring 과 Pydantic 모델에서 설명과 스키마를
알아서 뽑는다. 즉 "swagger 를 붙인다" 는 실질적으로 Spring 쪽 이야기다.

### Boot 4 호환은 실측으로 확인했다

springdoc-openapi 최신은 **2.8.6 이고 Boot 3 계열 대상**이다. 이 저장소는 Boot 4.0.7 이라
호환이 미확인이었다. 그래서 설계를 확정하기 전에 스파이크를 돌렸다 (2026-09-12).

| 항목 | 결과 |
|---|---|
| `./gradlew compileJava` | BUILD SUCCESSFUL |
| 기동 | "Started ApiApplication in 3.366 seconds". `NoSuchMethodError`/`NoClassDefFoundError` 없음, springdoc WARN 없음 |
| `/v3/api-docs` (JWT 붙임) | **200**, `{"openapi":"3.1.0",...}` 정상 생성 |
| `/swagger-ui/index.html` (JWT 붙임) | 200 |
| 인증 없이 | 401 `AUTHENTICATION_REQUIRED` (springdoc 문제가 아니라 `SecurityConfig` 의 `anyRequest().authenticated()` 때문) |
| `./gradlew test` | **206건 전부 통과** (failures 0 / errors 0 / skipped 0) |

해석된 의존성: `springdoc-openapi-starter-webmvc-ui:2.8.6` → `starter-webmvc-api`, `starter-common`,
`io.swagger.core.v3:swagger-core-jakarta:2.2.29`, `org.webjars:swagger-ui:5.20.1`, `webjars-locator-lite:1.1.3`.

### 규모

| 항목 | 수 |
|---|---|
| 컨트롤러 | 11 |
| 엔드포인트 | 33 |
| DTO | 44 |
| `ErrorCode` | 36 |

---

## 2. 검토한 대안과 선택 이유

### Spring REST Docs 를 기각했다

REST Docs 는 **테스트가 통과해야 문서가 생성되는** 방식이라 문서가 거짓말을 할 수 없다.
국내에서 Swagger 의 대안으로 자주 거론되고, 문서 정확성만 보면 더 나은 도구다.

**기각 사유는 도구의 우열이 아니라 이 저장소의 테스트 구조다.**
REST Docs 가 붙는 것은 MockMvc · WebTestClient · RestAssured 세 가지뿐인데,
기존 통합 테스트 206건은 **`TestRestTemplate` + 진짜 톰캣(`RANDOM_PORT`)** 이다. 붙지 않는다.

그래서 REST Docs 로 가려면 둘 중 하나를 해야 한다.

1. **206건을 MockMvc 로 재작성한다.** 비용보다 방향이 문제다. 이 저장소가 진짜 톰캣을 고집하는
   이유가 기록돼 있다: 통합 테스트 71건이 전부 초록인 상태에서 HTTP/2 업그레이드 버그가 났고,
   가짜 서버로는 재현 자체가 불가능했다. MockMvc 는 서블릿 컨테이너를 아예 안 띄우므로
   그때 못 잡은 부류를 더 못 잡는다. **문서를 얻으려고 테스트 신뢰도를 내리는 거래다.**
2. **문서 전용 테스트 33개를 병행한다.** 테스트가 두 벌이 되고, "문서가 거짓말 못 한다" 는
   장점이 문서용 테스트에 한해서만 성립한다. 그 테스트가 실제 동작을 안 태우면 결국 똑같이 거짓말한다.

→ **Swagger(springdoc) 채택.** 면접 답변: "REST Docs 가 문서 정확성은 더 낫다는 걸 알지만,
기존 통합 테스트가 진짜 톰캣 위 실제 HTTP 라서 붙지 않았고, MockMvc 로 바꾸는 것은 과거에
실제로 겪은 버그를 못 잡게 되는 거래라 택하지 않았습니다."

### `restdocs-api-spec` (REST Docs → OpenAPI → Swagger UI) 도 기각

정확성과 Try it out 을 둘 다 갖는 조합이지만, 위의 테스트 구조 문제가 그대로 남고
그 라이브러리의 Boot 4 호환은 또 미확인이다. 미확인 변수를 하나 더 들이지 않는다.

---

## 3. 노출 정책 (양쪽에서 막는다)

**로컬에서만 열린다.** 운영에는 노출하지 않는다.

이 저장소는 이미 **`SPRING_PROFILES_ACTIVE=prod` 가 운영 스위치**라는 축이 서 있다
(JWT 시크릿 가드, 빌링 키 가드가 전부 그 위에 있다). 새 축을 만들지 않고 이 축에 얹는다.
로컬은 프로파일 없이 돌고, 운영은 `docker-compose.prod.yml` 이 `prod` 를 준다.

| 겹 | 무엇 | 어디 |
|---|---|---|
| ① 문서 생성 자체를 끈다 | `springdoc.api-docs.enabled: false`, `springdoc.swagger-ui.enabled: false` | `application-prod.yaml` |
| ② 경로를 인증 뒤에 둔다 | `/v3/api-docs/**`, `/swagger-ui/**` 의 `permitAll` 을 `prod` 가 아닐 때만 건다 | `SecurityConfig` |

**한 겹만 두지 않는 이유가 이 저장소에 이미 있다.** 요금제 불변식("유료 요금제에는 카드가 있어야 한다")을
`PlanService` 와 `BillingService.delete` 양쪽에서 막은 것과 같다. 한쪽만 두면 우회 경로가 생겨
**규칙이 없는 것과 같아진다.**

- ①만 두면 나중에 누가 설정을 되돌리는 순간 전부 열린다.
- ②만 두면 문서는 계속 생성되면서 401 뒤에 숨어 있을 뿐이라, 계정 하나만 있으면 읽힌다.

### Python 은 손대지 않는다 (알고 남긴다)

`ai-service` 의 `/docs` 는 **조건 없이 항상 열려 있다.** 프로파일 분기도 스위치도 없다.
지금 안전한 이유는 배포 때 방화벽으로 `:8001` 을 막았기 때문이고, 이는 2026-09-07 에
외부에서 종료코드 1 로 실측 확인됐다.

즉 **Spring 은 두 겹, Python 은 네트워크 한 겹**이라 규칙이 어긋난다. 그럼에도 이번 범위에서 뺀다.
`/docs` 가 뚫릴 상황이면 `/internal/*` 자체가 이미 뚫린 것이라 문서가 추가로 주는 정보가 작고,
범위를 넓히면 Spring 33개도 Python 도 어중간해진다. **모르고 남긴 것이 아니라 알고 남긴 것이다.**
필요해지면 `config` 의 prod 플래그로 `docs_url=None` 을 거는 한 줄짜리 별도 슬라이스로 한다.

---

## 4. 공통 설정 (`OpenApiConfig` 한 파일)

컨트롤러마다 반복될 것을 한 곳에 모은다.

- **`Info`**: 제목 · 설명 · 버전. 설명에 아키텍처 한 줄을 넣는다.
  "외부에 노출되는 API 는 Spring 뿐이고 Python AI 서비스(:8001)는 내부망 전용이다."
  문서를 여는 사람이 가장 먼저 알아야 할 사실이다.
- **JWT 보안 스킴**: `bearerAuth`(HTTP bearer, JWT)를 정의하고 **전역 기본**으로 건다.
  Swagger UI 의 Authorize 에 토큰을 한 번 넣으면 전부 시험할 수 있다.
  인증이 없는 `/api/auth/signup` · `/api/auth/login` · `/api/w/**` 는 `@SecurityRequirements` 로 개별 해제한다.
- **공통 에러 응답**: `ErrorCode` 가 36개인데 엔드포인트마다 나열하면 문서를 못 읽는다.
  `OperationCustomizer` 로 **모든 엔드포인트에 공통인 것만**(401 · 500) 일괄로 붙이고,
  응답 스키마는 이 저장소의 전 계층 공통 포맷 `{ "error": { "code", "message" } }` 로 **한 번만 정의**한다.
  엔드포인트마다 의미가 다른 것(404 · 409 · 422 등)만 개별로 단다.

---

## 5. 애노테이션 범위와 깊이

| 대상 | 무엇 | 범위 |
|---|---|---|
| 컨트롤러 11개 | `@Tag(name, description)` | 전부 |
| 엔드포인트 33개 | `@Operation(summary, description)` | 전부 |
| 응답 코드 | `@ApiResponse` | 그 엔드포인트에서만 의미가 있는 것만. 공통 401 · 500 은 `OperationCustomizer` 담당 |
| 요청 DTO | `@Schema(description, example)` | 전부. Try it out 을 누르는 순간 필요한 값이라 example 이 실질적으로 중요하다 |
| 응답 DTO | `@Schema(description)` | **모호한 필드만.** `id` 에 "식별자", `createdAt` 에 "생성 시각" 을 다는 것은 노동이지 설명이 아니다 |

모든 문구는 **한국어**로 쓴다 (이 저장소 규칙).

### `description` 에는 "왜" 를 쓴다

`summary` 한 줄은 흔한 관행이지만, `description` 에 **"왜 이렇게 되어 있는가"** 를 쓰는 것은
흔하지 않다. 자동 생성으로는 절대 안 나오는 부분이고, 이 프로젝트가 파는 것이 정확히 그것이다.

써야 할 예:

- 문서 업로드가 왜 **202** 인가: 임베딩이 수십 초 걸려 HTTP 요청을 붙잡으면 타임아웃이 난다.
- 남의 봇이 왜 **403 이 아니라 404** 인가: 403 은 "그 봇이 존재한다" 를 알려주는 셈이라
  무작위 UUID 를 던져 403 만 골라내면 남의 봇 존재 여부를 훑을 수 있다.
- 위젯 설정 조회에서 `allowed_origins` 가 비면 왜 **전부 차단**인가: "전부 허용" 으로 두면
  모든 신규 봇이 무방비로 태어난다. publicKey 는 고객 사이트 HTML 에 그대로 노출된다.
- 채팅 응답의 `isFallback` 이 무엇인가: 문서에 근거가 없으면 지어내지 않는다는 제품의 핵심.
  검색 단계(`max_distance` · `answerable_max_distance`)와 생성 단계(`NO_ANSWER`) 두 겹.
- 위젯 채팅에 왜 rate limit 이 있는가: 인증 없이 열린 유일한 문이고, 채팅은 iframe 안에서
  나가 고객 Origin 이 오지 않아 Origin 검증을 걸 수 없다. 실질 방어가 rate limit 이다.

---

## 6. 검증

테스트 **두 개**를 넣는다. 이 저장소는 **"검사를 안 짠 게 아니라 짜둔 검사가 아무 데서도 안 돌았다"**
를 두 번 겪었다 (오픈 리다이렉트 `web/lib/redirect.check.ts`, 배포 rate limit 점검 명령).
그래서 둘 다 **CI 에서 도는 테스트**로 만든다. 문서에 적힌 수동 절차로 두지 않는다.

### ① 문서화 커버리지 테스트

`RequestMappingHandlerMapping` 에서 등록된 핸들러 목록을 받아, 각 핸들러 메서드에
`@Operation(summary)` 가 있는지 검사한다. **하나라도 없으면 실패**시키고, 없는 것들의
HTTP 메서드와 경로를 **전부 나열**한다 (하나만 찍으면 고칠 때마다 다시 돌려야 한다).

효과는 지금이 아니라 나중에 난다. 앞으로 34번째 엔드포인트를 추가할 때 설명을 빠뜨리면,
컴파일도 되고 기존 테스트도 초록이고 Swagger 화면도 뜨는데 그 하나만 조용히 껍데기로 남는다.
이 테스트가 그 순간 CI 에서 막는다.

**한계를 분명히 한다: 이 테스트는 빈칸만 본다.** `summary` 가 맞는 말인지는 검사하지 못한다.
`summary = "봇 목록 조회"` 라고 써놓고 실제로는 봇을 삭제하는 코드여도 통과한다.
이 저장소가 반복해서 낸 "기능은 고쳤는데 그것을 설명하는 자리를 안 고쳤다" 를 **완전히 막지는 못한다.**
빠뜨린 것만 잡는다.

### ② 운영 차단 테스트

`prod` 프로파일로 띄워 `/v3/api-docs` 와 `/swagger-ui/index.html` 이 **열리지 않는지** 확인한다.
3절의 두 겹이 실제로 동작한다는 것을 사람이 기억해서 확인하는 게 아니라 CI 가 확인한다.

`prod` 프로파일은 `DB_URL` 등을 환경변수로 요구하므로, 기존 Testcontainers 설정(`@ServiceConnection`)이
DB 를 주고 나머지 필수값(`JWT_SECRET`, `BILLING_CRYPTO_KEY`, `AI_SERVICE_BASE_URL`, `CORS_ALLOWED_ORIGINS`,
`TOSS_SECRET_KEY`)은 테스트 프로퍼티로 채운다.

---

## 7. PR 쪼개기

| PR | 내용 |
|---|---|
| **1** | 의존성 한 줄 + `application-prod.yaml` 두 줄 + `SecurityConfig` 프로파일 분기 + `OpenApiConfig` + **전 엔드포인트 `summary` 한 줄(33개)** + 테스트 ①② |
| **2** | 인증 · 봇 · 문서 깊게 (Auth 2 + Bot 5 + Document 3 = 10개) |
| **3** | 채팅 · 로그 · 위젯 · 충돌 깊게 (Chat 2 + Log 2 + Widget 2 + Conflict 3 = 9개) |
| **4** | 평가 · 사용량 · 결제 · 요금제 깊게 (Eval 7 + Usage 1 + Billing 4 + Plan 2 = 14개) |

PR 2~4 에서 더하는 것: `description`("왜"), 엔드포인트별 `@ApiResponse`, 요청 DTO `@Schema(example)`,
모호한 응답 필드 `@Schema(description)`.

**PR 1 에 `summary` 33개를 전부 넣는 이유**는 커버리지 테스트가 **첫 PR 부터 초록이어야** 하기 때문이다.
나중에 넣으면 그때까지 그 테스트가 없거나 빨간 채로 방치되고, 그것이 정확히 "안 도는 검사" 가 되는 경로다.
컨트롤러 11개 파일에 한 줄씩이라 기계적이고 리뷰 가능한 크기다.

전부 브랜치 + PR 로 간다 (인증 경로의 보안 설정을 건드리고, 왜 그렇게 했는지를 설명해야 하는 변경이다).

### 모델 배분

- **PR 1**: Opus. 보안 설정(`SecurityConfig` 프로파일 분기)과 테스트 설계가 들어간다.
- **PR 2~4**: Sonnet. 스펙이 확정된 뒤의 애노테이션 작업이다.
  단, `description` 문구의 정확성은 검토가 필요하므로 리뷰는 Opus 로 한다.

---

## 8. 한계 & 트레이드오프

- **springdoc 2.8.6 은 Boot 3 계열 대상이다.** Boot 4.0.7 에서 도는 것은 실측했지만
  (기동 · `/v3/api-docs` 200 · 테스트 206건 통과), **호환이 보장된 것이 아니라 우연히 맞는 것이다.**
  Boot 를 올릴 때 깨질 수 있고, 그때 springdoc 3.x 가 없으면 후퇴할 곳이 없다. 알고 택한다.
- **커버리지 테스트는 빈칸만 잡는다.** 내용의 정확성은 못 잡는다 (6절 ① 참고).
- **문서와 코드의 불일치를 원천 차단하지는 못한다.** 그것을 하는 도구는 REST Docs 인데
  2절의 이유로 기각했다. Swagger 애노테이션은 코드와 같은 파일에 있어 어긋날 확률을 낮출 뿐이다.
- **Python 은 여전히 네트워크 한 겹이다** (3절 참고). 알고 남긴다.
- **응답 DTO 의 `@Schema` 를 전부 달지 않는다.** "모호한 필드만" 의 판단은 주관적이라
  사람마다 경계가 다를 수 있다. 일관성보다 문서 가독성을 택했다.
- **운영에서 문서를 못 본다.** 면접에서 보여주려면 로컬에서 띄워야 한다.
  전시용이라는 목적과 일부 상충하지만, 노출 판단을 나중에 되돌리는 쪽이 그 반대보다 안전하다.
