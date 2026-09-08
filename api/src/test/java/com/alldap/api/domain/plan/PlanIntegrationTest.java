package com.alldap.api.domain.plan;

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
import java.util.Map;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 요금제 조회·변경 통합 테스트 (요금제 연동 4조각 중 <b>2번</b>).
 *
 * <p><b>여기서 지키려는 주장은 넷이다.</b>
 * <ul>
 *   <li>새 계정은 <b>무료</b>다 — V8 의 DEFAULT 와 {@code User.create} 가 어긋나지 않는다</li>
 *   <li>🔴 <b>카드 없이 유료로 못 바꾼다.</b> 이 불변식의 나머지 반쪽(유료 상태의 마지막 카드
 *       삭제 거부)은 {@code BillingIntegrationTest} 에 있다 — 한쪽만 막으면 규칙이 없는 것과 같다</li>
 *   <li>같은 요금제를 다시 보내도 <b>200</b>이다 (PUT 은 멱등해야 한다)</li>
 *   <li>DB 에도 <b>소문자</b>로 저장된다 — "한 값은 어느 계층에서나 같은 모양" 이라는 주장의 실증</li>
 * </ul>
 *
 * <p>🔴 <b>이 조각에는 청구가 없다.</b> 그래서 "요금제를 바꿨더니 돈이 나갔다" 를 검사하는
 * 테스트도 없다 — 검사할 동작 자체가 아직 없기 때문이다. 4번 조각에서 생긴다.
 */
@IntegrationTest
@DisplayName("요금제 통합 테스트")
class PlanIntegrationTest {

    private static final String PASSWORD = "correct-password-1234";
    private static final String PLAN = "/api/plan";
    private static final String METHODS = "/api/billing/methods";

    /** 카드 등록용 토스 응답. 이 테스트의 관심사는 카드 <내용>이 아니라 <있느냐> 다. */
    private static final String 발급성공 = """
            {"billingKey":"plan-test-billing-key","card":{"issuerCode":"41","number":"55201234****4567"}}""";

    @LocalServerPort
    private int port;

    @Autowired
    private UserRepository userRepository;

    @Autowired
    private TossStub tossStub;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    private RestTestClient client;
    private String token;
    private UUID userId;

    @BeforeEach
    void setUp() {
        client = RestTestClient.bindToServer().baseUrl("http://localhost:" + port).build();
        userRepository.deleteAll();
        // ⚠️ 스텁 정리를 빠뜨리면 "실행 순서에 따라 나타났다 사라지는" 실패가 난다.
        tossStub.reset();

        token = signup("owner@example.com");
        userId = userRepository.findByEmail("owner@example.com").orElseThrow().getId();
    }

    @Test
    @DisplayName("[요금제] 새 계정은 무료다")
    void 새_계정은_무료다() {
        Response 응답 = request(HttpMethod.GET, PLAN, token, null);

        assertThat(응답.status()).isEqualTo(200);
        assertThat(응답.json().path("plan").asString()).isEqualTo("free");
    }

    @Test
    @DisplayName("[요금제] 🔴 카드가 없으면 유료로 못 바꾼다 (409)")
    void 카드가_없으면_유료로_못_바꾼다() {
        Response 응답 = 요금제변경("pro");

        assertThat(응답.status()).isEqualTo(409);
        assertThat(응답.json().path("error").path("code").asString())
                .isEqualTo("PLAN_REQUIRES_BILLING_METHOD");
        // 🔴 거절만 하고 끝이 아니라 <무엇을 하면 되는지> 까지 안내해야 한다(이 저장소의 에러 규칙).
        assertThat(응답.json().path("error").path("message").asString()).contains("카드를 등록");
        // 실패했으면 값이 안 바뀌어야 한다. "409 가 났다" 만 보면 반쪽 저장을 놓친다.
        assertThat(요금제_DB값()).isEqualTo("free");
    }

