package com.alldap.api.global.exception;

import com.alldap.api.domain.auth.dto.SignupRequest;
import com.alldap.api.domain.user.repository.UserRepository;
import com.alldap.api.global.ratelimit.RateLimiter;
import com.alldap.api.support.IntegrationTest;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.web.server.LocalManagementPort;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.client.EntityExchangeResult;
import org.springframework.test.web.servlet.client.RestTestClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.nio.charset.StandardCharsets;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * <b>매핑도 정적 리소스도 없는 경로</b>가 어떻게 응답되는지 재는 통합 테스트.
 *
 * <h2>왜 필요한가</h2>
 * 이 앱은 얼마 전까지 <b>어떤</b> 없는 경로든 500 {@code INTERNAL_ERROR} 로 답했다.
 * {@link GlobalExceptionHandler} 의 마지막 그물이 {@code NoResourceFoundException} 까지
 * 잡아버렸기 때문이다. 그 문구는 "일시적인 오류입니다. 잠시 후 다시 시도해주세요" 인데
 * <b>없는 주소는 다시 시도해도 영원히 없다.</b>
 *
 * <p>운영에서 실제로 드러났다. actuator 를 management 포트로 옮긴 뒤
 * {@code GET https://alldap.duckdns.org/actuator/health} 가 500 을 줘서
 * <b>서버 장애처럼 보였다.</b> 하필 헬스체크로 쓰는 주소였다.
 *
 * <h2>가장 큰 위험은 404 가 아니라 정적 리소스다</h2>
 * {@code /widget/**} 은 고객 사이트의 {@code <script>} 태그가 인증 없이 받아가는 경로다
 * (빌드 시 저장소 루트 {@code widget/} 에서 {@code static/widget/} 으로 복사된다).
 * 새 핸들러가 정적 리소스 처리를 가로채면 <b>모든 고객 사이트의 위젯이 동시에 죽는다.</b>
 * 그래서 {@link #실재하는_정적_리소스는_그대로_200} 을 함께 둔다:
 * "안 깨졌을 것이다" 와 "안 깨진 것을 봤다" 는 다르다.
 *
 * <h2>404 로 바뀌어도 <b>존재 여부는 새지 않는다</b></h2>
 * 인증이 필요한 경로에 토큰 없이 접근하면 인가 필터가 먼저 401 을 내므로
 * 요청이 애초에 {@code DispatcherServlet} 의 핸들러 탐색까지 가지 않는다.
 * 즉 비로그인 상태에서는 존재하는 경로와 없는 경로가 <b>똑같이 401</b> 이다
 * (이 저장소가 남의 봇에 403 대신 404 를 주는 것과 같은 이유).
 * 응답 본문에 요청 경로를 되비추지 않는 것도 그래서다.
 */
@IntegrationTest
@DisplayName("없는 경로 404 처리")
class NotFoundIntegrationTest {

    @LocalServerPort
    private int port;

    @LocalManagementPort
    private int managementPort;

    @Autowired
    private UserRepository userRepository;

    @Autowired
    private RateLimiter rateLimiter;

    private RestTestClient client;

    @BeforeEach
    void setUp() {
        client = RestTestClient.bindToServer()
                .baseUrl("http://localhost:" + port)
                .build();

        // RANDOM_PORT 라 실제 HTTP 를 태운다 = 테스트 트랜잭션 롤백이 통하지 않는다.
        // 토큰을 얻으려고 가입하므로 앞뒤 테스트에 상태를 남기지 않게 직접 지운다.
        userRepository.deleteAll();
        // RateLimiter 는 상태를 가진 싱글턴이다. 로그인·가입 카운터가 넘어오면
        // 실행 순서에 따라 나타났다 사라지는 실패가 난다.
        rateLimiter.reset();
    }

    // ── ⓐ 없는 경로 → 404 + 공통 에러 포맷 ────────────────────────────────

    @Test
    @DisplayName("공개 경로 중 매핑이 사라진 주소(/actuator/health)는 500 이 아니라 404 다")
    void 매핑이_없는_공개_경로는_404() {
        // actuator 는 management 포트로 옮겨갔다. permitAll 이라 인가 필터를 통과하고,
        // 그 뒤 핸들러가 없어 NoResourceFoundException 이 난다 = 이 슬라이스가 고친 바로 그 경로.
        Response response = get("/actuator/health", null);

        assertThat(response.status()).isEqualTo(404);
        assertThat(response.json().path("error").path("code").asString())
                .isEqualTo(ErrorCode.RESOURCE_NOT_FOUND.getCode());
        assertThat(response.json().path("error").path("message").asString())
                .isEqualTo(ErrorCode.RESOURCE_NOT_FOUND.getMessage());
    }

    @Test
    @DisplayName("로그인한 사용자가 없는 주소를 부르면 404 다 (500 이 아니다)")
    void 로그인_상태에서_없는_주소는_404() {
        String token = 가입해서_토큰을_받는다();

        Response response = get("/api/does-not-exist-" + System.nanoTime(), token);

        assertThat(response.status()).isEqualTo(404);
        assertThat(response.json().path("error").path("code").asString())
                .isEqualTo(ErrorCode.RESOURCE_NOT_FOUND.getCode());
    }

    @Test
    @DisplayName("404 응답은 요청 경로를 되비추지 않는다 (경로 정찰 방지)")
    void 응답에_요청_경로가_실리지_않는다() {
        String token = 가입해서_토큰을_받는다();
        String 정찰용_경로 = "/api/secret-probe-marker";

        Response response = get(정찰용_경로, token);

        assertThat(response.status()).isEqualTo(404);
        // 경로 조각이 그대로 반사되면 응답이 "그 주소는 이렇게 생겼다"를 확인해주는 도구가 된다.
        assertThat(response.body()).doesNotContain("secret-probe-marker");
    }

    // ── ⓑ 실재하는 정적 리소스는 영향을 받지 않는다 ───────────────────────

    @Test
    @DisplayName("실재하는 정적 리소스(/widget/alldap-widget.js)는 여전히 200 이다")
    void 실재하는_정적_리소스는_그대로_200() {
        // NoResourceFoundException 은 ResourceHttpRequestHandler 가 파일을 <못 찾았을 때만> 던진다.
        // 실재하는 파일은 예외 없이 응답되므로 새 핸들러를 지나가지도 않는다. 그걸 여기서 확인한다.
        Response response = get("/widget/alldap-widget.js", null);

        assertThat(response.status()).isEqualTo(200);
        // 상태 코드만 보면 빈 파일이 나가도 통과한다. 로더의 실제 내용으로 확인한다.
        assertThat(response.body()).contains("data-public-key");
    }

    @Test
    @DisplayName("정적 리소스 경로 아래의 없는 파일은 404 다")
    void 없는_정적_리소스는_404() {
        Response response = get("/widget/no-such-file.js", null);

        assertThat(response.status()).isEqualTo(404);
        assertThat(response.json().path("error").path("code").asString())
                .isEqualTo(ErrorCode.RESOURCE_NOT_FOUND.getCode());
    }

    // ── ⓒ 인증이 필요한 경로는 여전히 401 ─────────────────────────────────

    @Test
    @DisplayName("실재하지만 인증이 필요한 경로는 여전히 401 이다 (404 로 바뀌면 안 된다)")
    void 인증이_필요한_실재_경로는_401() {
        // 404 로 바뀌었다면 인가 필터가 아니라 핸들러 탐색이 먼저 돌았다는 뜻이고,
        // 그건 보호 경로가 열렸다는 신호다.
        Response response = get("/api/bots", null);

        assertThat(response.status()).isEqualTo(401);
        assertThat(response.json().path("error").path("code").asString())
                .isEqualTo(ErrorCode.AUTHENTICATION_REQUIRED.getCode());
    }

    @Test
    @DisplayName("[실측 기록] 비로그인 상태에서는 있는 경로와 없는 경로가 똑같이 401 이다")
    void 비로그인_상태에서는_존재_여부가_새지_않는다() {
        // 이 두 응답이 갈리는 순간 "아무 주소나 던져 401 만 골라내면 실재 경로 목록이 나온다" 가 된다.
        Response 있는_경로 = get("/api/bots", null);
        Response 없는_경로 = get("/api/no-such-endpoint", null);

        assertThat(없는_경로.status()).isEqualTo(있는_경로.status()).isEqualTo(401);
        assertThat(없는_경로.body()).isEqualTo(있는_경로.body());
    }

    // ── management 포트(8081)에서도 같은 규칙 ─────────────────────────────

    @Test
    @DisplayName("[실측 기록] management 포트에서는 이 변경으로 바뀌는 것이 없다")
    void management_포트는_영향을_받지_않는다() {
        // management 포트(8081)는 <자식 컨텍스트>다. 이 슬라이스가 그쪽 동작을 바꾸는지 실제로 불러 확인한다.
        // 결과: 바꾸지 않는다. 이유는 그 포트에 "permitAll 인데 매핑이 없는 경로" 가 하나도 없기 때문이다.
        //   · permitAll 인 것(/actuator/health · /actuator/prometheus · /widget/**)은 전부 <실재>한다
        //   · 나머지는 SecurityConfig 의 anyRequest().authenticated() 가 <인가 필터에서> 먼저 401 로 끊어
        //     요청이 DispatcherServlet 의 핸들러 탐색까지 가지 않는다 = NoResourceFoundException 이 아예 안 난다
        RestTestClient management = RestTestClient.bindToServer()
                .baseUrl("http://localhost:" + managementPort)
                .build();

        EntityExchangeResult<byte[]> 없는_actuator = management.get()
                .uri("/actuator/no-such-endpoint").exchange().expectBody().returnResult();
        assertThat(없는_actuator.getStatus().value()).isEqualTo(401);

        // ⚠️ 이 포트도 정적 리소스를 준다(이 변경 <이전부터> 그랬다).
        //    호스트에 8081 을 열지 않는 것이 그대로 방어선이다(ManagementPortIntegrationTest 참고).
        EntityExchangeResult<byte[]> 위젯 = management.get()
                .uri("/widget/alldap-widget.js").exchange().expectBody().returnResult();
        assertThat(위젯.getStatus().value()).isEqualTo(200);
    }

    // ── 테스트 보조 ──────────────────────────────────────────────────────

    private String 가입해서_토큰을_받는다() {
        EntityExchangeResult<byte[]> result = client.post()
                .uri("/api/auth/signup")
                .contentType(MediaType.APPLICATION_JSON)
                .body(new SignupRequest("notfound-tester@example.com", "correct-password-1234", "테스터"))
                .exchange()
                .expectBody()
                .returnResult();

        Response response = new Response(result.getStatus().value(), decode(result.getResponseBody()));
        assertThat(response.status()).isEqualTo(201);
        return response.json().path("token").asString();
    }

    /** @param bearerToken null 이면 Authorization 헤더를 아예 붙이지 않는다(= 비로그인 요청) */
    private Response get(String uri, String bearerToken) {
        RestTestClient.RequestHeadersSpec<?> spec = client.get().uri(uri);
        if (bearerToken != null) {
            spec = spec.header(HttpHeaders.AUTHORIZATION, "Bearer " + bearerToken);
        }

        EntityExchangeResult<byte[]> result = spec.exchange().expectBody().returnResult();
        return new Response(result.getStatus().value(), decode(result.getResponseBody()));
    }

    private record Response(int status, String body) {

        JsonNode json() {
            return JSON.readTree(body);
        }
    }

    /** record 는 인스턴스 필드를 가질 수 없어 주입받은 매퍼를 쓸 수 없다. 파싱만 하므로 기본 매퍼면 충분하다. */
    private static final ObjectMapper JSON = new ObjectMapper();

    /**
     * 응답 바이트를 <b>UTF-8 로 명시해</b> 문자열로 만든다.
     * {@code expectBody(String.class)} 는 Content-Type 에 charset 이 없으면 자체 기본값으로
     * 디코딩해 한국어 메시지가 깨진다(AuthIntegrationTest 와 같은 이유).
     */
    private static String decode(byte[] raw) {
        return raw == null ? "" : new String(raw, StandardCharsets.UTF_8);
    }
}
