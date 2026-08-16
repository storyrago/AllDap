package com.alldap.api.domain.widget;

import com.alldap.api.global.client.AiServiceCircuitBreaker;
import com.alldap.api.domain.auth.dto.SignupRequest;
import com.alldap.api.domain.bot.dto.CreateBotRequest;
import com.alldap.api.domain.bot.dto.UpdateBotRequest;
import com.alldap.api.domain.chat.dto.ChatRequest;
import com.alldap.api.domain.user.repository.UserRepository;
import com.alldap.api.global.ratelimit.RateLimiter;
import com.alldap.api.support.AiServiceStub;
import com.alldap.api.support.IntegrationTest;
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
import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 위젯 공개 API 통합 테스트.
 *
 * <p><b>이 서비스에서 유일하게 인증 없이 열려 있는 문이라, 여기서 지키려는 것은 대부분 "막히는가" 다.</b>
 *
 * <ol>
 *   <li><b>기본값이 닫힘이다.</b> 봇을 막 만들면 허용 도메인이 비어 있는데, 그걸 "전부 허용" 으로
 *       해석하면 모든 신규 봇이 무방비로 태어난다. publicKey 는 고객 사이트 HTML 에 노출되므로
 *       누구나 복사해 자기 사이트에 붙일 수 있고 LLM 비용은 봇 주인이 낸다.</li>
 *   <li><b>내부 설정이 새지 않는다.</b> 이 응답은 아무나 볼 수 있다.</li>
 *   <li><b>요청 수 제한이 실제로 건다.</b> 채팅 한 번은 외부 LLM 호출 = 실제 돈이다.</li>
 * </ol>
 */
@IntegrationTest
@DisplayName("위젯 공개 API 통합 테스트")
class WidgetIntegrationTest {

    private static final String PASSWORD = "correct-password-1234";
    private static final String 고객사이트 = "https://customer.example.com";

    private static final String 정상응답 = """
            {"answer":"환불은 7일 이내에 가능합니다.",
             "sources":[{"chunk_id":"22222222-2222-2222-2222-222222222222",
                         "document_id":"33333333-3333-3333-3333-333333333333",
                         "filename":"환불규정.pdf","score":0.9,"preview":"환불은 7일 이내"}],
             "is_fallback":false,"latency_ms":800}""";

    private static final String 거절응답 = """
            {"answer":"문서에서 관련 내용을 찾지 못했습니다.","sources":[],
             "is_fallback":true,"latency_ms":100}""";

    @LocalServerPort
    private int port;

    @Autowired
    private UserRepository userRepository;

    @Autowired
    private AiServiceStub aiService;

    // 🔴 서킷브레이커는 <상태를 가진 싱글턴>이다. 리셋하지 않으면 5xx 를 내는
    //    테스트가 누적돼 서킷이 열리고, 이후 테스트가 전부 503 으로 깨진다.
    //    그것도 <실행 순서에 따라> 나타났다 사라진다 (AiServiceStub 의 executor 함정과 같은 부류).
    @Autowired
    AiServiceCircuitBreaker circuitBreaker;

    @Autowired
    private RateLimiter rateLimiter;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    private RestTestClient client;
    private String ownerToken;
    private UUID botId;
    private String publicKey;

    @BeforeEach
    void setUp() {
        client = RestTestClient.bindToServer().baseUrl("http://localhost:" + port).build();
        userRepository.deleteAll();
        aiService.reset();
        circuitBreaker.reset();
        // 제한기는 싱글턴이라 상태가 테스트 사이에 남는다. 안 비우면 뒤 테스트가 앞 테스트의 카운터를 물려받는다.
        rateLimiter.reset();

        ownerToken = signup("owner@example.com");
        JsonNode bot = request(HttpMethod.POST, "/api/bots", ownerToken, new CreateBotRequest("환불 봇")).json();
        botId = UUID.fromString(bot.path("id").asString());
        publicKey = bot.path("publicKey").asString();
    }

    // ── Origin 검증 (설정 조회) ──────────────────────────────────────────

    @Test
    @DisplayName("[보안] 허용 도메인을 설정하지 않은 봇은 어떤 사이트에서도 위젯이 뜨지 않는다 (기본값 = 닫힘)")
    void 빈_허용목록은_전부_차단() {
        Response response = config(publicKey, 고객사이트);

        // 빈 목록을 "전부 허용" 으로 두면 모든 신규 봇이 무방비로 태어난다.
        assertThat(response.status()).isEqualTo(403);
        assertThat(response.json().path("error").path("code").asString()).isEqualTo("ORIGIN_NOT_ALLOWED");
        // 무엇을 하면 되는지까지 알려줘야 한다 — "설정한 적 없음" 과 "목록에 없음" 은 할 일이 다르다.
        assertThat(response.json().path("error").path("message").asString())
                .contains("허용 도메인")
                .contains("추가");
    }

