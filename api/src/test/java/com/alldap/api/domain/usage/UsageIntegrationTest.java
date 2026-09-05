package com.alldap.api.domain.usage;

import com.alldap.api.global.client.AiServiceCircuitBreaker;
import com.alldap.api.domain.auth.dto.SignupRequest;
import com.alldap.api.domain.bot.dto.CreateBotRequest;
import com.alldap.api.domain.chat.dto.ChatRequest;
import com.alldap.api.domain.usage.entity.UsageEvent;
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
import java.sql.Timestamp;
import java.time.Instant;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 사용량 계량 통합 테스트.
 *
 * <p><b>여기서 지키려는 것은 "무엇이 과금되고 무엇이 안 되는가" 하나다.</b>
 * /pricing 이 이미 고객에게 약속한 내용이라, 이 테스트가 곧 그 약속의 검증이다.
 */
@IntegrationTest
@DisplayName("사용량 계량 통합 테스트")
class UsageIntegrationTest {

    private static final String PASSWORD = "correct-password-1234";

    private static final String 정상응답 = """
            {"answer":"환불은 7일 이내에 가능합니다.",
             "sources":[],"is_fallback":false,"latency_ms":800}""";

    private static final String 거절응답 = """
            {"answer":"문서에서 답을 찾지 못했어요. 담당자에게 문의해주세요.",
             "sources":[],"is_fallback":true,"latency_ms":120}""";

    @LocalServerPort
    private int port;

    @Autowired
    private UserRepository userRepository;

    @Autowired
    private AiServiceStub aiService;

    @Autowired
    AiServiceCircuitBreaker circuitBreaker;

    @Autowired
    private RateLimiter rateLimiter;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    private RestTestClient client;
    private String ownerToken;
    private UUID botId;
    private UUID userId;
    private String publicKey;

    @BeforeEach
    void setUp() {
        client = RestTestClient.bindToServer().baseUrl("http://localhost:" + port).build();
        userRepository.deleteAll();
        aiService.reset();
        circuitBreaker.reset();
        rateLimiter.reset();

        ownerToken = signup("owner@example.com");
        userId = userRepository.findByEmail("owner@example.com").orElseThrow().getId();
        JsonNode bot = request(HttpMethod.POST, "/api/bots", ownerToken, new CreateBotRequest("환불 봇")).json();
        botId = UUID.fromString(bot.path("id").asString());
        publicKey = bot.path("publicKey").asString();
    }

    @Test
    @DisplayName("[과금] 위젯 답변 1건이 사용량 1건으로 남는다")
    void 위젯_답변은_세어진다() {
        aiService.enqueue(200, 정상응답);
        widgetChat(publicKey, "환불 규정이 어떻게 되나요?");

        assertThat(countUsage(userId, UsageEvent.KIND_CHAT_ANSWER)).isEqualTo(1);
    }

    @Test
    @DisplayName("[과금] fallback 답변은 세지 않는다 (/pricing 의 약속)")
    void fallback_은_세지_않는다() {
        aiService.enqueue(200, 거절응답);
        widgetChat(publicKey, "사내 헬스장이 있나요?");

        // 답변 행은 남아야 한다 — 안 남으면 대화 로그가 비어 로그 화면이 깨진다
        assertThat(countMessages(botId)).isEqualTo(2);   // user + assistant
        assertThat(countUsage(userId, UsageEvent.KIND_CHAT_ANSWER)).isZero();
    }

    @Test
    @DisplayName("[과금] 관리자 테스트 채팅은 세지 않는다")
    void 테스트_채팅은_세지_않는다() {
        aiService.enqueue(200, 정상응답);
        request(HttpMethod.POST, "/api/bots/" + botId + "/chat", ownerToken,
                new ChatRequest("환불 규정이 어떻게 되나요?", "test-session-1"));

        aiService.enqueue(200, 정상응답);
        widgetChat(publicKey, "환불 규정이 어떻게 되나요?");

        // 위젯 1건만 세어진다. 테스트 채팅도 LLM 비용은 들지만 과금 대상이 아니다.
        assertThat(countUsage(userId, UsageEvent.KIND_CHAT_ANSWER)).isEqualTo(1);
    }

    @Test
    @DisplayName("[과금] 봇을 지워도 이미 센 사용량은 남는다 (이 설계의 존재 이유)")
    void 봇을_지워도_사용량은_남는다() {
        aiService.enqueue(200, 정상응답);
        widgetChat(publicKey, "환불 규정이 어떻게 되나요?");
        assertThat(countUsage(userId, UsageEvent.KIND_CHAT_ANSWER)).isEqualTo(1);

        // 봇을 지우면 conversations·messages 는 CASCADE 로 사라진다.
        // request() 는 항상 body 를 붙이는 helper 라 DELETE 에도 빈 객체를 실어 보낸다
        // (null 을 넘기면 RestTestClient 가 NPE 를 낸다 — 다른 통합 테스트는 DELETE 를 쓴 적이 없어 몰랐던 함정).
        request(HttpMethod.DELETE, "/api/bots/" + botId, ownerToken, new Object());
        assertThat(countMessages(botId)).isZero();

        // 🔴 그런데 사용량은 남아야 한다. 청구 근거가 삭제 버튼 하나로 사라지면 안 된다.
        assertThat(countUsage(userId, UsageEvent.KIND_CHAT_ANSWER)).isEqualTo(1);
    }

