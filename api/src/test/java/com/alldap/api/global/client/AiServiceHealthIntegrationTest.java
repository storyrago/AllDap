package com.alldap.api.global.client;

import com.alldap.api.support.AiServiceStub;
import com.alldap.api.support.IntegrationTest;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.web.server.LocalManagementPort;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Python 상태가 {@code /actuator/health} 에 어떻게 실리는지 <b>진짜 HTTP 로</b> 확인한다.
 *
 * <p>가짜 Python({@link AiServiceStub}) 을 세워 두고 management 포트를 직접 부른다.
 * 스텁은 준비된 응답이 없으면 500 을 주므로, 아무것도 넣지 않은 상태가 곧 "Python 이 아프다" 다.
 *
 * <p>여기서 지키려는 사실은 셋이다.
 * <ol>
 *   <li>루트는 Python 이 아프면 DOWN 이다 (예전엔 UP 이었다 = 거짓 신호)</li>
 *   <li>컨테이너 헬스체크가 부르는 {@code self} 는 Python 이 아파도 UP 이고, <b>Python 을 부르지도 않는다</b>
 *       (부르면 compose 의 depends_on 과 교착한다. AiServiceHealthIndicator 주석)</li>
 *   <li>헬스체크는 서킷브레이커를 건드리지도, 따르지도 않는다</li>
 * </ol>
 *
 * <p>JDK {@code HttpClient} 를 쓰는 이유는 {@code ManagementPortIntegrationTest} 의 클래스 주석과 같다.
 */
@IntegrationTest
@DisplayName("Python 헬스체크가 actuator health 에 실리는 방식")
class AiServiceHealthIntegrationTest {

    // 본문 전체가 아니라 status 조각만 본다. 루트 응답에는 그룹 목록({"groups":[...]})도 함께 실린다.
    private static final String UP = "\"status\":\"UP\"";
    private static final String DOWN = "\"status\":\"DOWN\"";
    private static final String PYTHON_OK = "{\"status\":\"ok\"}";

    @LocalManagementPort
    int managementPort;

    @Autowired
    AiServiceStub aiService;

    // 🔴 상태를 가진 싱글턴이다. 다른 테스트가 열어 둔 서킷이 이 클래스로 새지 않게 매번 비운다.
    @Autowired
    AiServiceCircuitBreaker circuitBreaker;

    private final HttpClient http = HttpClient.newHttpClient();

    @BeforeEach
    void setUp() {
        aiService.reset();
        circuitBreaker.reset();
    }

