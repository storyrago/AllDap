package com.alldap.api.domain.billing;

import com.alldap.api.domain.auth.dto.SignupRequest;
import com.alldap.api.domain.user.repository.UserRepository;
import com.alldap.api.support.IntegrationTest;
import com.alldap.api.support.TossStub;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.client.EntityExchangeResult;
import org.springframework.test.web.servlet.client.RestTestClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 결제 수단 등록·조회 통합 테스트. (삭제는 Task 3)
 *
 * <p><b>여기서 지키려는 주장은 네 개다.</b> 나머지는 배관이다.
 * <ul>
 *   <li>DB 에 <b>평문 빌링키가 없다</b> — 이 조각의 존재 이유</li>
 *   <li>어떤 응답 본문에도 <b>빌링키가 없다</b> — DTO 에 필드를 두지 않은 것의 실증</li>
 *   <li>쿼리로 온 {@code customerKey} 를 <b>신뢰하지 않는다</b> — 신뢰하면 남의 계정에 카드가 붙는다</li>
 *   <li>연결이 끊기면 <b>같은 멱등키로</b> 재시도한다 — 다른 키로 재시도하면 회수 불가능한 고아가 하나 더 는다</li>
 * </ul>
 *
 * <p>진짜 톰캣 + 진짜 PostgreSQL + {@link TossStub}(진짜 HTTP) 위에서 돈다.
 * Mockito 로 {@code TossClient} 를 흉내내면 "우리가 상상한 예외" 만 검증하게 된다 —
 * 이 저장소는 <b>통합 테스트 71건이 전부 초록불인 상태에서</b> HTTP/2 업그레이드 버그와
 * iframe Origin 버그를 놓친 적이 있다. HTTP 경계는 HTTP 로만 검증된다.
 */
@IntegrationTest
@DisplayName("결제 수단 통합 테스트")
class BillingIntegrationTest {

    private static final String PASSWORD = "correct-password-1234";

    /** 토스가 돌려주는 빌링키. 이 문자열이 DB·응답 어디에도 <그대로> 나오면 안 된다. */
    private static final String 빌링키 = "iQ4y9sTrKp2mBillingKeySecret0001";

    /**
     * 토스 발급 성공 응답. <b>일부러 우리 DTO 에 없는 필드를 잔뜩 넣었다</b> —
     * {@code mId}·{@code method}·{@code authenticatedAt}·{@code card.cardType} 등.
     * 토스 문서가 "하위호환을 위해 모르는 필드는 무시하라" 고 권고하므로, 그게 실제로
     * 되는지를 테스트가 못박는다. (Jackson 3 은 FAIL_ON_UNKNOWN_PROPERTIES 가 기본 off 다)
     *
     * <p>⚠️ {@code cardCompany}·{@code cardNumber} 는 <b>일부러 넣지 않았다.</b>
     * 2024-06-01 버전부터 응답에서 제거된 필드라, 그걸 읽는 코드는 운영에서 NPE 가 난다.
     */
    private static final String 발급성공 = """
            {"mId":"tosspayments","customerKey":"%s","authenticatedAt":"2026-09-06T14:03:11+09:00",
             "method":"카드","billingKey":"%s",
             "card":{"issuerCode":"61","acquirerCode":"61","number":"43301234****123*",
                     "cardType":"신용","ownerType":"개인"}}""";

    /** 토스 v1 에러 본문. {@code {"code","message","data"}} 모양이다. */
    private static final String 발급거절 = """
            {"code":"INVALID_CARD_EXPIRATION",
             "message":"카드 유효기간이 올바르지 않습니다.","data":null}""";

    @LocalServerPort
    private int port;

    @Autowired
    private UserRepository userRepository;

    @Autowired
    private TossStub tossStub;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    private RestTestClient client;
    private String ownerToken;
    private UUID userId;
    private String customerKey;