    @Test
    @DisplayName("[과금] 주인 없는 봇(V1 시드)의 답변은 500 없이 성공하고, 다만 세지 않는다")
    void 주인_없는_봇은_과금되지_않는다() {
        // V1__init.sql 이 심어두는 로컬 개발용 시드 봇. user_id 가 NULL 이다.
        // 청구할 계정이 없는 상태에서도 채팅 자체는 정상 동작해야 한다(회귀 확인).
        aiService.enqueue(200, 정상응답);
        Response response = widgetChat("pk_local_dev", "환불 규정이 어떻게 되나요?");

        assertThat(response.status()).isEqualTo(200);
        assertThat(countMessages(UUID.fromString("00000000-0000-0000-0000-000000000001"))).isEqualTo(2);
        assertThat(jdbcTemplate.queryForObject(
                "SELECT count(*) FROM usage_events WHERE bot_id = ?",
                Long.class, UUID.fromString("00000000-0000-0000-0000-000000000001"))).isZero();
    }

    @Test
    @DisplayName("[과금] completed 평가 실행만 센다 (partial·failed 는 측정이 안 된 것이다)")
    void completed_평가실행만_센다() {
        insertEvalRun(botId, "completed");
        insertEvalRun(botId, "partial");
        insertEvalRun(botId, "failed");

        assertThat(usage(ownerToken, null).json().path("evalRuns").asInt()).isEqualTo(1);
    }

    @Test
    @DisplayName("[과금] 사용량을 여러 번 조회해도 평가 실행이 중복으로 세어지지 않는다")
    void 메꾸기는_멱등하다() {
        insertEvalRun(botId, "completed");

        for (int i = 0; i < 3; i++) {
            assertThat(usage(ownerToken, null).json().path("evalRuns").asInt()).isEqualTo(1);
        }
        // DB 로도 확인한다 — 응답이 1 이어도 행이 3개면 다음 달 청구가 틀어진다
        assertThat(countUsage(userId, "eval_run")).isEqualTo(1);
    }

    @Test
    @DisplayName("[보안] 남의 계정 사용량이 내 숫자에 섞이지 않는다")
    void 계정_격리() {
        aiService.enqueue(200, 정상응답);
        widgetChat(publicKey, "환불 규정이 어떻게 되나요?");
        insertEvalRun(botId, "completed");

        String 침입자 = signup("intruder@example.com");

        JsonNode 남의것 = usage(침입자, null).json();
        assertThat(남의것.path("chatAnswers").asInt()).isZero();
        assertThat(남의것.path("evalRuns").asInt()).isZero();
    }

    @Test
    @DisplayName("[기간] 9월 1일 00:00 KST 를 경계로 8월분과 9월분이 갈린다")
    void 기간_경계는_KST_다() {
        // 2026-08-31 23:59:59 KST = 2026-08-31T14:59:59Z
        insertUsageAt(userId, "chat_answer", Instant.parse("2026-08-31T14:59:59Z"));
        // 2026-09-01 00:00:00 KST = 2026-08-31T15:00:00Z
        insertUsageAt(userId, "chat_answer", Instant.parse("2026-08-31T15:00:00Z"));

        assertThat(usage(ownerToken, "2026-08").json().path("chatAnswers").asInt()).isEqualTo(1);
        assertThat(usage(ownerToken, "2026-09").json().path("chatAnswers").asInt()).isEqualTo(1);
    }

    // ── 테스트 보조 ──────────────────────────────────────────────────────

    /** eval_runs 는 Python 소유 테이블이라 테스트에서 직접 넣는다 */
    private void insertEvalRun(UUID botId, String status) {
        jdbcTemplate.update(
                "INSERT INTO eval_runs (bot_id, status, created_at) VALUES (?, ?, now())",
                botId, status);
    }

    /** 기간 경계 검증용. 사건 시각을 직접 정해야 하므로 원장에 바로 넣는다 */
    private void insertUsageAt(UUID userId, String kind, Instant occurredAt) {
        jdbcTemplate.update("""
                INSERT INTO usage_events (user_id, bot_id, kind, source_ref, occurred_at)
                VALUES (?, NULL, ?, gen_random_uuid(), ?)""",
                userId, kind, Timestamp.from(occurredAt));
    }

    private Response usage(String token, String month) {
        String uri = month == null ? "/api/usage" : "/api/usage?month=" + month;
        return request(HttpMethod.GET, uri, token, null);
    }

    private long countUsage(UUID userId, String kind) {
        Long n = jdbcTemplate.queryForObject(
                "SELECT count(*) FROM usage_events WHERE user_id = ? AND kind = ?",
                Long.class, userId, kind);
        return n == null ? 0 : n;
    }

    private long countMessages(UUID botId) {
        Long n = jdbcTemplate.queryForObject("""
                SELECT count(*) FROM messages m
                  JOIN conversations c ON c.id = m.conversation_id
                 WHERE c.bot_id = ?""", Long.class, botId);
        return n == null ? 0 : n;
    }

    private Response widgetChat(String publicKey, String message) {
        return publicRequest(HttpMethod.POST, "/api/w/" + publicKey + "/chat", null,
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
        var spec = client.method(method).uri(uri);
        if (token != null) {
            spec.header(HttpHeaders.AUTHORIZATION, "Bearer " + token);
        }
        // GET 인 usage(...) 는 본문이 없다. body 를 강제로 붙이면 본문 없는 GET 요청을 표현할 수 없다.
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