    private HttpResponse<String> health(String suffix) {
        try {
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create("http://localhost:" + managementPort + "/actuator/health" + suffix))
                    .GET()
                    .build();
            return http.send(request, HttpResponse.BodyHandlers.ofString());
        } catch (IOException | InterruptedException e) {
            if (e instanceof InterruptedException) {
                Thread.currentThread().interrupt();
            }
            throw new IllegalStateException("health 호출에 실패했다: " + suffix, e);
        }
    }

    private long healthProbesSent() {
        return aiService.received().stream().filter(r -> r.path().equals("/health")).count();
    }

    @Test
    @DisplayName("Python 이 ok 를 주면 루트와 ai-service 그룹이 UP 이다")
    void pythonOk() {
        aiService.enqueue(200, PYTHON_OK);
        HttpResponse<String> root = health("");

        aiService.enqueue(200, PYTHON_OK);
        HttpResponse<String> ai = health("/ai-service");

        assertThat(root.statusCode()).isEqualTo(200);
        assertThat(root.body()).contains(UP);
        assertThat(ai.statusCode()).isEqualTo(200);
        assertThat(ai.body()).contains(UP);
        // 경로와 메서드까지 본다. 엉뚱한 경로를 불러도 스텁은 큐에서 응답을 꺼내 주기 때문이다.
        assertThat(aiService.received()).allSatisfy(r -> {
            assertThat(r.method()).isEqualTo("GET");
            assertThat(r.path()).isEqualTo("/health");
        });
    }

    @Test
    @DisplayName("Python 이 500 이면 루트와 ai-service 는 DOWN(503), self 는 UP 이다")
    void python500() {
        // 스텁에 응답을 넣지 않으면 500 이다 = Python 의 /health 가 DB 에 못 붙은 모양
        HttpResponse<String> root = health("");
        HttpResponse<String> ai = health("/ai-service");

        assertThat(root.statusCode()).isEqualTo(503);
        assertThat(root.body()).contains(DOWN);
        assertThat(ai.statusCode()).isEqualTo(503);
        assertThat(ai.body()).contains(DOWN);

        aiService.reset();
        HttpResponse<String> self = health("/self");
        assertThat(self.statusCode()).isEqualTo(200);
        assertThat(self.body()).contains(UP);
    }

    @Test
    @DisplayName("self 그룹은 Python 을 아예 부르지 않는다 (compose 교착 방지)")
    void selfDoesNotCallPython() {
        // "UP 이 나왔다" 만으로는 부족하다. Python 을 부르고 결과만 버리는 구현이어도 UP 이 나온다.
        // 교착을 막는 것은 <부르지 않는 것>이므로 요청이 스텁에 닿지 않았는지를 본다.
        HttpResponse<String> self = health("/self");

        assertThat(self.statusCode()).isEqualTo(200);
        assertThat(healthProbesSent()).isZero();
    }

    @Test
    @DisplayName("2xx 라도 status 가 ok 가 아니면 DOWN 이다")
    void pythonNotOkBody() {
        aiService.enqueue(200, "{\"status\":\"starting\"}");

        assertThat(health("/ai-service").statusCode()).isEqualTo(503);
    }

    @Test
    @DisplayName("Python 이 응답 도중 끊으면 DOWN 이다")
    void pythonAborts() {
        aiService.enqueueAbort();

        assertThat(health("/ai-service").statusCode()).isEqualTo(503);
    }

    @Test
    @DisplayName("Python 이 느리면 채팅의 읽기 타임아웃이 아니라 health-timeout(2초)에서 끊고 DOWN 이다")
    void pythonSlow() {
        // 테스트의 채팅 읽기 타임아웃도 2초라 그것만으로는 둘을 못 가른다. 그래서 시간이 아니라
        // "DOWN 으로 끝나고, 재시도 없이 한 번만 불렀는가" 를 본다. 재시도(연결 실패 전용)도 여기선 안 탄다.
        aiService.enqueueSlow(Duration.ofSeconds(4), 200, PYTHON_OK);

        long started = System.nanoTime();
        HttpResponse<String> ai = health("/ai-service");
        Duration took = Duration.ofNanos(System.nanoTime() - started);

        assertThat(ai.statusCode()).isEqualTo(503);
        assertThat(took).isLessThan(Duration.ofSeconds(4));
        assertThat(healthProbesSent()).isEqualTo(1);
    }

    @Test
    @DisplayName("헬스체크 실패는 서킷의 연속 실패로 세지 않는다")
    void healthFailuresDoNotOpenCircuit() {
        // 기본 임계치는 5회다. 넉넉히 넘겨 부른다.
        for (int i = 0; i < 7; i++) {
            assertThat(health("/ai-service").statusCode()).isEqualTo(503);
        }

        assertThat(circuitBreaker.state()).isEqualTo(AiServiceCircuitBreaker.State.CLOSED);
    }

    @Test
    @DisplayName("서킷이 열려 있어도 헬스체크는 Python 을 실제로 부르고, 성공해도 서킷을 닫지 않는다")
    void healthIgnoresOpenCircuit() {
        for (int i = 0; i < 5; i++) {
            circuitBreaker.recordFailure();
        }
        assertThat(circuitBreaker.state()).isEqualTo(AiServiceCircuitBreaker.State.OPEN);

        aiService.enqueue(200, PYTHON_OK);
        HttpResponse<String> ai = health("/ai-service");

        // 서킷을 따랐다면 Python 을 부르지 않고 DOWN 이었을 것이다
        assertThat(ai.statusCode()).isEqualTo(200);
        assertThat(healthProbesSent()).isEqualTo(1);
        // 서킷을 닫는 것은 사용자 요청(HALF_OPEN 탐색)의 성공뿐이다
        assertThat(circuitBreaker.state()).isEqualTo(AiServiceCircuitBreaker.State.OPEN);
    }
}
