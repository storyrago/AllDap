# 조사: AuthController 2개 엔드포인트의 실제 에러 응답 (2026-09-13)

**왜 조사했나:** Swagger PR 2(엔드포인트별 `@ApiResponse`)를 쓰기 전에, 각 엔드포인트가
<실제로> 낼 수 있는 응답이 무엇인지 확인하려고 했다. `ErrorCode` 에 정의돼 있다고 해서
그 엔드포인트에서 난다는 뜻이 아니기 때문이다. 없는 응답을 문서에 적으면 문서가 거짓말을 한다.

🔴 **PR 2 는 하지 않기로 했다(2026-09-13).** 이 API 를 쓰는 곳이 `web/` 하나뿐이고 이미 완성돼
있어서, 엔드포인트별 에러 문서화가 "아직 없는 사용자를 위한 문서" 였다. 근거는 `docs/decisions.md`
2026-09-13 항목. **이 파일은 그때 한 조사를 보존한 것이다** - 나중에 PR 2 를 하기로 하면
같은 조사를 다시 할 필요가 없다.

⚠️ **조사 시점은 `main` 의 `59f86e9` 다.** 코드가 바뀌면 아래 파일:줄 근거가 낡는다.
줄 번호가 안 맞으면 그 항목은 다시 확인할 것.

---

파일 경로는 전부 `api/src/main/java/com/alldap/api/` 기준이다.

## 공통 (두 엔드포인트 모두)

- 경로 보안: `SecurityConfig.java:92` 에서 `/api/auth/signup` · `/api/auth/login` 이 `permitAll`.
  컨트롤러에 `@SecurityRequirements` 가 이미 붙어 있다 (`AuthController.java:47`, `:75`).

- 🔴 **잘못된 토큰을 달고 와도 401 이 아니다** (확실함).
  `JwtAuthenticationFilter.java:90-107` 이 토큰 파싱 실패를 던지지 않고 요청에 기록만 한 뒤 통과시킨다.
  `permitAll` 경로라 인가 단계에서도 안 막힌다.
  → `INVALID_TOKEN` · `AUTHENTICATION_REQUIRED` 는 이 두 경로에서 원리적으로 나갈 수 없다. 달면 문서가 거짓말이 된다.

- 에러 본문 스키마: `ErrorResponse`, 즉 `{"error":{"code","message"}}`. PR 1 의 공통 스키마 그대로다.

---

## ① `POST /api/auth/signup`

### 1. 에러 응답 표

| HTTP | ErrorCode | 언제 나는가 | 근거 (파일:줄) | 확신도 |
|---|---|---|---|---|
| 409 | `EMAIL_ALREADY_EXISTS` | 이미 가입된 이메일. 사전검사(`existsByEmail`)와 DB UNIQUE 위반 두 경로가 같은 코드로 답한다 | `AuthService.java:118` / `:141` · 테스트 `AuthIntegrationTest.java:130` | 확실함 |
| 400 | `INVALID_INPUT` | `@Valid` 실패. 필드별 한국어 메시지를 `", "` 로 이어 `message` 에 담는다 | `GlobalExceptionHandler.java:48-57` | 확실함 |
| 400 | `INVALID_INPUT` | 본문이 없거나 깨진 JSON. `message` 가 고정 문구라 위와 <다르다> | `GlobalExceptionHandler.java:71-77` | 확실함 |
| 415 | `UNSUPPORTED_MEDIA_TYPE` | Content-Type 이 `application/json` 이 아닐 때 | `GlobalExceptionHandler.java:90-95` | 확실함 |
| 405 | `METHOD_NOT_ALLOWED` | GET 등 다른 메서드로 호출 | `GlobalExceptionHandler.java:104-117` | 확실함 |
| 500 | `INTERNAL_ERROR` | catch-all (DB 장애 등) | `GlobalExceptionHandler.java:257-262` | 확실함 |

