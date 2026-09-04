# 백엔드 리뷰 지적 수정 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 2026-09-03 백엔드 리뷰에서 나온 Critical 2건·Important 6건을, 서로 파일을 공유하지 않는 PR 5개로 고친다.

**Architecture:** 각 Task = 브랜치 1개 = PR 1개. 다섯 브랜치 모두 `main`에서 따며 파일이 겹치지 않아 **병렬 실행이 가능하다.** 설계 근거는 `docs/superpowers/specs/2026-09-03-backend-critical-fixes-design.md`에 있다 — 각 Task의 "한계 & 트레이드오프"는 그 문서의 해당 절에서 그대로 가져온다.

**Tech Stack:** Spring Boot 4.0.7 / Java 21 / JUnit5 + Testcontainers, Python 3 + FastAPI + psycopg3, Caddy 2

## Global Constraints

- **최소 수정.** 새 추상화·새 의존성·새 설정 파일을 만들지 않는다. 결함을 고치는 데 필요한 만큼만 바꾼다.
- **브랜치는 반드시 `main`에서 딴다.** `main`에 직접 커밋하지 않는다.
- 커밋 메시지: `<타입>: <한국어 요약>` (feat / fix / refactor / test / docs / chore / review). 본문 끝에 `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- **코드 주석과 에러 메시지는 한국어.** 사용자에게 보이는 에러는 "무엇을 어떻게 하면 되는지"까지 적는다.
- 에러 응답 포맷은 전 계층 공통: `{ "error": { "code": "...", "message": "..." } }`
- PR 본문은 `.github/PULL_REQUEST_TEMPLATE.md`를 채운다. **"한계 & 트레이드오프"와 "검토한 대안"은 비워두지 않는다** — 각 Task 끝에 그대로 쓸 내용을 적어뒀다.
- **PR 생성까지가 범위다. CI는 기다리지 않는다.**
- Spring 테스트 실행: `cd api && ./gradlew test --tests '<클래스명>'` (Docker 필요 — Testcontainers)
- Python 자체 점검 실행: `cd ai-service && .venv/bin/python -m app.<모듈명>`
- **거짓 완성 금지.** 검사를 실제로 돌리고 그 출력을 PR 본문에 붙인다. "돌려봤다"가 아니라 실행 결과다.

---

## Task 1: 위젯 rate limit 우회 차단 · 로그인 요청 제한

**브랜치:** `fix/widget-xff-ratelimit` · **모델: Opus**
(AGENTS.md 모델 선택의 명시적 예외 — *"보안 관련 코드는 비용이 더 들어도 Opus를 유지한다"*)

**Files:**
- Modify: `Caddyfile:16-28`
- Modify: `api/src/main/resources/application-prod.yaml:42-49`
- Modify: `api/src/main/resources/application.yaml:86-91`
- Modify: `api/src/main/java/com/alldap/api/domain/widget/controller/WidgetController.java` (`clientKey`)
- Modify: `api/src/main/java/com/alldap/api/global/config/WidgetProperties.java`
- Modify: `api/src/main/java/com/alldap/api/domain/auth/controller/AuthController.java`
- Modify: `api/src/test/java/com/alldap/api/support/TestcontainersConfiguration.java:115-116`
- Test: `api/src/test/java/com/alldap/api/domain/widget/WidgetIntegrationTest.java`
- Test: `api/src/test/java/com/alldap/api/domain/auth/AuthIntegrationTest.java`

**Interfaces:**
- Consumes: 기존 `RateLimiter.check(String bucket, String client, int limit, Duration window)` — 한도 초과 시 `ApiException(ErrorCode.RATE_LIMIT_EXCEEDED)`(429)
- Produces: `WidgetProperties`에 `loginPerMinute` 필드 추가. **이 record는 다른 Task가 건드리지 않는다.**

---

- [ ] **Step 1: 브랜치를 딴다**

```bash
cd /Users/cheonjamin/projects/AllDap
git checkout main && git checkout -b fix/widget-xff-ratelimit
```

- [ ] **Step 2: 실패하는 테스트를 쓴다 — XFF 위조로 한도를 우회할 수 없다**

`WidgetIntegrationTest.java`의 `한도는_봇마다_따로()` 메서드 **아래**, `// ── 테스트 보조 ──` 주석 **위**에 넣는다.

```java
    @Test
    @DisplayName("[비용] X-Forwarded-For 를 바꿔가며 보내도 채팅 한도를 우회할 수 없다")
    void 위조된_XFF_로는_한도를_우회할_수_없다() {
        // 테스트 컨텍스트의 한도는 분당 3회 (TestcontainersConfiguration)
        for (int i = 0; i < 3; i++) {
            aiService.enqueue(200, 정상응답);
            assertThat(widgetChatWithForwardedFor(publicKey, "질문 " + i, "1.2.3." + i).status())
                    .isEqualTo(200);
        }

        // 헤더만 바꾼 네 번째 요청. 프록시가 덮어쓰면 같은 클라이언트로 세어져 막혀야 한다.
        Response blocked = widgetChatWithForwardedFor(publicKey, "우회 시도", "9.9.9.9");

        assertThat(blocked.status()).isEqualTo(429);
        assertThat(blocked.json().path("error").path("code").asString())
                .isEqualTo("RATE_LIMIT_EXCEEDED");

        // 막힌 요청이 Python 까지 갔다면 LLM 비용이 이미 나간 뒤다.
        assertThat(aiService.received()).hasSize(3);
    }
```

같은 파일 `// ── 테스트 보조 ──` 절, `widgetChat(String, String, String)` 바로 아래에 보조 메서드를 넣는다.

```java
    /**
     * X-Forwarded-For 를 실어 보낸다. 이 헤더는 <b>클라이언트가 위조할 수 있는 값</b>이라,
     * 신뢰 프록시가 덮어쓰지 않으면 rate limit 키가 매번 달라져 한도가 무의미해진다.
     */
    private Response widgetChatWithForwardedFor(String publicKey, String message, String forwardedFor) {
        EntityExchangeResult<byte[]> result = client.method(HttpMethod.POST)
                .uri("/api/w/" + publicKey + "/chat")
                .header("X-Forwarded-For", forwardedFor)
                .contentType(MediaType.APPLICATION_JSON)
                .body(new ChatRequest(message, "widget-session-1"))
                .exchange().expectBody().returnResult();
        return new Response(result.getStatus().value(), decode(result.getResponseBody()));
    }
```

- [ ] **Step 3: 테스트를 돌려 실패를 확인한다**

```bash
cd api && ./gradlew test --tests 'WidgetIntegrationTest' --info
```

Expected: `위조된_XFF_로는_한도를_우회할_수_없다` FAIL
— 네 번째 요청이 429가 아니라 200이다(스텁에 응답을 안 넣었으므로 502/503일 수도 있다. **중요한 것은 429가 아니라는 사실**이다).

> 🔴 이 실패가 곧 버그의 증거다. PR 본문에 이 출력을 붙인다.

- [ ] **Step 4: `Caddyfile`을 고친다 — 실제 수정은 여기다**

`Caddyfile`의 `{$API_DOMAIN} { ... }` 블록에서 `reverse_proxy api:8080` **바로 위**에 `header_up` 한 줄을 넣고, 그 위 주석 문단을 통째로 아래 내용으로 바꾼다.

```
	# Spring 만 바깥에 노출된다. ai-service 는 여기에 없다 — 의도적이다.
	#
	# 🔴 클라이언트가 보낸 X-Forwarded-For 를 <버리고> 실제 접속 IP 로 덮어쓴다.
	#    Caddy 기본값은 덮어쓰기가 아니라 <잇기(append)> 라, 그냥 두면
	#    클라이언트가 보낸 위조값이 맨 앞에 남는다. 그런데 WidgetController.clientKey()
	#    와 Spring 의 ForwardedHeaderFilter 는 둘 다 <맨 앞 항목>을 원 클라이언트로 읽는다.
	#    → 헤더에 아무 IP 나 넣어 매 요청 rate limit 키를 바꾸면 한도가 무제한이 된다.
	#      인증 없이 열린 유일한 문이고 요청당 LLM 호출 = 실제 돈이라, 곧바로 요금 사고다.
	#
	# ⚠️ 이건 "프록시를 반드시 거친다" 는 전제를 <없앤> 것이 아니라 <성립하게 만든> 것이다.
	#    Spring 컨테이너 포트를 직접 노출하면 다시 뚫린다. compose 에서 api 의 ports 를 열지 말 것.
	header_up X-Forwarded-For {remote_host}
	reverse_proxy api:8080
```

> ⚠️ 기존 주석에 있던 TODO(*"`forward-headers-strategy: framework` 가 필요하다. 배포 후 바로 확인할 것"*)는 **지운다.** 이미 `application-prod.yaml:49`에 들어가 있어 낡은 안내다.

- [ ] **Step 4b: `WidgetController.clientKey()` 의 XFF 직접 파싱을 지운다**

🔴 **Caddyfile 만 고치면 이 테스트는 수정 후에도 실패한다.** 통합 테스트는 Caddy 를 거치지 않고 톰캣을 직접 때리므로, `clientKey()` 가 헤더를 직접 읽는 한 위조값을 그대로 본다. 그리고 그건 테스트만의 문제가 아니다 — **파싱 규칙이 Spring 과 Caddy 두 곳에 생기고, 둘 중 하나는 반드시 어긋난다.**

`WidgetController` 의 `clientKey` 메서드를 통째로 교체한다.

```java
    /**
     * 제한을 셀 단위. <b>IP 와 publicKey 를 함께</b> 쓴다.
     *
     * <p>IP 만 쓰면 한 회사에서 여러 봇을 쓸 때 서로의 한도를 잡아먹고,
     * publicKey 만 쓰면 한 명이 그 봇 전체를 마비시킬 수 있다.
     *
     * <p>🔴 <b>{@code X-Forwarded-For} 를 직접 읽지 않는다.</b> 예전에는 이 메서드가 그 헤더의
     * 맨 앞 항목을 원 클라이언트로 삼았는데, <b>그 값은 클라이언트가 위조할 수 있다.</b>
     * Caddy 의 기본 동작은 덮어쓰기가 아니라 <b>잇기(append)</b> 라 위조값이 맨 앞에 남고,
     * 결과적으로 요청마다 헤더만 바꾸면 rate limit 키가 달라져 한도가 무제한이 됐다.
     *
     * <p>이제 방어가 두 겹이다.
     * <ol>
     *   <li>{@code Caddyfile} 의 {@code header_up X-Forwarded-For {remote_host}} 가
     *       클라이언트가 보낸 값을 <b>버리고</b> 실제 접속 IP 로 덮어쓴다.</li>
     *   <li>{@code server.forward-headers-strategy: framework}(application-prod.yaml)가
     *       그 헤더를 읽어 {@code getRemoteAddr()} 자체를 실제 클라이언트 IP 로 바꿔준다.</li>
     * </ol>
     * 그래서 여기서는 {@code getRemoteAddr()} 만 부르면 된다. 헤더 파싱 규칙이 한 곳
     * (프레임워크)에만 있게 되어, 두 곳에 두었다가 어긋나는 사고가 원천적으로 사라진다.
     *
     * <p>⚠️ <b>실패 방향이 안전한 쪽으로 바뀐다.</b> 프록시 설정이 빠진 채 배포되면
     * 예전에는 "제한 없음"(위조 자유)이었지만, 이제는 모든 요청이 프록시 IP 하나로 묶여
     * <b>과하게 엄격해진다.</b> 보안 장치는 이 방향으로 실패해야 한다.
     */
    private String clientKey(HttpServletRequest request, String publicKey) {
        return request.getRemoteAddr() + "|" + publicKey;
    }
```