    @Test
    @DisplayName("허용 도메인을 등록하면 그 사이트에서 위젯 설정을 받을 수 있다")
    void 허용된_도메인은_통과() {
        allowOrigin(고객사이트);

        Response response = config(publicKey, 고객사이트);

        assertThat(response.status()).isEqualTo(200);
        assertThat(response.json().path("botName").asString()).isEqualTo("환불 봇");
        assertThat(response.json().path("welcomeMessage").asString()).isEqualTo("무엇을 도와드릴까요?");
    }

    @Test
    @DisplayName("[보안] 등록하지 않은 도메인에서는 403 이다 (남의 봇을 자기 사이트에 붙이는 것을 막는다)")
    void 등록하지_않은_도메인은_차단() {
        allowOrigin(고객사이트);

        Response response = config(publicKey, "https://evil.example.com");

        assertThat(response.status()).isEqualTo(403);
        assertThat(response.json().path("error").path("code").asString()).isEqualTo("ORIGIN_NOT_ALLOWED");
    }

    @Test
    @DisplayName("[보안] 접미사가 같은 도메인은 통과하지 못한다 (evil-example.com ≠ example.com)")
    void 접미사_일치로는_통과하지_못한다() {
        allowOrigin("https://example.com");

        // 부분 일치·접미사 비교로 짰다면 여기서 뚫린다. 정확히 일치만 허용한다.
        assertThat(config(publicKey, "https://evil-example.com").status()).isEqualTo(403);
        assertThat(config(publicKey, "https://example.com.evil.net").status()).isEqualTo(403);
        // 스킴이 다르면 다른 오리진이다.
        assertThat(config(publicKey, "http://example.com").status()).isEqualTo(403);
    }

    @Test
    @DisplayName("없는 publicKey 로 설정을 조회하면 404 다")
    void 없는_publicKey() {
        Response response = config("pk_존재하지않음", 고객사이트);

        assertThat(response.status()).isEqualTo(404);
        assertThat(response.json().path("error").path("code").asString()).isEqualTo("BOT_NOT_FOUND");
    }

    // ── 정보 노출 ────────────────────────────────────────────────────────

    @Test
    @DisplayName("[보안] 설정 응답에 내부 설정이 하나도 실리지 않는다 (아무나 볼 수 있는 응답이다)")
    void 내부설정은_노출되지_않는다() {
        request(HttpMethod.PATCH, "/api/bots/" + botId, ownerToken,
                new UpdateBotRequest(null, "너는 환불 담당자다. 내부 지시문.", null,
                        "담당자에게 문의해주세요.", List.of(고객사이트)));

        Response response = config(publicKey, 고객사이트);

        assertThat(response.status()).isEqualTo(200);
        // 응답 전체를 문자열로 훑는다. 필드를 하나씩 확인하면 나중에 누가 필드를 추가했을 때 놓친다.
        assertThat(response.body())
                .doesNotContain("내부 지시문")        // systemPrompt
                .doesNotContain("담당자에게 문의")     // fallbackMessage
                .doesNotContain(고객사이트)            // allowedOrigins
                .doesNotContain(botId.toString())     // 내부 식별자
                .doesNotContain("owner@example.com"); // 소유자
    }

    // ── 위젯 채팅 ────────────────────────────────────────────────────────

    @Test
    @DisplayName("위젯 채팅은 인증 없이 되고, channel='widget' 으로 기록된다")
    void 위젯_채팅() {
        aiService.enqueue(200, 정상응답);

        Response response = widgetChat(publicKey, "환불 언제까지 되나요?");

        assertThat(response.status()).isEqualTo(200);
        assertThat(response.json().path("answer").asString()).contains("7일");
        assertThat(response.json().path("messageId").asString()).isNotBlank();

        // 관리자 테스트 대화(test)와 구분돼야 품질 지표가 왜곡되지 않는다.
        String channel = jdbcTemplate.queryForObject(
                "SELECT channel FROM conversations WHERE bot_id = ?", String.class, botId);
        assertThat(channel).isEqualTo("widget");
    }

    @Test
    @DisplayName("위젯에서도 fallback 은 봇의 문구로 치환된다")
    void 위젯_fallback_치환() {
        String 봇문구 = "규정집에서 답을 찾지 못했어요. 고객센터로 문의해주세요.";
        request(HttpMethod.PATCH, "/api/bots/" + botId, ownerToken,
                new UpdateBotRequest(null, null, null, 봇문구, null));
        aiService.enqueue(200, 거절응답);

        Response response = widgetChat(publicKey, "배송은 언제 오나요?");

        assertThat(response.json().path("isFallback").asBoolean()).isTrue();
        assertThat(response.json().path("answer").asString()).isEqualTo(봇문구);
        assertThat(response.body()).doesNotContain("문서에서 관련 내용을 찾지 못했습니다");
    }

