package com.alldap.api.domain.auth;

import com.alldap.api.domain.auth.dto.LoginRequest;
import com.alldap.api.domain.auth.dto.SignupRequest;
import com.alldap.api.domain.user.repository.UserRepository;
import com.alldap.api.global.ratelimit.RateLimiter;
import com.alldap.api.support.IntegrationTest;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.web.servlet.client.EntityExchangeResult;
import org.springframework.test.web.servlet.client.RestTestClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.nio.charset.StandardCharsets;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 인증(가입·로그인·토큰 검증) 통합 테스트.
 *
 * <p>진짜 톰캣 + 진짜 PostgreSQL(Testcontainers) 위에서 실제 HTTP 로 검증한다.
 * 서비스 계층만 단위 테스트하면 <b>Security 필터 체인</b>(401 응답 포맷, JWT 필터)이 통째로 빠지는데,
 * 이 클래스가 지키려는 규칙의 절반이 바로 그 구간에 있다.
 *
 * <p>여기서 검증하는 것은 "기능이 돈다"가 아니라 <b>깨지면 안 되는 보안 규칙</b>이다.
 * <ol>
 *   <li>응답에 비밀번호(평문·해시)가 절대 실리지 않는다</li>
 *   <li>로그인 실패 응답이 "가입 여부"를 흘리지 않는다 — 없는 이메일과 틀린 비밀번호가 <b>구별 불가능</b>해야 한다</li>
 *   <li>인증 실패도 PRD §10.3 공통 에러 포맷을 지킨다 (프론트 {@code ApiErrorBody} 계약)</li>
 *   <li>비밀번호는 DB 에 해시로만 남는다</li>
 * </ol>
 */
@IntegrationTest
@DisplayName("인증 API 통합 테스트")
class AuthIntegrationTest {

    private static final String PASSWORD = "correct-password-1234";
    private static final String EMAIL = "tester@example.com";

    /**
     * {@code @IntegrationTest} 가 RANDOM_PORT 로 띄운 톰캣의 실제 포트.
     * 포트를 고정하지 않는 이유는 {@link IntegrationTest} 주석 참고.
     */
    @LocalServerPort
    private int port;

    /**
     * Spring Boot 4 가 자동 구성하는 <b>Jackson 3</b> 매퍼.
     * ⚠️ {@code com.fasterxml.jackson.databind.ObjectMapper}(Jackson 2)가 아니다 —
     * Jackson 3 에서 databind 패키지가 {@code tools.jackson.databind} 로 옮겨졌다.
     * (운영 코드 {@code ErrorResponseWriter} 도 같은 타입을 주입받는다)
     */
    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private UserRepository userRepository;

    /**
     * 비밀번호가 <b>DB 컬럼에</b> 어떻게 저장됐는지 확인하려고 쓴다.
     * 엔티티({@code User.getPasswordHash()})로 읽으면 JPA 를 한 번 거치므로
     * "정말 그 값이 테이블에 들어갔는가"를 보는 것과는 조금 다르다.
     * 검증 대상이 저장 그 자체이므로 SQL 로 원본 컬럼을 직접 읽는다.
     */
    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Autowired
    private PasswordEncoder passwordEncoder;

    @Autowired
    RateLimiter rateLimiter;

    private RestTestClient client;

    @BeforeEach
    void setUp() {
        // RestTestClient 는 Spring Framework 7 의 테스트용 HTTP 클라이언트다.
        // 4xx/5xx 에서 예외를 던지지 않아 "에러 응답 본문"을 검증하기에 알맞다
        // (RestClient/RestTemplate 은 기본적으로 4xx 에서 예외를 던져 본문 검증이 번거롭다).
        client = RestTestClient.bindToServer()
                .baseUrl("http://localhost:" + port)
                .build();

        // 컨테이너(=DB)는 여러 테스트가 공유한다. RANDOM_PORT 로 띄운 실제 서버에 HTTP 로 요청하므로
        // 테스트 메서드의 트랜잭션 롤백(@Transactional)이 통하지 않는다 —
        // 요청을 처리하는 스레드가 테스트 스레드와 다르기 때문이다.
        // 그래서 상태를 남기지 않으려면 이렇게 직접 지워야 한다.
        userRepository.deleteAll();

        // 🔴 RateLimiter 는 <상태를 가진 싱글턴>이다. 안 비우면 앞 테스트의 로그인 호출이
        //    카운터에 남아, 실행 순서에 따라 나타났다 사라지는 실패가 난다.
        //    (DocumentIntegrationTest 가 circuitBreaker.reset() 을 부르는 것과 같은 이유)
        rateLimiter.reset();
    }