쓰이지 않게 된 import 가 있으면 지운다(`HttpServletRequest` 는 계속 쓴다).

- [ ] **Step 5: `application-prod.yaml`의 틀린 전제 설명을 고친다**

`api/src/main/resources/application-prod.yaml`의 `server:` 블록 주석(42-48행)을 아래로 교체한다. `forward-headers-strategy: framework` 줄 자체는 **그대로 둔다.**

```yaml
server:
  port: ${SERVER_PORT:8080}
  # 리버스 프록시(Caddy) 뒤에서 돈다. X-Forwarded-* 를 신뢰하지 않으면
  # 요청자 IP 가 전부 <프록시의 IP> 로 보인다.
  # 위젯 채팅의 rate limit 이 IP 기준이라, 그대로 두면 전 세계가
  # 한 바구니에서 한도를 나눠 쓰게 된다.
  #
  # 🔴 안전한 전제는 "프록시만 포트를 연다" 가 아니라 <"프록시가 헤더를 덮어쓴다"> 다.
  #    Caddy 기본값은 잇기(append) 라 클라이언트가 보낸 위조값이 맨 앞에 남고,
  #    이 설정도 WidgetController 도 맨 앞 항목을 읽는다 = 위조가 그대로 통한다.
  #    그래서 Caddyfile 에 `header_up X-Forwarded-For {remote_host}` 를 명시했다.
  #    ⚠️ 그 한 줄이 이 설정의 전제다. Caddyfile 을 고칠 때 함께 볼 것.
  forward-headers-strategy: framework
```

- [ ] **Step 6: 테스트를 돌려 통과를 확인한다**

```bash
cd api && ./gradlew test --tests 'WidgetIntegrationTest'
```

Expected: PASS (전체 클래스)

이제 통과하는 이유: `clientKey()` 가 `getRemoteAddr()` 만 보는데, 테스트 프로파일에는 `forward-headers-strategy` 가 없어(그건 `application-prod.yaml` 에만 있다) 위조 헤더가 그 값을 바꾸지 못한다 → 네 요청이 같은 클라이언트로 세어져 네 번째가 429다.

> ⚠️ **이 테스트가 검증하는 것은 "Spring 이 헤더를 직접 믿지 않는다" 까지다.** `header_up` 한 줄이 실제로 프록시에서 동작하는지는 Caddy 설정이라 Testcontainers 가 닿지 않는다. **이 구분을 PR 본문에 그대로 적는다** — 이 저장소는 "통합 테스트 초록불"을 검증으로 착각해 두 번 물렸다(HTTP/2 h2c, iframe Origin).

- [ ] **Step 7: 커밋한다**

```bash
git add Caddyfile api/src/main/resources/application-prod.yaml \
        api/src/main/java/com/alldap/api/domain/widget/controller/WidgetController.java \
        api/src/test/java/com/alldap/api/domain/widget/WidgetIntegrationTest.java
git commit -m "$(cat <<'EOF'
fix: 위조된 X-Forwarded-For 로 위젯 rate limit 을 우회할 수 없게 했다

Caddy 기본값이 덮어쓰기가 아니라 잇기라, 클라이언트가 보낸 위조값이 맨 앞에 남고
WidgetController.clientKey() 가 그 맨 앞을 읽었다. 헤더에 아무 IP 나 넣어 매 요청
키를 바꾸면 한도가 무제한이 된다 — 인증 없이 열린 유일한 문이고 요청당 LLM 호출 = 실제 돈이다.

두 겹으로 막았다.
  1) Caddyfile 의 header_up 이 클라이언트가 보낸 값을 버리고 실제 접속 IP 로 덮어쓴다
  2) clientKey() 가 헤더를 직접 파싱하지 않고 getRemoteAddr() 만 본다
     (forward-headers-strategy 가 이미 그 값을 실제 클라이언트 IP 로 바꿔준다)

파싱 규칙이 프레임워크 한 곳에만 남아, 두 곳에 두었다가 어긋나는 사고가 사라진다.
실패 방향도 안전해진다 — 프록시 설정이 빠지면 "제한 없음" 이 아니라 "전부 한 바구니" 다.

application-prod.yaml 의 틀린 전제 설명("프록시만 포트를 여니 안전하다")도 고쳤다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 8: 실패하는 테스트를 쓴다 — 로그인 요청 제한**

`api/src/test/java/com/alldap/api/domain/auth/AuthIntegrationTest.java` 를 고친다. 이 파일의 보조 메서드는 `post(String uri, Object body)` 이고, 로그인 실패는 `401 INVALID_CREDENTIALS` 다(기존 테스트 `로그인_실패_응답이_가입여부를_흘리지_않는다` 에서 확인).

**(a)** import 와 필드를 추가한다. `@Autowired` 필드들 옆에 넣는다.

```java
import com.alldap.api.global.ratelimit.RateLimiter;
```

```java
    @Autowired
    RateLimiter rateLimiter;
```

**(b)** `@BeforeEach setUp()` **끝**에 한 줄 추가한다.

```java
        // 🔴 RateLimiter 는 <상태를 가진 싱글턴>이다. 안 비우면 앞 테스트의 로그인 호출이
        //    카운터에 남아, 실행 순서에 따라 나타났다 사라지는 실패가 난다.
        //    (DocumentIntegrationTest 가 circuitBreaker.reset() 을 부르는 것과 같은 이유)
        rateLimiter.reset();
```

**(c)** 테스트를 추가한다. `// ── 테스트 보조 ──` 주석 **위**에 넣는다.

```java
    @Test
    @DisplayName("[보안] 로그인 시도를 반복하면 429 로 막힌다 (비밀번호 추측 방지)")
    void 로그인_요청수_제한() {
        // 테스트 컨텍스트의 한도는 분당 3회 (TestcontainersConfiguration)
        for (int i = 0; i < 3; i++) {
            Response 실패 = post("/api/auth/login",
                    new LoginRequest("nobody@example.com", "wrong-password-1234"));
            assertThat(실패.status()).isEqualTo(401);
        }

        Response blocked = post("/api/auth/login",
                new LoginRequest("nobody@example.com", "wrong-password-1234"));

        // 이 제한이 없으면 유일한 방어가 BCrypt 비용(약 100ms/회)뿐이라
        // 병렬 커넥션으로 분당 수천 회를 추측할 수 있다.
        assertThat(blocked.status()).isEqualTo(429);
        assertThat(blocked.json().path("error").path("code").asString())
                .isEqualTo("RATE_LIMIT_EXCEEDED");
    }
```

> ⚠️ 기존 테스트 중 한 메서드 안에서 로그인을 **3회 넘게** 부르는 것이 있으면 그 테스트가 429로 깨진다. `grep -c "api/auth/login" AuthIntegrationTest.java` 로 확인하고, 그런 테스트가 있으면 테스트 한도를 3이 아니라 **5**로 올린다(Step 12에서 함께 조정).

- [ ] **Step 9: 테스트를 돌려 실패를 확인한다**

```bash
cd api && ./gradlew test --tests 'AuthIntegrationTest'
```

Expected: FAIL — 네 번째 로그인이 429가 아니라 401이다.

- [ ] **Step 10: `WidgetProperties`에 `loginPerMinute`를 추가한다**

```java
/**
 * 위젯 공개 API 설정. {@code application.yaml} 의 {@code app.widget.*} 를 바인딩한다.
 *
 * <p>숫자를 코드에 박지 않고 설정으로 뺀 이유: 이 값들은 <b>운영하면서 조정하게 되는</b> 종류다.
 * 실제 사용량을 보기 전까지는 어떤 값이 맞는지 알 수 없고, 값을 바꾸려고 재빌드하고 싶지 않다.
 *
 * @param chatPerMinute   같은 IP·같은 봇 기준 분당 채팅 허용 횟수.
 *                        채팅은 건당 LLM 비용이 들어 낮게 잡는다
 * @param configPerMinute 설정 조회 허용 횟수. 비용은 없지만 무제한이면
 *                        publicKey 를 무작위로 넣어 <b>존재하는 봇을 훑을 수</b> 있다
 * @param loginPerMinute  같은 IP 기준 분당 로그인 시도 허용 횟수.
 *                        <p>여기 있는 이유: 이 record 가 이미 "요청 수 제한 값들" 을 담고 있고,
 *                        값 하나 때문에 새 프로퍼티 클래스를 만들 이유가 없다.
 *                        (이름이 {@code app.widget} 인 것은 어색하지만, 프리픽스를 바꾸면
 *                        배포 환경변수까지 함께 바꿔야 해서 그 대가가 더 크다)
 */
@ConfigurationProperties(prefix = "app.widget")
public record WidgetProperties(
        int chatPerMinute,
        int configPerMinute,
        int loginPerMinute
) {
}
```

- [ ] **Step 11: `application.yaml`에 한도를 추가한다**

`api/src/main/resources/application.yaml`의 `widget:` 블록 끝(`config-per-minute` 아래)에 넣는다.

```yaml
    # 로그인 시도 제한. 키는 <IP> 다 — 이메일로 잡으면 남의 계정을 잠글 수 있다.
    # 10 인 근거: 사람이 비밀번호를 잘못 치는 횟수로는 넉넉하고,
    # 흔한 비밀번호 목록 대입에는 턱없이 부족하다. ⚠️ 실측으로 조정할 값이다.
    login-per-minute: ${LOGIN_PER_MINUTE:10}
```

- [ ] **Step 12: `TestcontainersConfiguration`에 테스트 한도를 추가한다**

115-116행 아래에 넣는다.

```java
            registry.add("app.widget.login-per-minute", () -> "3");
```

- [ ] **Step 13: `AuthController`에 제한을 건다**

import를 추가하고(`HttpServletRequest`, `RateLimiter`, `WidgetProperties`, `Duration`), 필드와 `login` 메서드를 고친다.

```java
    private final AuthService authService;
    private final RateLimiter rateLimiter;
    private final WidgetProperties widgetProperties;

    /**
     * POST /api/auth/login — 로그인.
     *
     * <p>200 OK 다. 로그인은 서버에 새 리소스를 만드는 행위가 아니라
     * 이미 있는 계정을 확인하고 토큰을 발급받는 행위이기 때문이다.
     *
     * <p><b>요청 수를 제한한다.</b> 이 경로는 {@code permitAll} 이고 실패 카운트도 지연도 없어,
     * 유일한 방어가 BCrypt 비용(약 100ms/회)뿐이었다. 병렬 커넥션이면 분당 수천 회 추측이 가능하고,
     * {@code PasswordEncoder.matches} 가 요청당 CPU 를 태우므로 그 자체가 저비용 DoS 이기도 하다.
     *
     * <p><b>키는 IP 다.</b> 이메일로 잡으면 남의 계정을 골라 잠글 수 있다(계정 잠금 공격).
     * ⚠️ 이 IP 가 믿을 수 있으려면 프록시가 X-Forwarded-For 를 덮어써야 한다 — Caddyfile 참고.
     */
    @PostMapping("/login")
    public ResponseEntity<AuthResponse> login(@Valid @RequestBody LoginRequest request,
                                              HttpServletRequest servletRequest) {
        rateLimiter.check("login", servletRequest.getRemoteAddr(),
                widgetProperties.loginPerMinute(), Duration.ofMinutes(1));
        AuthResponse response = authService.login(request);
        return ResponseEntity.ok(response);
    }
```

