package com.alldap.api.global.client;

import lombok.RequiredArgsConstructor;
import org.springframework.boot.health.contributor.Health;
import org.springframework.boot.health.contributor.HealthIndicator;
import org.springframework.stereotype.Component;

/**
 * Python AI 서비스의 상태를 {@code /actuator/health} 에 싣는다. 이름은 {@code aiService} 다
 * (Boot 가 빈 이름 {@code aiServiceHealthIndicator} 에서 접미사를 떼어 붙인다. application.yaml 의
 * health 그룹이 이 이름으로 이 지표를 넣고 뺀다).
 *
 * <h2>왜 필요한가</h2>
 * Python 이 죽으면 채팅·업로드·평가가 전부 죽는다. 그런데 이 지표가 없을 때 Spring 의 health 는
 * <b>UP</b> 이었다. "Spring 이 떠 있다" 와 "서비스가 된다" 를 한 값으로 뭉갠 것이다.
 *
 * <h2>🔴 이 지표는 컨테이너 헬스체크에 들어가지 않는다</h2>
 * 루트 {@code /actuator/health} 에는 들어가지만, {@code docker-compose.prod.yml} 의 api 헬스체크가
 * 부르는 {@code /actuator/health/self} 그룹에서는 <b>빠진다</b>(application.yaml). 이유는 둘이다.
 * <ol>
 *   <li><b>교착.</b> compose 에서 ai-service 는 {@code depends_on: api: condition: service_healthy} 다
 *       (스키마를 Spring 의 Flyway 가 만들기 때문). api 의 healthy 가 Python 에 기대면
 *       api 는 Python 을, Python 은 api 를 기다려 <b>둘 다 영영 안 뜬다.</b></li>
 *   <li><b>장애 전파.</b> 컨테이너 헬스체크는 "이 프로세스를 갈아엎어야 하는가" 를 묻는다.
 *       Python 이 죽었다고 멀쩡한 Spring 을 unhealthy 로 만들면 배포({@code up -d --wait})가 실패하고,
 *       나중에 자동 재시작 장치를 붙이면 Spring 까지 재시작돼 장애가 번진다.</li>
 * </ol>
 *
 * <h2>왜 DOWN 인가 (OUT_OF_SERVICE 가 아니라)</h2>
 * OUT_OF_SERVICE 는 "일부러 내려 둔 것(점검)" 이라는 뜻이다. Python 이 응답하지 않는 것은 점검이 아니라
 * 장애라서 DOWN 이 맞다. 둘 다 HTTP 503 으로 나가므로 상태 코드로 얻는 이득도 없다.
 */
@Component
@RequiredArgsConstructor
public class AiServiceHealthIndicator implements HealthIndicator {

    private final AiServiceClient aiServiceClient;

    @Override
    public Health health() {
        // 원인(연결 실패·타임아웃·Python 500)은 isHealthy() 가 로그에 가른다. 운영은 show-details: never 라
        // 여기 details 를 실어도 밖으로 안 나가므로 싣지 않는다(실리지도 않을 정보를 두 곳에서 관리하지 않는다).
        return aiServiceClient.isHealthy() ? Health.up().build() : Health.down().build();
    }
}
