# 조사: BotController 5개 엔드포인트의 실제 에러 응답 (2026-09-13)

**왜 조사했나:** Swagger PR 2(엔드포인트별 `@ApiResponse`)를 쓰기 전에, 각 엔드포인트가
<실제로> 낼 수 있는 응답이 무엇인지 확인하려고 했다. `ErrorCode` 에 정의돼 있다고 해서
그 엔드포인트에서 난다는 뜻이 아니기 때문이다. 없는 응답을 문서에 적으면 문서가 거짓말을 한다.

🔴 **PR 2 는 하지 않기로 했다(2026-09-13).** 이 API 를 쓰는 곳이 `web/` 하나뿐이고 이미 완성돼
있어서, 엔드포인트별 에러 문서화가 "아직 없는 사용자를 위한 문서" 였다. 근거는 `docs/decisions.md`
2026-09-13 항목. **이 파일은 그때 한 조사를 보존한 것이다** - 나중에 PR 2 를 하기로 하면
같은 조사를 다시 할 필요가 없다.

📌 **PR 2 와 무관하게 값어치가 남는 부분이 있다: 6절이다.** "남의 봇은 403 이 아니라 404" 와
"`allowedOrigins` 가 비면 전부 차단" 이 <어디서 강제되고 어디에 근거가 적혀 있는지>를 한자리에
모아뒀다. 둘 다 반대로 읽히면 곧바로 보안 오해가 되는 규칙이다.

⚠️ **조사 시점은 `main` 의 `59f86e9` 다.** 코드가 바뀌면 아래 파일:줄 근거가 낡는다.
줄 번호가 안 맞으면 그 항목은 다시 확인할 것.

---

읽은 파일: BotController · BotService · BotRepository · Bot(엔티티) · 4개 DTO · ErrorCode · GlobalExceptionHandler · ApiException · ApiAuthenticationEntryPoint · ApiAccessDeniedHandler · SecurityConfig · OpenApiConfig · BotIntegrationTest. 코드는 한 줄도 고치지 않았다.

## 0. 이 컨트롤러 전체에 공통인 것

| HTTP | ErrorCode | 언제 나는가 | 근거 (파일:줄) | 확신 |
|---|---|---|---|---|
| 401 | AUTHENTICATION_REQUIRED | 토큰을 아예 안 보냄. anyRequest().authenticated() 에 걸려 컨트롤러 도달 전 차단 | SecurityConfig.java:135, ApiAuthenticationEntryPoint.java:40 | 확실 |
| 401 | INVALID_TOKEN | 토큰은 왔는데 만료·서명 불일치. 필터가 ErrorResponseWriter.record 로 코드를 심고 EntryPoint 가 그걸 우선 사용 | JwtAuthenticationFilter.java:106, ErrorResponseWriter.java:64,74 | 확실 |
| 500 | INTERNAL_ERROR | 마지막 그물 | GlobalExceptionHandler.java:257-263 | 확실 |
| 405 | METHOD_NOT_ALLOWED | 주소는 맞고 메서드가 틀림(예: PUT /api/bots/{id}). Allow 헤더 동봉 | GlobalExceptionHandler.java:104-118 | 확실 |

🔴 401 두 개는 PR 1 이 이미 자동으로 붙인다. OpenApiConfig:104-108 이 @SecurityRequirements 가 없는 메서드에 AUTHENTICATION_REQUIRED 기준 401 을 단다. BotController 5개는 전부 해제 애노테이션이 없으니 401 을 다시 달면 안 된다. 응답을_없을_때만_붙인다 가 containsKey 로 덮지 않으므로, 직접 달면 공통 것이 지고 직접 단 것이 남는다. 다만 INVALID_TOKEN 은 공통 문구에 안 들어간다. 굳이 적으려면 description 에 한 줄로 쓰는 편이 낫다.

403 은 이 컨트롤러에서 나가지 않는다. ACCESS_DENIED 는 ApiAccessDeniedHandler 전용이고, 역할(role) 개념이 없어 지금 발동 경로가 없다(ApiAccessDeniedHandler.java:16-22 가 직접 그렇게 적어둠).

