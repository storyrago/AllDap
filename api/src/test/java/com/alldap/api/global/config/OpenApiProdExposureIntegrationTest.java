package com.alldap.api.global.config;

import com.alldap.api.support.TestcontainersConfiguration;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistrar;
import org.testcontainers.postgresql.PostgreSQLContainer;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * <b>운영 프로파일(prod)로 실제 기동해</b> API 문서가 열리지 않는지 재는 통합 테스트.
 *
 * <h2>왜 두 번 부르는가: 두 겹을 <b>각각</b> 확인하기 위해서다</h2>
 * <ul>
 *   <li><b>토큰 없이</b> 부르면 401 이다 → 겹 ②({@code SecurityConfig} 가 permitAll 을 걸지 않았다)가 동작한다.</li>
 *   <li><b>토큰을 붙여</b> 부르면 404 다 → 겹 ①({@code springdoc.api-docs.enabled: false} 로 문서가
 *       아예 생성되지 않았다)이 동작한다. 여기서 200 이 나오면 <b>계정 하나만 있으면 읽힌다</b>는 뜻이다.</li>
 * </ul>
 * 한 번만 부르면 401 에 가려 겹 ① 이 살아 있는지 <b>알 수 없다</b>. 그래서 둘 다 부른다.
 *
 * <h2>⚠️ 이 테스트는 애플리케이션 컨텍스트를 하나 더 만든다 (그래서 컨테이너도 하나 더 뜬다)</h2>
 * 활성 프로파일은 컨텍스트 캐시 키의 일부라 {@code @IntegrationTest}(프로파일 없음)와 같은
 * 컨텍스트를 쓸 수 없다. 대가를 알고 감수한다. 근거는 이 테스트가 담당하는 계획 문서의 Task 2 참고.
 *
 * <h2>prod 프로파일이 요구하는 환경변수를 어떻게 채우는가</h2>
 * {@code application-prod.yaml} 은 fail-closed 라 기본값이 없다({@code ${DB_URL}} 처럼).
 * 플레이스홀더는 <b>환경 프로퍼티 이름으로</b> 해석되므로, 환경변수와 같은 이름의 프로퍼티를 주면 채워진다.
 * <ul>
 *   <li>DB 셋은 컨테이너가 떠야 값이 정해지므로 {@link ProdEnvRegistrar} 가 동적으로 넣는다.</li>
 *   <li>나머지는 {@code @SpringBootTest(properties = ...)} 로 고정값을 준다.</li>
 * </ul>
 *
 * <p>⚠️ {@code JWT_SECRET} 과 {@code BILLING_CRYPTO_KEY} 는 <b>저장소에 공개된 로컬 기본값과 달라야 한다.</b>
 * {@code JwtService} · {@code BillingCrypto} 가 "공개된 기본값으로 운영에 뜨는 것" 을 막는 가드를 갖고 있어,
 * 기본값 그대로면 prod 프로파일에서 <b>기동 자체가 실패한다</b>(그게 그 가드의 목적이다).
 * {@code BILLING_CRYPTO_KEY} 는 디코딩하면 정확히 32바이트인 Base64 여야 한다.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = {
        // 32자 이상이고 JwtService.KNOWN_LOCAL_DEFAULT_SECRET 과 다르다.
        "JWT_SECRET=prod-profile-test-secret-0123456789-abcdefghijklmn",
        // Base64("alldap-prod-profile-test-key-32b") = 디코딩 32바이트. BillingCrypto 의 기본값과 다르다.
        "BILLING_CRYPTO_KEY=YWxsZGFwLXByb2QtcHJvZmlsZS10ZXN0LWtleS0zMmI=",
        // 이 테스트는 Python 을 부르지 않는다. 값이 필요한 것은 <기동>이지 호출이 아니다.
        "AI_SERVICE_BASE_URL=http://localhost:1",
        "CORS_ALLOWED_ORIGINS=http://localhost:3000",
        "TOSS_SECRET_KEY=test_sk_prod_profile_only",
})
@ActiveProfiles("prod")
@Import({TestcontainersConfiguration.class, OpenApiProdExposureIntegrationTest.ProdEnvRegistrar.class})
@DisplayName("OpenAPI 문서 노출 (운영 프로파일)")
class OpenApiProdExposureIntegrationTest {

