package com.alldap.api.domain.chat;

import com.alldap.api.global.client.AiServiceCircuitBreaker;
import com.alldap.api.domain.auth.dto.SignupRequest;
import com.alldap.api.domain.bot.dto.CreateBotRequest;
import com.alldap.api.domain.bot.dto.UpdateBotRequest;
import com.alldap.api.domain.chat.dto.ChatRequest;
import com.alldap.api.domain.chat.dto.FeedbackRequest;
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
import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 채팅·피드백 API 통합 테스트.
 *
 * <p>이 슬라이스에서 지키려는 것은 셋이다.
 *
 * <ol>
 *   <li><b>fallback 치환.</b> Python 은 봇별 거절 문구를 모른다. Spring 이 {@code is_fallback} 을 보고
 *       봇의 {@code fallbackMessage} 로 바꿔야 하고, <b>DB 에도 사용자가 실제로 본 문장</b>이 남아야 한다.
 *       이 제품의 핵심 가치(환각 억제)가 사용자 눈에 드러나는 지점이다.</li>
 *   <li><b>트랜잭션 경계.</b> Python 호출이 실패해도 질문은 남고, 답변 행만 없어야 한다.
 *       ("질문도 답도 없음"이면 트랜잭션이 통째로 묶여 있었다는 뜻이다)</li>
 *   <li><b>소유권 격리.</b> 남의 봇에 채팅하거나 남의 메시지에 피드백을 남길 수 없다.</li>
 * </ol>
 */
@IntegrationTest
@DisplayName("채팅 API 통합 테스트")
class ChatIntegrationTest {

    private static final String PASSWORD = "correct-password-1234";
    private static final String SESSION = "sess-test-0001";

    /** Python 이 근거를 찾아 정상 답변한 경우. */
    private static final String 정상응답 = """
            {"answer":"휴학은 매 학기 개강 후 30일 이내에 신청합니다.",
             "sources":[{"chunk_id":"22222222-2222-2222-2222-222222222222",
                         "document_id":"33333333-3333-3333-3333-333333333333",
                         "filename":"학사규정.pdf","score":0.87,"preview":"휴학 신청은 개강 후 30일 이내"}],
             "is_fallback":false,"latency_ms":1234}""";

    /**
     * Python 이 답변을 <받지 못한> 경우. {@code generator.GenerationFailed} → chat 의 503 이다.
     * 🔴 {@code detail} 이 문자열이 아니라 <b>객체</b>인 것이 이 실패를 "Python 이 아프다" 와
     * 가르는 유일한 신호다. Python 쪽 문구와 짝을 맞춰야 하는 API 컨트랙트다.
     */
    private static final String 잘림응답 = """
            {"detail":{"code":"GENERATION_INCOMPLETE",
                       "message":"답변을 완성하지 못했습니다. 질문을 더 좁혀서 다시 물어봐 주세요."}}""";

    /** Python 이 근거를 못 찾아 거절한 경우. answer 는 Python 의 기본 문구다. */
    private static final String 거절응답 = """
            {"answer":"문서에서 관련 내용을 찾지 못했습니다.","sources":[],
             "is_fallback":true,"latency_ms":210}""";

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
    private JdbcTemplate jdbcTemplate;

    // 지표 검증용. 컨텍스트를 공유하는 다른 테스트가 이미 값을 올려놨을 수 있으므로
    // 절대값이 아니라 <이 테스트 안에서의 증가분>만 본다.
    @Autowired
    private io.micrometer.core.instrument.MeterRegistry meterRegistry;

    private RestTestClient client;
    private String ownerToken;
    private String intruderToken;
    private UUID botId;

    @BeforeEach
    void setUp() {
        client = RestTestClient.bindToServer().baseUrl("http://localhost:" + port).build();
        userRepository.deleteAll();   // bots → conversations → messages 가 CASCADE 로 함께 사라진다
        aiService.reset();
        circuitBreaker.reset();

        ownerToken = signup("owner@example.com");
        intruderToken = signup("intruder@example.com");
        botId = createBot(ownerToken);
    }

    // ── 정상 흐름 ────────────────────────────────────────────────────────

