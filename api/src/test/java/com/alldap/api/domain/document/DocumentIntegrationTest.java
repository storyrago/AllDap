package com.alldap.api.domain.document;

import com.alldap.api.global.client.AiServiceCircuitBreaker;
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
import org.springframework.core.io.ByteArrayResource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.client.EntityExchangeResult;
import org.springframework.test.web.servlet.client.RestTestClient;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 문서 API 통합 테스트.
 *
 * <p>이 슬라이스는 <b>Spring 이 Python 을 처음으로 호출하는 지점</b>이다.
 * 그래서 지키려는 것이 앞선 슬라이스들과 다르다.
 *
 * <ol>
 *   <li><b>Python 을 부르기 전에 소유권을 막는다.</b> Python 의 {@code /internal/*} 에는 인증이 없다.
 *       404 를 돌려주는 것만으로는 부족하고, <b>요청이 Python 까지 가지 않았음</b>을 확인해야 한다.
 *       남의 봇 문서가 Python 에 도달했다면 그 시점에 이미 정보가 샌 것이다.</li>
 *   <li><b>Python 의 장애가 우리 장애로 둔갑하지 않는다.</b> Python 이 죽거나 느릴 때
 *       500(우리 잘못)이 아니라 503/504(의존 서비스 문제)가 나가야 프론트가 올바르게 대응한다.</li>
 *   <li><b>파일명이 Python 까지 살아서 간다.</b> multipart 에 파일명이 안 실리면
 *       Python 의 {@code detect_type()} 이 확장자를 못 읽어 멀쩡한 파일도 거절된다.</li>
 * </ol>
 *
 * <p>Python 자리에는 {@link AiServiceStub}(진짜 HTTP 서버)을 세운다. 이유는 그 클래스 주석 참고.
 */
@IntegrationTest
@DisplayName("문서 API 통합 테스트")
class DocumentIntegrationTest {

    private static final String PASSWORD = "correct-password-1234";

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

    /**
     * {@code documents} 행을 직접 넣는 데 쓴다.
     *
     * <p>Spring 코드로는 넣을 수 없다 — 이 테이블의 <b>쓰기 소유자가 Python</b>이라
     * 엔티티에 정적 팩토리조차 두지 않았다(그게 규칙이다).
     * 그래서 테스트에서는 SQL 로 "Python 이 넣어둔 상태"를 만든다.
     */
    @Autowired
    private JdbcTemplate jdbcTemplate;

    private RestTestClient client;
    private String ownerToken;
    private String intruderToken;
    private UUID botId;

    @BeforeEach
    void setUp() {
        client = RestTestClient.bindToServer().baseUrl("http://localhost:" + port).build();

        // 실제 HTTP 라 테스트 트랜잭션 롤백이 통하지 않는다. users 를 지우면
        // bots → documents 가 DB 의 ON DELETE CASCADE 로 함께 사라진다.
        userRepository.deleteAll();
        aiService.reset();
        circuitBreaker.reset();

        ownerToken = signup("owner@example.com");
        intruderToken = signup("intruder@example.com");
        botId = createBot(ownerToken);
    }

    // ── 소유권: Python 을 부르기 전에 막는다 ──────────────────────────────

    @Test
    @DisplayName("[보안] 남의 봇에 문서를 올리면 404 이고, 요청이 Python 까지 가지 않는다")
    void 남의_봇에_업로드() {
        Response response = upload(intruderToken, botId, "규정.pdf", "내용");

        assertThat(response.status()).isEqualTo(404);
        assertThat(response.json().path("error").path("code").asString()).isEqualTo("BOT_NOT_FOUND");

        // 이 줄이 이 테스트의 핵심이다. Python 에는 인증이 없으므로,
        // 요청이 거기까지 갔다면 404 를 돌려줬든 말든 이미 남의 봇에 문서가 들어간 뒤다.
        assertThat(aiService.received()).isEmpty();
    }

    @Test
    @DisplayName("[보안] 남의 봇 문서 목록을 조회하면 404 다")
    void 남의_봇_문서목록() {
        Response response = request(HttpMethod.GET, "/api/bots/" + botId + "/documents", intruderToken);

        assertThat(response.status()).isEqualTo(404);
        assertThat(response.json().path("error").path("code").asString()).isEqualTo("BOT_NOT_FOUND");
    }

    @Test
    @DisplayName("[보안] 문서 목록에 남의 봇 문서가 섞이지 않는다")
    void 목록은_내_봇의_문서만() {
        insertDocument(botId, "내문서.pdf", "ready");

        UUID 남의봇 = createBot(intruderToken);
        insertDocument(남의봇, "남의문서.pdf", "ready");

        JsonNode documents = request(HttpMethod.GET, "/api/bots/" + botId + "/documents", ownerToken).json();

        // ⚠️ 이 테스트가 없으면 조회를 findAll() 로 바꿔도 나머지 테스트가 전부 통과한다.
        // 실제로 리뷰 중에 그 회귀를 넣어봤고, 이 테스트가 생기기 전에는 CI 가 잡지 못했다.
        // "남의 봇 조회는 404" 만으로는 부족하다 — 막아야 할 것은 <내 목록에 남의 것이 섞이는> 경로다.
        assertThat(documents.size()).isEqualTo(1);
        assertThat(documents.get(0).path("filename").asString()).isEqualTo("내문서.pdf");
        // 응답 전체를 문자열로도 훑는다. 필드 하나씩 보면 나중에 필드가 추가됐을 때 놓친다.
        assertThat(documents.toString()).doesNotContain("남의문서.pdf");
    }

    @Test
    @DisplayName("[보안] 남의 문서를 삭제하면 404 이고, 삭제 요청이 Python 까지 가지 않는다")
    void 남의_문서_삭제() {
        UUID documentId = insertDocument(botId, "규정.pdf", "ready");

        Response response = request(HttpMethod.DELETE, "/api/documents/" + documentId, intruderToken);

        assertThat(response.status()).isEqualTo(404);
        assertThat(response.json().path("error").path("code").asString()).isEqualTo("DOCUMENT_NOT_FOUND");
        assertThat(aiService.received()).isEmpty();

        // 없는 문서와 응답이 같아야 "그 id 의 문서가 존재하는지"가 새지 않는다.
        Response 없는문서 = request(HttpMethod.DELETE, "/api/documents/" + UUID.randomUUID(), intruderToken);
        assertThat(response.body()).isEqualTo(없는문서.body());
    }

    @Test
    @DisplayName("[보안] 삭제 요청 경로에 botId 가 실려 Python 쪽에서도 봇으로 좁혀진다")
    void 삭제_요청에_botId_가_실린다() {
        UUID documentId = insertDocument(botId, "규정.pdf", "ready");
        aiService.enqueue(204, null);

        request(HttpMethod.DELETE, "/api/documents/" + documentId, ownerToken);

        // /internal/* 에는 인증이 없다. Python 쪽 WHERE 가 두 값으로 좁혀지려면
        // 경로에 botId 가 반드시 실려야 한다 — 그게 격리의 마지막 그물이다.
        assertThat(aiService.received()).hasSize(1);
        assertThat(aiService.received().get(0).path())
                .isEqualTo("/internal/bots/" + botId + "/documents/" + documentId);
    }

    // ── 정상 흐름 ────────────────────────────────────────────────────────

    @Test
    @DisplayName("문서를 올리면 202 로 접수되고, Python 에 파일명이 실린 multipart 가 전달된다")
    void 업로드_성공() {
        aiService.enqueue(202, """
                {"id":"11111111-1111-1111-1111-111111111111","filename":"규정.pdf",
                 "file_type":"pdf","status":"pending","error_message":null,
                 "char_count":null,"chunk_count":null}""");

        Response response = upload(ownerToken, botId, "규정.pdf", "%PDF-1.4 내용");

        // 201 이 아니라 202 여야 한다 — 행은 생겼지만 파싱·임베딩은 아직 안 끝났다.
        assertThat(response.status()).isEqualTo(202);

        JsonNode body = response.json();
        assertThat(body.path("status").asString()).isEqualTo("pending");
        // Python 의 snake_case 가 camelCase 로 바뀌어 나가는지 (PRD §10.3, 프론트 타입 계약)
        assertThat(body.has("fileType")).isTrue();
        assertThat(body.has("file_type")).isFalse();
        assertThat(body.path("fileType").asString()).isEqualTo("pdf");

        // Python 이 받은 요청 검증
        assertThat(aiService.received()).hasSize(1);
        AiServiceStub.Recorded sent = aiService.received().get(0);
        assertThat(sent.method()).isEqualTo("POST");
        assertThat(sent.path()).isEqualTo("/internal/bots/" + botId + "/documents");
        // ⚠️ 이 두 줄이 회귀를 막는 지점이다. filename 이 빠지면 Python 의 detect_type() 이
        // 확장자를 못 읽어 멀쩡한 PDF 도 "지원하지 않는 형식"으로 거절된다.
        assertThat(sent.body()).contains("name=\"file\"");
        assertThat(sent.body()).contains("규정.pdf");
    }

    @Test
    @DisplayName("[회귀] Python 호출에 HTTP/2 업그레이드 헤더가 붙지 않는다")
    void h2c_업그레이드_헤더를_보내지_않는다() {
        aiService.enqueue(202, """
                {"id":"11111111-1111-1111-1111-111111111111","filename":"규정.pdf",
                 "file_type":"pdf","status":"pending"}""");

        upload(ownerToken, botId, "규정.pdf", "내용");

        // ⚠️ 이 테스트는 <실제 Python 을 띄워본 뒤에> 생겼다.
        // JDK HttpClient 의 기본값이 HTTP_2 라 평문 상대에게 h2c 업그레이드를 함께 요청하는데,
        // uvicorn(h11)은 그걸 지원하지 않아 "Unsupported upgrade request" 를 남기고
        // <chunked 본문을 FastAPI 까지 전달하지 않는다>.
        // 그 결과 multipart 본문은 완벽한데 Python 이 "file 필드가 없다" 며 422 를 냈다.
        //
        // 가짜 서버로는 이 사고를 재현할 수 없다(업그레이드 요청을 그냥 무시하므로).
        // 그래서 "본문이 맞는가" 대신 <보내면 안 되는 헤더가 없는가> 를 검사한다.
        AiServiceStub.Recorded sent = aiService.received().get(0);
        assertThat(sent.hasHeader("Upgrade"))
                .as("Upgrade 헤더가 붙으면 uvicorn 이 본문을 버린다 — RestClientConfig 의 HTTP/1.1 고정을 확인할 것")
                .isFalse();
        assertThat(sent.hasHeader("HTTP2-Settings")).isFalse();
    }

    @Test
    @DisplayName("문서 목록은 DB 에서 읽으므로 업로드 시각이 함께 내려간다")
    void 문서목록_조회() {
        insertDocument(botId, "먼저.pdf", "ready");
        insertDocument(botId, "나중.docx", "processing");

        Response response = request(HttpMethod.GET, "/api/bots/" + botId + "/documents", ownerToken);

        assertThat(response.status()).isEqualTo(200);
        JsonNode documents = response.json();
        assertThat(documents.size()).isEqualTo(2);

        // Python 의 DocumentOut 에는 created_at 이 없다. DB 조회를 택한 이유가 이것이다.
        // ⚠️ path("createdAt").isNull() 로 확인하면 안 된다 — 필드가 <아예 없을> 때
        // Jackson 은 MissingNode 를 돌려주는데 그 isNull() 은 false 다. 즉 필드가 빠져도 통과한다.
        // 존재 여부(has)와 값(비어 있지 않은 문자열)을 따로 확인해야 한다.
        assertThat(documents.get(0).has("createdAt")).isTrue();
        assertThat(documents.get(0).path("createdAt").asString()).isNotBlank();
    }

    @Test
    @DisplayName("Python 이 죽어 있어도 문서 목록은 보인다 (DB 조회를 택한 이유)")
    void 문서목록은_Python_장애와_무관하다() {
        insertDocument(botId, "규정.pdf", "ready");

        // 스텁에 아무 응답도 넣지 않았다. 목록이 Python 을 부른다면 여기서 500 이 났을 것이다.
        Response response = request(HttpMethod.GET, "/api/bots/" + botId + "/documents", ownerToken);

        assertThat(response.status()).isEqualTo(200);
        assertThat(response.json().size()).isEqualTo(1);
        assertThat(aiService.received()).isEmpty();
    }

    @Test
    @DisplayName("내 문서를 삭제하면 204 이고, 실제 삭제는 Python 에 위임된다")
    void 문서_삭제() {
        UUID documentId = insertDocument(botId, "규정.pdf", "ready");
        aiService.enqueue(204, null);

        Response response = request(HttpMethod.DELETE, "/api/documents/" + documentId, ownerToken);

        assertThat(response.status()).isEqualTo(204);
        assertThat(aiService.received()).hasSize(1);
        assertThat(aiService.received().get(0).method()).isEqualTo("DELETE");
        // 🔴 경로에 botId 가 들어간다. /internal/* 에는 인증이 없어서, doc_id 만으로 DELETE 하면
        //    <남의 봇 문서를 지울 수 있다.> Python 쪽 WHERE 도 두 값으로 함께 좁힌다.
        assertThat(aiService.received().get(0).path())
                .isEqualTo("/internal/bots/" + botId + "/documents/" + documentId);

        // ⚠️ 위 세 줄만으로는 "Spring 이 <직접> 지우지 않았다"를 증명하지 못한다 —
        // Spring 이 Python 도 부르고 자기도 DELETE 했다면 위 단언은 그대로 통과한다.
        // 스텁은 SQL 을 실행하지 않으므로, 행이 남아 있다는 것이 곧
        // "지운 주체가 Spring 이 아니다"의 증거다 (쓰기 소유자는 Python).
        Integer 남은행 = jdbcTemplate.queryForObject(
                "SELECT count(*) FROM documents WHERE id = ?", Integer.class, documentId);
        assertThat(남은행).isEqualTo(1);
    }

    // ── Python 장애가 우리 장애로 둔갑하지 않는다 ─────────────────────────

    @Test
    @DisplayName("[장애] Python 이 응답 없이 끊기면 500 이 아니라 503 AI_SERVICE_UNAVAILABLE 이다")
    void Python이_죽으면_503() {
        aiService.enqueueAbort();

        Response response = upload(ownerToken, botId, "규정.pdf", "내용");

        // 500 이면 "우리 서버가 고장났다"는 거짓말이 된다. 프론트가 재시도 로직을 잘못 짜고,
        // 로그에도 가짜 ERROR 가 쌓여 진짜 장애가 묻힌다.
        assertThat(response.status()).isEqualTo(503);
        assertThat(response.json().path("error").path("code").asString()).isEqualTo("AI_SERVICE_UNAVAILABLE");
        assertThat(response.json().path("error").path("message").asString()).contains("다시 시도");
    }

    @Test
    @DisplayName("[장애] Python 이 읽기 타임아웃을 넘기면 504 AI_SERVICE_TIMEOUT 이다")
    void Python이_느리면_504() {
        // 테스트 컨텍스트의 read-timeout 은 2초다(TestcontainersConfiguration).
        aiService.enqueueSlow(Duration.ofSeconds(5), 202, "{}");

        Response response = upload(ownerToken, botId, "규정.pdf", "내용");

        // 503(연결 안 됨)과 구분한다 — 사용자가 할 수 있는 행동이 다르기 때문이다.
        assertThat(response.status()).isEqualTo(504);
        assertThat(response.json().path("error").path("code").asString()).isEqualTo("AI_SERVICE_TIMEOUT");
    }

    @Test
    @DisplayName("[장애] Python 이 5xx 면 503 이다 (Python 이 스스로 고장났다고 말한 것)")
    void Python이_5xx면_503() {
        aiService.enqueue(500, "{\"detail\":\"Internal Server Error\"}");

        Response response = upload(ownerToken, botId, "규정.pdf", "내용");

        assertThat(response.status()).isEqualTo(503);
        assertThat(response.json().path("error").path("code").asString()).isEqualTo("AI_SERVICE_UNAVAILABLE");
        // Python 의 내부 메시지를 사용자에게 흘리지 않는다.
        assertThat(response.body()).doesNotContain("Internal Server Error");
    }

    // ── 사용자 입력 오류 ─────────────────────────────────────────────────

    @Test
    @DisplayName("Python 이 형식을 거절하면 400 이고, Python 의 한국어 안내가 그대로 사용자에게 간다")
    void 지원하지_않는_형식() {
        // parsers.py 의 detect_type() 이 실제로 돌려주는 문구다.
        aiService.enqueue(400, """
                {"detail":"구버전 .hwp는 아직 지원하지 않습니다. 한글에서 .hwpx로 저장 후 올려주세요."}""");

        Response response = upload(ownerToken, botId, "규정.hwp", "내용");

        assertThat(response.status()).isEqualTo(400);
        assertThat(response.json().path("error").path("code").asString()).isEqualTo("UNSUPPORTED_FILE_TYPE");
        // ⚠️ 여기가 중요하다. Spring 이 이 문구를 자기 기본 문구로 뭉개면
        // 사용자는 "그래서 뭘 어떻게 하라고?"를 잃는다(AGENTS.md 작업 규칙 4).
        assertThat(response.json().path("error").path("message").asString())
                .contains(".hwpx")
                .contains("저장");
    }

    @Test
    @DisplayName("multipart 필드명을 잘못 보내면 500 이 아니라 400 이고, 올바른 필드명을 알려준다")
    void 잘못된_필드명() {
        MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();
        body.add("document", new ByteArrayResource("내용".getBytes(StandardCharsets.UTF_8)) {
            @Override
            public String getFilename() {
                return "규정.pdf";
            }
        });

        EntityExchangeResult<byte[]> result = client.post()
                .uri("/api/bots/{botId}/documents", botId)
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + ownerToken)
                .contentType(MediaType.MULTIPART_FORM_DATA)
                .body(body)
                .exchange().expectBody().returnResult();
        Response response = new Response(result.getStatus().value(), decode(result.getResponseBody()));

        // 500 이면 "서버 장애니까 재시도하자"는 잘못된 신호를 준다 — 같은 잘못된 요청을 계속 보내게 된다.
        assertThat(response.status()).isEqualTo(400);
        assertThat(response.json().path("error").path("code").asString()).isEqualTo("INVALID_INPUT");
        // 무엇을 어떻게 고치면 되는지까지 담겨야 한다(AGENTS.md 작업 규칙 4).
        assertThat(response.json().path("error").path("message").asString()).contains("'file'");
        assertThat(aiService.received()).isEmpty();
    }

    @Test
    @DisplayName("경로에 UUID 가 아닌 값이 오면 500 이 아니라 400 이다")
    void 잘못된_경로_UUID() {
        Response response = request(HttpMethod.GET, "/api/bots/이건UUID가아님/documents", ownerToken);

        // 아무 문자열이나 넣어 호출하는 것만으로 서버 로그에 ERROR 스택트레이스를 쌓을 수 있으면 안 된다.
        assertThat(response.status()).isEqualTo(400);
        assertThat(response.json().path("error").path("code").asString()).isEqualTo("INVALID_INPUT");
        // 내부 타입명(java.util.UUID)이 응답에 새지 않아야 한다.
        assertThat(response.body()).doesNotContain("UUID");
    }

    @Test
    @DisplayName("빈 파일은 Python 까지 보내지 않고 400 EMPTY_FILE 로 거절한다")
    void 빈_파일() {
        Response response = upload(ownerToken, botId, "빈파일.txt", "");

        assertThat(response.status()).isEqualTo(400);
        assertThat(response.json().path("error").path("code").asString()).isEqualTo("EMPTY_FILE");
        assertThat(aiService.received()).isEmpty();
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

    /** Python 이 넣어둔 문서 행을 흉내낸다. Spring 코드로는 INSERT 할 수 없다(쓰기 소유자가 Python). */
    private UUID insertDocument(UUID botId, String filename, String status) {
        UUID id = UUID.randomUUID();
        jdbcTemplate.update(
                "INSERT INTO documents (id, bot_id, filename, file_type, status) VALUES (?, ?, ?, ?, ?)",
                id, botId, filename, filename.substring(filename.lastIndexOf('.') + 1), status);
        return id;
    }

    /**
     * multipart 업로드.
     *
     * <p>{@code ByteArrayResource} 의 {@code getFilename()} 을 덮어쓰는 이유는 운영 코드
     * ({@code AiServiceClient.toFilePart})와 같다 — 파일명이 없으면 파트에 {@code filename=} 이 안 실린다.
     */
    private Response upload(String token, UUID botId, String filename, String content) {
        MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();
        body.add("file", new ByteArrayResource(content.getBytes(StandardCharsets.UTF_8)) {
            @Override
            public String getFilename() {
                return filename;
            }
        });

        EntityExchangeResult<byte[]> result = client.post()
                .uri("/api/bots/{botId}/documents", botId)
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + token)
                .contentType(MediaType.MULTIPART_FORM_DATA)
                .body(body)
                .exchange()
                .expectBody()
                .returnResult();

        return new Response(result.getStatus().value(), decode(result.getResponseBody()));
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
