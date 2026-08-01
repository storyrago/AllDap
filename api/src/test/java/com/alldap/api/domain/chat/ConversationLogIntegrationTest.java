package com.alldap.api.domain.chat;

import com.alldap.api.domain.auth.dto.SignupRequest;
import com.alldap.api.domain.bot.dto.CreateBotRequest;
import com.alldap.api.domain.chat.dto.ChatRequest;
import com.alldap.api.domain.user.repository.UserRepository;
import com.alldap.api.support.AiServiceStub;
import com.alldap.api.support.IntegrationTest;
import org.hibernate.SessionFactory;
import org.hibernate.stat.Statistics;
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

import jakarta.persistence.EntityManagerFactory;

import java.nio.charset.StandardCharsets;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 대화 로그 API 통합 테스트.
 *
 * <p>이 슬라이스에서 지키려는 것은 셋이다.
 *
 * <ol>
 *   <li><b>N+1 이 없다.</b> 로그 목록은 대화가 쌓일수록 커지는 화면이라, 대화 건마다 쿼리가 나가면
 *       실사용에서 가장 먼저 느려진다. "쿼리가 몇 번 나갔는지" 를 <b>실제로 세서</b> 검증한다.</li>
 *   <li><b>집계가 맞다.</b> {@code hasFallback} 은 W3 미답변 목록의 근거라 틀리면 품질 지표가 거짓이 된다.</li>
 *   <li><b>소유권 격리.</b> 남의 봇 로그, 남의 대화 상세를 볼 수 없다.</li>
 * </ol>
 */
@IntegrationTest
@DisplayName("대화 로그 API 통합 테스트")
class ConversationLogIntegrationTest {

    private static final String PASSWORD = "correct-password-1234";

    private static final String 정상응답 = """
            {"answer":"휴학은 개강 후 30일 이내에 신청합니다.",
             "sources":[{"chunk_id":"22222222-2222-2222-2222-222222222222",
                         "document_id":"33333333-3333-3333-3333-333333333333",
                         "filename":"학사규정.pdf","score":0.9,"preview":"휴학 신청은"}],
             "is_fallback":false,"latency_ms":900}""";

    private static final String 거절응답 = """
            {"answer":"문서에서 관련 내용을 찾지 못했습니다.","sources":[],
             "is_fallback":true,"latency_ms":120}""";

    @LocalServerPort
    private int port;

    @Autowired
    private UserRepository userRepository;

    @Autowired
    private AiServiceStub aiService;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    /**
     * Hibernate 통계로 <b>실제 실행된 쿼리 수</b>를 센다.
     *
     * <p>{@code EntityManagerFactory} 를 Hibernate 의 {@code SessionFactory} 로 풀어야
     * {@code Statistics} 에 닿는다. JPA 표준에는 이런 계측 수단이 없기 때문이다.
     * (통계는 {@code application.yaml} 이 아니라 이 테스트에서만 켜고 끈다 —
     *  운영에서 켜두면 요청마다 오버헤드가 붙는다)
     */
    @Autowired
    private EntityManagerFactory entityManagerFactory;

    private RestTestClient client;
    private String ownerToken;
    private String intruderToken;
    private UUID botId;

    @BeforeEach
    void setUp() {
        client = RestTestClient.bindToServer().baseUrl("http://localhost:" + port).build();
        userRepository.deleteAll();
        aiService.reset();

        ownerToken = signup("owner@example.com");
        intruderToken = signup("intruder@example.com");
        botId = createBot(ownerToken);
    }

    // ── N+1 ─────────────────────────────────────────────────────────────