    @Test
    @DisplayName("질문하면 답변·근거·messageId 가 오고, 대화와 메시지 2건이 저장된다")
    void 채팅_성공() {
        aiService.enqueue(200, 정상응답);

        Response response = chat(ownerToken, botId, "휴학 신청 기간이 언제야?");

        assertThat(response.status()).isEqualTo(200);
        JsonNode body = response.json();
        assertThat(body.path("answer").asString()).contains("30일");
        assertThat(body.path("isFallback").asBoolean()).isFalse();
        assertThat(body.path("latencyMs").asInt()).isEqualTo(1234);
        // messageId 가 없으면 프론트가 👍/👎 를 호출할 수 없다 — 이 값은 Spring 만 안다.
        assertThat(body.path("messageId").asString()).isNotBlank();

        // Python 의 snake_case 가 camelCase 로 바뀌어 나가는지 (프론트 타입 계약)
        assertThat(body.path("sources").get(0).path("chunkId").asString()).isNotBlank();
        assertThat(response.body()).doesNotContain("chunk_id").doesNotContain("is_fallback");

        // 질문 + 답변 두 건이 남는다
        assertThat(countMessages()).isEqualTo(2);
        assertThat(countConversations()).isEqualTo(1);
    }

    @Test
    @DisplayName("관리자 테스트 채팅은 channel='test' 로 기록된다 (품질 지표에서 제외하기 위해)")
    void 채널이_test로_기록된다() {
        aiService.enqueue(200, 정상응답);

        chat(ownerToken, botId, "질문");

        String channel = jdbcTemplate.queryForObject(
                "SELECT channel FROM conversations WHERE bot_id = ?", String.class, botId);
        // 관리자가 돌려본 대화가 실사용 수치에 섞이면 응답률·미답변 목록이 왜곡된다.
        assertThat(channel).isEqualTo("test");
    }

    @Test
    @DisplayName("같은 sessionId 로 다시 질문하면 대화가 이어진다 (대화 1건, 메시지 4건)")
    void 같은_세션이면_대화가_이어진다() {
        aiService.enqueue(200, 정상응답);
        aiService.enqueue(200, 정상응답);

        chat(ownerToken, botId, "첫 질문");
        chat(ownerToken, botId, "두 번째 질문");

        assertThat(countConversations()).isEqualTo(1);
        assertThat(countMessages()).isEqualTo(4);
    }

    @Test
    @DisplayName("근거 청크는 messages.sources 에 우리 camelCase 형식으로 저장된다")
    void 근거가_JSONB로_저장된다() {
        aiService.enqueue(200, 정상응답);

        chat(ownerToken, botId, "질문");

        String sources = jdbcTemplate.queryForObject(
                "SELECT sources::text FROM messages WHERE role = 'assistant'", String.class);
        assertThat(sources).isNotNull();
        // 저장 형식이 공개 API 형식과 같아야 로그 화면에서 파싱해 그대로 내려줄 수 있다.
        assertThat(sources).contains("chunkId").doesNotContain("chunk_id");
        assertThat(sources).contains("학사규정.pdf");
    }

    // ── fallback 치환 (제품의 핵심 가치) ──────────────────────────────────

    @Test
    @DisplayName("[핵심] 근거를 못 찾으면 Python 문구가 아니라 봇의 fallbackMessage 가 나가고, DB 에도 그게 남는다")
    void fallback_치환() {
        String 봇문구 = "규정집에서 답을 찾지 못했어요. 학사지원팀(02-000-0000)으로 문의해주세요.";
        request(HttpMethod.PATCH, "/api/bots/" + botId, ownerToken,
                new UpdateBotRequest(null, null, null, 봇문구, null));

        aiService.enqueue(200, 거절응답);

        Response response = chat(ownerToken, botId, "학식 메뉴 알려줘");

        assertThat(response.status()).isEqualTo(200);
        JsonNode body = response.json();
        assertThat(body.path("isFallback").asBoolean()).isTrue();
        // Python 은 봇별 문구를 모른다. Spring 이 치환하지 않으면 봇마다 같은 문구가 나간다.
        assertThat(body.path("answer").asString()).isEqualTo(봇문구);
        assertThat(response.body()).doesNotContain("문서에서 관련 내용을 찾지 못했습니다");

        // ⚠️ DB 에도 <사용자가 실제로 본 문장>이 남아야 한다.
        // Python 원본을 저장하면 나중에 로그를 봐도 사용자가 뭘 봤는지 알 수 없다.
        String saved = jdbcTemplate.queryForObject(
                "SELECT content FROM messages WHERE role = 'assistant'", String.class);
        assertThat(saved).isEqualTo(봇문구);

        // 품질 대시보드의 미답변 집계가 전부 이 컬럼에서 나온다. 기록을 생략하면 W3 이 성립하지 않는다.
        Boolean isFallback = jdbcTemplate.queryForObject(
                "SELECT is_fallback FROM messages WHERE role = 'assistant'", Boolean.class);
        assertThat(isFallback).isTrue();
    }

