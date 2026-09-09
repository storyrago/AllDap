package com.alldap.api.domain.bot;

import com.alldap.api.domain.auth.dto.SignupRequest;
import com.alldap.api.domain.bot.dto.CreateBotRequest;
import com.alldap.api.domain.user.repository.UserRepository;
import com.alldap.api.support.IntegrationTest;
import jakarta.persistence.EntityManagerFactory;
import org.hibernate.SessionFactory;
import org.hibernate.stat.Statistics;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.http.HttpHeaders;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.test.web.servlet.client.RestTestClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 봇 카드 집계(PRD §8: 문서 수·주간 대화 수·최근 평가 점수) 통합 테스트.
 *
 * <p>여기서 지키려는 것은 세 가지다.
 * <ol>
 *   <li><b>N+1 이 없다.</b> 봇이 1개든 3개든 쿼리 수가 같아야 한다.
 *       "숫자가 맞다" 만 보는 테스트는 봇마다 count 를 도는 구현도 통과시킨다.</li>
 *   <li><b>남의 봇 숫자가 새지 않는다.</b> 집계 쿼리에도 소유권이 걸려야 한다.</li>
 *   <li><b>평가 점수는 전체 충실성이다.</b> 평균(avg_faithfulness)을 그대로 쓰면
 *       답을 덜 할수록 올라간다(생존 편향). 두 값이 다른 상황을 일부러 만들어 확인한다.</li>
 * </ol>
 *
 * <p>문서·평가 실행은 <b>Python 이 쓰는 테이블</b>이라 Spring 에 저장 경로가 없다.
 * 그래서 픽스처는 SQL 로 직접 넣는다. 운영 코드는 여전히 읽기만 한다(AGENTS.md 테이블 소유권).
 */
@IntegrationTest
@DisplayName("봇 카드 집계 통합 테스트")
class BotSummaryIntegrationTest {

    private static final String PASSWORD = "correct-password-1234";
    private static final ObjectMapper JSON = new ObjectMapper();

    @LocalServerPort
    private int port;

    @Autowired
    private UserRepository userRepository;

    @Autowired
    private JdbcClient jdbc;

    @Autowired
    private EntityManagerFactory entityManagerFactory;

    private RestTestClient client;
    private String ownerToken;
    private String intruderToken;

    @BeforeEach
    void setUp() {
        client = RestTestClient.bindToServer().baseUrl("http://localhost:" + port).build();
        userRepository.deleteAll();   // bots·documents·conversations·eval_runs 는 CASCADE 로 함께 사라진다
        ownerToken = signup("owner@example.com");
        intruderToken = signup("intruder@example.com");
    }

    @Test
    @DisplayName("카드에 문서 수·주간 대화 수·최근 평가 점수가 실린다")
    void 집계가_실린다() {
        UUID botId = createBot(ownerToken, "집계 봇");

        insertDocument(botId, "규정.pdf", "ready");
        insertDocument(botId, "처리중.pdf", "pending");   // 처리 중인 문서도 문서 목록에 보이므로 함께 센다
        insertConversation(botId, Instant.now().minus(Duration.ofDays(1)));
        insertConversation(botId, Instant.now().minus(Duration.ofDays(8)));   // 창 밖이라 세면 안 된다
        // 16문항 중 14문항만 채점됨: 평균 0.900 이지만 전체 충실성은 0.900 × 14 / 16 = 0.788
        insertEvalRun(botId, "completed", "0.900", 16, 14, Instant.now());

        JsonNode card = firstCard(ownerToken);

        assertThat(card.path("documentCount").asInt()).isEqualTo(2);
        assertThat(card.path("weeklyConversationCount").asInt()).isEqualTo(1);
        // 🔴 0.900(평균)이 아니어야 한다. 평균을 카드에 띄우면 생존 편향을 화면으로 옮기는 것이다.
        assertThat(card.path("latestOverallFaithfulness").asDouble()).isEqualTo(0.788);
    }

    @Test
    @DisplayName("평가를 한 번도 안 돌렸으면 점수는 null 이다 (0 으로 채우지 않는다)")
    void 평가_없으면_null() {
        createBot(ownerToken, "새 봇");

        JsonNode card = firstCard(ownerToken);

        assertThat(card.path("documentCount").asInt()).isZero();
        assertThat(card.path("latestOverallFaithfulness").isNull()).isTrue();
    }

    @Test
    @DisplayName("분모를 모르거나 아직 안 끝난 실행은 건너뛰고 계산 가능한 최신 실행을 고른다")
    void 계산할_수_없는_실행은_건너뛴다() {
        UUID botId = createBot(ownerToken, "이력 있는 봇");

        insertEvalRun(botId, "completed", "0.800", 10, 10, Instant.now().minus(Duration.ofDays(3)));
        // 옛 실행이라 분모 미기록(V3 이전). 이걸 고르면 점수를 지어내야 한다.
        insertEvalRun(botId, "completed", "1.000", null, null, Instant.now().minus(Duration.ofDays(2)));
        // 아직 돌고 있어 점수가 없다.
        insertEvalRun(botId, "running", null, 10, null, Instant.now().minus(Duration.ofDays(1)));

        assertThat(firstCard(ownerToken).path("latestOverallFaithfulness").asDouble()).isEqualTo(0.800);
    }

