package com.alldap.api.global.config;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

import java.time.Duration;

/**
 * Python AI 서비스(:8001) 호출 설정. {@code application.yaml} 의 {@code app.ai-service.*} 를 바인딩한다.
 *
 * <p>record 로 둔 이유: 설정값은 기동 시점에 정해지고 이후 바뀌지 않으므로 불변이 맞다.
 * Spring Boot 는 record 를 생성자 바인딩으로 처리한다.
 *
 * @param baseUrl        Python 서비스 주소. 내부망 전용이며 절대 외부에 노출하면 안 된다.
 * @param connectTimeout TCP 연결 타임아웃
 * @param readTimeout    응답 대기 타임아웃 (RestClientConfig 주석에 근거 설명)
 * @param retryMaxAttempts 총 시도 횟수(재시도 횟수가 아니다). 1 이면 재시도하지 않는다.
 *                         <b>연결 실패에만 적용된다</b> — 근거는 AiServiceClient 의 재시도 주석 참고.
 * @param retryDelay       재시도 전 대기. 길게 잡으면 사용자를 그만큼 더 기다리게 한다.
 * @param circuitFailureThreshold 연속 실패 몇 번에 서킷을 열 것인가
 * @param circuitOpenDuration     서킷이 열린 뒤 얼마 동안 호출하지 않을 것인가
 */
@ConfigurationProperties(prefix = "app.ai-service")
public record AiServiceProperties(
        String baseUrl,
        Duration connectTimeout,
        Duration readTimeout,
        @DefaultValue("2") int retryMaxAttempts,
        @DefaultValue("200ms") Duration retryDelay,
        @DefaultValue("5") int circuitFailureThreshold,
        @DefaultValue("30s") Duration circuitOpenDuration
) {
}