    @BeforeEach
    void setUp() {
        client = RestTestClient.bindToServer().baseUrl("http://localhost:" + port).build();

        // billing_methods 는 ON DELETE CASCADE 라 이 한 줄로 함께 지워진다.
        userRepository.deleteAll();

        // ⚠️ 스텁 정리를 빠뜨리면 "실행 순서에 따라 나타났다 사라지는" 실패가 난다.
        //    이 저장소가 AiServiceStub 에서 이미 두 번 겪은 부류다.
        tossStub.reset();

        ownerToken = signup("owner@example.com");
        userId = userRepository.findByEmail("owner@example.com").orElseThrow().getId();
        customerKey = customerKeyOf(userId);
    }

    @Test
    @DisplayName("[결제] 카드를 등록하면 카드사 이름·마스킹 번호·등록일이 돌아온다")
    void 카드_등록_성공() {
        tossStub.enqueue(200, 발급성공.formatted(customerKey, 빌링키));

        Response 응답 = post(ownerToken, customerKey, "auth-key-1");

        assertThat(응답.status()).isEqualTo(200);
        JsonNode json = 응답.json();
        assertThat(json.path("customerKey").asString()).isEqualTo(customerKey);
        // issuerCode "61" → "현대". 코드→이름 변환이 Spring 책임이라는 것을 여기서 못박는다.
        assertThat(json.path("method").path("issuerName").asString()).isEqualTo("현대");
        assertThat(json.path("method").path("cardNumberMasked").asString()).isEqualTo("43301234****123*");
        // KST 오프셋으로 직렬화된다 — UsageResponse.periodStart 와 같은 규칙이다.
        assertThat(json.path("method").path("registeredAt").asString()).endsWith("+09:00");

        // 우리가 실제로 보낸 요청도 확인한다. 헤더는 소문자로 정규화돼 있다.
        List<TossStub.Recorded> 보낸것 = tossStub.received();
        assertThat(보낸것).hasSize(1);
        assertThat(보낸것.getFirst().path()).isEqualTo("/v1/billing/authorizations/issue");
        assertThat(보낸것.getFirst().body()).contains(customerKey).contains("auth-key-1");
        assertThat(보낸것.getFirst().header("idempotency-key")).isNotBlank();
        // Basic base64(secretKey + ":") — 콜론이 빠지면 토스가 INCORRECT_BASIC_AUTH_FORMAT 을 준다.
        String 인증 = 보낸것.getFirst().header("authorization");
        assertThat(인증).startsWith("Basic ");
        assertThat(new String(Base64.getDecoder().decode(인증.substring(6)), StandardCharsets.UTF_8))
                .endsWith(":");
    }

    @Test
    @DisplayName("[결제] DB 에 평문 빌링키가 저장되지 않는다 (이 조각의 존재 이유)")
    void 저장된_빌링키는_평문이_아니다() {
        tossStub.enqueue(200, 발급성공.formatted(customerKey, 빌링키));
        post(ownerToken, customerKey, "auth-key-1");

        String 저장값 = jdbcTemplate.queryForObject(
                "SELECT billing_key_enc FROM billing_methods WHERE user_id = ?", String.class, userId);

        assertThat(저장값).isNotBlank().doesNotContain(빌링키);
        // 🔴 Base64 를 한 번 풀어서도 확인한다. 인코딩만 해두고 "암호화했다" 고 부르는 사고를 막는다.
        assertThat(new String(Base64.getDecoder().decode(저장값), StandardCharsets.UTF_8))
                .doesNotContain(빌링키);
    }

    @Test
    @DisplayName("[결제] 어떤 응답 본문에도 빌링키가 실리지 않는다")
    void 응답에는_빌링키가_없다() {
        tossStub.enqueue(200, 발급성공.formatted(customerKey, 빌링키));

        assertThat(post(ownerToken, customerKey, "auth-key-1").body()).doesNotContain(빌링키);
        assertThat(get(ownerToken).body()).doesNotContain(빌링키);
    }