    // ── 가입 ────────────────────────────────────────────────────────────

    @Test
    @DisplayName("가입에 성공하면 201 과 함께 토큰이 발급되고, 응답에는 비밀번호가 어떤 형태로도 실리지 않는다")
    void 가입_성공() {
        Response response = post("/api/auth/signup", new SignupRequest(EMAIL, PASSWORD, "테스터"));

        assertThat(response.status()).isEqualTo(201);

        JsonNode body = response.json();
        assertThat(body.path("token").asString()).isNotBlank();
        assertThat(body.path("user").path("email").asString()).isEqualTo(EMAIL);
        assertThat(body.path("user").path("name").asString()).isEqualTo("테스터");
        assertThat(body.path("user").path("id").asString()).isNotBlank();

        // 응답 본문 전체를 문자열로 훑는다. 필드 하나씩 확인하면
        // "나중에 누가 필드를 추가했을 때" 놓친다. 여기서 막고 싶은 건 그 미래의 실수다.
        assertThat(response.body())
                .doesNotContain(PASSWORD)      // 평문
                .doesNotContain("password")    // passwordHash 등 어떤 이름으로든
                .doesNotContain("$2a$");       // BCrypt 해시 접두사
    }

    @Test
    @DisplayName("이미 가입된 이메일로 다시 가입하면 409 EMAIL_ALREADY_EXISTS 로 거절한다")
    void 가입_이메일_중복() {
        post("/api/auth/signup", new SignupRequest(EMAIL, PASSWORD, "먼저"));

        Response response = post("/api/auth/signup", new SignupRequest(EMAIL, "another-password-1234", "나중"));

        assertThat(response.status()).isEqualTo(409);
        assertThat(response.json().path("error").path("code").asString()).isEqualTo("EMAIL_ALREADY_EXISTS");
        // 사용자에게 "다음에 뭘 하면 되는지"까지 알려주는지 확인한다(CLAUDE.md 작업 규칙 4).
        assertThat(response.json().path("error").path("message").asString()).contains("로그인");
    }

    // ── 로그인 ──────────────────────────────────────────────────────────

    @Test
    @DisplayName("가입한 계정으로 로그인하면 200 과 함께 토큰이 발급된다")
    void 로그인_성공() {
        post("/api/auth/signup", new SignupRequest(EMAIL, PASSWORD, "테스터"));

        Response response = post("/api/auth/login", new LoginRequest(EMAIL, PASSWORD));

        assertThat(response.status()).isEqualTo(200);
        assertThat(response.json().path("token").asString()).isNotBlank();
        assertThat(response.json().path("user").path("email").asString()).isEqualTo(EMAIL);
    }

    @Test
    @DisplayName("[보안] 없는 이메일로 로그인한 응답과 비밀번호가 틀린 응답이 상태코드·본문까지 완전히 같다")
    void 로그인_실패_응답이_가입여부를_흘리지_않는다() {
        post("/api/auth/signup", new SignupRequest(EMAIL, PASSWORD, "테스터"));

        Response 없는이메일 = post("/api/auth/login", new LoginRequest("nobody@example.com", PASSWORD));
        Response 틀린비밀번호 = post("/api/auth/login", new LoginRequest(EMAIL, "wrong-password-1234"));

        // 둘 중 하나라도 다르면 로그인 폼이 "이 이메일 가입돼 있나요?" 조회 도구가 된다.
        assertThat(없는이메일.status()).isEqualTo(401);
        assertThat(틀린비밀번호.status()).isEqualTo(401);
        assertThat(없는이메일.body()).isEqualTo(틀린비밀번호.body());
        assertThat(없는이메일.json().path("error").path("code").asString()).isEqualTo("INVALID_CREDENTIALS");
    }

    // ── 보호 경로 · 토큰 검증 ────────────────────────────────────────────

