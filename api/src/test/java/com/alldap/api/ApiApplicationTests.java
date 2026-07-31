package com.alldap.api;

import com.alldap.api.support.IntegrationTest;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 애플리케이션 컨텍스트가 뜨는지 확인하는 최소 테스트.
 *
 * <p>사실상 <b>스키마 정합성 테스트</b>다. 컨텍스트가 뜨려면
 * ① Flyway 마이그레이션이 전부 성공하고 ② Hibernate 의 {@code ddl-auto: validate} 가
 * 모든 엔티티를 실제 테이블과 대조해 통과해야 하기 때문이다.
 * 엔티티에 컬럼을 잘못 적으면 이 테스트가 먼저 깨진다.
 *
 * <p>{@code @SpringBootTest} 를 직접 붙이지 않고 {@link IntegrationTest} 를 쓰는 이유:
 * 설정 조합이 다르면 스프링이 애플리케이션 컨텍스트를 하나 더 만들고,
 * 그러면 Testcontainers 컨테이너도 하나 더 뜬다. 조합은 한 곳에서만 정의한다.
 */
@IntegrationTest
@DisplayName("애플리케이션 컨텍스트 로딩 (Flyway 마이그레이션 + JPA 스키마 검증)")
class ApiApplicationTests {

	@Test
	void contextLoads() {
	}

}