    @Test
    @DisplayName("Python 이 근거를 하나도 주지 않으면 sources 는 null 로 저장된다")
    void 근거가_아예_없으면_sources는_null() {
        aiService.enqueue(200, 거절응답);   // sources: []

        chat(ownerToken, botId, "질문");

        Integer nonNull = jdbcTemplate.queryForObject(
                "SELECT count(*) FROM messages WHERE role='assistant' AND sources IS NOT NULL", Integer.class);
        assertThat(nonNull).isZero();
    }

    @Test
    @DisplayName("fallback 이어도 근거가 딸려 오면 그대로 저장한다 (실제 Python 이 이렇게 동작한다)")
    void fallback이어도_근거가_있으면_저장한다() {
        // ⚠️ 이 테스트는 종단 확인에서 배운 것을 고정한다.
        // 위 테스트가 쓰는 거절응답은 sources 가 비어 있지만, <실제 Python 은 그렇지 않다>.
        // 검색 컷오프(max_distance=0.55)를 통과한 청크가 있는 채로 생성 단계에서 NO_ANSWER 가 나면
        // is_fallback=true 인데 sources 는 1건 이상 딸려 온다 — 실측에서 그랬다.
        // "무엇을 근거로 봤는데도 답을 못 했나" 가 남아야 W3 미답변 분석에 쓸 수 있다.
        aiService.enqueue(200, """
                {"answer":"문서에서 관련 내용을 찾지 못했습니다.",
                 "sources":[{"chunk_id":"22222222-2222-2222-2222-222222222222",
                             "document_id":"33333333-3333-3333-3333-333333333333",
                             "filename":"학사규정.pdf","score":0.58,"preview":"휴학 신청은"}],
                 "is_fallback":true,"latency_ms":300}""");

        Response response = chat(ownerToken, botId, "학식 메뉴 알려줘");

        assertThat(response.json().path("isFallback").asBoolean()).isTrue();
        assertThat(response.json().path("sources").size()).isEqualTo(1);

        String sources = jdbcTemplate.queryForObject(
                "SELECT sources::text FROM messages WHERE role = 'assistant'", String.class);
        assertThat(sources).isNotNull().contains("학사규정.pdf");
    }

    // ── 재시도 · 서킷브레이커 ────────────────────────────────────────────

    @Test
    @DisplayName("[재시도] 🔴 Python 5xx 는 재시도하지 않는다 — 요청이 이미 도달했기 때문이다")
    void 오류응답은_재시도하지_않는다() {
        // 5xx 는 Python 이 <응답을 준> 것이다 = 요청이 도달했다 = 부작용이 남았을 수 있다.
        // 재시도하면 같은 작업이 두 번 돈다(LLM 이 두 번 과금되거나 행이 중복된다).
        // 요청을 1건만 큐에 넣고, 스텁이 <정확히 1건만> 받았는지로 확인한다.
        aiService.enqueue(500, "{\"detail\":\"boom\"}");

        Response response = chat(ownerToken, botId, "질문");

        assertThat(response.status()).isEqualTo(503);
        assertThat(aiService.received()).hasSize(1);
    }

    @Test
    @DisplayName("[잘림] 🔴 답변이 잘리면 422 ANSWER_INCOMPLETE 다. 재시도하라고 안내하지 않는다")
    void 답변이_잘리면_재시도_안내를_하지_않는다() {
        // Python 이 generator.GenerationFailed 를 만났을 때 실제로 주는 본문이다
        // (ai-service/app/main.py 의 chat 503). detail 이 <객체>인 것이 신호다.
        aiService.enqueue(503, 잘림응답);

        Response response = chat(ownerToken, botId, "회사 규정 전체를 요약해줘");

        // 🔴 503(AI_SERVICE_UNAVAILABLE)이 아니다. 생성은 temperature=0 이라 다시 물어도
        //    같은 자리에서 잘린다. "잠시 후 다시 시도해주세요" 는 거짓 안내였다.
        assertThat(response.status()).isEqualTo(422);
        assertThat(response.json().path("error").path("code").asString()).isEqualTo("ANSWER_INCOMPLETE");
        // 안내가 사용자에게 <무엇을 하라고> 말하는지까지 고정한다. 코드만 보면
        // 문구가 옛날로 돌아가도 테스트가 통과한다.
        assertThat(response.json().path("error").path("message").asString())
                .contains("질문을 더 좁혀서")
                .doesNotContain("잠시 후");

        // 답변을 <받지 못한> 것이므로 assistant 행이 생기면 안 된다.
        // (fallback 이었다면 "문서에서 찾지 못했다" 답변 행이 남는다. 그것과 다른 사실이다)
        assertThat(countMessagesByRole("user")).isEqualTo(1);
        assertThat(countMessagesByRole("assistant")).isZero();
    }