    @Test
    @DisplayName("[보안] 남의 봇 문서·대화·평가가 내 카드 숫자에 섞이지 않는다")
    void 집계도_소유자로_격리된다() {
        UUID myBot = createBot(ownerToken, "내 봇");
        UUID theirBot = createBot(intruderToken, "남의 봇");

        insertDocument(theirBot, "남의문서.pdf", "ready");
        insertConversation(theirBot, Instant.now());
        insertEvalRun(theirBot, "completed", "1.000", 10, 10, Instant.now());

        JsonNode cards = request("/api/bots", ownerToken);
        assertThat(cards.size()).isEqualTo(1);
        assertThat(cards.get(0).path("id").asString()).isEqualTo(myBot.toString());
        assertThat(cards.get(0).path("documentCount").asInt()).isZero();
        assertThat(cards.get(0).path("weeklyConversationCount").asInt()).isZero();
        assertThat(cards.get(0).path("latestOverallFaithfulness").isNull()).isTrue();
    }

    @Test
    @DisplayName("[N+1] 봇이 1개든 3개든 쿼리는 2번으로 고정이다")
    void 쿼리_수가_봇_개수에_비례하지_않는다() {
        createBot(ownerToken, "봇 1");
        insertDocument(createBot(ownerToken, "봇 2"), "a.pdf", "ready");

        long withTwo = countQueries(() -> request("/api/bots", ownerToken));

        UUID third = createBot(ownerToken, "봇 3");
        insertDocument(third, "b.pdf", "ready");
        insertConversation(third, Instant.now());
        insertEvalRun(third, "completed", "0.900", 10, 9, Instant.now());

        long withThree = countQueries(() -> request("/api/bots", ownerToken));

        // 봇마다 세는 구현이면 여기서 갈린다(2 → 3N+1).
        assertThat(withThree).isEqualTo(withTwo);
        // 목록 1번 + 집계 1번. 숫자를 못박아 둬야 "안 늘었다"가 아니라 "몇 번인지"를 말할 수 있다.
        assertThat(withThree).isEqualTo(2);
    }

    // ── 보조 ────────────────────────────────────────────────────────────

    /**
     * 실행 중에 나간 SQL 문 수.
     *
     * <p>{@code generate_statistics} 설정을 켜는 대신 런타임에 통계를 켠다.
     * 프로퍼티로 켜면 테스트 컨텍스트 설정이 갈라져 컨테이너가 하나 더 뜬다
     * ({@code TestcontainersConfiguration} 주석 참고).
     */
    private long countQueries(Runnable action) {
        Statistics statistics = entityManagerFactory.unwrap(SessionFactory.class).getStatistics();
        statistics.setStatisticsEnabled(true);
        statistics.clear();
        action.run();
        long count = statistics.getPrepareStatementCount();
        statistics.setStatisticsEnabled(false);
        return count;
    }

    private JsonNode firstCard(String token) {
        return request("/api/bots", token).get(0);
    }

    private void insertDocument(UUID botId, String filename, String status) {
        jdbc.sql("INSERT INTO documents (bot_id, filename, file_type, status) VALUES (?, ?, 'pdf', ?)")
                .params(botId, filename, status)
                .update();
    }

    private void insertConversation(UUID botId, Instant createdAt) {
        jdbc.sql("INSERT INTO conversations (bot_id, session_id, channel, created_at) VALUES (?, ?, 'widget', ?)")
                .params(botId, UUID.randomUUID().toString(), java.sql.Timestamp.from(createdAt))
                .update();
    }

    /** {@code avgFaithfulness} 는 NUMERIC(4,3) 이라 문자열로 넘겨 부동소수점 오차를 피한다. */
    private void insertEvalRun(UUID botId, String status, String avgFaithfulness,
                               Integer questionCount, Integer scoredCount, Instant createdAt) {
        jdbc.sql("""
                        INSERT INTO eval_runs (bot_id, status, avg_faithfulness, question_count, scored_count, created_at)
                        VALUES (?, ?, CAST(? AS NUMERIC), ?, ?, ?)
                        """)
                .params(botId, status, avgFaithfulness, questionCount, scoredCount,
                        java.sql.Timestamp.from(createdAt))
                .update();
    }

    private String signup(String email) {
        return post("/api/auth/signup", null, new SignupRequest(email, PASSWORD, null))
                .path("token").asString();
    }

    private UUID createBot(String token, String name) {
        return UUID.fromString(post("/api/bots", token, new CreateBotRequest(name)).path("id").asString());
    }

    private JsonNode request(String uri, String token) {
        byte[] body = client.get().uri(uri)
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + token)
                .exchange().expectBody().returnResult().getResponseBody();
        return JSON.readTree(new String(body, StandardCharsets.UTF_8));
    }

    private JsonNode post(String uri, String token, Object body) {
        var spec = client.post().uri(uri);
        if (token != null) {
            spec.header(HttpHeaders.AUTHORIZATION, "Bearer " + token);
        }
        byte[] raw = spec.body(body).exchange().expectBody().returnResult().getResponseBody();
        return JSON.readTree(new String(raw, StandardCharsets.UTF_8));
    }
}
