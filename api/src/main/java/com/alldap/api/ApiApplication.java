package com.alldap.api;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;

/**
 * AllDap Spring Boot API (:8080).
 *
 * <p>외부에 노출되는 유일한 API 서비스다. 인증·권한·봇/문서 메타·대화 로그를 담당하고,
 * AI 관련 작업(파싱·임베딩·검색·생성)은 내부망의 Python 서비스(:8001)에 위임한다.
 *
 * <p>{@code @ConfigurationPropertiesScan} 을 붙인 이유:
 * {@code AiServiceProperties} · {@code JwtProperties} 같은 설정 record 를
 * 설정 클래스마다 {@code @EnableConfigurationProperties} 로 일일이 등록하지 않아도 되게 하기 위해서다.
 */
@SpringBootApplication
@ConfigurationPropertiesScan
public class ApiApplication {

	public static void main(String[] args) {
		SpringApplication.run(ApiApplication.class, args);
	}

}
