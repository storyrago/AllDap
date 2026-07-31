package com.alldap.api.global.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.data.jpa.repository.config.EnableJpaAuditing;

/**
 * JPA 감사(auditing) 설정.
 *
 * <p>{@code @EnableJpaAuditing} 이 있어야 {@link com.alldap.api.global.common.BaseEntity} 의
 * {@code @CreatedDate} 가 동작한다.
 *
 * <p>메인 클래스가 아니라 별도 설정 클래스에 둔 이유:
 * {@code @EnableJpaAuditing} 을 {@code @SpringBootApplication} 에 붙이면
 * {@code @WebMvcTest} 같은 슬라이스 테스트에서도 감사 설정이 딸려 올라와
 * {@code JpaMetamodelMappingContext} 빈이 없다는 이유로 테스트가 깨진다.
 */
@Configuration
@EnableJpaAuditing
public class JpaConfig {
}
