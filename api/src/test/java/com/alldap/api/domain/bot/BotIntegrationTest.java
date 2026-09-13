package com.alldap.api.domain.bot;

import com.alldap.api.domain.auth.dto.SignupRequest;
import com.alldap.api.domain.bot.dto.CreateBotRequest;
import com.alldap.api.domain.bot.dto.UpdateBotRequest;
import com.alldap.api.domain.user.repository.UserRepository;
import com.alldap.api.support.IntegrationTest;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.client.EntityExchangeResult;
import org.springframework.test.web.servlet.client.RestTestClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.nio.charset.StandardCharsets;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 봇 CRUD 통합 테스트.
 *
 * <p>이 슬라이스에서 <b>처음으로 소유권 검사(bot_id 스코프 격리)가 걸린다.</b>
 * 그래서 여기서 지키려는 것은 "CRUD 가 돈다"가 아니라 다음 두 가지다.
 *
 * <ol>
 *   <li><b>남의 봇에 손댈 수 없다.</b> 조회·수정·삭제 전부. 봇 id 는 URL 에 노출되므로
 *       "id 를 모를 것"에 기대는 방어는 방어가 아니다.</li>
 *   <li><b>남의 봇은 403 이 아니라 404 로 답한다.</b> 403 은 "그 봇은 있는데 네 것이 아니다"라는
 *       정보를 준다. 무작위 id 를 던져 403 이 나오는 것만 골라내면 남의 봇 존재 여부를 훑을 수 있다.</li>
 * </ol>
 *
 * <p>404 만 확인하고 끝내지 않는다 — 상태 코드만 맞고 실제로는 수정·삭제가 일어났을 수 있으므로,
 * <b>피해자 쪽에서 다시 조회해</b> 아무 일도 없었음을 확인한다.
 */
@IntegrationTest
@DisplayName("봇 API 통합 테스트")
class BotIntegrationTest {

    /** 존재하지 않는 id. 순번이라 이만큼 큰 값은 테스트 안에서 만들어질 수 없다. */
    private static final long MISSING_ID = 999_999_999L;

    private static final String PASSWORD = "correct-password-1234";

    @LocalServerPort
    private int port;

    @Autowired
    private UserRepository userRepository;

    private RestTestClient client;

    /** 주인(피해자)과 침입자. 매 테스트마다 새로 가입시켜 토큰을 받는다. */
    private String ownerToken;
    private String intruderToken;

    @BeforeEach
    void setUp() {
        client = RestTestClient.bindToServer()
                .baseUrl("http://localhost:" + port)
                .build();

        // 실제 서버에 HTTP 로 요청하므로 테스트 트랜잭션 롤백이 통하지 않는다(AuthIntegrationTest 주석 참고).
        // users 를 지우면 bots 는 DB 의 ON DELETE CASCADE 로 함께 사라진다 —
        // 봇을 따로 지울 필요가 없다는 사실 자체가 deleteBot 의 동작과 같은 근거 위에 있다.
        userRepository.deleteAll();

        ownerToken = signup("owner@example.com");
        intruderToken = signup("intruder@example.com");
    }

    // ── 생성 ────────────────────────────────────────────────────────────

    @Test
    @DisplayName("봇을 만들면 201 과 함께 publicKey 가 발급되고 기본 문구가 채워진다")
    void 봇_생성() {
        Response response = request(HttpMethod.POST, "/api/bots", ownerToken, new CreateBotRequest("우리 회사 봇"));

        assertThat(response.status()).isEqualTo(201);

        JsonNode body = response.json();
        assertThat(body.path("id").asString()).isNotBlank();
        assertThat(body.path("name").asString()).isEqualTo("우리 회사 봇");
        // publicKey 는 서버가 만든다 — 클라이언트가 정할 수 있으면 남의 위젯 주소를 선점할 수 있다.
        assertThat(body.path("publicKey").asString()).startsWith("pk_");
        // DB DEFAULT 가 아니라 Bot.create() 가 넣은 값이다(Hibernate 는 INSERT 에 모든 컬럼을 쓴다).
        assertThat(body.path("welcomeMessage").asString()).isEqualTo("무엇을 도와드릴까요?");
        assertThat(body.path("fallbackMessage").asString()).isNotBlank();
        // allowed_origins 가 null 이어도 프론트가 배열을 전제로 하므로 빈 배열이어야 한다.
        assertThat(body.path("allowedOrigins").isArray()).isTrue();

        // Location 은 실제로 조회 가능한 주소여야 한다. 형식만 맞고 404 면 없느니만 못하다.
        String location = response.location();
        assertThat(location).isEqualTo("/api/bots/" + body.path("id").asString());
        assertThat(request(HttpMethod.GET, location, ownerToken, null).status()).isEqualTo(200);
    }