    @Test
    @DisplayName("토큰 없이 보호 경로에 접근하면 401 이고, 본문이 공통 에러 포맷을 지킨다")
    void 토큰_없이_보호경로_접근() {
        Response response = get("/api/bots", null);

        assertThat(response.status()).isEqualTo(401);

        // 컨트롤러에 닿기 전에 Security 필터 체인이 끊은 요청이다.
        // @RestControllerAdvice 가 못 잡는 구간이라, 여기서 포맷이 깨지기 쉽다 —
        // 실제로 ApiAuthenticationEntryPoint 가 없으면 본문이 비어 나간다.
        JsonNode error = response.json().path("error");
        assertThat(error.isObject()).isTrue();
        assertThat(error.path("code").asString()).isEqualTo("AUTHENTICATION_REQUIRED");
        assertThat(error.path("message").asString()).isNotBlank();

        // 한글이 깨지지 않는지도 함께 본다. charset 을 빼먹으면 여기서 물음표가 나온다.
        assertThat(error.path("message").asString()).contains("로그인");
    }

    @Test
    @DisplayName("서명이 조작된 토큰으로 접근하면 401 INVALID_TOKEN 으로 거절한다")
    void 조작된_토큰() {
        String token = post("/api/auth/signup", new SignupRequest(EMAIL, PASSWORD, "테스터"))
                .json().path("token").asString();

        // JWT 는 header.payload.signature 구조다. 서명 부분을 한 글자 바꾸면
        // "내용은 그럴듯한데 우리 키로 서명되지 않은" 위조 토큰이 된다.
        //
        // ⚠️ 바꿀 글자로 <마지막> 이 아니라 <서명의 첫> 글자를 고른 이유 (이것 때문에 CI 가 깨졌었다)
        //
        // HS256 서명은 32바이트 = 256비트인데, base64url 43자는 43 × 6 = 258비트를 담는다.
        // 남는 2비트는 디코딩할 때 그냥 버려진다. 즉 <마지막 글자는 4비트만 유효>하고,
        // 상위 4비트가 같은 글자끼리는 디코딩 결과가 완전히 같다.
        // 옛 코드는 마지막 글자를 'A'↔'B' 로 바꿨는데 'A'=0, 'B'=1 은 상위 4비트가 똑같아서,
        // 서명이 'A' 로 끝나면 <문자열만 달라지고 서명 바이트는 그대로>였다.
        // → 토큰이 정상 검증돼 401 이 나지 않는다. 16번에 1번(6.25%) 꼴로 실패하는 플래키 테스트였다.
        //
        // 서명의 첫 글자는 6비트가 전부 유효하므로, 바꾸면 반드시 서명 바이트가 달라진다.
        int signatureStart = token.lastIndexOf('.') + 1;
        String tampered = token.substring(0, signatureStart)
                + (token.charAt(signatureStart) == 'A' ? 'B' : 'A')
                + token.substring(signatureStart + 1);
        assertThat(tampered).isNotEqualTo(token).hasSameSizeAs(token);

        Response response = get("/api/bots", tampered);

        assertThat(response.status()).isEqualTo(401);
        // AUTHENTICATION_REQUIRED(토큰 없음)와 코드가 달라야
        // 프론트가 "저장된 토큰을 버리고 다시 로그인" 을 판단할 수 있다.
        assertThat(response.json().path("error").path("code").asString()).isEqualTo("INVALID_TOKEN");
    }

    // ── 저장 ────────────────────────────────────────────────────────────

    @Test
    @DisplayName("[보안] 비밀번호는 평문이 아니라 BCrypt 해시로 DB 에 저장된다")
    void 비밀번호는_해시로_저장된다() {
        post("/api/auth/signup", new SignupRequest(EMAIL, PASSWORD, "테스터"));

        String storedHash = jdbcTemplate.queryForObject(
                "SELECT password_hash FROM users WHERE email = ?", String.class, EMAIL);

        assertThat(storedHash).isNotNull();
        assertThat(storedHash).isNotEqualTo(PASSWORD);
        // BCrypt 해시는 "$2a$" / "$2b$" / "$2y$" + cost 로 시작한다.
        assertThat(storedHash).startsWith("$2");
        // 형식만 맞는 게 아니라 실제로 이 비밀번호의 해시가 맞는지까지 확인한다.
        assertThat(passwordEncoder.matches(PASSWORD, storedHash)).isTrue();
    }

