package com.alldap.api.global.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.time.Duration;

/**
 * JWT 설정. {@code application.yaml} 의 {@code app.jwt.*} 를 바인딩한다.
 *
 * @param secret         서명 키. 로컬에만 기본값이 있고 운영(application-prod.yaml)에서는
 *                       {@code JWT_SECRET} 환경변수가 없으면 기동이 실패한다.
 *                       HS256 은 최소 256비트(32바이트) 이상이어야 한다.
 * @param accessTokenTtl 액세스 토큰 유효 기간
 */
@ConfigurationProperties(prefix = "app.jwt")
public record JwtProperties(
        String secret,
        Duration accessTokenTtl
) {
}