> 🔴 **`getRemoteAddr()`을 쓴다.** `WidgetController.clientKey()`처럼 XFF를 직접 파싱하지 않는다 — `forward-headers-strategy: framework`가 이미 `ForwardedHeaderFilter`를 통해 `getRemoteAddr()`을 실제 클라이언트 IP로 바꿔주기 때문이다. XFF를 또 손으로 읽으면 파싱 규칙이 두 곳에 생기고, 그중 하나가 반드시 어긋난다.

- [ ] **Step 14: 테스트를 돌려 통과를 확인한다**

```bash
cd api && ./gradlew test --tests 'AuthIntegrationTest' --tests 'WidgetIntegrationTest'
```

Expected: PASS (두 클래스 전체)

- [ ] **Step 15: 전체 테스트를 돌린다**

```bash
cd api && ./gradlew test
```

Expected: PASS. 실패하면 **`WidgetProperties` 생성자 인자가 늘어난 곳**을 먼저 본다(테스트에서 직접 `new WidgetProperties(...)` 하는 곳이 있으면 인자를 추가한다).

- [ ] **Step 16: 커밋하고 PR을 연다**

```bash
git add -A
git commit -m "$(cat <<'EOF'
fix: 로그인에 요청 수 제한을 걸었다 (IP 기준 분당 10회)

/api/auth/login 은 permitAll 인데 실패 카운트도 지연도 없어, 유일한 방어가
BCrypt 비용뿐이었다. 병렬 커넥션이면 분당 수천 회 추측이 가능하고
PasswordEncoder.matches 가 요청당 CPU 를 태워 그 자체가 저비용 DoS 였다.

키를 이메일이 아니라 IP 로 잡았다 — 이메일이면 남의 계정을 골라 잠글 수 있다.
이미 있는 RateLimiter 빈을 재사용했다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
git push -u origin fix/widget-xff-ratelimit
gh pr create --title "fix: 위젯 rate limit XFF 우회 차단 · 로그인 요청 제한" --body "$(cat <<'EOF'
## 무엇을 왜 바꿨나요

인증 없이 열린 유일한 문(위젯 채팅)의 rate limit 이 **헤더 한 줄로 완전히 우회**됐습니다.

`WidgetController.clientKey()` 가 클라이언트가 보낸 `X-Forwarded-For` 의 **맨 앞 값**을 신뢰하는데,
`Caddyfile` 의 `reverse_proxy` 는 기본 동작이 **덮어쓰기가 아니라 잇기(append)** 입니다.
따라서 위조값이 항상 0번 자리에 남고, 코드는 정확히 그 0번을 읽습니다.
`forward-headers-strategy: framework` 도 구제하지 못합니다 — `ForwardedHeaderFilter` 역시 첫 항목을 봅니다.

```
POST /api/w/{publicKey}/chat
X-Forwarded-For: 1.2.3.<매 요청마다 증가>
```
→ rate-limit 키가 매번 달라져 분당 한도가 **무제한**. 요청당 Cloudflare 생성 호출 = 실제 돈입니다.

**부수 피해:** 그 루프로 키를 10만 개 넘기면 `RateLimiter:65` 의 `counters.clear()` 가 돌아
**그 순간 모든 봇·모든 방문자의 카운터가 리셋**됩니다. 공격자 한 명이 전역 제한을 주기적으로 지울 수 있습니다.

함께: `/api/auth/login` 에 IP 기준 분당 10회 제한을 걸었습니다(같은 `RateLimiter` 재사용).
XFF 수정이 선행 조건이라 같은 PR 입니다 — 먼저 고치지 않으면 로그인 제한도 똑같이 위조됩니다.

## 어떻게 해결했나요

**두 겹으로 막았습니다.**

1. `Caddyfile` 에 `header_up X-Forwarded-For {remote_host}` — 클라이언트가 보낸 값을 **버리고** 실제 접속 IP 로 덮어씁니다.
2. `WidgetController.clientKey()` 가 헤더를 **직접 파싱하지 않고** `getRemoteAddr()` 만 봅니다.
   `forward-headers-strategy: framework` 가 이미 그 값을 실제 클라이언트 IP 로 바꿔주기 때문입니다.

②가 없으면 파싱 규칙이 Spring 과 Caddy 두 곳에 생기고, 둘 중 하나는 반드시 어긋납니다.
그리고 **②가 없으면 이 PR 의 회귀 테스트가 아예 성립하지 않습니다** — 통합 테스트는 Caddy 를
거치지 않으므로, Spring 이 헤더를 직접 읽는 한 수정 전에도 후에도 똑같이 실패합니다.

🔴 **실패 방향도 바뀝니다.** 프록시 설정이 빠진 채 배포되면 예전에는 "제한 없음"(위조 자유)이었지만,
이제는 모든 요청이 프록시 IP 하나로 묶여 **과하게 엄격해집니다.** 보안 장치는 이 방향으로 실패해야 합니다.

`application-prod.yaml` 의 **틀린 전제 설명**("Caddy 만 포트를 여므로 안전하다")도 고쳤습니다 —
문제는 "누가 포트에 닿는가" 가 아니라 **"프록시가 헤더를 덮어쓰는가"** 였습니다.

<!-- 실제 실행 결과를 여기에 붙일 것: Step 3 의 FAIL 출력과 Step 15 의 PASS 출력 -->

## 한계 & 트레이드오프

- **여전히 "프록시를 반드시 거친다" 는 전제 위에 서 있습니다.** Spring 컨테이너 포트를 직접
  노출하면 다시 뚫립니다. 바뀐 것은 전제를 **없앤** 게 아니라 **성립하게 만든** 것입니다.
- 신뢰 프록시가 **정확히 1단**일 때만 맞습니다. 앞에 CDN 을 하나 더 세우면 다시 계산해야 합니다.
- 🔴 **테스트가 검증하는 것은 "Spring 이 헤더를 직접 믿지 않는다" 까지입니다.** `header_up` 한 줄이
  실제 프록시에서 동작하는지는 Caddy 설정이라 Testcontainers 가 닿지 않습니다. 검증이
  "테스트 2건 + 배포 후 실제 요청 확인" 둘로 갈리고, **후자는 아직입니다.**
  이 저장소는 "통합 테스트 초록불" 을 검증으로 착각해 두 번 물렸습니다(HTTP/2 h2c, iframe Origin).
- 인메모리 고정 윈도우라는 기존 한계는 그대로입니다(인스턴스 늘면 무력, 윈도우 경계 문제).
- 로그인 한도 10회는 **실측한 값이 아닙니다.** 사람이 오타 내는 횟수로는 넉넉하고 사전 대입에는
  부족하다는 판단이며, 운영하면서 조정할 값입니다.

## 검토한 대안

- **Spring 에서 XFF 의 맨 뒤 항목 읽기** — 신뢰 프록시가 정확히 1단일 때만 성립하고,
  프록시 없이 직접 노출하면 다시 뚫립니다. 무엇보다 **파싱 규칙을 Spring 에 남기는 선택**이라,
  Caddy 쪽 규칙과 어긋날 여지가 그대로 남습니다.
- **Caddyfile 만 고치고 Spring 은 그대로 두기** — 운영에서는 동작하지만 **회귀 테스트를 쓸 수 없습니다.**
  통합 테스트가 Caddy 를 거치지 않으므로 위조 헤더가 그대로 통과합니다. 막은 것을 증명할 방법이 없는 수정은
  다음 사람이 되돌립니다.
- **로그인 키를 이메일로** — 남의 계정을 골라 잠글 수 있어(계정 잠금 공격) 기각했습니다.
- **Bucket4j 도입** — 필요한 규칙이 "같은 키로 1분에 N번" 하나뿐이라 의존성을 늘리지 않았습니다.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Task 2: 평가 측정이 채점 실패를 fallback 으로 뭉개지 않게

**브랜치:** `fix/eval-measurement` · **모델: Sonnet**

**Files:**
- Modify: `ai-service/app/evalrun.py:187-194` (집계 루프), `:233-239` (status 결정)
- Modify: `ai-service/app/judge.py:139-150` (`fetch_contents`를 try 안으로)
- Create: `ai-service/app/evalrun_check.py`

**Interfaces:**
- Consumes: `judge.score(question, ground_truth, sources, answer) -> Scores | None` — `None`은 "채점하지 못했다"이지 0점이 아니다
- Produces: `evalrun._run_status(processed: int, total: int, judge_failed: int) -> str` — `"failed"` / `"partial"` / `"completed"` 중 하나를 돌려주는 **순수 함수**. `evalrun_check`가 이것을 검사한다.

---

- [ ] **Step 1: 브랜치를 딴다**

```bash
cd /Users/cheonjamin/projects/AllDap
git checkout main && git checkout -b fix/eval-measurement
```

- [ ] **Step 2: 실패하는 검사를 쓴다**

`ai-service/app/evalrun_check.py`를 새로 만든다. 다른 `*_check.py`와 같은 형태다(assert 기반, 프레임워크 없음, DB·모델 호출 없음).

```python
"""evalrun 의 실행 상태 판정 자체 점검. DB·모델을 부르지 않는다.

왜 이 검사가 있나
─────────────────────────────────────────────────────────────────────────────
`eval_runs.status` 는 <이 실행을 다른 설정과 비교해도 되는가> 를 말한다.
그런데 판정이 틀리면 화면에 "완료" 로 보이는 실행의 숫자가 거짓이 되고,
그 숫자로 W4 의 before/after 결론을 내리게 된다. 실제로 그렇게 틀린 결론을
한 번 냈다(2026-08-13, 리랭커 융합 — AGENTS.md 참고).

🔴 특히 <채점 실패> 를 잡는지 본다. 채점 실패는 fallback 과 완전히 다른 사실인데,
   `scored_count` 에서 빠지는 결과만 같아 뭉개지기 쉽다. 그리고 Spring 의
   전체 충실성이 `avg × scored / total` 이라 <충실성 0점으로 환산된다.>
"""
from __future__ import annotations

from .evalrun import _run_status


def check_all_processed_and_scored_is_completed() -> None:
    """전부 처리하고 전부 채점했으면 completed. 비교에 쓸 수 있다."""
    assert _run_status(processed=16, total=16, judge_failed=0) == "completed"


def check_nothing_processed_is_failed() -> None:
    """한 문항도 처리하지 못했으면 측정 자체가 없다.

    2026-08-12 에 16문항이 전부 429 로 죽었는데 completed 로 남아,
    지표가 NULL 인 그 실행을 유효한 측정으로 착각한 적이 있다."""
    assert _run_status(processed=0, total=16, judge_failed=0) == "failed"