🔴 **429 는 가입에서 날 수 없다** (확실함).
`rateLimiter` 호출이 signup 경로에 한 군데도 없다. `AuthService.java:85-88` 에
"TODO(W2 이후): 가입에도 IP 단위 rate limit 을 걸 것" 으로 남아 있다.
`ErrorCode` enum 에 `RATE_LIMIT_EXCEEDED` 가 있다고 달면 안 된다.

### 2. 성공 응답

**201 Created** · 본문 `AuthResponse`.
`Location` 헤더 없음. 이유가 `AuthController.java:40-42` 주석에 있다
(사용자 단건 조회 경로가 PRD §10.1 에 없어서. 없는 주소를 가리킬 수 없다).

### 3. 요청 DTO: `SignupRequest` (record)

| 필드 | 검증 제약 | example 지을 때 주의 |
|---|---|---|
| `email` | `@NotBlank` · `@Email` · `@Size(max=255)` | `name@example.com` |
| `password` | `@NotBlank` · `@Size(min=8, max=64)` [문자 수] · `@ByteLength(max=72)` [UTF-8 바이트] | 최소 8자. 두 제약이 서로 다른 단위를 잰다 (`SignupRequest.java:20-25`). 한글은 24자가 상한 |
| `name` | `@Size(max=50)`. `@NotBlank` 없음 = 선택 입력 | 공백만 넣으면 `null` 로 저장 (`AuthService.normalizeName`) |

`@ByteLength` 는 커스텀 제약 (`global/validation/ByteLength.java`). 필드 제약이라 `@Valid` 경로를
그대로 타서 다른 검증 실패와 완전히 같은 모양의 400 이 나간다
(`ByteLength.java:22-27` 이 그걸 선택 이유로 적어뒀다).

### 4. 응답 DTO 중 뜻이 모호한 필드

- `AuthResponse.token`: 액세스 토큰(JWT), TTL 24h. **리프레시 토큰은 없다** (`AuthResponse.java:14-15` TODO).
  이름만 보면 무슨 토큰인지, 얼마나 사는지 모른다. `description` 에 적을 값어치가 있다.
- `AuthResponse.user` = `UserResponse`: `id`(UUID) · `email` · `name`(nullable) · `createdAt`(`Instant`).
- `passwordHash` 는 절대 안 실린다 (`UserResponse.java:11`). 테스트가 응답 본문 전체를 문자열로 훑어
  `"password"` · `"$2a$"` 부재까지 검사한다 (`AuthIntegrationTest.java:121-125`).

### 5. `description` 재료 (전부 코드에 이미 있음)

1. **가입 직후 토큰까지 준다**, 재로그인을 시키지 않는다. `AuthController.java:38`
2. **201 인데 `Location` 이 없는 이유**: 사용자 단건 조회 경로가 없다. `AuthController.java:40-42`
3. 🔴 **가입은 사용자 열거(enumeration)를 일부러 막지 않는다.** 로그인은 더미 해시까지 써서 가입 여부를
   감추는데 가입은 409 로 그대로 알려준다. 비대칭은 빠뜨린 게 아니라 저울질한 결과다: 메일 발송 수단이
   없어 "가입 요청 접수" 로 뭉개면 사용자가 왜 로그인이 안 되는지 영영 알 수 없고, 그 UX 손해가 보안
   이득보다 크다고 판단했다. `AuthService.java:95-108` ← PR 2 `description` 에서 가장 값어치 있는 재료
4. **`saveAndFlush` 를 쓰는 이유**: `save()` 면 Hibernate 가 INSERT 를 커밋까지 미뤄
   catch 가 제약 위반을 못 잡고 500 이 나간다. `AuthService.java:126-129`
5. **비밀번호 제약이 두 개인 이유**: BCrypt 72바이트 한계. 없으면 한글 25자(75바이트)가
   `@Size(max=64)` 를 통과한 뒤 인코딩에서 터져 실제로 500 이 났었다.
   `SignupRequest.java:20-25` · `ByteLength.java:12-20`

⚠️ 문서화 대상은 아니지만 알아둘 것 (추정이 아니라 코드 사실):
`catch (DataIntegrityViolationException)` 이 **모든** 제약 위반을 `EMAIL_ALREADY_EXISTS` 로
변환한다 (`AuthService.java:133-143`). `users` 테이블에 다른 제약이 생기면 조용히 오답이 된다.