rate limit 도 이 컨트롤러에는 없다. RateLimiter 사용처는 WidgetController · AuthController(+AuthService) 뿐이다. RATE_LIMIT_EXCEEDED · TOO_MANY_LOGIN_FAILURES 는 달면 거짓말이다.

415 UNSUPPORTED_MEDIA_TYPE 은 본문을 받는 둘(createBot · updateBot)에서만 난다. 본문이 없는 셋에서는 Content-Type 협상 자체가 없다. 추정(높음) - HttpMediaTypeNotSupportedException 이 @RequestBody 바인딩에서만 나오기 때문이고, 실제로 돌려보지는 않았다.

## 1. GET /api/bots - getMyBots

성공: 200 · List<BotSummaryResponse> (배열). 봇이 없으면 빈 배열 [] (BotService.java:69-71)

| HTTP | ErrorCode | 언제 나는가 | 근거 | 확신 |
|---|---|---|---|---|
| 401 | AUTHENTICATION_REQUIRED / INVALID_TOKEN | 위 공통 | 공통 | 확실 |
| 500 | INTERNAL_ERROR | 공통 그물 | 공통 | 확실 |

그 외에는 없다. 입력이 없고(경로변수·본문·쿼리 전부 없음) 서비스가 던지는 예외도 없다.

요청 DTO: 없음

응답 DTO 필드 중 뜻이 모호한 것 (BotSummaryResponse.java)
- publicKey - 위젯 공개 주소 /w/{publicKey} 에 쓰는 키. 고객 사이트 HTML 에 그대로 노출되는 값이다. "pk_" + 16바이트 난수의 URL-safe Base64(패딩 없음) = 25자. 봇 id(UUID)와 분리한 이유는 "유출 시 키만 재발급" 하려는 것이다 (Bot.java:84-90, 57-59)
- allowedOrigins - 아래 6절 참고. 빈 배열 = 전부 차단
- documentCount - 처리 중·실패 문서까지 포함한 전체 개수. 문서 관리 화면 목록 길이와 일치 (BotSummaryResponse.java:31)
- weeklyConversationCount - 달력 주가 아니라 지금으로부터 168시간 롤링 창. 위젯 채팅과 관리자 테스트 채팅을 모두 셈 (BotService.java:44-57)
- latestOverallFaithfulness - 가장 최근 완료된 평가 실행의 전체 충실성 = avg_faithfulness × scored_count / question_count, 소수 3자리. 평균(avgFaithfulness)이 아니다. 평균은 답을 덜 할수록 올라가는 생존 편향이 있어 일부러 다른 값을 쓴다. 계산 불가능한 실행은 0 이 아니라 null 이다("모른다" 와 "0점" 은 다른 사실) (BotSummaryResponse.java:35-47, BotRepository.java:64-75)
- systemPrompt - nullable. 봇별 답변 지침이고 실제 답변에 반영된다. 단 Spring 이 전달하는 게 아니라 Python 이 bots 컬럼을 직접 읽는다 (Bot.java:92-108)

description 재료 ("왜")
- 목록 응답이 상세(BotResponse)와 다른 타입인 이유: 한 DTO 를 공유하면 상세 응답에서 집계 3개가 전부 null 이 되어 "집계가 0 이다" 와 "이 응답은 집계를 담지 않는다" 가 같은 모양이 된다 (BotSummaryResponse.java:15-20)
- 쿼리가 봇 개수와 무관하게 정확히 2번이다(목록 1 + 집계 1). 카드마다 세면 3N+1 이 된다 (BotService.java:62-65, BotRepository.java:31-47)

## 2. POST /api/bots - createBot

성공: 201 Created · BotResponse · Location: /api/bots/{id} 헤더 동봉 (BotController.java:75, 테스트 BotIntegrationTest:83,99)