    @Test
    @DisplayName("[성능] 대화가 5건이어도 목록 조회 쿼리는 늘어나지 않는다 (N+1 없음)")
    void 목록은_N플러스1이_없다() {
        for (int i = 0; i < 5; i++) {
            chatWithSession(ownerToken, "세션-" + i, 정상응답, "질문 " + i);
        }

        Statistics statistics = statistics();
        statistics.clear();

        Response response = request(HttpMethod.GET, "/api/bots/" + botId + "/logs", ownerToken);

        assertThat(response.status()).isEqualTo(200);
        assertThat(response.json().path("items").size()).isEqualTo(5);

        // 대화 페이지 조회 + 개수(count) + 집계 = 3번. 대화 건수가 늘어도 이 수는 그대로다.
        // 대화마다 메시지를 조회했다면 5번이 더 붙었을 것이다.
        long queries = statistics.getPrepareStatementCount();
        assertThat(queries)
                .as("실행된 쿼리 %d 개 — 대화 건수(5)에 비례해 늘면 N+1 이다", queries)
                .isLessThanOrEqualTo(4);
    }

    // ── 집계 ────────────────────────────────────────────────────────────

    @Test
    @DisplayName("목록 한 줄에 메시지 수·fallback 여부·첫 질문이 함께 나온다")
    void 목록_집계() {
        chatWithSession(ownerToken, "세션-A", 정상응답, "휴학 신청은 언제?");

        JsonNode item = request(HttpMethod.GET, "/api/bots/" + botId + "/logs", ownerToken)
                .json().path("items").get(0);

        assertThat(item.path("messageCount").asInt()).isEqualTo(2);   // 질문 + 답변
        assertThat(item.path("hasFallback").asBoolean()).isFalse();
        // 목록에서 미리 보여줄 첫 질문 — 답변이 아니라 <질문>이어야 한다.
        assertThat(item.path("firstUserMessage").asString()).isEqualTo("휴학 신청은 언제?");
        assertThat(item.path("channel").asString()).isEqualTo("test");
        assertThat(item.path("sessionId").asString()).isEqualTo("세션-A");
    }

    @Test
    @DisplayName("한 세션에 fallback 이 하나라도 있으면 hasFallback 이 true 다 (W3 미답변 집계의 근거)")
    void hasFallback_집계() {
        aiService.enqueue(200, 정상응답);
        aiService.enqueue(200, 거절응답);
        chat(ownerToken, "세션-B", "답할 수 있는 질문");
        chat(ownerToken, "세션-B", "문서에 없는 질문");

        JsonNode item = request(HttpMethod.GET, "/api/bots/" + botId + "/logs", ownerToken)
                .json().path("items").get(0);

        assertThat(item.path("messageCount").asInt()).isEqualTo(4);
        // 4건 중 1건만 fallback 이어도 이 세션은 "미답변이 있었다" 로 잡혀야 한다.
        assertThat(item.path("hasFallback").asBoolean()).isTrue();
    }

    // ── 필터 ────────────────────────────────────────────────────────────

    @Test
    @DisplayName("onlyFallback=true 면 fallback 이 있었던 세션만 나온다")
    void 필터_onlyFallback() {
        chatWithSession(ownerToken, "정상세션", 정상응답, "질문");
        chatWithSession(ownerToken, "거절세션", 거절응답, "문서에 없는 질문");

        JsonNode all = request(HttpMethod.GET, "/api/bots/" + botId + "/logs", ownerToken).json();
        assertThat(all.path("items").size()).isEqualTo(2);

        JsonNode filtered = request(HttpMethod.GET,
                "/api/bots/" + botId + "/logs?onlyFallback=true", ownerToken).json();

        assertThat(filtered.path("items").size()).isEqualTo(1);
        assertThat(filtered.path("items").get(0).path("sessionId").asString()).isEqualTo("거절세션");
        // totalElements 도 필터를 반영해야 한다. 조인으로 짰다면 여기가 부풀어 올랐을 것이다.
        assertThat(filtered.path("totalElements").asInt()).isEqualTo(1);
    }

    @Test
    @DisplayName("onlyThumbsDown=true 면 👎 가 달린 세션만 나온다")
    void 필터_onlyThumbsDown() {
        chatWithSession(ownerToken, "그냥세션", 정상응답, "질문");

        aiService.enqueue(200, 정상응답);
        UUID messageId = UUID.fromString(
                chat(ownerToken, "싫어요세션", "질문").json().path("messageId").asString());
        jdbcTemplate.update("UPDATE messages SET feedback = -1 WHERE id = ?", messageId);

        JsonNode filtered = request(HttpMethod.GET,
                "/api/bots/" + botId + "/logs?onlyThumbsDown=true", ownerToken).json();

        assertThat(filtered.path("items").size()).isEqualTo(1);
        assertThat(filtered.path("items").get(0).path("sessionId").asString()).isEqualTo("싫어요세션");
    }