def check_partial_processing_is_partial() -> None:
    """일부만 처리했으면 <분모가 달라> 다른 설정과 비교할 수 없다."""
    assert _run_status(processed=13, total=16, judge_failed=0) == "partial"


def check_judge_failure_is_partial() -> None:
    """🔴 이 검사가 이 파일의 존재 이유다.

    검색·생성은 전부 됐는데 채점만 실패한 경우. 예전에는 completed 였다.
    그러면 Spring 의 전체 충실성(avg × scored / total)이 그 문항을
    <충실성 0점> 으로 환산하는데, 화면에는 "완료" 로 보인다.

    실제 시나리오: 16문항 전부 정답(실제 1.000)인데 judge 가 2건에서
    코드펜스 없는 잡소리를 뱉어 _extract_json 이 None 을 반환
    → avg=1.000, scored=14, total=16 → 대시보드 0.875.
    그 값을 다른 설정의 0.875 와 나란히 놓고 "차이 없음" 이라고 결론낸다."""
    assert _run_status(processed=16, total=16, judge_failed=2) == "partial"


def check_judge_failure_does_not_mask_failed() -> None:
    """전멸은 채점 실패가 있어도 여전히 failed 다. failed 가 더 강한 사실이다."""
    assert _run_status(processed=0, total=16, judge_failed=0) == "failed"