    @Test
    @DisplayName("이름 없이 봇을 만들면 400 INVALID_INPUT 으로 거절한다")
    void 봇_생성_이름_누락() {
        Response response = request(HttpMethod.POST, "/api/bots", ownerToken, new CreateBotRequest("   "));

        assertThat(response.status()).isEqualTo(400);
        assertThat(response.json().path("error").path("code").asString()).isEqualTo("INVALID_INPUT");
    }

    // ── 소유권 격리 (이 슬라이스의 핵심) ──────────────────────────────────

    @Test
    @DisplayName("[보안] 목록에는 내 봇만 나온다 — 남의 봇이 섞이지 않는다")
    void 목록은_내_봇만() {
        createBot(ownerToken, "주인 봇");
        createBot(intruderToken, "침입자 봇");

        JsonNode bots = request(HttpMethod.GET, "/api/bots", ownerToken, null).json();

        assertThat(bots.isArray()).isTrue();
        assertThat(bots.size()).isEqualTo(1);
        assertThat(bots.get(0).path("name").asString()).isEqualTo("주인 봇");
    }

    @Test
    @DisplayName("[보안] 남의 봇을 조회하면 403 이 아니라 404 BOT_NOT_FOUND 다")
    void 남의_봇_조회() {
        Long botId = createBot(ownerToken, "주인 봇");

        Response response = request(HttpMethod.GET, "/api/bots/" + botId, intruderToken, null);

        assertThat(response.status()).isEqualTo(404);
        assertThat(response.json().path("error").path("code").asString()).isEqualTo("BOT_NOT_FOUND");

        // 존재하지 않는 봇과 응답이 완전히 같아야 "그 id 의 봇이 있는지"가 새지 않는다.
        Response 없는봇 = request(HttpMethod.GET, "/api/bots/" + MISSING_ID, intruderToken, null);
        assertThat(response.body()).isEqualTo(없는봇.body());
    }

    @Test
    @DisplayName("[보안] 남의 봇은 수정되지 않는다 — 404 로 막고 값도 그대로다")
    void 남의_봇_수정() {
        Long botId = createBot(ownerToken, "주인 봇");

        Response response = request(HttpMethod.PATCH, "/api/bots/" + botId, intruderToken,
                new UpdateBotRequest("탈취된 봇", null, null, null, null));

        assertThat(response.status()).isEqualTo(404);

        // 상태 코드만 믿지 않는다. 주인 눈으로 다시 확인해야 "정말 안 바뀌었다"를 증명한 것이다.
        JsonNode bot = request(HttpMethod.GET, "/api/bots/" + botId, ownerToken, null).json();
        assertThat(bot.path("name").asString()).isEqualTo("주인 봇");
    }

    @Test
    @DisplayName("[보안] 남의 봇은 삭제되지 않는다 — 404 로 막고 봇도 그대로 남는다")
    void 남의_봇_삭제() {
        Long botId = createBot(ownerToken, "주인 봇");

        Response response = request(HttpMethod.DELETE, "/api/bots/" + botId, intruderToken, null);

        assertThat(response.status()).isEqualTo(404);
        assertThat(request(HttpMethod.GET, "/api/bots/" + botId, ownerToken, null).status()).isEqualTo(200);
    }

    // ── 수정 · 삭제 ──────────────────────────────────────────────────────