    @LocalServerPort
    int port;

    private final HttpClient http = HttpClient.newHttpClient();

    /**
     * prod 프로파일의 {@code ${DB_URL}} 등을 컨테이너 값으로 채운다.
     *
     * <p>{@code @ServiceConnection} 이 DataSource 배선을 이미 해주지만, {@code application-prod.yaml} 의
     * {@code spring.datasource.url: ${DB_URL}} 은 <b>바인딩 시점에 플레이스홀더가 해석돼야</b> 한다.
     * 해석되지 않으면 "Could not resolve placeholder 'DB_URL'" 로 컨텍스트가 뜨지 않는다.
     * 같은 컨테이너를 가리키므로 두 경로가 어긋날 일은 없다.
     */
    @TestConfiguration(proxyBeanMethods = false)
    static class ProdEnvRegistrar {

        @Bean
        DynamicPropertyRegistrar prodDbEnvRegistrar(PostgreSQLContainer container) {
            return registry -> {
                registry.add("DB_URL", container::getJdbcUrl);
                registry.add("DB_USERNAME", container::getUsername);
                registry.add("DB_PASSWORD", container::getPassword);
            };
        }
    }

    @Test
    @DisplayName("겹 ②: 토큰 없이 부르면 문서 경로가 401 이다 (permitAll 이 걸리지 않았다)")
    void 운영에서는_문서_경로가_인증_뒤에_있다() {
        assertThat(get("/v3/api-docs", null).statusCode()).isEqualTo(401);
        assertThat(get("/swagger-ui/index.html", null).statusCode()).isEqualTo(401);
    }

    @Test
    @DisplayName("겹 ①: 로그인한 사용자가 불러도 문서가 없다 (생성 자체가 꺼져 있다)")
    void 운영에서는_문서가_생성되지_않는다() {
        String token = 가입해서_토큰을_받는다();

        // 여기서 200 이 나오면 겹 ① 이 죽은 것이다 = 계정 하나만 있으면 전 API 명세가 읽힌다.
        assertThat(get("/v3/api-docs", token).statusCode()).isEqualTo(404);
        assertThat(get("/swagger-ui/index.html", token).statusCode()).isEqualTo(404);
    }

    /**
     * 가입은 prod 에서도 permitAll 이다(가입을 막으면 서비스가 성립하지 않는다).
     * JSON 파싱을 붙이지 않고 문자열에서 토큰만 꺼낸다. 이 테스트가 검증하려는 것이 토큰 구조가 아니다.
     */
    private String 가입해서_토큰을_받는다() {
        String 본문 = """
                {"email":"prod-doc-tester@example.com","password":"correct-password-1234","name":"테스터"}""";
        HttpResponse<String> response = post("/api/auth/signup", 본문);
        assertThat(response.statusCode())
                .withFailMessage("가입이 실패하면 겹 ① 을 잴 수 없다. 응답: %s", response.body())
                .isEqualTo(201);

        String 시작표시 = "\"token\":\"";
        int 시작 = response.body().indexOf(시작표시) + 시작표시.length();
        return response.body().substring(시작, response.body().indexOf('"', 시작));
    }

    /** @param bearerToken null 이면 Authorization 헤더를 붙이지 않는다(= 비로그인 요청) */
    private HttpResponse<String> get(String path, String bearerToken) {
        HttpRequest.Builder builder = HttpRequest.newBuilder()
                .uri(URI.create("http://localhost:" + port + path))
                .GET();
        if (bearerToken != null) {
            builder.header("Authorization", "Bearer " + bearerToken);
        }
        return send(builder.build(), path);
    }

    private HttpResponse<String> post(String path, String jsonBody) {
        HttpRequest request = HttpRequest.newBuilder()
                .uri(URI.create("http://localhost:" + port + path))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(jsonBody))
                .build();
        return send(request, path);
    }

    private HttpResponse<String> send(HttpRequest request, String path) {
        try {
            return http.send(request, HttpResponse.BodyHandlers.ofString());
        } catch (IOException e) {
            throw new AssertionError("요청이 실패했다: " + path, e);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new AssertionError("요청이 중단됐다: " + path, e);
        }
    }
}