| HTTP | ErrorCode | 언제 나는가 | 근거 | 확신 |
|---|---|---|---|---|
| 400 | INVALID_INPUT | name 이 빈 값/공백/누락 → "봇 이름을 입력해주세요." · 100자 초과 → "봇 이름은 100자까지 입력할 수 있습니다." (필드명 접두사 "name: " 가 붙음) | CreateBotRequest.java:13-15, GlobalExceptionHandler.java:48-58, 테스트 :104-108 | 확실 |
| 400 | INVALID_INPUT | JSON 이 깨졌거나 본문이 아예 없음 → "요청 본문(JSON)을 읽을 수 없습니다…" | GlobalExceptionHandler.java:71-78 | 확실 |
| 415 | UNSUPPORTED_MEDIA_TYPE | Content-Type 이 application/json 이 아님 | GlobalExceptionHandler.java:90-96 | 추정(높음) |
| 401 | INVALID_TOKEN | 🔴 토큰은 유효한데 그 사이 계정이 삭제된 경우. 이 엔드포인트에만 있다 | BotService.java:93-94 | 확실(테스트는 없음) |
| 500 | INTERNAL_ERROR | publicKey UNIQUE 충돌(의도적으로 재시도 안 함) 등 | BotService.java:100-102 | 확실 |

요청 DTO: CreateBotRequest { String name }
- @NotBlank(message="봇 이름을 입력해주세요.") · @Size(max=100, message="봇 이름은 100자까지 입력할 수 있습니다.")
- 서비스에서 trim() 후 저장 (BotService.java:96)
- example 후보: {"name": "사내 규정 안내봇"}

응답 DTO: BotResponse (아래 3절 참고)

description 재료
- 이름 하나만 받는 이유: 나머지 설정(인사말·거절 문구·허용 도메인)은 기본값으로 만들고 설정 화면에서 고치게 한다. 생성 단계를 가볍게 둬야 이탈이 적다 (CreateBotRequest.java:9-10)
- 생성 직후 기본값 (Bot.create, Bot.java:150-159): welcomeMessage = "무엇을 도와드릴까요?", fallbackMessage = "문서에서 답을 찾지 못했어요. 담당자에게 문의해주세요.", systemPrompt = null, allowedOrigins = [] (= 위젯 전부 차단), publicKey 자동 생성
- Location 헤더를 붙인 이유: 만들어진 리소스를 조회할 경로가 실제로 존재하기 때문이다(AuthController 와 다른 점) (BotController.java:67-68)
- publicKey 충돌 재시도를 안 넣은 이유: 16바이트 난수라 확률이 무시할 수준이고, 재시도 루프를 넣는 순간 그 루프가 맞는지 검증할 방법이 없어진다 (BotService.java:100-102)

## 3. GET /api/bots/{botId} - getBot

성공: 200 · BotResponse

| HTTP | ErrorCode | 언제 나는가 | 근거 | 확신 |
|---|---|---|---|---|
| 404 | BOT_NOT_FOUND | 없는 봇 그리고 남의 봇 (6절 참고) | BotService.java:140-143, 테스트 :128-134 | 확실 |
| 400 | INVALID_INPUT | {botId} 가 UUID 형식이 아님(예: /api/bots/hello) → "주소에 잘못된 값이 들어 있습니다…" | GlobalExceptionHandler.java:153-161 | 확실 |
| 401 / 500 | 공통 | | | 확실 |

요청 DTO: 없음. 경로변수 botId (UUID)

응답 DTO: BotResponse { id, name, publicKey, systemPrompt, welcomeMessage, fallbackMessage, allowedOrigins, createdAt }
- systemPrompt 는 nullable (null 로 나갈 수 있음)
- allowedOrigins 는 DB 가 null 이어도 빈 배열로 내려간다(BotResponse.java:37-39). 프론트가 배열을 전제로 하기 때문이다. 즉 응답에서는 "설정 안 함" 과 "빈 목록" 이 구분되지 않는다
- fallbackMessage - 근거를 못 찾았을 때 보여줄 문구. Python 은 is_fallback=true 만 돌려주고 이 문구를 모르며, Spring 이 답변을 이 값으로 치환한다 (Bot.java:115-121)
- publicKey - 위 1절과 동일

