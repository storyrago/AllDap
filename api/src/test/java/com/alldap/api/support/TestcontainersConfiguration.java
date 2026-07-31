package com.alldap.api.support;

import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.springframework.context.annotation.Bean;
import org.testcontainers.postgresql.PostgreSQLContainer;
import org.testcontainers.utility.DockerImageName;

/**
 * 통합 테스트가 붙을 PostgreSQL 컨테이너 정의. 이 파일이 <b>유일한</b> 컨테이너 선언 지점이다.
 *
 * <h2>왜 H2 가 아니라 진짜 PostgreSQL 인가</h2>
 * 이 프로젝트에서 스키마의 단일 진실 공급원은 Flyway 마이그레이션
 * ({@code src/main/resources/db/migration/V1__init.sql})이다.
 * 그 SQL 은 {@code CREATE EXTENSION vector}, {@code TEXT[]}, {@code JSONB},
 * {@code gen_random_uuid()} 처럼 PostgreSQL 전용 문법을 쓴다.
 * H2 로는 마이그레이션이 아예 실행되지 않고, 억지로 우회하면
 * "테스트는 통과하는데 운영에서 깨지는" 상태가 된다.
 * 게다가 Spring 의 JPA 엔티티는 {@code ddl-auto: validate} 로 <b>실제 스키마와 대조</b>되는데,
 * 대조 상대가 가짜 스키마면 검증의 의미가 사라진다.
 *
 * <h2>⚠️ 함정 1 — 평범한 {@code postgres:16} 이미지로는 기동이 실패한다</h2>
 * {@code V1__init.sql} 첫 줄이 {@code CREATE EXTENSION IF NOT EXISTS vector} 다.
 * 공식 {@code postgres} 이미지에는 pgvector 확장이 들어 있지 않아
 * Flyway 가 {@code ERROR: extension "vector" is not available} 로 죽고,
 * 그 결과 애플리케이션 컨텍스트 로딩 자체가 실패한다.
 * 그래서 pgvector 가 미리 설치된 {@code pgvector/pgvector:pg16} 이미지를 쓴다.
 * (로컬 개발용 {@code docker-compose.yml} 도 같은 계열 이미지를 쓴다 — 테스트와 로컬을 일치시킨다.)
 *
 * <h2>⚠️ 함정 2 — {@code asCompatibleSubstituteFor("postgres")}</h2>
 * Testcontainers 는 "PostgreSQLContainer 에는 postgres 이미지가 와야 한다"고 검증한다.
 * 이름이 {@code pgvector/pgvector} 라 그대로 넘기면
 * {@code IllegalStateException: Failed to verify that image ... is a compatible substitute for "postgres"} 로 거절당한다.
 * {@code asCompatibleSubstituteFor} 는 "이 이미지는 postgres 를 대체할 수 있다"고 우리가 보증하는 선언이다.
 *
 * <h2>왜 {@code @ServiceConnection} 인가 ({@code @DynamicPropertySource} 대신)</h2>
 * 예전 방식은 컨테이너를 띄운 뒤 {@code spring.datasource.url/username/password} 를
 * 손으로 하나씩 덮어쓰는 것이었다. {@code @ServiceConnection} 은
 * 컨테이너 타입을 보고 그 배선을 Boot 가 알아서 한다 — 손으로 적을 프로퍼티 이름이 없으니
 * 오타로 조용히 로컬 DB 에 붙어버리는 사고가 구조적으로 사라진다.
 * 컨테이너의 start/stop 도 Boot 가 관리하므로 {@code @Testcontainers}·{@code @Container}
 * (testcontainers-junit-jupiter 모듈)가 필요 없다. 그래서 그 의존성을 넣지 않았다 —
 * 생명주기를 관리하는 주체는 하나여야 한다.
 *
 * <h2>컨테이너가 테스트 클래스마다 새로 뜨지 않는 이유</h2>
 * 컨테이너는 스프링 <b>빈</b>이라 애플리케이션 컨텍스트와 수명을 같이 한다.
 * 스프링 테스트 프레임워크는 <b>설정이 같은 컨텍스트를 캐시해 재사용</b>하므로,
 * 모든 통합 테스트가 {@link IntegrationTest} 하나로 똑같은 설정을 갖게 하면
 * 컨텍스트가 하나만 만들어지고 → 컨테이너도 하나만 뜬다.
 * 반대로 테스트마다 {@code @SpringBootTest} 옵션을 제각각 붙이면 설정이 갈라져
 * 컨텍스트가 여러 개 생기고 Docker 컨테이너도 그만큼 뜬다. 그래서 조합을 흩뿌리지 않는다.
 */
@TestConfiguration(proxyBeanMethods = false)
public class TestcontainersConfiguration {

    /**
     * pgvector 가 포함된 PostgreSQL 16 이미지.
     * {@code V1__init.sql} 의 {@code VECTOR(1536)} 컬럼 정의가 이 확장에 의존한다.
     */
    private static final DockerImageName PGVECTOR_IMAGE =
            DockerImageName.parse("pgvector/pgvector:pg16")
                    .asCompatibleSubstituteFor("postgres");

    /**
     * ⚠️ Testcontainers 2.x 에서 {@code PostgreSQLContainer} 의 패키지가 바뀌었다.
     * 1.x: {@code org.testcontainers.containers.PostgreSQLContainer<SELF>} (제네릭 self-type)
     * 2.x: {@code org.testcontainers.postgresql.PostgreSQLContainer} (제네릭 없음)
     * 1.x 예제를 그대로 붙여넣으면 {@code PostgreSQLContainer<?>} 같은 제네릭 표기에서 컴파일이 깨진다.
     */
    @Bean
    @ServiceConnection
    PostgreSQLContainer postgresContainer() {
        return new PostgreSQLContainer(PGVECTOR_IMAGE);
    }
}