    @Test
    @DisplayName("[보안] 한 IP 가 여러 계정을 훑으면 요청 수 제한이 429 로 막는다")
    void 로그인_요청수_제한() {
        // 테스트 컨텍스트의 요청 한도는 분당 6회 (TestcontainersConfiguration)
        //
        // 🔴 매번 <다른> 이메일을 쓰는 것이 이 테스트의 핵심이다.
        //    같은 이메일을 반복하면 (IP + 이메일) 실패 누적 제한이 먼저 걸려(한도 2)
        //    여기서 재려는 IP 요청 수 제한에 닿기도 전에 429 가 난다.
        //    이메일을 바꾸면 실패 카운터가 계정마다 흩어져 1 에 머무르므로, 남는 방어는 IP 요청 수뿐이다.
        //    (그리고 이게 실제 공격 모양이기도 하다: 계정 하나를 파고드는 대신 목록을 훑는 것)
        for (int i = 0; i < 6; i++) {
            Response 실패 = post("/api/auth/login",
                    new LoginRequest("nobody" + i + "@example.com", "wrong-password-1234"));
            assertThat(실패.status()).isEqualTo(401);
        }

        Response blocked = post("/api/auth/login",
                new LoginRequest("nobody6@example.com", "wrong-password-1234"));

        // 이 제한이 없으면 유일한 방어가 BCrypt 비용(약 100ms/회)뿐이라
        // 병렬 커넥션으로 분당 수천 회를 추측할 수 있다.
        assertThat(blocked.status()).isEqualTo(429);
        assertThat(blocked.json().path("error").path("code").asString())
                .isEqualTo("RATE_LIMIT_EXCEEDED");
    }

    @Test
    @DisplayName("[보안] 같은 계정에 실패가 쌓이면 비밀번호를 대조하기도 전에 429 로 끊는다")
    void 로그인_실패누적_제한() {
        post("/api/auth/signup", new SignupRequest(EMAIL, PASSWORD, "테스터"));

        // 테스트 컨텍스트의 실패 한도는 2회 (TestcontainersConfiguration)
        for (int i = 0; i < 2; i++) {
            assertThat(post("/api/auth/login", new LoginRequest(EMAIL, "wrong-password-1234")).status())
                    .isEqualTo(401);
        }

        Response blocked = post("/api/auth/login", new LoginRequest(EMAIL, "wrong-password-1234"));

        assertThat(blocked.status()).isEqualTo(429);
        assertThat(blocked.json().path("error").path("code").asString())
                .isEqualTo("TOO_MANY_LOGIN_FAILURES");
        // 사용자가 다음에 뭘 하면 되는지까지 알려주는지 확인한다(CLAUDE.md 작업 규칙 4).
        assertThat(blocked.json().path("error").path("message").asString()).contains("15분");

        // 🔴 가장 중요한 검증: 차단 중에는 <맞는 비밀번호도> 통과하지 못한다.
        //    실패를 센 뒤에 막는 구조였다면 공격자가 정답을 찾아낸 그 요청은 이미 통과한 뒤라
        //    방어가 아무것도 막지 못한다.
        Response 맞는비밀번호 = post("/api/auth/login", new LoginRequest(EMAIL, PASSWORD));
        assertThat(맞는비밀번호.status()).isEqualTo(429);
    }

    @Test
    @DisplayName("[보안] 실패 누적으로 차단된 응답도 가입 여부를 흘리지 않는다")
    void 차단_응답이_가입여부를_흘리지_않는다() {
        post("/api/auth/signup", new SignupRequest(EMAIL, PASSWORD, "테스터"));

        Response 가입된계정_차단 = 실패를_쌓아_차단시킨다(EMAIL);

        // 카운터를 비워 두 번째 절반을 첫 절반과 똑같은 조건에서 재현한다.
        // (IP 요청 수 한도까지 초기화되므로 뒤 절반이 앞 절반 때문에 막히지 않는다)
        rateLimiter.reset();

        Response 없는계정_차단 = 실패를_쌓아_차단시킨다("nobody@example.com");

        // 하나라도 다르면 "몇 번 만에, 어떤 응답으로 막히는가" 가 가입 여부를 알려주게 된다.
        // 응답 본문만 통일하고 <차단되는 시점>이 갈려도 마찬가지로 새는 것이라, 둘 다 3번째에 막혀야 한다.
        assertThat(가입된계정_차단.status()).isEqualTo(429);
        assertThat(없는계정_차단.status()).isEqualTo(429);
        assertThat(가입된계정_차단.body()).isEqualTo(없는계정_차단.body());
    }

