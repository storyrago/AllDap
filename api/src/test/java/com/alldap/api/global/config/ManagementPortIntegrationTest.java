package com.alldap.api.global.config;

import com.alldap.api.support.IntegrationTest;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.web.server.LocalManagementPort;
import org.springframework.boot.test.web.server.LocalServerPort;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * management 포트(8081) 분리가 실제로 어떻게 동작하는지 <b>재는</b> 테스트.
 *
 * <h2>왜 이 테스트가 필요한가</h2>
 * management 포트를 분리하면 Spring Boot 가 <b>별도 자식 컨텍스트</b>를 만든다.
 * 부모(주 애플리케이션) 컨텍스트의 {@code SecurityFilterChain} 빈이 자식 컨텍스트의
 * 서블릿 필터로도 등록되는지는 <b>문서로 확언할 수 없었다.</b>
 * 등록되지 않으면 8081 은 인증 없이 열리기 때문이다.
 *
 * <p><b>실측 결과: 등록된다.</b> Boot 4.0.7 에서 {@code /actuator/metrics} 는 이 포트에서도
 * 401 이다. 그래서 {@code SecurityConfig} 에 {@code /actuator/prometheus} permitAll 을 추가했다
 * (안 열면 Prometheus 스크레이퍼가 401 만 받는다). 그래도 포트를 열지 않는 방어는 그대로 둔다.
 *
 * <p>포트를 {@code docker-compose.prod.yml} 에서 열지 않으므로 실질 위험은 없다.
 * 그래도 재는 이유는 <b>"그렇게 되어 있다는 걸 아는 것"과 "그럴 것이라 믿는 것"이 다르기</b> 때문이다.
 * 이 저장소는 짜둔 검사가 아무 데서도 안 돌아 오픈 리다이렉트가 뚫린 적이 있다.
 *
 * <h2>{@code @LocalManagementPort} 가 필요한 이유</h2>
 * {@link IntegrationTest} 는 {@code RANDOM_PORT} 다. Boot 의
 * {@code SpringBootTestRandomPortContextCustomizer} 가 서비스 포트뿐 아니라
 * {@code management.server.port} 도 함께 무작위로 바꾼다(그래서 8081 로 고정해도
 * 기존 통합 테스트들이 포트 충돌로 깨지지 않는다). 실제 포트는 이 애너테이션으로 받는다.
 *
 * <h2>{@code TestRestTemplate} 대신 JDK {@code HttpClient} 를 쓰는 이유</h2>
 * Boot 4 에서는 {@code TestRestTemplate} 빈이 자동 등록되지 않는다. 주입받으려면
 * {@code @AutoConfigureTestRestTemplate} 이 필요한데, 그러면 이 클래스만 테스트 설정이 달라져
 * <b>애플리케이션 컨텍스트가 하나 더 생긴다</b>({@link IntegrationTest} 주석이 경계하는 그 상황이다.
 * 컨텍스트가 갈라지면 Testcontainers 도 하나 더 뜬다).
 * 게다가 {@code new TestRestTemplate()} 을 직접 만들어도 {@code spring-boot-http-client} 가
 * 이 프로젝트의 테스트 클래스패스에 없어 {@code NoClassDefFoundError} 가 난다(실측).
 * 이 테스트가 필요한 것은 <b>상태 코드와 본문 문자열</b>뿐이라, 의존성을 늘리는 대신
 * JDK 표준 {@code java.net.http.HttpClient} 로 두 포트를 직접 부른다.
 * (참고: 이 저장소는 Spring→Python 호출에서 {@code HttpClient} 기본값이 HTTP/2 라
 * 겪은 함정이 있는데, 여기는 상대가 톰캣이라 해당되지 않는다.)
 */
@IntegrationTest
@DisplayName("management 포트 분리")
class ManagementPortIntegrationTest {

    /** 서비스 포트(운영의 8080 자리). RANDOM_PORT 라 값은 매 실행마다 다르다. */
    @LocalServerPort
    int serverPort;

    @LocalManagementPort
    int managementPort;

    private final HttpClient http = HttpClient.newHttpClient();

