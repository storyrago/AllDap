package com.alldap.api;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;
import org.springframework.boot.security.autoconfigure.UserDetailsServiceAutoConfiguration;

/**
 * AllDap Spring Boot API (:8080).
 *
 * <p>외부에 노출되는 유일한 API 서비스다. 인증·권한·봇/문서 메타·대화 로그를 담당하고,
 * AI 관련 작업(파싱·임베딩·검색·생성)은 내부망의 Python 서비스(:8001)에 위임한다.
 *
 * <p>{@code @ConfigurationPropertiesScan} 을 붙인 이유:
 * {@code AiServiceProperties} · {@code JwtProperties} 같은 설정 record 를
 * 설정 클래스마다 {@code @EnableConfigurationProperties} 로 일일이 등록하지 않아도 되게 하기 위해서다.
 *
 * <p><b>{@code UserDetailsServiceAutoConfiguration} 을 제외하는 이유.</b>
 * 스프링 시큐리티를 의존성에 넣으면 부트가 "아무 인증 수단도 없으면 곤란하니"
 * 기본 사용자({@code user})를 하나 만들고 무작위 비밀번호를 기동 로그에 찍는다.
 * 우리 인증은 {@code JwtAuthenticationFilter} 가 전부 처리하므로 그 계정은 쓰이지 않는데,
 * ① 기동할 때마다 비밀번호가 로그에 남고
 * ② 우리가 만들지 않은 계정이 {@code AuthenticationManager} 에 등록돼 있다.
 * 지금은 무해하지만 나중에 폼 로그인이나 {@code httpBasic} 을 잠깐 켜는 순간 실제로 로그인되는 계정이 된다.
 * "쓰지 않는 인증 수단은 아예 만들지 않는다"가 안전하다.
 */
@SpringBootApplication(exclude = UserDetailsServiceAutoConfiguration.class)
@ConfigurationPropertiesScan
public class ApiApplication {

	public static void main(String[] args) {
		SpringApplication.run(ApiApplication.class, args);
	}

}