---

## ② `POST /api/auth/login`

### 1. 에러 응답 표

| HTTP | ErrorCode | 언제 나는가 | 근거 (파일:줄) | 확신도 |
|---|---|---|---|---|
| 401 | `INVALID_CREDENTIALS` | 없는 이메일과 틀린 비밀번호 <둘 다>. 상태코드·본문이 완전히 동일 | `AuthService.java:203-208` · 테스트 `AuthIntegrationTest.java:157-168` | 확실함 |
| 429 | `RATE_LIMIT_EXCEEDED` | IP 당 분당 요청 수 초과. 기본 10회/분 (`application.yaml:152`, `LOGIN_PER_MINUTE`) | `AuthController.java:80` → `RateLimiter.java:125-132` · 테스트 `:244` | 확실함 |
| 429 | `TOO_MANY_LOGIN_FAILURES` | (IP + 이메일) 연속 실패 누적. 기본 5회 / 15분 고정 윈도우 | `AuthService.java:189-193` · `:48` · `application.yaml:157` · 테스트 `:270` | 확실함 |
| 400 | `INVALID_INPUT` | `@Valid` 실패 (빈 값, 72바이트 초과 비밀번호) | `GlobalExceptionHandler.java:48-57` | 확실함 |
| 400 | `INVALID_INPUT` | 깨진/빈 JSON 본문 (`message` 고정 문구) | `GlobalExceptionHandler.java:71-77` | 확실함 |
| 415 | `UNSUPPORTED_MEDIA_TYPE` | Content-Type 불일치 | `GlobalExceptionHandler.java:90-95` | 확실함 |
| 405 | `METHOD_NOT_ALLOWED` | GET 등 | `GlobalExceptionHandler.java:104-117` | 확실함 |
| 500 | `INTERNAL_ERROR` | catch-all | `GlobalExceptionHandler.java:257-262` | 확실함 |

🔴 **429 가 두 종류다.** 같은 상태 코드에 다른 `code` 가 나가고 원인도 다르다 (요청 수 vs 실패 누적).
springdoc `@ApiResponse` 는 상태 코드 하나에 응답 하나라, 429 하나에 두 코드를 어떻게 설명할지
PR 2 를 하게 되면 먼저 정해야 한다.

⚠️ **검사 순서도 문서화 가치가 있다** (확실함):
`AuthController.java:80` (IP 요청 수) → `AuthService.java:189` (실패 누적) → `:201` (비밀번호 대조).
실패 누적 차단은 대조 <전에> 걸리므로, **차단 중에는 맞는 비밀번호도 429 다**
(테스트 `AuthIntegrationTest.java:288-294` 가 이걸 "가장 중요한 검증" 으로 적어뒀다).

### 2. 성공 응답

**200 OK** · 본문 `AuthResponse` (signup 과 같은 DTO).
201 이 아닌 이유가 `AuthController.java:56-58` 에 있다: 새 리소스를 만드는 게 아니라
이미 있는 계정을 확인하고 토큰을 발급받는 행위라서.

### 3. 요청 DTO: `LoginRequest` (record)

| 필드 | 검증 제약 |
|---|---|
| `email` | `@NotBlank` <만>. `@Email` 을 일부러 안 붙였다 |
| `password` | `@NotBlank` · `@ByteLength(max=72)`. 최소 길이 없음 |

🔴 **`@Email` 과 `@Size(min=8)` 이 없는 것이 설계다.** 실패 사유를 세분화하면
"이 이메일은 가입돼 있다" 가 샌다 (`LoginRequest.java:9-11`, `:23`).

`@ByteLength` 만 예외인 이유: BCrypt 가 72바이트에서 **조용히 잘라내서**, 검증이 없으면
비밀번호가 정확히 72바이트인 계정에 73 · 75바이트 비밀번호로도 로그인이 성공한다. 리뷰에서 세 가지
다른 비밀번호가 같은 계정에 전부 200 으로 로그인되는 것이 실기동으로 확인됐다 (`LoginRequest.java:13-22`).
그리고 이 400 은 계정 존재 여부와 무관해서 열거를 유발하지 않는다 (`LoginRequest.java:20-22`).
이 구분 자체가 `description` 재료다.

