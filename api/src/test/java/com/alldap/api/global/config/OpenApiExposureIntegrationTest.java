package com.alldap.api.global.config;

import com.alldap.api.support.IntegrationTest;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.web.server.LocalServerPort;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * <b>로컬</b>에서 API 문서가 토큰 없이 열리는지 재는 통합 테스트.
 *
 * <h2>왜 "토큰 없이" 가 검증 대상인가</h2>
 * 문서의 목적이 전시다. 열 때마다 먼저 가입하고 토큰을 붙여야 한다면 목적을 못 이룬다.
 * (Swagger UI 의 Authorize 는 <b>Try it out 으로 실제 API 를 부를 때</b> 쓰는 것이고,
 *  문서를 <b>읽는</b> 데에는 필요하지 않다)
 *
 * <p>운영에서 열리지 않는 것은 짝 테스트인 {@code OpenApiProdExposureIntegrationTest} 가 잰다.
 * 두 테스트는 프로파일이 달라 <b>같은 클래스에 둘 수 없다</b>(활성 프로파일은 컨텍스트 단위 설정이다).
 *
 * <h2>JDK {@code HttpClient} 를 쓰는 이유</h2>
 * Boot 4 에서는 {@code TestRestTemplate} 빈이 자동 등록되지 않아
 * {@code @AutoConfigureTestRestTemplate} 을 붙여야 하는데, 그러면 이 클래스만 테스트 설정이 달라져
 * 애플리케이션 컨텍스트가 하나 더 생기고 Testcontainers 도 하나 더 뜬다
 * ({@code IntegrationTest} 주석이 경계하는 그 상황). 필요한 것이 상태 코드와 본문뿐이라
 * {@code ManagementPortIntegrationTest} 와 같은 방식으로 JDK 표준 클라이언트를 쓴다.
 */
@IntegrationTest
@DisplayName("OpenAPI 문서 노출 (로컬)")
class OpenApiExposureIntegrationTest {

    @LocalServerPort
    int port;

    private final HttpClient http = HttpClient.newHttpClient();

    @Test
    @DisplayName("/v3/api-docs 는 토큰 없이 200 이고 OpenAPI 문서를 준다")
    void api_docs_는_토큰_없이_열린다() {
        HttpResponse<String> response = get("/v3/api-docs");

        assertThat(response.statusCode()).isEqualTo(200);
        // 200 만 보면 빈 본문이어도 통과한다. 실제로 OpenAPI 문서인지까지 확인한다.
        assertThat(response.body()).contains("\"openapi\"");
        // 우리 엔드포인트가 실제로 수집됐는가. springdoc 이 떠도 스캔이 비면 문서는 껍데기다.
        assertThat(response.body()).contains("/api/bots");
    }

    @Test
    @DisplayName("Swagger UI 화면도 토큰 없이 200 이다")
    void swagger_ui_는_토큰_없이_열린다() {
        // springdoc 은 /swagger-ui.html 로 오면 /swagger-ui/index.html 로 보낸다.
        // JDK HttpClient 는 기본적으로 리다이렉트를 따라가지 않으므로 최종 주소를 직접 부른다.
        HttpResponse<String> response = get("/swagger-ui/index.html");

        assertThat(response.statusCode()).isEqualTo(200);
    }

    @Test
    @DisplayName("[실측 기록] 문서를 열어도 보호 경로는 그대로 401 이다")
    void 보호_경로는_영향을_받지_않는다() {
        // permitAll 을 잘못 적어 /api/** 까지 열리는 사고를 이 한 줄이 잡는다.
        assertThat(get("/api/bots").statusCode()).isEqualTo(401);
    }

    private HttpResponse<String> get(String path) {
        try {
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create("http://localhost:" + port + path))
                    .GET()
                    .build();
            return http.send(request, HttpResponse.BodyHandlers.ofString());
        } catch (IOException e) {
            throw new AssertionError("요청이 실패했다: " + path, e);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new AssertionError("요청이 중단됐다: " + path, e);
        }
    }
}