    @Test
    @DisplayName("날짜 필터는 그 날짜를 포함한다 (to=오늘 이면 오늘 대화가 나온다)")
    void 필터_날짜() {
        chatWithSession(ownerToken, "오늘세션", 정상응답, "질문");

        // 오늘 만든 대화가 to=오늘 에 포함되어야 한다.
        // to 를 그대로 00:00 으로 비교하면 오늘 대화가 전부 빠진다 — 흔한 off-by-one 이다.
        String 오늘 = java.time.LocalDate.now(java.time.ZoneId.of("Asia/Seoul")).toString();
        JsonNode 포함 = request(HttpMethod.GET,
                "/api/bots/" + botId + "/logs?from=" + 오늘 + "&to=" + 오늘, ownerToken).json();
        assertThat(포함.path("items").size()).isEqualTo(1);

        // 어제까지로 자르면 오늘 대화는 빠져야 한다.
        String 어제 = java.time.LocalDate.now(java.time.ZoneId.of("Asia/Seoul")).minusDays(1).toString();
        JsonNode 제외 = request(HttpMethod.GET,
                "/api/bots/" + botId + "/logs?to=" + 어제, ownerToken).json();
        assertThat(제외.path("items").size()).isZero();
    }

    // ── 상세 ────────────────────────────────────────────────────────────

    @Test
    @DisplayName("대화 상세는 메시지를 시간순으로 주고, 근거는 파싱해서 내려준다")
    void 대화_상세() {
        chatWithSession(ownerToken, "세션-C", 정상응답, "휴학 신청은 언제?");
        UUID conversationId = UUID.fromString(
                request(HttpMethod.GET, "/api/bots/" + botId + "/logs", ownerToken)
                        .json().path("items").get(0).path("id").asString());

        Response response = request(HttpMethod.GET,
                "/api/bots/" + botId + "/logs/" + conversationId, ownerToken);

        assertThat(response.status()).isEqualTo(200);
        JsonNode messages = response.json();
        assertThat(messages.size()).isEqualTo(2);

        // 질문이 먼저다. 순서가 뒤집히면 화면에서 대화가 거꾸로 보인다.
        assertThat(messages.get(0).path("role").asString()).isEqualTo("user");
        assertThat(messages.get(0).path("content").asString()).isEqualTo("휴학 신청은 언제?");
        assertThat(messages.get(0).path("sources").isNull()).isTrue();

        JsonNode answer = messages.get(1);
        assertThat(answer.path("role").asString()).isEqualTo("assistant");
        assertThat(answer.path("latencyMs").asInt()).isEqualTo(900);
        // JSONB 문자열이 그대로 나가면 안 된다 — 파싱된 배열이어야 프론트가 쓸 수 있다.
        assertThat(answer.path("sources").isArray()).isTrue();
        assertThat(answer.path("sources").get(0).path("filename").asString()).isEqualTo("학사규정.pdf");
    }

    @Test
    @DisplayName("sources JSON 이 깨져 있어도 대화 조회가 500 이 되지 않는다")
    void 깨진_JSON도_조회된다() {
        chatWithSession(ownerToken, "세션-D", 정상응답, "질문");
        // 과거에 저장된 데이터가 깨진 상황을 만든다. 우리가 지금 고칠 수 없는 값이다.
        jdbcTemplate.update("UPDATE messages SET sources = '{\"안맞는\":\"구조\"}'::jsonb "
                + "WHERE role = 'assistant'");

        UUID conversationId = UUID.fromString(
                request(HttpMethod.GET, "/api/bots/" + botId + "/logs", ownerToken)
                        .json().path("items").get(0).path("id").asString());

        Response response = request(HttpMethod.GET,
                "/api/bots/" + botId + "/logs/" + conversationId, ownerToken);

        // 한 건이 깨졌다고 멀쩡한 나머지 메시지까지 못 보게 되면 안 된다.
        assertThat(response.status()).isEqualTo(200);
        assertThat(response.json().size()).isEqualTo(2);
        assertThat(response.json().get(1).path("sources").isNull()).isTrue();
    }