def main() -> None:
    checks = [
        check_all_processed_and_scored_is_completed,
        check_nothing_processed_is_failed,
        check_partial_processing_is_partial,
        check_judge_failure_is_partial,
        check_judge_failure_does_not_mask_failed,
    ]
    for fn in checks:
        fn()
        print(f"✅ {fn.__name__}")
    print(f"\n{len(checks)}가지 전부 통과.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 검사를 돌려 실패를 확인한다**

```bash
cd ai-service && .venv/bin/python -m app.evalrun_check
```

Expected: `ImportError: cannot import name '_run_status' from 'app.evalrun'`

- [ ] **Step 4: `_run_status`를 순수 함수로 뽑는다**

`ai-service/app/evalrun.py`에서 `def execute(...)` **위**(모듈 상단 함수들 사이)에 추가한다.

```python
def _run_status(processed: int, total: int, judge_failed: int) -> str:
    """이 실행을 <다른 설정과 비교해도 되는가> 를 판정한다.

      completed  전 질문을 처리하고 전부 채점했다 = 설정 비교에 쓸 수 있다
      partial    일부가 처리 실패했거나(429·타임아웃) <채점>에 실패했다 = 비교하면 안 된다
      failed     한 문항도 처리하지 못했다 = 측정 자체가 없다

    🔴 judge_failed 를 보는 이유. 채점 실패는 fallback 과 <완전히 다른 사실>인데
       둘 다 scored_count 에서 빠져 결과가 같아 보인다. 그런데 Spring 의 전체 충실성은
       `avg_faithfulness × scored_count / question_count` 다(EvalRunResponse.overall).
       즉 <채점하지 못한 문항이 "충실성 0점" 으로 환산된다.>

       16문항 전부 정답(실제 1.000)인데 judge 가 2건에서 JSON 을 못 뱉으면
       avg=1.000 · scored=14 · total=16 → 대시보드 0.875 다. 그리고 processed 는
       검색·생성만 세므로 status 는 completed 로 남아, <화면 어디에도 경고가 없다.>

       AGENTS.md 의 "낸 버그 4건" 과 정확히 같은 부류다 — 원인이 다른 두 사실을
       같은 값으로 뭉갠 것. 그 절은 "다섯 번째를 조심할 것" 으로 끝난다.

    ⚠️ 순수 함수로 뽑은 이유는 <검사할 수 있게 하려고> 다(evalrun_check).
       DB 와 모델 호출에 묶여 있으면 이 판정만 따로 재현할 방법이 없다.
    """
    if not processed:
        return "failed"
    if processed < total or judge_failed:
        return "partial"
    return "completed"
```

- [ ] **Step 5: 검사를 돌려 통과를 확인한다**

```bash
cd ai-service && .venv/bin/python -m app.evalrun_check
```

Expected: `5가지 전부 통과.`

- [ ] **Step 6: `_execute`가 새 함수를 쓰게 한다**

`ai-service/app/evalrun.py`의 `_execute` 안을 세 군데 고친다.

**(a)** `processed = 0` 선언 **바로 아래**에 추가:

```python
    # ⚠️ 채점까지 못 간 것. fallback 과 <다른 사실>이라 따로 센다.
    #    둘 다 scored_count 에서 빠지지만, fallback 은 "근거가 없어 못 답했다"(제품의 품질)이고
    #    채점 실패는 "우리가 재지 못했다"(측정의 실패)다. 뭉개면 전자가 후자로 둔갑한다.
    judge_failed = 0
```

**(b)** `sc = judge.score(...)` 아래의 `if sc is None:` 블록을 교체:

```python
        sc = judge.score(question, ground_truth, sources, answer)
        if sc is None:
            # 채점 실패는 0점이 아니다. 평균에서 빼고 행만 남긴다.
            # 그리고 <세어둔다> — 이게 있으면 이 실행은 비교에 쓸 수 없다(_run_status).
            judge_failed += 1
            rows.append((run_id, qid, answer, retrieved, None, None))
            continue
```

**(c)** 기존 `if not processed: ... elif ... else:` 블록을 **통째로** 아래 한 줄로 바꾼다. **그 위에 붙어 있던 긴 주석(🔴 처리하지 못한 질문이 있으면 …)은 지우지 않고 그대로 둔다** — 그 기록이 이 판정의 근거다.

```python
    status = _run_status(processed, total, judge_failed)
```

- [ ] **Step 7: 완료 로그에 채점 실패 건수를 넣는다**

같은 파일 끝의 `_log.info(...)` 를 고친다. **채점 실패가 몇 건인지 로그에 안 보이면, `partial`을 보고도 원인을 못 찾는다.**

```python
    used = cf.neurons_used()
    _log.info(
        "평가 실행 완료 run_id=%s [%s] 질문 %d개 · 처리 %d개(실패 %d) · 답변 %d개 "
        "· 채점 %d개(실패 %d) · 💰 %.1f 뉴런 (%s)",
        run_id, status, total, processed, total - processed, answered,
        len(faiths), judge_failed,
        sum(used.values()),
        " / ".join(f"{m.rsplit('/', 1)[-1]} {n:.1f}" for m, n in sorted(used.items(), key=lambda x: -x[1])),
    )
```

- [ ] **Step 8: 커밋한다**

```bash
git add ai-service/app/evalrun.py ai-service/app/evalrun_check.py
git commit -m "$(cat <<'EOF'
fix: 채점 실패한 실행을 completed 가 아니라 partial 로 남긴다

judge.score 가 None 을 돌려주는 두 경우 — fallback 과 <채점 실패> — 가 같은 값으로
뭉개져 있었다. 둘 다 scored_count 에서 빠지는데, Spring 의 전체 충실성이
avg × scored / total 이라 채점하지 못한 문항이 <충실성 0점으로 환산>된다.
그런데 processed 는 검색·생성만 세므로 status 는 completed 로 남아 경고가 없다.

16문항 전부 정답(1.000)인데 judge 가 2건에서 JSON 을 못 뱉으면 대시보드는 0.875 를
보여주고, 그 값을 다른 설정과 나란히 놓고 "차이 없음" 이라고 결론내게 된다.

판정을 순수 함수 _run_status 로 뽑아 DB 없이 검사할 수 있게 했다(evalrun_check).

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 9: `judge.fetch_contents`를 try 안으로 옮긴다**

`ai-service/app/judge.py`에서 `contents = fetch_contents(...)` 부터 `user = (...)` 까지를 **아래 `try:` 블록 안으로** 옮긴다. 위의 긴 주석(⚠️ preview 가 아니라 전체 본문 …)은 `contents` 줄과 함께 옮긴다.

```python
    try:
        # ⚠️ preview(앞 200자)가 아니라 <전체 본문>을 준다.
        #    (…기존 주석 전문을 그대로 옮긴다…)
        #
        # 🔴 이 DB 조회가 try <안> 에 있는 이유 (2026-09-03):
        #    밖에 있으면 PoolTimeout·DB 재시작 같은 실패가 예외로 위로 새어나가
        #    evalrun._execute 를 뚫는다. 그런데 eval_results 의 INSERT 는 <루프가 끝난 뒤>
        #    한 번에 하므로, 15문항을 다 채점하고 마지막에 DB 가 1초 딸꾹하면
        #    <그때까지 모은 결과가 한 건도 저장되지 않는다.> 뉴런 800개를 쓰고 0건이다.
        #    이 함수의 계약은 이미 "실패하면 None" 이라 안으로 넣어도 의미가 바뀌지 않는다.
        contents = fetch_contents([src.chunk_id for src in sources])
        context = "\n\n".join(
            f"[근거 {i}] (출처: {src.filename})\n{contents.get(src.chunk_id, src.preview)}"
            for i, src in enumerate(sources, 1)
        )
        user = (
            f"<근거>\n{context}\n</근거>\n\n"
            f"<질문>\n{question}\n\n"
            f"<기대 답변>\n{ground_truth}\n\n"
            f"<채점할 답변>\n{answer}"
        )

        result = cf.run(s.judge_model, {
            # …기존 그대로…
        })
    except Exception as e:  # noqa: BLE001 - 한 건 실패가 실행 전체를 죽이면 안 된다
        _log.warning("채점 호출 실패: %s: %s", type(e).__name__, e)
        return None
```

- [ ] **Step 10: 문법과 import를 확인한다**

```bash
cd ai-service && .venv/bin/python -c "from app import judge, evalrun; print('import OK')"
.venv/bin/python -m app.evalrun_check
```

Expected: `import OK` 그리고 `5가지 전부 통과.`

- [ ] **Step 11: 커밋하고 PR을 연다**

```bash
git add ai-service/app/judge.py
git commit -m "$(cat <<'EOF'
fix: 채점의 DB 조회를 try 안으로 옮겨 실행 전체가 날아가지 않게 했다

judge.score 의 fetch_contents 가 try 밖이라, PoolTimeout·DB 재시작 같은 실패가
evalrun._execute 를 뚫고 나갔다. eval_results INSERT 는 루프가 끝난 뒤 한 번에 하므로
15문항을 다 채점하고 마지막에 DB 가 딸꾹하면 결과가 한 건도 저장되지 않는다.

이 함수의 계약이 이미 "실패하면 None" 이라 안으로 넣어도 의미가 바뀌지 않는다.
⚠️ 앞 커밋(채점 실패 → partial)과 반드시 함께 가야 한다. 이것만 먼저 고치면
DB 딸꾹이 None 이 되어 "충실성 0점" 으로 둔갑한다 — 지금보다 나빠진다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
git push -u origin fix/eval-measurement
gh pr create --title "fix: 평가 측정이 채점 실패를 fallback 으로 뭉개지 않게" --body "$(cat <<'EOF'
## 무엇을 왜 바꿨나요

`judge.score()` 가 `None` 을 돌려주는 두 경우가 같은 값으로 뭉개져 있었습니다.

| 사실 | `scored_count` 에서 빠지는 게 | 맞나 |
|---|---|---|
| fallback (근거가 없어 못 답함) | 빠진다 | ✅ 맞다. 전체 충실성이 내려가야 옳다 |
| **채점 실패** (judge JSON 파싱 실패·5xx·잘림) | 빠진다 | ❌ 측정이 **안 된** 것이다 |

그런데 Spring 의 전체 충실성은 `avg_faithfulness × scored_count / question_count` 입니다
(`EvalRunResponse.java:84`). 즉 **채점하지 못한 문항이 "충실성 0점" 으로 환산됩니다.**
그리고 `processed` 는 검색·생성만 세므로 `status` 는 `completed` 로 남아 화면 어디에도 경고가 없습니다.

**실패 시나리오:** 16문항 전부 정답(실제 1.000)인데 judge 가 2건에서 코드펜스 없는 잡소리를 뱉어
`_extract_json` 이 `None` 반환 → `avg=1.000 · scored=14 · total=16` → 대시보드 **0.875**.
이 값을 다른 설정의 0.875 와 나란히 놓고 **"차이 없음"이라고 결론냅니다.**
(실제로 발생하는 경로입니다 — `config.py` 가 `gpt-oss-120b` 를 "JSON 파싱 실패"로 탈락시킨 기록이 있습니다)

🔴 AGENTS.md 의 **"낸 버그 4건"과 정확히 같은 부류**입니다. 넷 다 *원인이 다른 두 사실을 같은 값으로
뭉갠 것*이었고, 그 절은 **"다섯 번째를 조심할 것"** 으로 끝납니다. 이게 다섯 번째입니다.
그리고 `partial` 상태는 **바로 이 상황을 잡으려고 만든 것**인데, 검색·생성 실패만 잡고 채점 실패를 놓쳤습니다.

함께: `judge.score` 의 `fetch_contents` 가 `try` 밖이라, DB 가 잠깐 딸꾹하면 예외가
`_execute` 를 뚫고 나가 **그때까지 모은 결과가 한 건도 저장되지 않았습니다**(INSERT 가 루프 후 일괄).
15문항을 다 채점하고 마지막에 실패하면 뉴런 800개를 쓰고 0건입니다.

**두 수정은 반드시 함께 가야 합니다.** 후자만 먼저 고치면 DB 딸꾹이 `None` 이 되어
"충실성 0점" 으로 둔갑합니다 — 지금보다 나빠집니다.

## 어떻게 해결했나요

판정을 순수 함수 `_run_status(processed, total, judge_failed)` 로 뽑고 `judge_failed` 를 세게 했습니다.
DB·모델 없이 검사할 수 있어 `app/evalrun_check.py` 5건이 이 판정만 따로 재현합니다.

<!-- 실제 실행 결과를 여기에 붙일 것: Step 3 의 ImportError 와 Step 10 의 "5가지 전부 통과" -->

## 한계 & 트레이드오프

- **`partial` 의 의미가 넓어집니다.** 원래는 "일부 문항을 처리하지 못했다" 였는데 이제
  "일부를 채점하지 못했다" 도 포함합니다. 화면에서 둘을 구분하려면 사유 컬럼이 필요하지만,
  **지금 필요한 것은 "이 실행을 유효한 측정으로 쓰면 안 된다" 는 신호 하나**라 컬럼을 늘리지 않았습니다.
  대신 완료 로그에 채점 실패 건수를 찍어, `partial` 을 보고 원인을 찾을 수 있게 했습니다.
- 🔴 **과거 실행은 소급 정정할 수 없습니다.** `judge_failed` 를 기록한 적이 없어 이미 쌓인 측정치가
  채점 실패를 포함하는지 알 방법이 없습니다. W4 의 수치들은 그대로 두고 이 사실만 남깁니다.
- `evalrun_check` 는 **판정 로직만** 검사합니다. `_execute` 가 그 함수를 실제로 부르는지는
  DB 와 모델이 필요해 검사하지 않습니다. 다음에 평가를 돌릴 때 로그의 `[status]` 로 확인합니다.

## 검토한 대안

- **`eval_runs` 에 `judge_failed_count` 컬럼 추가(V5)** — 화면에서 사유를 구분해 보여줄 수 있지만,
  지금 필요한 신호는 "쓰면 안 된다" 하나입니다. 필요해지면 그때 마이그레이션을 넣습니다.
- **채점 실패를 0점으로 처리** — 그게 지금 <사실상> 벌어지던 일이고, 바로 그것이 버그입니다.
- **`_execute` 를 통째로 검사** — DB·Cloudflare 가 필요해 검사 비용이 실제 평가 1회와 같아집니다.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Task 3: `/internal/*` 에 빠진 `bot_id` 조건 채우기

**브랜치:** `fix/internal-bot-scope` · **모델: Sonnet**

**Files:**
- Modify: `ai-service/app/main.py:174-186` (`delete_document`)
- Delete: `ai-service/app/main.py:442-459` (`list_eval_results` 라우트)
- Modify: `api/src/main/java/com/alldap/api/global/client/AiServiceClient.java:163-172`
- Modify: `api/src/main/java/com/alldap/api/domain/document/service/DocumentService.java` (`delete` 메서드)
- Test: `api/src/test/java/com/alldap/api/domain/document/DocumentIntegrationTest.java`

**Interfaces:**
- Consumes: `Document.getBot()` → `Bot`, `Bot.getId()` → `UUID` (기존 엔티티)
- Produces: `AiServiceClient.deleteDocument(UUID botId, UUID documentId)` — **인자가 하나 늘어난다.** 호출부는 `DocumentService.delete` 하나뿐이다.
- Python 경로 변경: `DELETE /internal/documents/{doc_id}` → `DELETE /internal/bots/{bot_id}/documents/{doc_id}`

---

- [ ] **Step 1: 브랜치를 딴다**

```bash
cd /Users/cheonjamin/projects/AllDap
git checkout main && git checkout -b fix/internal-bot-scope
```

- [ ] **Step 2: `list_eval_results` 를 아무도 안 부르는지 확인한다**

```bash
grep -rn "eval/runs/.*results\|list_eval_results" --include=*.java --include=*.ts --include=*.tsx --include=*.js --include=*.py . | grep -v node_modules
```

Expected: `ai-service/app/main.py` 의 정의 한 곳만 나온다.
**하나라도 호출부가 나오면 지우지 말고 멈춘다.** 그때는 경로를 `/internal/bots/{bot_id}/eval/runs/{run_id}/results` 로 바꾸고 `JOIN eval_runs run ON run.id = r.run_id AND run.bot_id = %s` 를 거는 쪽으로 간다.

- [ ] **Step 3: 실패하는 테스트를 쓴다 — 남의 봇 문서는 지워지지 않는다**

`DocumentIntegrationTest.java` 의 기존 `문서_삭제()` 테스트에서 경로 단언을 고친다. 지금은 이렇게 돼 있다:

```java
        assertThat(aiService.received().get(0).path()).isEqualTo("/internal/documents/" + documentId);
```

이것을 아래로 바꾼다.

```java
        // 🔴 경로에 botId 가 들어간다. /internal/* 에는 인증이 없어서, doc_id 만으로 DELETE 하면
        //    <남의 봇 문서를 지울 수 있다.> Python 쪽 WHERE 도 두 값으로 함께 좁힌다.
        assertThat(aiService.received().get(0).path())
                .isEqualTo("/internal/bots/" + botId + "/documents/" + documentId);
```

- [ ] **Step 4: 테스트를 돌려 실패를 확인한다**

```bash
cd api && ./gradlew test --tests 'DocumentIntegrationTest'
```

Expected: `문서_삭제` FAIL — 실제 경로가 `/internal/documents/<uuid>` 로 온다.

- [ ] **Step 5: Python 의 `delete_document` 를 고친다**

`ai-service/app/main.py` 의 `delete_document` 를 통째로 교체한다. **위에 붙어 있는 `response_model=None` 설명 주석은 그대로 둔다.**

```python
@app.delete("/internal/bots/{bot_id}/documents/{doc_id}", status_code=204, response_model=None)
def delete_document(bot_id: UUID, doc_id: UUID) -> None:
    """문서 1건을 지운다. 청크는 CASCADE 로 함께 사라진다.

    🔴 <b>경로에 bot_id 가 반드시 있어야 한다.</b> `/internal/*` 에는 인증이 없어서
    doc_id 만으로 DELETE 하면 <남의 봇 문서를 통째로 지울 수 있다.> 그리고 이건
    되돌릴 수 없다 — chunks 와 doc_conflicts 가 CASCADE 로 함께 사라진다.

    같은 파일의 `update_conflict_status` 가 정확히 이 이유로 bot_id 를 요구한다.
    여기만 규칙에서 빠져 있었고, 파괴력은 이쪽이 더 크다.

    ⚠️ 소유권을 "검사" 하지 않고 <조회 조건에 못박는다>. 검사 방식은 빠뜨려도
    테스트가 통과하지만, WHERE 에 못박으면 빠뜨릴 자리가 없다(AGENTS.md 원칙).

    없는 문서를 지워도 204 다(SQL DELETE 가 0행을 지운 것뿐).
    "없는 문서" 판단은 Spring 이 이 호출 <전에> DB 조회로 끝낸다.
    """
    with cursor(commit=True) as cur:
        cur.execute(
            "DELETE FROM documents WHERE id=%s AND bot_id=%s", (doc_id, bot_id)
        )
```

- [ ] **Step 6: `list_eval_results` 라우트를 지운다**

`ai-service/app/main.py` 에서 `@app.get("/internal/eval/runs/{run_id}/results", ...)` 데코레이터부터 그 함수 본문 끝까지를 지운다. 지운 자리에 남기는 주석은 없다 — **git 이 기록이다.**

지운 뒤 `EvalResultOut` 이 다른 곳에서 안 쓰이면 `from .schemas import (...)` 목록에서도 뺀다.

```bash
cd /Users/cheonjamin/projects/AllDap && grep -n "EvalResultOut" ai-service/app/main.py
```

Expected: 아무것도 안 나오면 import 목록에서 제거한다.

- [ ] **Step 7: `AiServiceClient.deleteDocument` 를 고친다**

```java
    /**
     * 문서 삭제. chunks 는 DB 의 ON DELETE CASCADE 로 함께 지워진다.
     *
     * <p>Spring 이 documents 를 직접 DELETE 하지 않는 이유: 쓰기 소유자가 Python 이기 때문이다.
     * 양쪽이 같은 테이블에 쓰기 시작하면 누가 무엇을 바꿨는지 추적이 불가능해진다.
     *
     * <p><b>botId 를 함께 보낸다.</b> Python 의 {@code /internal/*} 에는 인증이 없어서,
     * 그쪽 SQL 의 {@code WHERE ... AND bot_id = %s} 가 봇 간 격리의 마지막 그물이다.
     * Spring 이 이미 소유권을 확인했지만, 격리를 <b>한 겹으로 두지 않는다.</b>
     */
    public void deleteDocument(UUID botId, UUID documentId) {
        call("문서 삭제", () -> aiServiceRestClient.delete()
                .uri("/internal/bots/{botId}/documents/{documentId}", botId, documentId)
                .retrieve()
                .toBodilessEntity());

        // Python 의 DELETE 는 없는 id 를 지워도 204 다(SQL DELETE 가 0행을 지운 것뿐).
        // 그래서 "없는 문서" 판단은 Spring 이 이 호출 <전에> DB 조회로 끝낸다(DocumentService).
        // 여기서 다시 확인하려 들면 Python 컨트랙트에 없는 의미를 우리가 지어내는 셈이다.
    }
```

- [ ] **Step 8: `DocumentService.delete` 의 호출을 고친다**

```java
        // ⚠️ documentRepository.delete() 를 부르면 안 된다. documents 의 쓰기 소유자는 Python 이다.
        // 실제 DELETE 는 Python 이 하고, chunks 는 DB 의 ON DELETE CASCADE 로 함께 사라진다.
        //
        // botId 를 함께 넘긴다 — Python 쪽 WHERE 가 두 값으로 좁혀지므로,
        // 여기 소유권 검사가 언젠가 빠지더라도 남의 봇 문서까지는 지워지지 않는다.
        aiServiceClient.deleteDocument(document.getBot().getId(), document.getId());
```

> ⚠️ `delete`는 `@Transactional` 이 아니고 `open-in-view=false` 다. `findByIdAndBotUserId` 가 `Bot` 을 LAZY 로 물고 있으면 `document.getBot().getId()` 에서 터질 수 있다. **Step 10에서 테스트가 그것까지 확인한다.** 만약 `LazyInitializationException` 이 나면 `DocumentRepository.findByIdAndBotUserId` 에 `@EntityGraph(attributePaths = "bot")` 를 붙인다(그게 최소 수정이다 — `@Transactional` 을 붙이면 Python 호출이 트랜잭션 안으로 들어가 풀이 마른다).

- [ ] **Step 9: 남의 문서 삭제 테스트에 단언을 하나 더 넣는다**

`DocumentIntegrationTest.java` 의 기존 `남의_문서_삭제()` 는 이미 `assertThat(aiService.received()).isEmpty()` 로 **"요청이 Python 까지 가지 않았다"** 를 확인한다. 그대로 두고, 아래 테스트를 그 **바로 아래**에 추가한다.

```java
    @Test
    @DisplayName("[보안] 삭제 요청 경로에 botId 가 실려 Python 쪽에서도 봇으로 좁혀진다")
    void 삭제_요청에_botId_가_실린다() {
        UUID documentId = insertDocument(botId, "규정.pdf", "ready");
        aiService.enqueue(204, null);

        request(HttpMethod.DELETE, "/api/documents/" + documentId, ownerToken);

        // /internal/* 에는 인증이 없다. Python 쪽 WHERE 가 두 값으로 좁혀지려면
        // 경로에 botId 가 반드시 실려야 한다 — 그게 격리의 마지막 그물이다.
        assertThat(aiService.received().get(0).path())
                .isEqualTo("/internal/bots/" + botId + "/documents/" + documentId);
    }
```

- [ ] **Step 10: 테스트를 돌려 통과를 확인한다**

```bash
cd api && ./gradlew test --tests 'DocumentIntegrationTest'
```

Expected: PASS (전체 클래스)

- [ ] **Step 11: Python 이 뜨는지 확인한다**

라우트를 지웠으므로 import 가 깨졌을 수 있다.

```bash
cd ai-service && .venv/bin/python -c "from app.main import app; print([r.path for r in app.routes if 'documents' in r.path or 'results' in r.path])"
```

Expected: `/internal/bots/{bot_id}/documents/{doc_id}` 가 있고 `/internal/eval/runs/{run_id}/results` 는 **없다.**

- [ ] **Step 12: 전체 Spring 테스트를 돌린다**

```bash
cd api && ./gradlew test
```

Expected: PASS

- [ ] **Step 13: 커밋하고 PR을 연다**

```bash
git add -A
git commit -m "$(cat <<'EOF'
fix: /internal 문서 삭제에 bot_id 를 못박고, 격리 없는 죽은 라우트를 지웠다

/internal/* 에는 인증이 없어 SQL 의 bot_id 조건이 봇 간 격리의 전부다.
그런데 delete_document 는 doc_id 만으로 DELETE 했다 — 파괴력이 가장 큰 경로인데
(문서 + 청크 + doc_conflicts 가 CASCADE) 격리가 Spring 한 겹뿐이었다.
같은 파일의 update_conflict_status 는 정확히 이 이유로 bot_id 를 요구한다.

list_eval_results 는 run_id 만으로 남의 봇 답변·정답·파일명을 돌려주는데
Spring 이 부르지 않는 죽은 코드였다. 지웠다 — 필요해지면 bot_id 를 낀 경로로 다시 만든다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
git push -u origin fix/internal-bot-scope
gh pr create --title "fix: /internal 경로에 빠진 bot_id 조건 채우기" --body "$(cat <<'EOF'
## 무엇을 왜 바꿨나요

`/internal/*` 에는 **인증이 없습니다.** SQL 의 `bot_id` 조건이 봇 간 격리의 전부입니다.
같은 파일의 `update_conflict_status` 는 **정확히 이 이유로** 경로에 `bot_id` 를 요구하는데,
두 곳만 규칙에서 빠져 있었습니다.

**① `delete_document`** — `DELETE FROM documents WHERE id=%s` 뿐이었습니다.
파괴력이 가장 큰 경로입니다. 문서 + 전 청크 + `doc_conflicts` 가 CASCADE 로 함께 사라지고
**되돌릴 수 없습니다.**

**② `list_eval_results`** — `run_id` 만으로 조회하고, 응답에 `generated_answer`·`ground_truth`·
`retrieved_chunks`(파일명 포함)가 들어갑니다 = 남의 봇 문서 내용입니다.
그런데 Spring 은 이걸 **부르지 않습니다** — `EvalService.findResults` 가 `findByIdAndBotId` 로
소유권을 확인하고 DB 를 직접 읽습니다. 격리가 약한 **죽은 코드**였습니다.

**실패 시나리오:** 지금은 Spring 의 `findByIdAndBotUserId` 가 막아주므로 **격리 전체가 Spring 한 겹**입니다.
Python 이 내부망에 노출되거나(AGENTS.md 가 배포 시 알려진 위험으로 적어둔 것), Spring 에 소유권 검사를
빠뜨린 경로가 하나라도 생기면, `doc_id` 하나로 남의 봇 코퍼스가 통째로 지워집니다.

AGENTS.md 의 원칙 — *"소유권을 검사하지 않고 조회 쿼리에 못박는다"* — 을 어긴 유일한 쓰기 경로였습니다.

## 어떻게 해결했나요

경로를 `/internal/bots/{bot_id}/documents/{doc_id}` 로 바꾸고 `WHERE id=%s AND bot_id=%s` 로 좁혔습니다.
②는 지웠습니다 — 호출부가 없음을 grep 으로 확인했고, 필요해지면 `bot_id` 를 낀 경로로 다시 만듭니다.

테스트는 **"404 가 났다"가 아니라 "요청이 Python 까지 가지 않았다"** 와
**"간 요청에는 botId 가 실렸다"** 를 확인합니다.

<!-- 실제 실행 결과를 여기에 붙일 것: Step 4 의 FAIL 출력과 Step 12 의 PASS 출력 -->

## 한계 & 트레이드오프

- 🔴 **경로가 바뀌므로 Spring 과 Python 을 함께 배포해야 합니다.** 한쪽만 올리면 문서 삭제가 404 입니다.
  무중단이 아니라 잠깐 멈추고 둘 다 올립니다 — 1인 개발·단일 인스턴스라 이 대가가 쌉니다.
- **이 수정이 Spring 의 소유권 검사를 대체하지 않습니다.** 여전히 Spring 이 1차 관문이고,
  Python 의 `bot_id` 는 **그물**입니다. 두 겹으로 만든 것이지 한 겹을 옮긴 게 아닙니다.
- ②를 지운 것은 **되돌릴 수 있는 결정**입니다(코드가 git 에 남습니다). 반면 남겨두는 것은
  되돌릴 수 없는 유출의 가능성을 남깁니다.
- `documents` 의 다른 경로(업로드·목록)는 이미 `/internal/bots/{bot_id}/...` 라 손대지 않았습니다.

## 검토한 대안

- **Python 이 소유권을 조회해 검사** — `findById` 후 `if 남의 것 throw` 방식은 검사를 빠뜨려도
  테스트가 통과합니다. 그래서 조회 조건에 못박는 쪽을 택했습니다(AGENTS.md 원칙).
- **②를 지우지 않고 경로만 고치기** — 아무도 안 부르는 코드에 격리를 붙이는 일이라,
  유지비만 늘고 검증할 방법도 없습니다.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Task 4: 청킹 — 마침표 없는 긴 줄에 마지막 그물

**브랜치:** `fix/chunker-hard-split` · **모델: Sonnet**

**Files:**
- Modify: `ai-service/app/chunker.py:46-65` (`_split_sentences`)
- Modify: `ai-service/app/chunker_check.py` (회귀 검사 1건 추가)
- Create: `/private/tmp/claude-501/.../scratchpad/chunk_compare.py` (일회용 대조 스크립트 — **저장소에 커밋하지 않는다**)

**Interfaces:**
- Consumes: `chunk_text(text, *, size, overlap, split_headings) -> list[Chunk]` (`Chunk.content`, `Chunk.index`, `Chunk.meta`)
- Produces: 없음. 이 Task는 다른 Task가 의존하는 것을 만들지 않는다.

---

- [ ] **Step 1: 브랜치를 딴다**

```bash
cd /Users/cheonjamin/projects/AllDap
git checkout main && git checkout -b fix/chunker-hard-split
```

- [ ] **Step 2: 실패하는 검사를 쓴다**

`ai-service/app/chunker_check.py` 의 `check_long_section_still_splits` **바로 아래**에 넣는다.

```python
def check_line_without_period_is_still_split() -> None:
    """🔴 마침표가 <없는> 긴 줄도 size 를 넘지 않아야 한다.

    _split_sentences 가 `line.split(".")` 로만 자르기 때문에, 마침표가 없으면
    조각이 하나뿐이라 <길이 상한이 전혀 적용되지 않았다.> 실측(2026-09-03):
        "## 긴 표\\n" + "가나다라마바사아자차"*300, size=500  →  청크 길이 [6, 3008]

    3008자 청크는 이 모듈의 존재 이유("청크 하나에 주제 하나")가 정면으로 무너진 것이다.
    2026-08-03 에 478자 청크에 조항 4개가 들어가 fallback 이 났던 것과 <같은 실패 모드>이고
    규모가 6배다.

    ⚠️ 바로 위 check_long_section_still_splits 는 이걸 못 잡는다 —
       그 지문("가나다라마바사아자차. " * 80)은 <마침표를 갖고 있다.>

    현실적인 입력: PDF·HWPX 표 한 행, 마침표 없이 개행·중점으로만 나열된 조항.
    parsers._parse_docx 가 표를 " | " 로 이어 붙인 줄이 정확히 이 모양이다.
    """
    no_period = "## 긴 표\n" + ("가나다라마바사아자차" * 300)
    chunks = chunk_text(no_period, size=500, overlap=50, split_headings=True)
    lengths = [len(c.content) for c in chunks]
    assert all(n <= 500 + 50 for n in lengths), lengths
```

`main()` 의 `checks` 목록에 `check_long_section_still_splits` **다음** 줄로 추가한다.

```python
        check_long_section_still_splits,
        check_line_without_period_is_still_split,
```

- [ ] **Step 3: 검사를 돌려 실패를 확인한다**

```bash
cd ai-service && .venv/bin/python -m app.chunker_check
```

Expected: `AssertionError: [6, 3008]`

- [ ] **Step 4: `_split_sentences` 에 마지막 그물을 건다**

`ai-service/app/chunker.py` 의 `_split_sentences` 마지막 줄 `return out or [line[:size]]` 를 교체한다.

```python
    if buf.strip():
        out.append(buf.strip())
    # 🔴 마지막 그물. 위 루프는 마침표로만 자르므로, 마침표가 없는 줄은
    #    조각이 하나뿐이라 <길이 상한이 전혀 적용되지 않는다.>
    #    (실측 2026-09-03: 마침표 없는 3000자 줄 → 3008자 청크 하나)
    #    표 한 행처럼 마침표가 없는 입력에서는 자를 자리를 알 방법이 없어 강제로 끊는다.
    #    문장 중간이 잘리는 것은 대가지만, 3000자 한 덩어리보다 낫다.
    #    ⚠️ `out or [line]` 인 이유: 위 루프가 한 조각도 못 만든 경우에도
    #       원본 줄 전체를 잘라 담아야 한다(예전에는 `line[:size]` 로 <뒤를 버렸다>).
    return [p[i : i + size] for p in (out or [line]) for i in range(0, len(p), size)]
```

> 🔴 **버려지던 내용이 함께 고쳐진다.** 기존 `[line[:size]]` 는 size 이후를 **통째로 버렸다.** 위 수정은 전부 담는다. 이 사실을 PR 본문에 적는다.

- [ ] **Step 5: 검사를 돌려 통과를 확인한다**

```bash
cd ai-service && .venv/bin/python -m app.chunker_check
```

Expected: `9가지 전부 통과.` (기존 8 + 새 1)

> ⚠️ 기존 검사 중 하나라도 깨지면 **멈춘다.** 특히 `check_idempotent`(같은 입력에 몇 번 돌려도 같은 결과)와 `check_legacy_behavior` 가 중요하다.

- [ ] **Step 6: 🔴 기존 코퍼스의 청크가 바뀌는지 대조한다 — 이 Task의 핵심이다**

**청크가 하나라도 바뀌면 W4 측정치가 전부 무효가 된다.** 먼저 안 바뀌는지 확인한다.

스크래치패드에 대조 스크립트를 쓴다(저장소에 커밋하지 않는다).

```bash
cat > /private/tmp/claude-501/-Users-cheonjamin-projects-AllDap/c30a4c2b-e21f-43ce-b40b-237015b8df00/scratchpad/chunk_compare.py <<'PY'
"""고친 청커로 코퍼스를 다시 청킹해 DB 의 chunks 와 문자열 단위로 대조한다.

목적은 하나다: <이 수정이 기존 측정치를 무효화하는가.>
하나라도 다르면 재임베딩·평가 재측정이 필요하고, 그건 이 PR 의 범위가 아니다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve()))
from app.chunker import chunk_text
from app.config import get_settings
from app.db import cursor

s = get_settings()
corpus = sorted(Path("testdata/corpus").glob("*.md"))
print(f"코퍼스 파일 {len(corpus)}개")

mismatch = 0
missing = 0
for path in corpus:
    text = path.read_text(encoding="utf-8")
    fresh = [c.content for c in chunk_text(
        text, size=s.chunk_size, overlap=s.chunk_overlap,
        split_headings=s.chunk_split_headings)]

    with cursor() as cur:
        cur.execute(
            """SELECT c.content FROM chunks c
                 JOIN documents d ON d.id = c.document_id
                WHERE d.filename = %s ORDER BY c.chunk_index""",
            (path.name,),
        )
        stored = [r[0] for r in cur.fetchall()]

    if not stored:
        print(f"  ? {path.name}: DB 에 없음 (파일명이 다를 수 있다)")
        missing += 1
        continue
    if fresh != stored:
        mismatch += 1
        print(f"  ❌ {path.name}: 청크 {len(stored)} → {len(fresh)}")
        for i, (a, b) in enumerate(zip(stored, fresh)):
            if a != b:
                print(f"     [{i}] 저장={len(a)}자 새로={len(b)}자")
                print(f"          저장: {a[:80]!r}")
                print(f"          새로: {b[:80]!r}")
                break

print(f"\n다른 파일 {mismatch}개 · DB 에 없는 파일 {missing}개")
sys.exit(1 if mismatch else 0)
PY
cd ai-service && .venv/bin/python /private/tmp/claude-501/-Users-cheonjamin-projects-AllDap/c30a4c2b-e21f-43ce-b40b-237015b8df00/scratchpad/chunk_compare.py
```

> ⚠️ DB 가 떠 있어야 한다: `docker compose up -d`

| 결과 | 다음 행동 |
|---|---|
| `다른 파일 0개` (예상) | Step 7로 간다. **PR 본문에 이 출력을 실측으로 붙인다** |
| 하나라도 다름 | 🔴 **여기서 멈추고 사람에게 보고한다.** 재청킹·재임베딩·평가 재측정이 필요하고 그건 별도 결정이다 |

- [ ] **Step 7: 커밋하고 PR을 연다**

```bash
git add ai-service/app/chunker.py ai-service/app/chunker_check.py
git commit -m "$(cat <<'EOF'
fix: 마침표 없는 긴 줄도 청크 크기를 넘지 않게 했다

_split_sentences 가 line.split(".") 로만 자르기 때문에, 마침표가 없으면 조각이
하나뿐이라 길이 상한이 전혀 적용되지 않았다. 실측: 마침표 없는 3000자 줄 →
3008자 청크(size=500). 2026-08-03 에 478자 청크에 조항 4개가 들어가 fallback 이
났던 것과 같은 실패 모드이고 규모가 6배다.

기존 check_long_section_still_splits 는 지문에 마침표가 있어 못 잡았다.
마침표 없는 케이스를 회귀 검사로 추가했다.

부수 수정: 기존 폴백 `[line[:size]]` 는 size 이후를 통째로 버렸다. 전부 담게 했다.

기존 코퍼스 50문서의 청크는 하나도 바뀌지 않는다(대조 실측). 재임베딩 불필요.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
git push -u origin fix/chunker-hard-split
gh pr create --title "fix: 마침표 없는 긴 줄이 청크 크기를 넘던 것" --body "$(cat <<'EOF'
## 무엇을 왜 바꿨나요

`chunker._split_sentences` 는 `line.split(".")` 로만 자릅니다.
**마침표가 없으면 조각이 하나뿐이라 길이 상한이 전혀 적용되지 않습니다.**

재현 (실측, 2026-09-03):
```
text = "## 긴 표\n" + "가나다라마바사아자차" * 300     # size=500
→ 청크 2개, 길이 [6, 3008]
```

두 가지가 동시에 깨집니다.

- **3008자 청크** — 이 모듈의 존재 이유("청크 하나에 주제 하나")가 정면으로 무너집니다.
  2026-08-03 에 478자 청크에 조항 4개가 들어가 fallback 이 났던 것과 **같은 실패 모드이고 규모가 6배**입니다.
- **제목이 6자 단독 청크로 떨어집니다** — `_pack` 에서 `candidate` 가 size 를 넘는 순간
  제목만 든 `buf` 를 먼저 뱉기 때문입니다.

**현실적인 입력:** PDF·HWPX 표 한 행, 마침표 없이 개행·중점으로만 나열된 조항.
`parsers._parse_docx` 가 표를 ` | ` 로 이어 붙인 줄이 정확히 이 모양입니다.

**기존 검사는 못 잡습니다** — `check_long_section_still_splits` 의 지문
(`"가나다라마바사아자차. " * 80`)이 **마침표를 갖고 있습니다.**

## 어떻게 해결했나요

`_split_sentences` 의 반환에 강제 분할을 걸고, 마침표 없는 케이스를 회귀 검사로 추가했습니다.

**부수 수정:** 기존 폴백 `[line[:size]]` 는 size 이후를 **통째로 버렸습니다.** 이제 전부 담습니다.

<!-- 실제 실행 결과를 여기에 붙일 것: Step 3 의 AssertionError [6, 3008] 과 Step 5 의 "9가지 전부 통과" -->

**기존 코퍼스는 영향이 없습니다 — 예상이 아니라 대조 실측입니다.**
`testdata/corpus/` 50개를 고친 청커로 다시 청킹해 DB 의 `chunks` 와 문자열 단위로 대조했습니다.

<!-- 실제 실행 결과를 여기에 붙일 것: Step 6 의 "다른 파일 0개" 출력 -->

→ 재임베딩·평가 재측정이 필요 없고, **W4 의 측정치는 그대로 유효합니다.**

## 한계 & 트레이드오프

- **강제 분할은 문장 중간을 자릅니다.** 마침표가 없는 줄에서는 그것 말고 자를 자리를 알 수 없습니다.
  3008자 한 덩어리보다는 낫다는 판단이고, 문장 경계 인식이 필요해지면 별도 슬라이스입니다.
- 🔴 **제목이 단독 청크로 떨어지는 문제는 이 수정으로 완전히 사라지지 않습니다.** 본문이 강제
  분할되면 첫 조각에는 제목이 붙지만 그 뒤 조각들은 제목 없이 남습니다. 근본 해결은 `_pack` 이
  제목을 각 조각에 복제하는 것인데, 그건 **청크 내용을 바꾸는 변경이라 기존 측정치를 무효화합니다.**
  이번 범위에서 뺐습니다.
- 이 수정이 검색 품질을 **개선한다고 주장하지 않습니다.** 현재 코퍼스에서는 아무것도 바뀌지 않습니다.
  앞으로 들어올 문서를 위한 그물입니다.

## 검토한 대안

- **`_pack` 에서 길이를 강제** — 거기서 자르면 제목·문단 구조를 잃습니다. 잘라야 할 것은
  "한 줄이 너무 길다" 는 경우뿐이라 그 자리에서 막는 쪽이 맞습니다.
- **문장 경계 인식 라이브러리(kss 등) 도입** — 의존성이 늘고, 표 한 행에는 문장 경계가
  애초에 없습니다. 이 버그를 고치지 못합니다.
- **`chunk_size` 를 늘려 회피** — 증상만 가립니다. 3000자든 5000자든 상한이 없는 것은 같습니다.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Task 5: W1 fallback 검사가 봇 지침을 태우게

**브랜치:** `fix/fallback-check-prompt` · **모델: Sonnet**

**Files:**
- Modify: `ai-service/app/fallback_e2e_check.py:45` (import), `:130-165` (`generate` 호출 3곳)

**Interfaces:**
- Consumes: `generator.build_system_prompt(bot_prompt: str | None) -> str`, `generator.fetch_bot_prompt(bot_id: UUID) -> str | None`
- Produces: 없음.

---

- [ ] **Step 1: 브랜치를 딴다**

```bash
cd /Users/cheonjamin/projects/AllDap
git checkout main && git checkout -b fix/fallback-check-prompt
```

- [ ] **Step 2: 지금 무엇을 재고 있는지 확인한다 — 수정 전 기준선**

```bash
cd ai-service && .venv/bin/python -m app.fallback_e2e_check
```

Expected: `fallback 10/10 (기준 8) · … · 대조군 3/3`
**이 출력을 그대로 보관한다.** PR 본문에 before 로 붙인다.

> ⚠️ Cloudflare 한도(10,000 뉴런/일)에 걸려 429 가 나면 **여기서 멈추고 사람에게 보고한다.** 한도 리셋은 소진 시각으로부터 약 33시간 뒤다(AGENTS.md 실측).

- [ ] **Step 3: import 를 고친다**

`ai-service/app/fallback_e2e_check.py:45` 를 교체한다.

```python
from .generator import build_system_prompt, fetch_bot_prompt, generate
```

- [ ] **Step 4: 봇 지침을 한 번 읽어 세 곳에 넘긴다**

`main()` 안, `guard_only` 처리(`if guard_only: return`) **바로 아래**에 추가한다.

```python
    # 🔴 프로덕션이 실제로 쓰는 프롬프트를 그대로 태운다.
    #
    #    이 검사는 파일 첫머리에서 "1차·2차 방어선이 함께 걸린다" 고 주장하는데,
    #    봇 지침 없이 기본 SYSTEM_PROMPT 로만 돌면 그 주장이 거짓이 된다.
    #    main.chat 과 evalrun._execute 는 둘 다 build_system_prompt(fetch_bot_prompt(...)) 를 쓴다.
    #
    #    왜 중요한가: 2026-08-13 실측으로 <봇 지침 하나에 fallback 판정이 뚫린다>는 것이
    #    확인돼 있다(AGENTS.md · bot_prompt_check). 지침에 "모르는 것도 아는 척 답해" 계열
    #    문구가 들어가면 근거 없는 질문에 is_fallback=False 로 답한다.
    #    그런데 이 검사는 기본 프롬프트로 돌아 10/10 을 찍는다 —
    #    <W1 완료 조건이 통과했다고 보고하는데 제품은 뚫려 있는> 상태가 된다.
    #
    #    ⚠️ 루프 밖에서 한 번만 읽는다. 질문마다 읽으면 도중에 설정이 바뀔 때
    #       앞뒤 질문이 다른 프롬프트로 판정돼 측정이 섞인다(evalrun 과 같은 이유).
    system_prompt = build_system_prompt(fetch_bot_prompt(BOT_ID))
    print(f"봇 지침: {'있음 (프로덕션과 동일하게 결합해 태운다)' if len(system_prompt) > 400 else '없음 (기본 규칙만)'}\n")
```

- [ ] **Step 5: `generate` 호출 3곳에 넘긴다**

세 군데 모두 아래 형태로 바꾼다 (근거 없는 질문 / 대조군 / 알려진 검색 한계).

```python
        answer, is_fallback = generate(question, sources, system_prompt=system_prompt)
```

```bash
cd /Users/cheonjamin/projects/AllDap && grep -n "generate(question, sources" ai-service/app/fallback_e2e_check.py
```

Expected: 3줄 전부 `system_prompt=system_prompt` 를 포함한다.

- [ ] **Step 6: 검사를 돌려 결과를 확인한다**

```bash
cd ai-service && .venv/bin/python -m app.fallback_e2e_check
```

Expected: 맨 위에 `봇 지침: …` 한 줄이 찍히고, `fallback 10/10 · 대조군 3/3` 이 **유지된다.**

| 결과 | 해석과 다음 행동 |
|---|---|
| 10/10 · 3/3 유지 + `봇 지침: 없음` | 정상. **"지침이 없어서 결과가 같았다"** 를 PR 본문에 명시한다 |
| 10/10 · 3/3 유지 + `봇 지침: 있음` | 정상. 지침이 있는데도 방어선이 버텼다 = 더 강한 결과다 |
| 숫자가 떨어짐 | 🔴 **버그가 아니라 발견이다.** 봇 지침이 실제로 방어선을 약화시키고 있다는 뜻이다. **멈추고 사람에게 보고한다** — 그 사실 자체가 이 수정의 가치다 |

- [ ] **Step 7: 커밋하고 PR을 연다**

```bash
git add ai-service/app/fallback_e2e_check.py
git commit -m "$(cat <<'EOF'
fix: W1 fallback 검사가 프로덕션과 같은 프롬프트를 태우게 했다

이 검사는 "1차·2차 방어선이 함께 걸린다" 고 주장하면서 봇 지침을 태우지 않았다.
main.chat 과 evalrun._execute 는 둘 다 build_system_prompt(fetch_bot_prompt(...)) 를 쓴다.

2026-08-13 실측으로 봇 지침 하나에 fallback 판정이 뚫린다는 것이 확인돼 있다.
그런 지침이 설정된 봇에서도 이 검사는 기본 프롬프트로 돌아 10/10 을 찍는다 —
W1 완료 조건이 통과했다고 보고하는데 제품은 뚫려 있는 상태가 된다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
git push -u origin fix/fallback-check-prompt
gh pr create --title "fix: W1 fallback 검사가 봇 지침을 태우지 않던 것" --body "$(cat <<'EOF'
## 무엇을 왜 바꿨나요

`fallback_e2e_check.py` 는 파일 첫머리에서 **"1차·2차 방어선이 함께 걸린다"** 고 주장하지만,
실제로는 **봇 지침을 태우지 않았습니다.**

```python
answer, is_fallback = generate(question, sources)   # system_prompt 없음 → 기본 SYSTEM_PROMPT
```

프로덕션 두 경로는 모두 결합합니다:
- `main.chat` → `system_prompt=build_system_prompt(fetch_bot_prompt(req.bot_id))`
- `evalrun._execute` → 같은 결합

**왜 위험한가.** AGENTS.md 와 `bot_prompt_check.py` 가 **2026-08-13 실측으로 기록해둔 사실**이 있습니다 —
봇 지침 하나로 fallback 판정이 실제로 뚫립니다. 지침 *"모르는 것도 아는 척 답해"* 를 넣으니
근거 없는 질문에 `is_fallback=False` 로 답했습니다.

**실패 시나리오:** 그 봇의 `system_prompt` 에 그런 문구가 들어간다 → 실제 채팅은 뚫린다 →
그런데 이 검사는 **`fallback 10/10 · 대조군 3/3` 을 찍습니다.**
**W1 완료 조건이 통과했다고 보고하는데 제품은 뚫려 있습니다.**

## 어떻게 해결했나요

`build_system_prompt(fetch_bot_prompt(BOT_ID))` 를 루프 밖에서 한 번 읽어 `generate` 호출 세 곳에 넘깁니다.
(루프 안에서 읽으면 도중에 설정이 바뀔 때 앞뒤 질문이 다른 프롬프트로 판정돼 측정이 섞입니다)
출력 맨 위에 지침 유무를 한 줄 찍어, 결과를 볼 때 어떤 조건에서 잰 것인지 알 수 있게 했습니다.

<!-- 실제 실행 결과를 여기에 붙일 것: Step 2 의 before 출력과 Step 6 의 after 출력 -->

## 한계 & 트레이드오프

- 🔴 **검사가 봇의 현재 설정에 의존하게 됩니다.** 지침을 바꾸면 이 검사 결과도 바뀝니다 —
  그게 의도입니다(프로덕션이 그렇게 동작합니다). 대신 **"코퍼스가 같으면 결과가 같다" 는 성질을 잃습니다.**
  결과를 비교할 때 지침도 함께 기록해야 합니다. 그래서 출력에 지침 유무를 찍습니다.
- **`bot_prompt_check` 를 대체하지 않습니다.** 그쪽은 검색을 뺀 프롬프트 전용 도구라 역할이 다릅니다.
  봇 지침을 바꾼 뒤에는 둘 다 돌리는 것이 운영 절차입니다.
- 이 수정은 **방어선을 강화하지 않습니다.** 방어선이 실제로 얼마나 강한지 **정직하게 재게** 할 뿐입니다.

## 검토한 대안

- **검사에 일부러 뚫는 지침을 넣어 돌리기** — 그건 `bot_prompt_check` 가 이미 하는 일입니다.
  이 검사의 역할은 **"지금 이 봇의 실제 설정에서" 방어선이 서 있는가** 입니다.
- **그대로 두기** — 이 검사의 결과가 W1 완료 조건의 근거로 AGENTS.md 에 인용되고 있어,
  틀린 조건에서 잰 숫자를 계속 인용하게 됩니다.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## 실행 순서

다섯 Task는 **파일을 공유하지 않으므로 병렬로 실행할 수 있다.** 다만 두 가지를 지킨다.

1. **Task 5는 Cloudflare 뉴런을 쓴다** (검사 1회 ≈ 26회 호출). Task 2·4는 안 쓴다.
   한도가 빠듯하면 Task 5를 마지막에 돌린다.
2. **Task 1과 Task 3은 둘 다 `./gradlew test` 를 돌린다.** 같은 머신에서 동시에 돌리면
   Testcontainers 가 포트를 다투거나 Docker 가 느려질 수 있다. 순차로 돌리는 편이 빠를 수 있다.

## 멈춰야 하는 지점 — 사람에게 보고할 것

| Task | 조건 |
|---|---|
| 3 | Step 2 의 grep 에서 `list_eval_results` 호출부가 하나라도 나오면 |
| 4 | Step 6 의 대조에서 **다른 파일이 하나라도 나오면** (재임베딩·재측정은 별도 결정) |
| 5 | Step 2 에서 Cloudflare 429 가 나거나, Step 6 에서 숫자가 떨어지면 |
| 전부 | 기존 테스트·검사가 깨지면 |

## 머지 후 (이 계획의 범위 밖 — 사람이 한다)

`docs/decisions.md` 에 3줄을 추가한다.

```
2026-09-03 | 위젯 rate limit 의 클라이언트 IP 를 Caddy 가 덮어쓰게 했다 | XFF 는 클라이언트가 위조할 수 있고 Caddy 기본값은 잇기라 위조값이 맨 앞에 남는다 | Spring 에서 맨 뒤 항목 읽기(프록시 1단 전제라 직접 노출 시 다시 뚫림)
2026-09-03 | 채점 실패를 partial 로 갈랐다 | fallback 과 뭉개지면 "충실성 0점" 으로 환산되는데 실행은 completed 로 남아 거짓 측정이 된다 | 사유 컬럼 추가(지금 필요한 신호는 "쓰면 안 된다" 하나)
2026-09-03 | /internal 문서 삭제 경로에 bot_id 를 넣었다 | 격리가 Spring 한 겹이었고 삭제는 CASCADE 라 되돌릴 수 없다 | Python 에서 소유권 조회 후 검사(빠뜨려도 통과하므로 조회 조건에 못박는다)
```

그리고 `AGENTS.md` 의 "낸 버그 4건" 표에 **다섯 번째 줄**을 추가한다 — Task 2 가 그 부류다.

```
| judge 실패를 fallback 과 같은 값으로 (2026-09-03) | "못 답했다" 와 <"재지 못했다"> 를 뭉갰다. 전체 충실성이 avg × scored / total 이라 채점 실패가 0점으로 환산됐다 |
```
