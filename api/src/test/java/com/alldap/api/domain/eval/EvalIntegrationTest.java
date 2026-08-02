package com.alldap.api.domain.eval;

import com.alldap.api.domain.auth.dto.SignupRequest;
import com.alldap.api.domain.bot.dto.CreateBotRequest;
import com.alldap.api.domain.user.repository.UserRepository;
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
import java.time.Duration;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 품질 평가 API 통합 테스트 (W3).
 *
 * <p>이 슬라이스에서 지키려는 것은 앞선 것들과 겹치면서도 하나가 더 있다.
 *
 * <ol>
 *   <li><b>Python 을 부르기 전에 소유권을 막는다.</b> {@code /internal/*} 에는 인증이 없어
 *       요청이 거기 도달한 시점에 이미 샌 것이다. 404 만 확인하면 부족하고
 *       <b>요청이 Python 까지 가지 않았음</b>을 봐야 한다.</li>
 *   <li><b>평가 전용 4xx 매퍼가 문구를 뭉개지 않는다.</b> 업로드 매퍼를 재사용하면 400 이
 *       {@code UNSUPPORTED_FILE_TYPE} 이 되어 <b>"질문을 만들 문서가 없습니다" 상황에
 *       "지원하지 않는 파일 형식입니다"가 나간다.</b> 이게 이 슬라이스 고유의 위험이다.</li>
 *   <li><b>점수 null 이 0 으로 둔갑하지 않는다.</b> {@code running} 이거나 채점 대상이 없으면
 *       평균이 없다. 0 으로 내려가면 화면이 "품질 0점"이라고 거짓말한다.</li>
 * </ol>
 *
 * <p>{@code eval_*} 는 <b>쓰기 소유자가 Python</b>이라 Spring 코드로 INSERT 할 수 없다.
 * 그래서 "Python 이 넣어둔 상태"는 {@link JdbcTemplate} 로 만든다(문서 테스트와 같은 방식).
 */
@IntegrationTest
@DisplayName("품질 평가 API 통합 테스트")
class EvalIntegrationTest {

    private static final String PASSWORD = "correct-password-1234";

    @LocalServerPort
    private int port;

    @Autowired
    private UserRepository userRepository;

    @Autowired
    private AiServiceStub aiService;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    private RestTestClient client;
    private String ownerToken;
    private String intruderToken;
    private UUID botId;

    @BeforeEach
    void setUp() {
        client = RestTestClient.bindToServer().baseUrl("http://localhost:" + port).build();

        // 실제 HTTP 라 테스트 트랜잭션 롤백이 통하지 않는다.
        // users 를 지우면 bots → eval_* 이 DB 의 ON DELETE CASCADE 로 함께 사라진다.
        userRepository.deleteAll();
        aiService.reset();

        ownerToken = signup("owner@example.com");
        intruderToken = signup("intruder@example.com");
        botId = createBot(ownerToken);
    }

    // ── 소유권: Python 을 부르기 전에 막는다 ──────────────────────────────

    @Test
    @DisplayName("[보안] 남의 봇 질문 목록은 404 다")
    void 남의_봇_질문목록() {
        Response response = request(HttpMethod.GET, "/api/bots/" + botId + "/eval/questions", intruderToken);

        assertThat(response.status()).isEqualTo(404);
        assertThat(response.json().path("error").path("code").asString()).isEqualTo("BOT_NOT_FOUND");
    }

    @Test
    @DisplayName("[보안] 남의 봇에 질문 생성을 걸면 404 이고, 요청이 Python 까지 가지 않는다")
    void 남의_봇_질문생성() {
        Response response = jsonRequest(HttpMethod.POST,
                "/api/bots/" + botId + "/eval/questions/generate", intruderToken, "{\"count\":3}");

        assertThat(response.status()).isEqualTo(404);
        // 이 줄이 핵심이다. Python 에는 인증이 없으므로 요청이 거기까지 갔다면
        // 404 를 돌려줬든 말든 이미 남의 봇 문서로 질문이 만들어진 뒤다.
        assertThat(aiService.received()).isEmpty();
    }

    @Test
    @DisplayName("[보안] 남의 봇에 평가를 실행하면 404 이고, 요청이 Python 까지 가지 않는다")
    void 남의_봇_평가실행() {
        Response response = request(HttpMethod.POST, "/api/bots/" + botId + "/eval/runs", intruderToken);

        assertThat(response.status()).isEqualTo(404);
        assertThat(aiService.received()).isEmpty();
    }

    @Test
    @DisplayName("[보안] 남의 봇 실행 이력은 404 다")
    void 남의_봇_실행이력() {
        Response response = request(HttpMethod.GET, "/api/bots/" + botId + "/eval/runs", intruderToken);

        assertThat(response.status()).isEqualTo(404);
    }

    @Test
    @DisplayName("[보안] 실행 id 를 알아도 남의 봇 경로로는 결과를 못 본다 — 403 이 아니라 404")
    void 남의_봇_실행결과() {
        UUID runId = insertRun(botId, "completed");

        Response response = request(HttpMethod.GET,
                "/api/bots/" + botId + "/eval/runs/" + runId + "/results", intruderToken);

        // 403 으로 답하면 "그 실행은 존재한다"를 알려주는 셈이라
        // 무작위 UUID 를 던져 남의 데이터 존재 여부를 훑을 수 있다.
        assertThat(response.status()).isEqualTo(404);
    }

    @Test
    @DisplayName("[보안] 내 봇이어도 다른 봇의 실행 결과는 못 본다")
    void 다른_봇의_실행결과() {
        UUID otherBotId = createBot(ownerToken);          // 같은 사람의 <다른> 봇
        UUID runId = insertRun(otherBotId, "completed");

        Response response = request(HttpMethod.GET,
                "/api/bots/" + botId + "/eval/runs/" + runId + "/results", ownerToken);

        // botId 와 runId 를 <함께> 쿼리에 넣지 않으면 여기서 남의 봇 결과가 새어 나온다.
        assertThat(response.status()).isEqualTo(404);
        assertThat(response.json().path("error").path("code").asString()).isEqualTo("RESOURCE_NOT_FOUND");
    }

    @Test
    @DisplayName("[보안] 토큰이 없으면 401 이다")
    void 인증_없음() {
        EntityExchangeResult<byte[]> result = client.get()
                .uri("/api/bots/{botId}/eval/questions", botId)
                .exchange().expectBody().returnResult();

        assertThat(result.getStatus().value()).isEqualTo(401);
    }

    // ── 평가 전용 4xx 매퍼: Python 의 한국어 안내를 뭉개지 않는다 ──────────

    @Test
    @DisplayName("Python 이 400 이면 EVAL_NOT_READY 로 바꾸고 <Python 의 한국어 안내를 그대로> 전달한다")
    void python_400_은_안내를_보존한다() {
        // Python 이 실제로 주는 문구. 업로드 매퍼를 재사용하면 이게 통째로 버려지고
        // "지원하지 않는 파일 형식입니다"로 바뀐다 — 사용자가 멀쩡한 파일을 의심하게 된다.
        aiService.enqueue(400,
                "{\"detail\":\"처리가 끝난 문서가 없습니다. 문서를 올린 뒤 상태가 '준비됨'이 되면 다시 시도해주세요.\"}");

        Response response = jsonRequest(HttpMethod.POST,
                "/api/bots/" + botId + "/eval/questions/generate", ownerToken, "{\"count\":3}");

        assertThat(response.status()).isEqualTo(400);
        assertThat(response.json().path("error").path("code").asString()).isEqualTo("EVAL_NOT_READY");
        assertThat(response.json().path("error").path("message").asString())
                .contains("처리가 끝난 문서가 없습니다")
                .doesNotContain("파일 형식");   // ← 업로드 매퍼 재사용 방지 회귀 테스트
    }

    @Test
    @DisplayName("평가 실행 시 Python 이 400 이면 그 안내도 그대로 전달한다")
    void 평가실행_400() {
        aiService.enqueue(400,
                "{\"detail\":\"평가할 테스트 질문이 없습니다. 먼저 문서에서 질문을 생성한 뒤 다시 시도해주세요.\"}");

        Response response = request(HttpMethod.POST, "/api/bots/" + botId + "/eval/runs", ownerToken);

        assertThat(response.status()).isEqualTo(400);
        assertThat(response.json().path("error").path("message").asString())
                .contains("테스트 질문이 없습니다");
    }

    @Test
    @DisplayName("Python 의 422(우리가 잘못 호출)는 사용자 잘못이 아니므로 502 다")
    void python_422_는_502() {
        aiService.enqueue(422, "{\"detail\":[{\"loc\":[\"body\",\"count\"],\"msg\":\"...\"}]}");

        Response response = jsonRequest(HttpMethod.POST,
                "/api/bots/" + botId + "/eval/questions/generate", ownerToken, "{\"count\":3}");

        // 422 는 Spring 이 스키마에 안 맞는 요청을 보냈다는 뜻이다.
        // 사용자에게 "고칠 수 있다"고 말하면 안 되므로 4xx 가 아니라 502 로 답한다.
        assertThat(response.status()).isEqualTo(502);
        assertThat(response.json().path("error").path("code").asString()).isEqualTo("AI_SERVICE_ERROR");
    }

    // ── Python 장애가 우리 장애로 둔갑하지 않는다 ─────────────────────────

    @Test
    @DisplayName("Python 이 처리 중 죽으면 500 이 아니라 503 이다")
    void python_이_죽으면_503() {
        aiService.enqueueAbort();

        Response response = request(HttpMethod.POST, "/api/bots/" + botId + "/eval/runs", ownerToken);

        // 500 이 나가면 "우리 서버가 고장났다"로 읽혀 프론트가 재시도 로직을 잘못 짠다.
        assertThat(response.status()).isEqualTo(503);
        assertThat(response.json().path("error").path("code").asString()).isEqualTo("AI_SERVICE_UNAVAILABLE");
    }

    @Test
    @DisplayName("Python 이 5xx 를 주면 503 이다")
    void python_5xx_는_503() {
        aiService.enqueue(500, "{\"detail\":\"internal\"}");

        Response response = request(HttpMethod.POST, "/api/bots/" + botId + "/eval/runs", ownerToken);

        assertThat(response.status()).isEqualTo(503);
    }

    // ── 정상 흐름 ────────────────────────────────────────────────────────

    @Test
    @DisplayName("질문 생성은 200 이고, Python 응답을 camelCase 로 바꿔 내려준다")
    void 질문생성_정상() {
        UUID questionId = UUID.randomUUID();
        UUID chunkId = UUID.randomUUID();
        aiService.enqueue(200, """
                [{"id":"%s","question":"연차는 며칠인가요?","ground_truth":"15일입니다.",
                  "source_chunk_id":"%s","is_active":true,"created_at":"2026-08-02T00:00:00Z"}]
                """.formatted(questionId, chunkId));

        Response response = jsonRequest(HttpMethod.POST,
                "/api/bots/" + botId + "/eval/questions/generate", ownerToken, "{\"count\":3}");

        assertThat(response.status()).isEqualTo(200);
        JsonNode first = response.json().get(0);
        // snake_case → camelCase 변환이 이 경계에서 일어난다(AGENTS.md 작업 규칙 5).
        assertThat(first.path("groundTruth").asString()).isEqualTo("15일입니다.");
        assertThat(first.path("sourceChunkId").asString()).isEqualTo(chunkId.toString());
        assertThat(first.path("isActive").asBoolean()).isTrue();
        // snake_case 가 새어 나가면 프론트 타입이 전부 거짓이 된다.
        assertThat(response.body()).doesNotContain("ground_truth").doesNotContain("is_active");

        // 요청 본문에 count 가 실려 나갔는가
        assertThat(aiService.received()).hasSize(1);
        assertThat(aiService.received().getFirst().body()).contains("\"count\":3");
    }

    @Test
    @DisplayName("count 를 안 보내도 기본값으로 동작한다")
    void 질문생성_본문_없음() {
        aiService.enqueue(200, "[]");

        Response response = request(HttpMethod.POST,
                "/api/bots/" + botId + "/eval/questions/generate", ownerToken);

        assertThat(response.status()).isEqualTo(200);
        assertThat(aiService.received().getFirst().body()).contains("\"count\":10");
    }

    @Test
    @DisplayName("count 가 0 이하면 Python 까지 가지 않고 400 이다")
    void 질문생성_count_하한() {
        Response response = jsonRequest(HttpMethod.POST,
                "/api/bots/" + botId + "/eval/questions/generate", ownerToken, "{\"count\":0}");

        assertThat(response.status()).isEqualTo(400);
        assertThat(response.json().path("error").path("code").asString()).isEqualTo("INVALID_INPUT");
        // 상한(20)은 Python 이 판단한다. 하한만 여기서 막아 왕복 한 번을 아낀다.
        assertThat(aiService.received()).isEmpty();
    }

    @Test
    @DisplayName("평가 실행은 202 이고 config 를 camelCase 객체로 바꿔 내려준다")
    void 평가실행_정상() {
        UUID runId = UUID.randomUUID();
        aiService.enqueue(202, """
                {"id":"%s","status":"running",
                 "config":{"top_k":5,"max_distance":0.55,"chat_model":"gemini-3.5-flash-lite",
                           "embedding_model":"@cf/baai/bge-m3","judge_model":"@cf/mistralai/x",
                           "hybrid":false,"reranker":false},
                 "avg_faithfulness":null,"avg_relevancy":null,"answered_rate":null,
                 "created_at":"2026-08-02T00:00:00Z"}
                """.formatted(runId));

        Response response = request(HttpMethod.POST, "/api/bots/" + botId + "/eval/runs", ownerToken);

        // 200 이 아니라 202 다. 200 으로 답하면 프론트가 "다 됐다"고 읽고 폴링을 안 한다.
        assertThat(response.status()).isEqualTo(202);
        assertThat(response.json().path("status").asString()).isEqualTo("running");

        JsonNode config = response.json().path("config");
        assertThat(config.path("topK").asInt()).isEqualTo(5);
        assertThat(config.path("maxDistance").asDouble()).isEqualTo(0.55);
        assertThat(config.path("embeddingModel").asString()).isEqualTo("@cf/baai/bge-m3");
        assertThat(response.body()).doesNotContain("top_k").doesNotContain("max_distance");
    }

    @Test
    @DisplayName("[중요] 점수가 없으면 0 이 아니라 null 로 내려간다")
    void 점수_null_은_0_이_아니다() {
        aiService.enqueue(202, """
                {"id":"%s","status":"running","config":null,
                 "avg_faithfulness":null,"avg_relevancy":null,"answered_rate":null,
                 "created_at":"2026-08-02T00:00:00Z"}
                """.formatted(UUID.randomUUID()));

        Response response = request(HttpMethod.POST, "/api/bots/" + botId + "/eval/runs", ownerToken);

        // 0 으로 내려가면 화면이 "품질 0점"이라고 거짓말한다.
        // Double 이 아니라 double 로 받으면 Jackson 이 조용히 0.0 으로 바꾼다.
        assertThat(response.json().path("avgFaithfulness").isNull()).isTrue();
        assertThat(response.json().path("answeredRate").isNull()).isTrue();
    }

    @Test
    @DisplayName("실행 이력은 DB 에서 읽는다 — Python 을 부르지 않는다")
    void 실행이력_조회() {
        insertRun(botId, "completed");

        Response response = request(HttpMethod.GET, "/api/bots/" + botId + "/eval/runs", ownerToken);

        assertThat(response.status()).isEqualTo(200);
        assertThat(response.json()).hasSize(1);
        // 폴링 대상이라 호출이 잦다. Python 이 죽어도 목록은 보여야 한다.
        assertThat(aiService.received()).isEmpty();
    }

    @Test
    @DisplayName("config JSON 이 깨져 있어도 이력 조회가 500 이 되지 않는다")
    void 깨진_config() {
        UUID runId = UUID.randomUUID();
        jdbcTemplate.update(
                "INSERT INTO eval_runs (id, bot_id, config, status) VALUES (?, ?, ?::jsonb, 'completed')",
                runId, botId, "\"이건 객체가 아니라 문자열이다\"");

        Response response = request(HttpMethod.GET, "/api/bots/" + botId + "/eval/runs", ownerToken);

        // 점수는 멀쩡히 있는데 화면이 통째로 안 뜨는 게 더 나쁘다. config 만 null 로 내려간다.
        assertThat(response.status()).isEqualTo(200);
        assertThat(response.json().get(0).path("config").isNull()).isTrue();
    }

    @Test
    @DisplayName("질문별 결과에서 retrievedChunks 가 파싱된 목록으로 나온다")
    void 결과_조회() {
        UUID runId = insertRun(botId, "completed");
        UUID questionId = insertQuestion(botId, "연차는 며칠인가요?", "15일입니다.");
        UUID chunkId = UUID.randomUUID();
        jdbcTemplate.update("""
                INSERT INTO eval_results
                    (run_id, question_id, generated_answer, retrieved_chunks, faithfulness, relevancy)
                VALUES (?, ?, ?, ?::jsonb, ?, ?)""",
                runId, questionId, "연차는 15일입니다.",
                "[{\"chunk_id\":\"" + chunkId + "\",\"filename\":\"규정.md\",\"score\":0.87}]",
                0.9, 1.0);

        Response response = request(HttpMethod.GET,
                "/api/bots/" + botId + "/eval/runs/" + runId + "/results", ownerToken);

        assertThat(response.status()).isEqualTo(200);
        JsonNode first = response.json().get(0);
        assertThat(first.path("question").asString()).isEqualTo("연차는 며칠인가요?");
        assertThat(first.path("groundTruth").asString()).isEqualTo("15일입니다.");
        // 문자열이 아니라 <파싱된 배열>이어야 한다. 문자열로 내려가면 프론트가 또 파싱해야 하고
        // 그 규칙이 두 벌이 되어 언젠가 어긋난다.
        assertThat(first.path("retrievedChunks").isArray()).isTrue();
        assertThat(first.path("retrievedChunks").get(0).path("filename").asString()).isEqualTo("규정.md");
        assertThat(response.body()).doesNotContain("chunk_id");
    }

    @Test
    @DisplayName("retrieved_chunks JSON 이 깨져 있어도 결과 조회가 500 이 되지 않는다")
    void 깨진_retrieved_chunks() {
        UUID runId = insertRun(botId, "completed");
        UUID questionId = insertQuestion(botId, "질문", "정답");
        jdbcTemplate.update("""
                INSERT INTO eval_results (run_id, question_id, generated_answer, retrieved_chunks)
                VALUES (?, ?, ?, ?::jsonb)""",
                runId, questionId, "답변", "{\"이건\":\"배열이 아니다\"}");

        Response response = request(HttpMethod.GET,
                "/api/bots/" + botId + "/eval/runs/" + runId + "/results", ownerToken);

        assertThat(response.status()).isEqualTo(200);
        // 근거를 못 보여줄 뿐 나머지는 다 보인다.
        assertThat(response.json().get(0).path("retrievedChunks").isArray()).isTrue();
        assertThat(response.json().get(0).path("retrievedChunks")).isEmpty();
        assertThat(response.json().get(0).path("generatedAnswer").asString()).isEqualTo("답변");
    }

    @Test
    @DisplayName("[중요] 채점 안 된 결과는 0 이 아니라 null 로 내려간다")
    void 미채점_결과는_null() {
        UUID runId = insertRun(botId, "completed");
        UUID questionId = insertQuestion(botId, "질문", "정답");
        jdbcTemplate.update("""
                INSERT INTO eval_results (run_id, question_id, generated_answer, faithfulness, relevancy)
                VALUES (?, ?, ?, NULL, NULL)""",
                runId, questionId, "문서에서 답을 찾지 못했어요.");

        Response response = request(HttpMethod.GET,
                "/api/bots/" + botId + "/eval/runs/" + runId + "/results", ownerToken);

        JsonNode first = response.json().get(0);
        // null 은 "채점하지 못했다"이지 0점이 아니다. fallback 이라 채점 대상이 아니었거나
        // 채점 호출이 실패한 경우인데, 0 으로 내려가면 품질 저하로 둔갑한다.
        assertThat(first.path("faithfulness").isNull()).isTrue();
        assertThat(first.path("relevancy").isNull()).isTrue();
    }

    @Test
    @DisplayName("질문 목록에는 비활성 질문도 함께 나온다 — 껐다 켜야 하기 때문")
    void 질문목록_비활성_포함() {
        insertQuestion(botId, "활성 질문", "정답1");
        UUID inactive = insertQuestion(botId, "비활성 질문", "정답2");
        jdbcTemplate.update("UPDATE eval_questions SET is_active = false WHERE id = ?", inactive);

        Response response = request(HttpMethod.GET, "/api/bots/" + botId + "/eval/questions", ownerToken);

        assertThat(response.status()).isEqualTo(200);
        // 꺼진 질문이 안 보이면 다시 켤 방법이 없다.
        assertThat(response.json()).hasSize(2);
        assertThat(response.body()).contains("비활성 질문");
    }

    @Test
    @DisplayName("질문 목록에 남의 봇 질문이 섞이지 않는다")
    void 질문목록은_내_봇만() {
        UUID otherBotId = createBot(ownerToken);
        insertQuestion(botId, "내 봇 질문", "정답");
        insertQuestion(otherBotId, "다른 봇 질문", "정답");

        Response response = request(HttpMethod.GET, "/api/bots/" + botId + "/eval/questions", ownerToken);

        assertThat(response.json()).hasSize(1);
        assertThat(response.body()).contains("내 봇 질문").doesNotContain("다른 봇 질문");
    }

    // ── 테스트 보조 ──────────────────────────────────────────────────────

    private String signup(String email) {
        return jsonRequest(HttpMethod.POST, "/api/auth/signup", null,
                new SignupRequest(email, PASSWORD, null)).json().path("token").asString();
    }

    private UUID createBot(String token) {
        return UUID.fromString(jsonRequest(HttpMethod.POST, "/api/bots", token,
                new CreateBotRequest("테스트 봇")).json().path("id").asString());
    }

    /** Python 이 넣어둔 실행을 흉내낸다. Spring 코드로는 INSERT 할 수 없다(쓰기 소유자가 Python). */
    private UUID insertRun(UUID botId, String status) {
        UUID id = UUID.randomUUID();
        jdbcTemplate.update(
                "INSERT INTO eval_runs (id, bot_id, config, status) VALUES (?, ?, ?::jsonb, ?)",
                id, botId, "{\"top_k\":5,\"max_distance\":0.55}", status);
        return id;
    }

    private UUID insertQuestion(UUID botId, String question, String groundTruth) {
        UUID id = UUID.randomUUID();
        jdbcTemplate.update(
                "INSERT INTO eval_questions (id, bot_id, question, ground_truth) VALUES (?, ?, ?, ?)",
                id, botId, question, groundTruth);
        return id;
    }

    private Response request(HttpMethod method, String uri, String token) {
        EntityExchangeResult<byte[]> result = client.method(method).uri(uri)
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + token)
                .exchange().expectBody().returnResult();
        return new Response(result.getStatus().value(), decode(result.getResponseBody()));
    }

    private Response jsonRequest(HttpMethod method, String uri, String token, Object body) {
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

    /** 한국어 에러 메시지가 깨지지 않도록 UTF-8 을 명시해 디코딩한다. */
    private static String decode(byte[] raw) {
        return raw == null ? "" : new String(raw, StandardCharsets.UTF_8);
    }
}