    // ── 소유권 격리 ──────────────────────────────────────────────────────

    @Test
    @DisplayName("[보안] 남의 봇 로그를 조회하면 404 다")
    void 남의_봇_로그() {
        chatWithSession(ownerToken, "세션-E", 정상응답, "질문");

        Response response = request(HttpMethod.GET, "/api/bots/" + botId + "/logs", intruderToken);

        assertThat(response.status()).isEqualTo(404);
        assertThat(response.json().path("error").path("code").asString()).isEqualTo("BOT_NOT_FOUND");
    }

    @Test
    @DisplayName("[보안] 목록에 남의 봇 대화가 섞이지 않는다")
    void 목록은_내_봇_대화만() {
        chatWithSession(ownerToken, "내세션", 정상응답, "내 질문");

        UUID 남의봇 = createBot(intruderToken);
        aiService.enqueue(200, 정상응답);
        request(HttpMethod.POST, "/api/bots/" + 남의봇 + "/chat", intruderToken,
                new ChatRequest("남의 질문", "남의세션"));

        JsonNode items = request(HttpMethod.GET, "/api/bots/" + botId + "/logs", ownerToken)
                .json().path("items");

        assertThat(items.size()).isEqualTo(1);
        assertThat(items.toString()).doesNotContain("남의세션").doesNotContain("남의 질문");
    }

    @Test
    @DisplayName("[보안] 내 봇 id 에 남의 대화 id 를 붙여도 볼 수 없다")
    void 남의_대화_상세() {
        UUID 남의봇 = createBot(intruderToken);
        aiService.enqueue(200, 정상응답);
        request(HttpMethod.POST, "/api/bots/" + 남의봇 + "/chat", intruderToken,
                new ChatRequest("남의 질문", "남의세션"));
        UUID 남의대화 = UUID.fromString(jdbcTemplate.queryForObject(
                "SELECT id::text FROM conversations WHERE bot_id = ?", String.class, 남의봇));

        // 봇 소유권만 확인하고 대화가 그 봇의 것인지 안 보면 여기서 남의 대화가 열린다.
        Response response = request(HttpMethod.GET,
                "/api/bots/" + botId + "/logs/" + 남의대화, ownerToken);

        assertThat(response.status()).isEqualTo(404);
        assertThat(response.body()).doesNotContain("남의 질문");
    }

    // ── 테스트 보조 ──────────────────────────────────────────────────────

    private Statistics statistics() {
        Statistics statistics = entityManagerFactory.unwrap(SessionFactory.class).getStatistics();
        statistics.setStatisticsEnabled(true);
        return statistics;
    }

    /** 한 세션에서 한 번 질문한다. */
    private void chatWithSession(String token, String sessionId, String aiResponse, String message) {
        aiService.enqueue(200, aiResponse);
        chat(token, sessionId, message);
    }

    private Response chat(String token, String sessionId, String message) {
        return request(HttpMethod.POST, "/api/bots/" + botId + "/chat", token,
                new ChatRequest(message, sessionId));
    }

    private String signup(String email) {
        return request(HttpMethod.POST, "/api/auth/signup", null,
                new SignupRequest(email, PASSWORD, null)).json().path("token").asString();
    }

    private UUID createBot(String token) {
        return UUID.fromString(request(HttpMethod.POST, "/api/bots", token,
                new CreateBotRequest("테스트 봇")).json().path("id").asString());
    }

    private Response request(HttpMethod method, String uri, String token) {
        return request(method, uri, token, null);
    }

    private Response request(HttpMethod method, String uri, String token, Object body) {
        var spec = client.method(method).uri(uri);
        if (token != null) {
            spec.header(HttpHeaders.AUTHORIZATION, "Bearer " + token);
        }
        var ready = body == null ? spec : spec.contentType(MediaType.APPLICATION_JSON).body(body);
        EntityExchangeResult<byte[]> result = ready.exchange().expectBody().returnResult();
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