    @Test
    @DisplayName("로그인에 성공하면 그동안 쌓인 실패가 지워진다 (연속 실패만 의심한다)")
    void 로그인_성공하면_실패누적이_지워진다() {
        post("/api/auth/signup", new SignupRequest(EMAIL, PASSWORD, "테스터"));

        assertThat(post("/api/auth/login", new LoginRequest(EMAIL, "wrong-password-1234")).status())
                .isEqualTo(401);
        assertThat(post("/api/auth/login", new LoginRequest(EMAIL, PASSWORD)).status())
                .isEqualTo(200);

        // 누적이 지워지지 않았다면 이 두 번째 실패에서 카운터가 2 에 닿아
        // 마지막 요청이 429 가 된다. 401 이 나온다는 것이 곧 지워졌다는 증거다.
        assertThat(post("/api/auth/login", new LoginRequest(EMAIL, "wrong-password-1234")).status())
                .isEqualTo(401);
        assertThat(post("/api/auth/login", new LoginRequest(EMAIL, "wrong-password-1234")).status())
                .isEqualTo(401);
    }

    /** 한도(2회)까지 실패를 쌓은 뒤, 차단된 세 번째 응답을 돌려준다. */
    private Response 실패를_쌓아_차단시킨다(String email) {
        for (int i = 0; i < 2; i++) {
            post("/api/auth/login", new LoginRequest(email, "wrong-password-1234"));
        }
        return post("/api/auth/login", new LoginRequest(email, "wrong-password-1234"));
    }

    // ── 테스트 보조 ──────────────────────────────────────────────────────

    /**
     * 한 번의 HTTP 교환 결과.
     *
     * @param status HTTP 상태 코드
     * @param body   응답 본문 (UTF-8 로 디코딩한 문자열)
     */
    private record Response(int status, String body) {

        JsonNode json() {
            return JSON.readTree(body);
        }
    }

    /**
     * {@link Response#json()} 이 쓰는 매퍼.
     *
     * <p>record 는 인스턴스 필드를 가질 수 없어(=컴포넌트만 필드가 된다)
     * 주입받은 {@code objectMapper} 를 쓸 수 없다. 파싱만 하는 용도라 기본 매퍼로 충분하다.
     */
    private static final ObjectMapper JSON = new ObjectMapper();

    /** 요청 본문은 운영 DTO({@code SignupRequest} 등)를 그대로 쓴다 — API 계약이 바뀌면 테스트가 컴파일 단계에서 깨지도록. */
    private Response post(String uri, Object body) {
        EntityExchangeResult<byte[]> result = client.post()
                .uri(uri)
                .contentType(MediaType.APPLICATION_JSON)
                .body(body)
                .exchange()
                .expectBody()          // 타입 지정 없이 받으면 원본 바이트가 그대로 담긴다
                .returnResult();

        return new Response(result.getStatus().value(), decode(result.getResponseBody()));
    }

    /** @param bearerToken null 이면 Authorization 헤더를 아예 붙이지 않는다(= 비로그인 요청) */
    private Response get(String uri, String bearerToken) {
        RestTestClient.RequestHeadersSpec<?> spec = client.get().uri(uri);
        if (bearerToken != null) {
            spec = spec.header(HttpHeaders.AUTHORIZATION, "Bearer " + bearerToken);
        }

        EntityExchangeResult<byte[]> result = spec.exchange().expectBody().returnResult();
        return new Response(result.getStatus().value(), decode(result.getResponseBody()));
    }

    /**
     * 응답 바이트를 <b>UTF-8 로 명시해</b> 문자열로 만든다.
     *
     * <p>{@code expectBody(String.class)} 를 쓰지 않는 이유:
     * {@code StringHttpMessageConverter} 는 응답 Content-Type 에 charset 이 없으면
     * 자체 기본 charset 으로 디코딩한다. 그러면 한국어 에러 메시지가 깨져
     * "코드는 멀쩡한데 테스트만 실패하는" 상황이 생긴다.
     * 바이트를 직접 받아 UTF-8 로 디코딩하면 그 변수를 없앨 수 있다.
     */
    private static String decode(byte[] raw) {
        return raw == null ? "" : new String(raw, StandardCharsets.UTF_8);
    }
}