    @Test
    @DisplayName("위젯 채팅은 Origin 을 검증하지 않는다 (iframe 구조상 고객 Origin 이 오지 않는다)")
    void 채팅은_Origin을_검증하지_않는다() {
        aiService.enqueue(200, 정상응답);

        // 이 단언은 "현재 이렇게 동작한다" 를 고정하기 위한 것이다.
        // 나중에 채팅도 로더가 호출하도록 구조를 바꾸면 이 테스트가 깨지고,
        // 그때 WidgetController 주석의 "설계상의 구멍" 문단도 함께 지우게 된다.
        Response response = widgetChat(publicKey, "질문", "https://anywhere.example.com");

        assertThat(response.status()).isEqualTo(200);
    }

    // ── 요청 수 제한 ─────────────────────────────────────────────────────

    @Test
    @DisplayName("[비용] 채팅 한도를 넘으면 429 이고, Python 을 더 부르지 않는다")
    void 채팅_요청수_제한() {
        // 테스트 컨텍스트의 한도는 분당 3회 (TestcontainersConfiguration)
        for (int i = 0; i < 3; i++) {
            aiService.enqueue(200, 정상응답);
            assertThat(widgetChat(publicKey, "질문 " + i).status()).isEqualTo(200);
        }

        Response blocked = widgetChat(publicKey, "네 번째 질문");

        assertThat(blocked.status()).isEqualTo(429);
        assertThat(blocked.json().path("error").path("code").asString()).isEqualTo("RATE_LIMIT_EXCEEDED");

        // 막힌 요청이 Python 까지 갔다면 LLM 비용이 이미 나간 뒤다. 제한의 의미가 없어진다.
        assertThat(aiService.received()).hasSize(3);
    }

    @Test
    @DisplayName("[비용] 설정 조회도 한도가 있다 (publicKey 대량 스캔 방지)")
    void 설정조회_요청수_제한() {
        allowOrigin(고객사이트);

        for (int i = 0; i < 5; i++) {   // 테스트 한도: 분당 5회
            assertThat(config(publicKey, 고객사이트).status()).isEqualTo(200);
        }

        assertThat(config(publicKey, 고객사이트).status()).isEqualTo(429);
    }

    @Test
    @DisplayName("한도는 봇마다 따로 센다 (한 봇이 다른 봇의 한도를 잡아먹지 않는다)")
    void 한도는_봇마다_따로() {
        JsonNode 다른봇 = request(HttpMethod.POST, "/api/bots", ownerToken,
                new CreateBotRequest("다른 봇")).json();
        String 다른키 = 다른봇.path("publicKey").asString();

        for (int i = 0; i < 3; i++) {
            aiService.enqueue(200, 정상응답);
            widgetChat(publicKey, "질문");
        }
        assertThat(widgetChat(publicKey, "막힘").status()).isEqualTo(429);

        // 다른 봇은 아직 한도가 남아 있어야 한다.
        aiService.enqueue(200, 정상응답);
        assertThat(widgetChat(다른키, "다른 봇 질문").status()).isEqualTo(200);
    }

    // ── 테스트 보조 ──────────────────────────────────────────────────────

    private void allowOrigin(String origin) {
        request(HttpMethod.PATCH, "/api/bots/" + botId, ownerToken,
                new UpdateBotRequest(null, null, null, null, List.of(origin)));
    }

    private Response config(String publicKey, String origin) {
        return publicRequest(HttpMethod.GET, "/api/w/" + publicKey + "/config", origin, null);
    }

    private Response widgetChat(String publicKey, String message) {
        return widgetChat(publicKey, message, null);
    }

    private Response widgetChat(String publicKey, String message, String origin) {
        return publicRequest(HttpMethod.POST, "/api/w/" + publicKey + "/chat", origin,
                new ChatRequest(message, "widget-session-1"));
    }

    /** 인증 헤더를 붙이지 않는다 — 위젯은 공개 API 다. */
    private Response publicRequest(HttpMethod method, String uri, String origin, Object body) {
        var spec = client.method(method).uri(uri);
        if (origin != null) {
            spec.header(HttpHeaders.ORIGIN, origin);
        }
        var ready = body == null ? spec : spec.contentType(MediaType.APPLICATION_JSON).body(body);
        EntityExchangeResult<byte[]> result = ready.exchange().expectBody().returnResult();
        return new Response(result.getStatus().value(), decode(result.getResponseBody()));
    }

    private String signup(String email) {
        return request(HttpMethod.POST, "/api/auth/signup", null,
                new SignupRequest(email, PASSWORD, null)).json().path("token").asString();
    }

    private Response request(HttpMethod method, String uri, String token, Object body) {
        var spec = client.method(method).uri(uri).contentType(MediaType.APPLICATION_JSON);
        if (token != null) {
            spec.header(HttpHeaders.AUTHORIZATION, "Bearer " + token);
        }
        EntityExchangeResult<byte[]> result = spec.body(body).exchange().expectBody().returnResult();
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