    /** 인증 헤더 없이 GET 한다. 실패를 예외가 아니라 테스트 실패로 보이게 감싼다. */
    private HttpResponse<String> get(int port, String path) {
        try {
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create("http://localhost:" + port + path))
                    .GET()
                    .build();
            return http.send(request, HttpResponse.BodyHandlers.ofString());
        } catch (IOException | InterruptedException e) {
            if (e instanceof InterruptedException) {
                Thread.currentThread().interrupt();  // 인터럽트 상태를 되살린다(삼켜서는 안 된다)
            }
            throw new IllegalStateException(port + " 포트 호출에 실패했다: " + path, e);
        }
    }

    @Test
    @DisplayName("서비스 포트에서는 actuator 가 사라진다")
    void actuatorIsGoneFromServicePort() {
        // actuator 가 자식 컨텍스트로 옮겨갔으므로 이 포트에는 그 경로가 없다.
        HttpResponse<String> response = get(serverPort, "/actuator/health");

        // 🔴 계획은 404 를 기대했지만 실측값은 <500> 이다. 이 PR 이 만든 것이 아니라
        //    GlobalExceptionHandler 의 catch-all(@ExceptionHandler(Exception.class))이
        //    없는 경로의 NoResourceFoundException 까지 INTERNAL_ERROR 로 뭉개기 때문이다.
        //    즉 이 앱에서는 <어떤> 없는 경로든 500 이다. 고치는 것은 별도 슬라이스다.
        //    여기서 재려는 사실은 "이 포트에 actuator 가 없다" 하나뿐이라,
        //    그 무관한 동작에 단언을 못박지 않고 200 이 아님 + 본문에 health 응답이 없음으로 확인한다.
        assertThat(response.statusCode()).isNotEqualTo(200);
        assertThat(response.body()).doesNotContain("\"status\":\"UP\"");
    }

    @Test
    @DisplayName("management 포트에서 health 가 UP 을 준다")
    void healthIsServedOnManagementPort() {
        HttpResponse<String> response = get(managementPort, "/actuator/health");

        assertThat(response.statusCode()).isEqualTo(200);
        assertThat(response.body()).contains("\"status\":\"UP\"");
    }

    @Test
    @DisplayName("management 포트에서 prometheus 스크레이프가 나온다")
    void prometheusIsServedOnManagementPort() {
        HttpResponse<String> response = get(managementPort, "/actuator/prometheus");

        assertThat(response.statusCode()).isEqualTo(200);
        // Prometheus 텍스트 포맷의 첫 글자는 주석(#)이다. 지표 이름 하나로 내용을 확인한다.
        assertThat(response.body()).contains("jvm_memory_used_bytes");
    }

    @Test
    @DisplayName("management 포트에는 Hikari·Tomcat 지표가 실제로 실려 나온다")
    void poolAndThreadMetricsArePresent() {
        // 이 두 지표가 부하테스트의 판정 근거다. 없으면 관측을 구축한 의미가 없다.
        // 특히 tomcat_threads_busy_threads 는 server.tomcat.mbeanregistry.enabled=true 가 없으면
        // 조용히 사라진다(에러가 아니라 지표가 그냥 안 나온다).
        String body = get(managementPort, "/actuator/prometheus").body();

        assertThat(body).contains("hikaricp_connections_pending");
        assertThat(body).contains("tomcat_threads_busy_threads");
    }

    @Test
    @DisplayName("[실측 기록] management 포트에도 SecurityConfig 필터 체인이 붙는다")
    void managementPortIsSecured() {
        // JWT 없이 부른다. /actuator/metrics 는 SecurityConfig 의 anyRequest().authenticated() 대상이다.
        HttpResponse<String> response = get(managementPort, "/actuator/metrics");

        // 🔴 이 단언이 <401> 인 것이 이 테스트의 요점이다. Boot 4.0.7 은 management 포트를
        //    분리해 자식 컨텍스트를 만들면서도 부모의 SecurityFilterChain 을 그 자식에 등록한다.
        //    = 8081 은 인증 없이 통째로 열리지 않는다. 방어가 두 겹이라는 뜻이다:
        //      ① docker-compose.prod.yml 이 api 에 ports: 를 안 써서 호스트에 뜨지 않는다(1차)
        //      ② 그럼에도 metrics 는 인증을 요구한다(2차)
        //    다만 /actuator/prometheus 는 스크레이프를 위해 permitAll 이라 ①이 여전히 유일한 방어다.
        //    ⚠️ 이 테스트가 200 으로 깨지면 Boot 가 동작을 바꾼 것이다. 그때는 이 주석과
        //      application.yaml · application-prod.yaml 의 관련 주석을 함께 고칠 것(깨진 채로 두지 말 것).
        assertThat(response.statusCode()).isEqualTo(401);
    }
}
