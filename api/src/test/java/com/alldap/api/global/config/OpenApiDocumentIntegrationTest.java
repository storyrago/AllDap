package com.alldap.api.global.config;

import com.alldap.api.global.exception.ErrorCode;
import com.alldap.api.support.IntegrationTest;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.web.server.LocalServerPort;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 생성된 OpenAPI 문서의 <b>내용</b>을 재는 통합 테스트.
 * (열리는지 여부는 {@code OpenApiExposureIntegrationTest} 가 잰다)
 *
 * <h2>왜 JSON 을 직접 파싱하는가</h2>
 * {@code OpenApiConfig} 의 빈을 단위 테스트로 검사하면 "우리가 만든 모델" 만 보게 된다.
 * 정작 알고 싶은 것은 springdoc 이 그 모델과 컨트롤러 애노테이션을 합쳐 <b>실제로 내보낸 결과</b>다.
 * 두 Jackson(Boot 4 의 Jackson 3 / swagger-core 의 Jackson 2)이 한 클래스패스에 있는 상황이라
 * 더욱 결과물을 봐야 한다.
 *
 * <h2>401 을 전부에 달지 않는 것이 검증 대상이다</h2>
 * 가입과 위젯은 토큰을 받지 않으므로 401 이 나갈 수 없다. 일괄로 달면 문서가 <b>없는 응답을
 * 있다고 말한다.</b> 그래서 "보호 경로에는 있고, 공개 경로에는 없다" 를 양쪽에서 확인한다.
 */
@IntegrationTest
@DisplayName("OpenAPI 문서 내용")
class OpenApiDocumentIntegrationTest {

    private static final ObjectMapper JSON = new ObjectMapper();

    @LocalServerPort
    int port;

    private JsonNode 문서;

    @BeforeEach
    void 문서를_한_번_읽는다() {
        문서 = JSON.readTree(get("/v3/api-docs"));
    }

    @Test
    @DisplayName("JWT 보안 스킴이 정의돼 있고 전역 기본으로 걸려 있다")
    void jwt_스킴이_전역으로_걸린다() {
        JsonNode 스킴 = 문서.path("components").path("securitySchemes").path("bearerAuth");
        assertThat(스킴.path("type").asString()).isEqualTo("http");
        assertThat(스킴.path("scheme").asString()).isEqualTo("bearer");
        assertThat(스킴.path("bearerFormat").asString()).isEqualTo("JWT");

        // 전역으로 걸려 있어야 Swagger UI 의 Authorize 에 토큰을 한 번 넣고 전부 시험할 수 있다.
        assertThat(문서.path("security").toString()).contains("bearerAuth");
    }

    @Test
    @DisplayName("공통 에러 스키마가 중첩 구조로 정의돼 있다")
    void 에러_스키마가_중첩_구조다() {
        JsonNode 스키마 = 문서.path("components").path("schemas").path("ErrorResponse");
        // 평평하게 만들면 프론트(ApiErrorBody)·Python·위젯이 모두 어긋난다.
        JsonNode 내부 = 스키마.path("properties").path("error").path("properties");
        assertThat(내부.has("code")).isTrue();
        assertThat(내부.has("message")).isTrue();
    }

    @Test
    @DisplayName("보호 엔드포인트에는 공통 401 과 500 이 붙는다")
    void 보호_엔드포인트에_공통_응답이_붙는다() {
        JsonNode 응답 = 문서.path("paths").path("/api/bots").path("get").path("responses");

        assertThat(응답.has("401")).isTrue();
        assertThat(응답.has("500")).isTrue();
        assertThat(응답.path("401").path("description").asString())
                .contains(ErrorCode.AUTHENTICATION_REQUIRED.getCode());
        assertThat(응답.path("500").path("description").asString())
                .contains(ErrorCode.INTERNAL_ERROR.getCode());
    }

    @Test
    @DisplayName("공개 엔드포인트에는 401 이 붙지 않는다 (500 만 붙는다)")
    void 공개_엔드포인트에는_401이_없다() {
        // 가입은 토큰을 받지 않으므로 401 이 나갈 수 없다. 붙으면 문서가 거짓말을 한다.
        JsonNode 가입 = 문서.path("paths").path("/api/auth/signup").path("post");
        assertThat(가입.path("responses").has("401")).isFalse();
        assertThat(가입.path("responses").has("500")).isTrue();
        // 전역 JWT 요구를 개별 해제했으므로 빈 배열이어야 한다.
        assertThat(가입.path("security").isArray()).isTrue();
        assertThat(가입.path("security").isEmpty()).isTrue();

        JsonNode 위젯채팅 = 문서.path("paths").path("/api/w/{publicKey}/chat").path("post");
        assertThat(위젯채팅.path("responses").has("401")).isFalse();
        assertThat(위젯채팅.path("security").isEmpty()).isTrue();
    }

    @Test
    @DisplayName("문서 제목과 설명에 아키텍처 한 줄이 들어 있다")
    void 설명에_아키텍처가_들어_있다() {
        assertThat(문서.path("info").path("title").asString()).isEqualTo("AllDap API");
        // 문서를 여는 사람이 가장 먼저 알아야 할 사실이다: 외부에 열린 API 는 Spring 뿐이다.
        assertThat(문서.path("info").path("description").asString()).contains("내부망");
    }

    private String get(String path) {
        try {
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create("http://localhost:" + port + path))
                    .GET()
                    .build();
            return HttpClient.newHttpClient()
                    .send(request, HttpResponse.BodyHandlers.ofString())
                    .body();
        } catch (IOException e) {
            throw new AssertionError("요청이 실패했다: " + path, e);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new AssertionError("요청이 중단됐다: " + path, e);
        }
    }
}