    @Test
    @DisplayName("[보안] 남의 customerKey 를 실어 보내면 400 이고 토스를 부르지 않는다")
    void 남의_customerKey_는_거부한다() {
        String 남의키 = customerKeyOf(userRepository.findByEmail(signupAndReturnEmail()).orElseThrow().getId());

        Response 응답 = post(ownerToken, 남의키, "auth-key-1");

        assertThat(응답.status()).isEqualTo(400);
        assertThat(응답.json().path("error").path("code").asString()).isEqualTo("INVALID_INPUT");
        // 🔴 "400 이 났다" 가 아니라 <요청이 토스까지 가지 않았다> 를 확인한다.
        //    소유권 판단이 외부 호출 <전에> 끝나야 한다는 이 저장소의 규칙 그대로다.
        assertThat(tossStub.received()).isEmpty();
    }

    @Test
    @DisplayName("[결제] 이미 카드가 있으면 409 다 (계정당 1장)")
    void 이미_등록된_카드가_있으면_409() {
        tossStub.enqueue(200, 발급성공.formatted(customerKey, 빌링키));
        post(ownerToken, customerKey, "auth-key-1");

        Response 두번째 = post(ownerToken, customerKey, "auth-key-2");

        assertThat(두번째.status()).isEqualTo(409);
        assertThat(두번째.json().path("error").path("code").asString())
                .isEqualTo("BILLING_METHOD_ALREADY_EXISTS");
        // 두 번째는 토스를 부르지 않았어야 한다 — 불렀다면 회수 못 하는 고아 빌링키가 생긴다.
        assertThat(tossStub.received()).hasSize(1);
    }

    @Test
    @DisplayName("[결제] 토스가 카드를 거절하면 400 이고 토스의 한국어 문구가 그대로 실린다")
    void 토스가_거절하면_400_에_토스_메시지가_실린다() {
        tossStub.enqueue(400, 발급거절);

        Response 응답 = post(ownerToken, customerKey, "auth-key-1");

        assertThat(응답.status()).isEqualTo(400);
        assertThat(응답.json().path("error").path("code").asString()).isEqualTo("BILLING_AUTH_FAILED");
        // 🔴 우리 기본 문구로 뭉개면 사용자가 <다음에 뭘 해야 하는지> 를 잃는다.
        //    문서 업로드에서 Python 의 ParseError 문구를 그대로 내려보내는 것과 같은 규칙이다.
        assertThat(응답.json().path("error").path("message").asString())
                .isEqualTo("카드 유효기간이 올바르지 않습니다.");
    }

    @Test
    @DisplayName("[결제] 토스가 5xx 면 503 이고 재시도하지 않는다")
    void 토스가_5xx_면_503() {
        tossStub.enqueue(500, "{\"code\":\"FAILED_INTERNAL_SYSTEM_PROCESSING\",\"message\":\"내부 오류\"}");

        Response 응답 = post(ownerToken, customerKey, "auth-key-1");

        assertThat(응답.status()).isEqualTo(503);
        assertThat(응답.json().path("error").path("code").asString())
                .isEqualTo("BILLING_PROVIDER_UNAVAILABLE");
        // 🔴 5xx 는 <토스가 응답했다> = 요청이 도달했다는 뜻이다. 발급이 됐을 수도 있으므로
        //    자동으로 다시 보내지 않는다. 재시도는 I/O 실패에만 한다(아래 테스트).
        assertThat(tossStub.received()).hasSize(1);
    }