description 재료: 상세 조회는 목록의 집계 3개(documentCount · weeklyConversationCount · latestOverallFaithfulness)를 내려주지 않는다. 이유는 1절 참고.

## 4. PATCH /api/bots/{botId} - updateBot

성공: 200 · BotResponse (수정 후 상태)

| HTTP | ErrorCode | 언제 나는가 | 근거 | 확신 |
|---|---|---|---|---|
| 404 | BOT_NOT_FOUND | 없는 봇/남의 봇 | BotService.java:107 → 140-143, 테스트 :143-149 | 확실 |
| 400 | INVALID_INPUT | name 100자 초과 | UpdateBotRequest.java:25-26 | 확실 |
| 400 | INVALID_INPUT | 깨진 JSON / 본문 없음 | GlobalExceptionHandler.java:71-78 | 확실 |
| 400 | INVALID_INPUT | {botId} UUID 형식 아님 | GlobalExceptionHandler.java:153-161 | 확실 |
| 415 | UNSUPPORTED_MEDIA_TYPE | Content-Type 불일치 | GlobalExceptionHandler.java:90-96 | 추정(높음) |
| 401 / 500 | 공통 | | | 확실 |

요청 DTO: UpdateBotRequest { name, systemPrompt, welcomeMessage, fallbackMessage, allowedOrigins }
- 🔴 name 에만 검증이 있다: @Size(max=100). @NotBlank 는 일부러 없다
- systemPrompt · welcomeMessage · fallbackMessage · allowedOrigins 에는 검증 애노테이션이 하나도 없다. 길이 제한도, origin 형식 검사도, 개수 제한도 없다 (확실. UpdateBotRequest.java 전체 확인)
- null = "안 보냄" = 기존 값 유지. 보낸 필드만 바뀐다 (Bot.updateSettings, Bot.java:180-198)
- ⚠️ 빈 문자열 "" 은 null 이 아니므로 실제로 지운다. 설정 화면이 "지우기" 를 "" 로 표현한다 (UpdateBotRequest.java:14-22)
- example 후보: {"welcomeMessage": "무엇이든 물어보세요.", "allowedOrigins": ["https://example.com"]}

description 재료
- 부분 수정인 이유와 그 대가: 모든 필드가 nullable 이라 "null 로 지우기" 와 "안 보냄" 을 구분할 수 없다. 검토했던 JsonNullable 도입도, PUT 전체 교체로 바꾸는 것도 하지 않기로 했다. 설정 화면이 systemPrompt 를 항상 문자열로 보내기 때문에 그 구분이 실제로 필요하지 않았다 (UpdateBotRequest.java:14-22)
- publicKey 와 소유자는 인자에 아예 없어서 바꾸는 코드를 쓸 수가 없다(@Setter 를 안 쓴 이유) (Bot.java:176-178)
- 변경 감지(dirty checking) 라 save() 호출이 없다 (BotService.java:108-109)
- ⚠️ systemPrompt 를 바꾸면 환각 억제가 깨질 수 있다. 봇 지침으로 NO_ANSWER 규칙이 실제로 뚫리는 것이 실측돼 있다(ai-service/app/bot_prompt_check.py). 결합은 대체가 아니라 덧붙임이지만 방어이지 보장이 아니다 (Bot.java:92-108). description 에 넣을 값어치가 큰 사실이다

## 5. DELETE /api/bots/{botId} - deleteBot

성공: 204 No Content · 본문 없음 (ResponseEntity<Void>, BotController.java:106, 테스트 :193)

| HTTP | ErrorCode | 언제 나는가 | 근거 | 확신 |
|---|---|---|---|---|
| 404 | BOT_NOT_FOUND | 없는 봇/남의 봇 | BotService.java:127 → 140-143, 테스트 :158-164 | 확실 |
| 400 | INVALID_INPUT | {botId} UUID 형식 아님 | GlobalExceptionHandler.java:153-161 | 확실 |
| 401 / 500 | 공통 | | | 확실 |