    @Test
    @DisplayName("PATCH 는 보낸 필드만 바꾸고 나머지는 그대로 둔다")
    void 봇_부분_수정() {
        Long botId = createBot(ownerToken, "옛 이름");

        Response response = request(HttpMethod.PATCH, "/api/bots/" + botId, ownerToken,
                new UpdateBotRequest("새 이름", null, null, null, List.of("https://example.com")));

        assertThat(response.status()).isEqualTo(200);

        JsonNode bot = response.json();
        assertThat(bot.path("name").asString()).isEqualTo("새 이름");
        assertThat(bot.path("allowedOrigins").get(0).asString()).isEqualTo("https://example.com");
        // 보내지 않은 필드(null)는 기존 값 유지여야 한다. 여기가 깨지면 설정 화면에서
        // 이름만 고쳐도 인사말이 지워지는 사고가 난다.
        assertThat(bot.path("welcomeMessage").asString()).isEqualTo("무엇을 도와드릴까요?");
        assertThat(bot.path("fallbackMessage").asString()).isNotBlank();
    }

    @Test
    @DisplayName("내 봇을 삭제하면 204 이고 목록에서 사라진다")
    void 봇_삭제() {
        Long botId = createBot(ownerToken, "지울 봇");

        assertThat(request(HttpMethod.DELETE, "/api/bots/" + botId, ownerToken, null).status()).isEqualTo(204);
        assertThat(request(HttpMethod.GET, "/api/bots/" + botId, ownerToken, null).status()).isEqualTo(404);
        assertThat(request(HttpMethod.GET, "/api/bots", ownerToken, null).json().size()).isZero();
    }

    // ── 테스트 보조 ──────────────────────────────────────────────────────

    private String signup(String email) {
        return request(HttpMethod.POST, "/api/auth/signup", null, new SignupRequest(email, PASSWORD, null))
                .json().path("token").asString();
    }

    private Long createBot(String token, String name) {
        return request(HttpMethod.POST, "/api/bots", token, new CreateBotRequest(name))
                        .json().path("id").asLong();
    }

    /**
     * 한 번의 HTTP 교환 결과.
     *
     * @param status   HTTP 상태 코드
     * @param body     응답 본문 (UTF-8 로 디코딩한 문자열)
     * @param location {@code Location} 헤더. 없으면 null
     */
    private record Response(int status, String body, String location) {

        JsonNode json() {
            return JSON.readTree(body);
        }
    }

    /** record 는 인스턴스 필드를 못 가져서 주입받은 매퍼를 쓸 수 없다. 파싱 전용이라 기본 매퍼로 충분하다. */
    private static final ObjectMapper JSON = new ObjectMapper();

    /**
     * 메서드 4가지(GET·POST·PATCH·DELETE)를 하나로 처리한다.
     *
     * <p>메서드마다 헬퍼를 따로 두면 헤더를 붙이는 코드가 네 번 반복되고,
     * 그중 한 곳에서 토큰을 빠뜨려도 테스트는 조용히 통과해버린다.
     *
     * @param token 인증 토큰. null 이면 {@code Authorization} 헤더를 아예 붙이지 않는다
     * @param body  요청 본문. null 이면 본문 없이 보낸다.
     *              운영 DTO 를 그대로 쓰므로 API 계약이 바뀌면 테스트가 컴파일 단계에서 깨진다
     */
    private Response request(HttpMethod method, String uri, String token, Object body) {
        RestTestClient.RequestBodySpec spec = client.method(method).uri(uri);
        if (token != null) {
            spec.header(HttpHeaders.AUTHORIZATION, "Bearer " + token);
        }

        RestTestClient.RequestHeadersSpec<?> ready = body == null
                ? spec
                : spec.contentType(MediaType.APPLICATION_JSON).body(body);

        EntityExchangeResult<byte[]> result = ready.exchange().expectBody().returnResult();
        return new Response(
                result.getStatus().value(),
                decode(result.getResponseBody()),
                result.getResponseHeaders().getFirst(HttpHeaders.LOCATION));
    }

    /** 한국어 에러 메시지가 깨지지 않도록 UTF-8 을 명시해 디코딩한다(AuthIntegrationTest 주석 참고). */
    private static String decode(byte[] raw) {
        return raw == null ? "" : new String(raw, StandardCharsets.UTF_8);
    }
}