    @Test
    @DisplayName("[결제] 연결이 끊기면 <같은 멱등키로> 한 번만 재시도한다")
    void 연결이_끊기면_같은_멱등키로_재시도한다() {
        tossStub.enqueueAbort();                                   // 1회차: 응답 없이 끊김
        tossStub.enqueue(200, 발급성공.formatted(customerKey, 빌링키)); // 2회차: 성공

        Response 응답 = post(ownerToken, customerKey, "auth-key-1");

        assertThat(응답.status()).isEqualTo(200);
        List<TossStub.Recorded> 보낸것 = tossStub.received();
        assertThat(보낸것).hasSize(2);
        // 🔴 이 한 줄이 이 기능의 전부다. 다른 키로 재시도하면 토스는 <두 번째 빌링키>를 발급하고,
        //    조회 API 가 없어서 그 고아를 영원히 회수할 수 없다.
        assertThat(보낸것.get(0).header("idempotency-key"))
                .isEqualTo(보낸것.get(1).header("idempotency-key"));
    }

    @Test
    @DisplayName("[결제] 카드가 없어도 customerKey 는 내려온다 (결제창을 열려면 필요하다)")
    void 카드가_없으면_method_는_null_이다() {
        Response 응답 = get(ownerToken);

        assertThat(응답.status()).isEqualTo(200);
        assertThat(응답.json().path("customerKey").asString()).isEqualTo(customerKey);
        // 필드가 <있고 값이 null> 이어야 한다. 통째로 빠지면 프론트가 "아직 안 불러온 것" 과 구별 못 한다.
        assertThat(응답.json().path("method").isNull()).isTrue();
    }

    @Test
    @DisplayName("[보안] 남의 결제 수단이 내 조회에 섞이지 않는다")
    void 남의_카드는_내_조회에_안_섞인다() {
        tossStub.enqueue(200, 발급성공.formatted(customerKey, 빌링키));
        post(ownerToken, customerKey, "auth-key-1");

        String 침입자 = signup("intruder@example.com");
        Response 응답 = get(침입자);

        assertThat(응답.status()).isEqualTo(200);
        assertThat(응답.json().path("method").isNull()).isTrue();
        // customerKey 도 자기 것이어야 한다 — 남의 것을 받으면 남의 계정에 카드를 붙일 수 있다.
        assertThat(응답.json().path("customerKey").asString()).isNotEqualTo(customerKey);
    }

    // ── 테스트 보조 ──────────────────────────────────────────────────────

    private String customerKeyOf(UUID userId) {
        return jdbcTemplate.queryForObject(
                "SELECT billing_customer_key FROM users WHERE id = ?", String.class, userId);
    }

    private Response post(String token, String customerKey, String authKey) {
        return request(HttpMethod.POST, "/api/billing/method", token,
                Map.of("authKey", authKey, "customerKey", customerKey));
    }

    private Response get(String token) {
        return request(HttpMethod.GET, "/api/billing/method", token, null);
    }

    private String signup(String email) {
        return request(HttpMethod.POST, "/api/auth/signup", null,
                new SignupRequest(email, PASSWORD, null)).json().path("token").asString();
    }

    /** 남의 customerKey 를 얻기 위한 계정 하나. 토큰은 쓰지 않는다. */
    private String signupAndReturnEmail() {
        signup("stranger@example.com");
        return "stranger@example.com";
    }

    private Response request(HttpMethod method, String uri, String token, Object body) {
        var spec = client.method(method).uri(uri);
        if (token != null) {
            spec.header(HttpHeaders.AUTHORIZATION, "Bearer " + token);
        }
        // GET 에는 본문을 붙이지 않는다. 강제로 붙이면 본문 없는 GET 을 표현할 수 없다.
        EntityExchangeResult<byte[]> result = (body == null
                ? spec
                : spec.contentType(MediaType.APPLICATION_JSON).body(body))
                .exchange().expectBody().returnResult();
        return new Response(result.getStatus().value(), decode(result.getResponseBody()));
    }

    private record Response(int status, String body) {
        JsonNode json() {
            return JSON.readTree(body);
        }
    }

    private static final ObjectMapper JSON = new ObjectMapper();

    private static String decode(byte[] raw) {
        return raw == null ? "" : new String(raw, StandardCharsets.UTF_8);
    }
}