    @Test
    @DisplayName("[요금제] 카드를 등록하면 유료로 바꿀 수 있고, 같은 값을 다시 보내도 200 이다")
    void 카드가_있으면_유료로_바꾼다() {
        카드를_등록한다();

        Response 응답 = 요금제변경("pro");

        assertThat(응답.status()).isEqualTo(200);
        assertThat(응답.json().path("plan").asString()).isEqualTo("pro");
        assertThat(request(HttpMethod.GET, PLAN, token, null).json().path("plan").asString())
                .isEqualTo("pro");

        // PUT 은 멱등하다 — 사용자가 "Pro" 를 두 번 눌렀다고 오류를 볼 이유가 없다.
        assertThat(요금제변경("pro").status()).isEqualTo(200);
        assertThat(요금제_DB값()).isEqualTo("pro");

        // 무료로 되돌리는 데는 조건이 없다.
        assertThat(요금제변경("free").json().path("plan").asString()).isEqualTo("free");
    }

    @Test
    @DisplayName("[요금제] DB 에도 소문자로 저장된다 — 계층마다 표기가 갈리지 않는다")
    void DB에도_소문자로_저장된다() {
        카드를_등록한다();
        요금제변경("pro");

        // 🔴 @Enumerated(STRING) 이었다면 여기가 "PRO" 다. Plan.JpaConverter 가 있어서 소문자다.
        //    DB·JSON·프론트가 같은 문자열을 쓰는 것이 이 enum 의 설계 의도다.
        assertThat(요금제_DB값()).isEqualTo("pro");
    }

    @Test
    @DisplayName("[요금제] 모르는 요금제 문자열은 400 이고 값이 바뀌지 않는다")
    void 모르는_요금제는_400() {
        Response 응답 = 요금제변경("enterprise");

        assertThat(응답.status()).isEqualTo(400);
        // 🔴 조용히 free 로 떨어뜨리면 사용자는 "요금제를 바꿨는데 무료가 됐다" 를 겪는다.
        assertThat(요금제_DB값()).isEqualTo("free");
    }

    @Test
    @DisplayName("[요금제] 요금제를 비워 보내면 400 이다")
    void 요금제가_비면_400() {
        Response 응답 = request(HttpMethod.PUT, PLAN, token, Map.of());

        assertThat(응답.status()).isEqualTo(400);
        assertThat(요금제_DB값()).isEqualTo("free");
    }

    @Test
    @DisplayName("[보안] 남의 요금제가 내 조회에 섞이지 않는다")
    void 남의_요금제는_안_섞인다() {
        카드를_등록한다();
        요금제변경("pro");

        String 침입자 = signup("intruder@example.com");

        // 토큰의 주인 것만 본다 — userId 를 파라미터로 받지 않으므로 남의 것을 지정할 자리가 없다.
        assertThat(request(HttpMethod.GET, PLAN, 침입자, null).json().path("plan").asString())
                .isEqualTo("free");
    }

    @Test
    @DisplayName("[보안] 인증 없이는 조회도 변경도 못 한다")
    void 인증이_없으면_401() {
        assertThat(request(HttpMethod.GET, PLAN, null, null).status()).isEqualTo(401);
        assertThat(request(HttpMethod.PUT, PLAN, null, Map.of("plan", "pro")).status()).isEqualTo(401);
    }

    // ── 보조 ─────────────────────────────────────────────────────────────

    private void 카드를_등록한다() {
        tossStub.enqueue(200, 발급성공);
        String customerKey = jdbcTemplate.queryForObject(
                "SELECT billing_customer_key FROM users WHERE id = ?", String.class, userId);
        Response 응답 = request(HttpMethod.POST, METHODS, token,
                Map.of("authKey", "auth-" + UUID.randomUUID(), "customerKey", customerKey));
        assertThat(응답.status())
                .as("카드 등록이 먼저 성공해야 요금제 변경을 검사할 수 있다. 본문=%s", 응답.body())
                .isEqualTo(200);
    }

    private Response 요금제변경(String plan) {
        return request(HttpMethod.PUT, PLAN, token, Map.of("plan", plan));
    }

    /** 응답만 보면 직렬화 버그와 구별이 안 된다. 저장된 값을 <DB 에서 직접> 읽는다. */
    private String 요금제_DB값() {
        return jdbcTemplate.queryForObject("SELECT plan FROM users WHERE id = ?", String.class, userId);
    }

    private String signup(String email) {
        return request(HttpMethod.POST, "/api/auth/signup", null,
                new SignupRequest(email, PASSWORD, null)).json().path("token").asString();
    }

    private Response request(HttpMethod method, String uri, String token, Object body) {
        var spec = client.method(method).uri(uri);
        if (token != null) {
            spec.header(HttpHeaders.AUTHORIZATION, "Bearer " + token);
        }
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