    @Test
    @DisplayName("[잘림] 🔴 잘림은 서킷 실패로 세지 않는다. 질문 하나가 나빴을 뿐 Python 은 멀쩡하다")
    void 잘림은_서킷을_열지_않는다() {
        // 서킷 임계치(5)만큼 잘림을 낸 뒤에도 다음 요청이 Python 까지 가야 한다.
        // 세었다면 여기서 서킷이 열려 아래 요청은 호출 없이 503 이 된다.
        for (int i = 0; i < 5; i++) {
            aiService.enqueue(503, 잘림응답);
            chat(ownerToken, botId, "잘리는 질문 " + i);
        }
        int callsBefore = aiService.received().size();
        aiService.enqueue(200, 정상응답);

        Response response = chat(ownerToken, botId, "짧은 질문");

        assertThat(response.status()).isEqualTo(200);
        // 🔴 핵심: 요청이 실제로 나갔다 = 서킷이 닫혀 있었다.
        assertThat(aiService.received()).hasSize(callsBefore + 1);
    }

    @Test
    @DisplayName("[서킷] 연속 실패가 임계치를 넘으면 Python 을 호출하지 않고 즉시 안내한다")
    void 서킷이_열리면_호출하지_않는다() {
        // 임계치(5)만큼 실패시킨다. 매번 스텁이 요청을 받는다.
        for (int i = 0; i < 5; i++) {
            aiService.enqueue(500, "{}");
            chat(ownerToken, botId, "질문 " + i);
        }
        int callsBeforeOpen = aiService.received().size();

        Response response = chat(ownerToken, botId, "서킷이 열린 뒤의 질문");

        assertThat(response.status()).isEqualTo(503);
        assertThat(response.json().path("error").path("code").asString()).isEqualTo("AI_SERVICE_UNAVAILABLE");
        // 🔴 핵심: 요청 수가 <늘지 않았다> = 아예 호출하지 않았다.
        //    이게 스레드를 지키는 방식이다 — 연결 타임아웃 3초를 기다리지도 않는다.
        assertThat(aiService.received()).hasSize(callsBeforeOpen);
    }

    @Test
    @DisplayName("[지표] 🔴 급속 503(서킷이 막음)과 느린 503(Python 5xx)이 지표에서 갈린다")
    void 두_종류의_503이_지표에서_갈린다() {
        double 서킷거절_전 = 호출수("chat", "circuit_open");
        double 파이썬오류_전 = 호출수("chat", "python_5xx");

        for (int i = 0; i < 5; i++) {
            aiService.enqueue(500, "{}");
            chat(ownerToken, botId, "질문 " + i);
        }
        Response 급속거절 = chat(ownerToken, botId, "서킷이 열린 뒤의 질문");

        // 사용자에게 나가는 응답은 여섯 번 다 똑같다. 이게 뭉개짐의 정체다 —
        // http_server_requests{status="503"} 만 보면 여섯 건이 한 덩어리다.
        assertThat(급속거절.status()).isEqualTo(503);
        assertThat(급속거절.json().path("error").path("code").asString()).isEqualTo("AI_SERVICE_UNAVAILABLE");

        // 🔴 지표에서는 갈린다. 원인이 다르고 볼 곳이 다르므로 같은 값이면 안 된다.
        assertThat(호출수("chat", "python_5xx") - 파이썬오류_전).isEqualTo(5);
        assertThat(호출수("chat", "circuit_open") - 서킷거절_전).isEqualTo(1);
    }

    private double 호출수(String operation, String outcome) {
        io.micrometer.core.instrument.Timer timer = meterRegistry.find("alldap.ai.call")
                .tag("operation", operation)
                .tag("outcome", outcome)
                .timer();
        return timer == null ? 0 : timer.count();
    }