요청 DTO: 없음. 응답 DTO: 없음(204)

description 재료
- 되돌릴 수 없다. 문서·청크·대화 로그·eval_runs 가 DB 의 ON DELETE CASCADE 로 함께 사라진다 (BotController.java:96-99, BotService.java:117-118)
- 🔴 삭제 직전에 usage_events 를 한 번 메꾼다(backfillEvalRuns). 평가 실행 사용량은 "사용량 화면을 열 때" 메꾸는 방식이라, 아무도 화면을 열기 전에 봇을 지우면 청구 근거가 통째로 사라진다. 채팅 답변은 그 순간 기록되므로 이 구멍이 없고, 평가 실행만 유일하게 노출돼 있었다. 멱등(ON CONFLICT DO NOTHING)이다. 그리고 소유권 확인이 메꾸기보다 먼저 와야 한다. 순서가 바뀌면 404 가 날 요청마다 자기 이력 전체를 훑는 헛수고가 벌어진다 (BotService.java:117-128)
- 204 인 이유: 지워진 리소스를 본문에 담아 돌려줄 이유가 없다 (BotController.java:98)

## 6. 강조된 둘

### ① 남의 봇 = 403 이 아니라 404

구현 위치는 딱 한 곳이다.

```
BotService.findOwnedBot(userId, botId)   // BotService.java:140-143
  → botRepository.findByIdAndUserId(botId, userId)
      .orElseThrow(() -> new ApiException(ErrorCode.BOT_NOT_FOUND))
```

5개 중 4개에 적용되고, 1개는 애초에 해당이 없다 (확실):

| 엔드포인트 | 경유 |
|---|---|
| getBot | findMyBot → findOwnedBot (BotService.java:84-86) ✅ |
| updateBot | findOwnedBot (:107) ✅ |
| deleteBot | findOwnedBot (:127) ✅ |
| getMyBots | botId 를 받지 않음. 대신 목록·집계 쿼리 양쪽이 user_id 로 좁혀져 남의 봇이 결과에 들어올 경로 자체가 없음 (BotService.java:68, BotRepository.java:38-42,77) ✅ |
| createBot | 아직 봇이 없음. 해당 없음 |

이유가 기록된 자리는 3곳이다(전부 근거로 쓸 수 있다):
- BotService.java:133-138 - "남의 봇을 403 으로 구분해주면 '이 id 의 봇이 존재한다' 는 사실이 새어나가, 무작위 id 를 던져 남의 봇 목록을 뽑아낼 수 있다"
- BotRepository.java:22-29 - 검사가 아니라 조회 쿼리에 못박는 이유: findById 후 나중에 비교하면 검사를 빠뜨려도 컴파일이 통과한다
- ApiAccessDeniedHandler.java:20-22 - "봇 소유권 검사는 이 핸들러가 아니라 서비스 계층에서 404 로 처리한다"
- ErrorCode.java:29-30 의 ACCESS_DENIED 는 정의돼 있지만 봇 접근에는 쓰지 않는다. 문서에 403 을 적으면 안 된다

테스트가 이 사실을 직접 재고 있다: BotIntegrationTest 의 남의_봇_조회(404 + BOT_NOT_FOUND 코드까지 단언) · 남의_봇_수정 · 남의_봇_삭제(삭제 실패 후 주인이 여전히 200 으로 조회되는 것까지 확인, :164).

문서 문구 제안: 404 의 설명을 "봇이 없음" 으로만 쓰면 반쪽이다. "존재하지 않는 봇과 다른 사용자의 봇을 구분하지 않고 똑같이 404 로 답합니다. 403 으로 구분하면 봇의 존재 여부가 새어나갑니다" 까지 적어야 맞다.

### ② allowedOrigins 가 비면 "전부 차단"