### 4. 응답 DTO 중 뜻이 모호한 필드

signup 과 동일 (`AuthResponse` / `UserResponse`). `token` 의 TTL 24h · 리프레시 없음이 여기서도 모호한 지점.

### 5. `description` 재료 (전부 코드에 이미 있음)

1. **실패 응답이 하나뿐인 이유**: 구분해주면 로그인 폼이 가입 여부 조회 도구가 된다. `AuthService.java:181-183`
2. **타이밍 공격 방어**: 사용자를 못 찾아도 기동 시 만든 <더미 해시>로 `matches()` 를 한 번 돌린다.
   본문을 통일해도 응답 <속도>가 가입 여부를 알려주기 때문이다. 평문을 하드코딩하지 않고 기동마다
   랜덤 UUID 로 만드는 이유까지 적혀 있다. `AuthService.java:56-75`
3. **두 겹 방어의 <세는 대상이 다르다>**: IP(여러 계정 훑기) vs IP+이메일(한 계정 파고들기).
   분당 10회면 하루 14,400회라 요청 수 제한만으로는 부족하다. `AuthService.java:185-197`
4. **키가 왜 IP <와> 이메일 둘 다인가**: IP 만이면 NAT 뒤 동료에게 말려들고, 이메일만이면 공격자가
   남의 계정을 잠그는 서비스 거부가 된다. 대가는 분산 공격(봇넷)을 못 막는 것이고 그건 캡차 · 2단계
   인증의 몫이라고 명시돼 있다. `AuthService.java:198-210`
5. **왜 지연(sleep)이 아니라 차단인가**: 지연은 톰캣 스레드를 붙잡아 방어 장치 자체가 서비스 거부
   수단이 된다. 막힌 요청은 BCrypt 대조조차 안 해서 더 싸다. `AuthService.java:212-218`
6. **왜 영구 잠금이 아니라 15분인가**: 풀어줄 관리자 화면도 메일 발송 수단도 없어서. 영구 잠금이면
   "남의 계정 잠그기" 가 곧 완전한 서비스 거부가 된다. `AuthService.java:39-46`
7. 🔴 **429 문구가 가입 여부를 흘리지 않게 쓰여 있다.** "그 계정은" 이나 "비밀번호가" 라고 말하면 안 된다.
   가입되지 않은 이메일로 실패를 쌓아도 똑같이 나가기 때문이다 (`ErrorCode.java` 의
   `TOO_MANY_LOGIN_FAILURES` 바로 위 주석). 전용 테스트도 있다 (`AuthIntegrationTest.java:296`).
8. ⚠️ **"15분" 이 `ErrorCode` 문구와 `AuthService.FAILURE_WINDOW` 양쪽에 글자로 박혀 있고**, 양쪽 주석이
   서로를 가리키며 "한쪽만 고치면 안내가 거짓이 된다" 고 경고한다. `description` 에 숫자를 또 적으면
   <세 번째 사본>이 생긴다. PR 2 를 하게 되면 그때 판단할 것.
9. **IP 신뢰 전제**: `getRemoteAddr()` 이고, 앞단 Caddy 가 `Forwarded` 를 지워야 유효하다.
   `AuthController.java:65` · `AuthService.java:220-221`

---

## 마무리

표의 모든 행은 호출 경로를 끝까지 따라가 확인했고 대부분 통합 테스트로 뒷받침된다. 추정으로 적은 것은 없다.

다만 405 · 415 · 500 은 이 두 엔드포인트 고유가 아니라 JSON 엔드포인트 전반에 공통이다.
엔드포인트별 `@ApiResponse` 로 달지, 공통 처리로 둘지는 PR 2 를 하게 되면 정해야 한다
(PR 1 이 공통 401 을 "토큰을 받는 경로에만" 붙인 것과 같은 부류의 판단이다).