    // ── 트랜잭션 경계 ────────────────────────────────────────────────────

    @Test
    @DisplayName("[트랜잭션] Python 이 죽으면 503 이고, 질문은 남되 답변 행은 생기지 않는다")
    void Python_장애시_질문만_남는다() {
        aiService.enqueueAbort();

        Response response = chat(ownerToken, botId, "질문");

        assertThat(response.status()).isEqualTo(503);
        assertThat(response.json().path("error").path("code").asString()).isEqualTo("AI_SERVICE_UNAVAILABLE");

        // 질문이 남아 있다는 것은 저장이 <Python 호출 전에 이미 커밋됐다>는 뜻이다.
        // 하나의 트랜잭션으로 묶여 있었다면 롤백돼 0건이었을 것이고,
        // 그 말은 수십 초짜리 Python 호출 동안 DB 커넥션을 붙잡고 있었다는 뜻이 된다.
        assertThat(countMessagesByRole("user")).isEqualTo(1);
        assertThat(countMessagesByRole("assistant")).isZero();
    }

    @Test
    @DisplayName("[장애] Python 이 느리면 504 다 (읽기 타임아웃)")
    void Python이_느리면_504() {
        aiService.enqueueSlow(Duration.ofSeconds(5), 200, 정상응답);

        Response response = chat(ownerToken, botId, "질문");

        assertThat(response.status()).isEqualTo(504);
        assertThat(response.json().path("error").path("code").asString()).isEqualTo("AI_SERVICE_TIMEOUT");
    }

    @Test
    @DisplayName("[장애] Python 이 4xx 면 파일 관련 문구가 아니라 채팅에 맞는 오류가 나간다")
    void Python_4xx는_파일오류가_아니다() {
        aiService.enqueue(422, "{\"detail\":[{\"loc\":[\"body\",\"message\"],\"msg\":\"too long\"}]}");

        Response response = chat(ownerToken, botId, "질문");

        // 업로드용 4xx 매퍼를 그대로 재사용하면 여기서 "지원하지 않는 파일 형식입니다"가 나간다.
        assertThat(response.body()).doesNotContain("파일");
        assertThat(response.json().path("error").path("code").asString()).isEqualTo("AI_SERVICE_ERROR");
    }

    // ── 소유권 격리 ──────────────────────────────────────────────────────

    @Test
    @DisplayName("[보안] 남의 봇에 채팅하면 404 이고, 질문이 Python 까지 가지 않는다")
    void 남의_봇에_채팅() {
        Response response = chat(intruderToken, botId, "남의 봇에 질문");

        assertThat(response.status()).isEqualTo(404);
        assertThat(response.json().path("error").path("code").asString()).isEqualTo("BOT_NOT_FOUND");
        assertThat(aiService.received()).isEmpty();
        // 남의 봇 대화 로그에 흔적을 남길 수도 없어야 한다.
        assertThat(countMessages()).isZero();
    }

    // ── 피드백 ───────────────────────────────────────────────────────────

    @Test
    @DisplayName("답변에 👍 를 남기면 204 이고 DB 에 기록된다")
    void 피드백_성공() {
        aiService.enqueue(200, 정상응답);
        UUID messageId = UUID.fromString(chat(ownerToken, botId, "질문").json().path("messageId").asString());

        Response response = request(HttpMethod.POST, "/api/messages/" + messageId + "/feedback",
                ownerToken, new FeedbackRequest((short) 1));

        assertThat(response.status()).isEqualTo(204);
        Short saved = jdbcTemplate.queryForObject(
                "SELECT feedback FROM messages WHERE id = ?", Short.class, messageId);
        assertThat(saved).isEqualTo((short) 1);
    }

    @Test
    @DisplayName("[보안] 남의 메시지에 피드백을 남기면 404 다")
    void 남의_메시지에_피드백() {
        aiService.enqueue(200, 정상응답);
        UUID messageId = UUID.fromString(chat(ownerToken, botId, "질문").json().path("messageId").asString());

        Response response = request(HttpMethod.POST, "/api/messages/" + messageId + "/feedback",
                intruderToken, new FeedbackRequest((short) -1));

        assertThat(response.status()).isEqualTo(404);
        assertThat(response.json().path("error").path("code").asString()).isEqualTo("MESSAGE_NOT_FOUND");

        // 없는 메시지와 응답이 같아야 "그 id 의 메시지가 존재하는지"가 새지 않는다.
        Response 없는메시지 = request(HttpMethod.POST, "/api/messages/" + UUID.randomUUID() + "/feedback",
                intruderToken, new FeedbackRequest((short) -1));
        assertThat(response.body()).isEqualTo(없는메시지.body());
    }