강제되는 자리는 Bot.isOriginAllowed(Bot.java:221-232) 한 곳이다. 로직상 빈 배열이면 루프가 한 번도 안 돌아 무조건 false 를 반환한다. null 도 마찬가지로 false 다.

근거 주석은 Bot.java:200-219 에 상세히 있다:
- 봇을 만들면 allowedOrigins 는 빈 배열이다(Bot.create, :157). 이걸 "아직 설정 안 했으니 다 열자" 로 해석하면 모든 신규 봇이 무방비로 태어난다
- publicKey 는 고객 사이트 HTML 에 노출되므로 누구나 복사해 자기 사이트에 붙일 수 있고, 그러면 LLM 비용이 봇 주인에게 청구된다
- 정확히 일치만 허용한다. 와일드카드 없음. 접미사 비교는 evil-example.com 이 example.com 으로 통과하는 고전적 실수를 부른다
- 비교는 trim() 후 대소문자 무시. Origin 은 스킴+호스트+포트이고 경로는 들어 있지 않다 (https://example.com:8443)
- 차단되면 ORIGIN_NOT_ALLOWED(403) 가 나가는데, 그건 위젯 API(/api/w/**) 쪽이지 BotController 가 아니다

⚠️ BotController 에서 이 규칙이 강제되지는 않는다. 여기서는 값을 읽고 쓰기만 한다. updateBot 은 origin 문자열을 전혀 검증하지 않는다. 형식도, 개수도, 길이도. 아무 문자열이나 들어간다.

두 응답에서 이 필드가 보이는 모습: BotResponse·BotSummaryResponse 둘 다 DB 가 null 이면 빈 배열 [] 로 바꿔서 내려보낸다(BotResponse.java:37-39, BotSummaryResponse.java:59-60). 프론트가 배열을 전제로 하기 때문이다. 따라서 응답만 봐서는 "NULL" 과 "빈 배열" 을 구분할 수 없고, 어느 쪽이든 의미는 같다(전부 차단).

문서 문구 제안: 이 필드의 description 에 "빈 배열은 '모든 도메인 허용' 이 아니라 '모든 도메인 차단' 입니다" 를 명시적으로 쓰는 것이 좋다. 반대로 읽히면 곧바로 보안 오해다.

## 7. 확신도가 낮은 것 (추정 표시)

- 415 가 createBot·updateBot 에만 난다 - 추정(높음). HttpMediaTypeNotSupportedException 이 @RequestBody 바인딩 경로에서만 나온다는 일반 지식에 근거했고, 실제로 돌려보지는 않았다
- 알 수 없는 JSON 필드는 무시된다 - 추정(높음). Boot 4 는 Jackson 3 이고 FAIL_ON_UNKNOWN_PROPERTIES 가 기본 off 다(TossBillingKeyResponse.java:8 가 그렇게 적고 있음). 설정에서 이를 켜는 곳은 없었다. 따라서 오타 필드로 400 이 나지는 않는다
- createBot 의 INVALID_TOKEN(계정 삭제) - 코드상 확실하지만(BotService.java:93-94) 테스트로 재고 있지는 않다. 문서에 적을지는 판단이 필요하다. 공통 401 에 이미 코드가 다른 401 이 하나 들어 있고, 여기에 또 다른 원인의 401 이 겹친다
- METHOD_NOT_ALLOWED(405) - 코드 경로는 확실하지만, 매 엔드포인트 문서에 405 를 다는 것이 값어치가 있는지는 판단 대상이다. 5개 전부에 참이라 공통 커스터마이저로 올리는 편이 나을 수도 있다(PR 1 의 500 처럼). 다만 그건 PR 2 의 범위를 넘는다

## 8. 작업 시 주의 하나

OpenApiConfig.응답을_없을_때만_붙인다 는 이미 있는 응답을 덮지 않는다(:115-117). 즉 @ApiResponse(responseCode="500", ...) 를 엔드포인트에 직접 달면 공통 500 이 지고 직접 단 것이 이긴다. 500 과 401 은 엔드포인트별로 달지 말 것. 공통이 붙이는 게 더 일관된다.
