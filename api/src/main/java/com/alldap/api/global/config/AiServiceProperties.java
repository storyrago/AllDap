package com.alldap.api.global.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

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
 */
@ConfigurationProperties(prefix = "app.ai-service")
public record AiServiceProperties(
        String baseUrl,
        Duration connectTimeout,
        Duration readTimeout
) {
}