    @Test
    @DisplayName("질문(user 메시지)에는 피드백을 남길 수 없다")
    void 질문에는_피드백_불가() {
        aiService.enqueue(200, 정상응답);
        chat(ownerToken, botId, "질문");
        UUID userMessageId = UUID.fromString(jdbcTemplate.queryForObject(
                "SELECT id::text FROM messages WHERE role = 'user'", String.class));

        Response response = request(HttpMethod.POST, "/api/messages/" + userMessageId + "/feedback",
                ownerToken, new FeedbackRequest((short) 1));

        // 질문에 "도움이 됐다"를 매기면 품질 지표가 오염된다. 엔티티가 막는다.
        assertThat(response.status()).isEqualTo(400);
        assertThat(response.json().path("error").path("message").asString()).contains("답변");
    }

    @Test
    @DisplayName("피드백 값 0 은 거절한다 (@Min/@Max 만으로는 통과하는 값)")
    void 피드백_0은_거절() {
        aiService.enqueue(200, 정상응답);
        UUID messageId = UUID.fromString(chat(ownerToken, botId, "질문").json().path("messageId").asString());

        Response response = request(HttpMethod.POST, "/api/messages/" + messageId + "/feedback",
                ownerToken, new FeedbackRequest((short) 0));

        // FeedbackRequest 의 @Min(-1) @Max(1) 은 0 을 통과시킨다. 엔티티가 마지막 방어선이다.
        assertThat(response.status()).isEqualTo(400);
    }

    // ── 컨트랙트 갭 (거짓 완성 방지) ──────────────────────────────────────

    @Test
    @DisplayName("systemPrompt 는 Python 요청에 실리지 않는다 — 저장은 되지만 답변에 반영되지 않는다")
    void systemPrompt는_아직_전달되지_않는다() {
        request(HttpMethod.PATCH, "/api/bots/" + botId, ownerToken,
                new UpdateBotRequest(null, "너는 학사 담당자다. 반드시 존댓말로 답하라.", null, null, null));
        aiService.enqueue(200, 정상응답);

        chat(ownerToken, botId, "질문");

        // 이 단언은 "동작하지 않음"을 <고정>하기 위한 것이다.
        // Python 의 ChatRequest 스키마에 자리가 없어 보낼 방법이 없다(AiChatRequest 주석).
        // 나중에 Python 을 고쳐 실어 보내게 되면 이 테스트가 깨지고,
        // 그때 문서의 "알려진 한계"도 함께 지우게 된다 — 그게 이 테스트의 목적이다.
        String sent = aiService.received().get(0).body();
        assertThat(sent).contains("bot_id").contains("message").contains("session_id");
        assertThat(sent).doesNotContain("존댓말");
        assertThat(sent).doesNotContain("system_prompt");
    }

    // ── 테스트 보조 ──────────────────────────────────────────────────────

    private Response chat(String token, UUID botId, String message) {
        return request(HttpMethod.POST, "/api/bots/" + botId + "/chat", token,
                new ChatRequest(message, SESSION));
    }

    private String signup(String email) {
        return request(HttpMethod.POST, "/api/auth/signup", null,
                new SignupRequest(email, PASSWORD, null)).json().path("token").asString();
    }

    private UUID createBot(String token) {
        return UUID.fromString(request(HttpMethod.POST, "/api/bots", token,
                new CreateBotRequest("테스트 봇")).json().path("id").asString());
    }

    private int countMessages() {
        return jdbcTemplate.queryForObject("SELECT count(*) FROM messages", Integer.class);
    }

    private int countMessagesByRole(String role) {
        return jdbcTemplate.queryForObject(
                "SELECT count(*) FROM messages WHERE role = ?", Integer.class, role);
    }

    private int countConversations() {
        return jdbcTemplate.queryForObject("SELECT count(*) FROM conversations", Integer.class);
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

    /** 한국어가 깨지지 않도록 UTF-8 을 명시해 디코딩한다. */
    private static String decode(byte[] raw) {
        return raw == null ? "" : new String(raw, StandardCharsets.UTF_8);
    }
}
