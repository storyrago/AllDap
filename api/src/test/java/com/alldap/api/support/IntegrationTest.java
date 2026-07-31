package com.alldap.api.support;

import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;

import java.lang.annotation.Documented;
import java.lang.annotation.ElementType;
import java.lang.annotation.Inherited;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * 통합 테스트용 메타 애너테이션. 통합 테스트는 <b>전부</b> 이것 하나만 붙인다.
 *
 * <h2>왜 애너테이션을 따로 만드는가</h2>
 * 테스트마다 {@code @SpringBootTest(...)} + {@code @Import(...)} 를 손으로 조합하면
 * 조합이 조금씩 어긋나기 마련이다. 그런데 스프링 테스트는 <b>설정이 같을 때만</b>
 * 애플리케이션 컨텍스트를 캐시해 재사용한다. 조합이 갈라지는 순간 컨텍스트가 하나 더 생기고,
 * 컨테이너는 그 컨텍스트의 빈이므로 <b>Docker 컨테이너도 하나 더 뜬다</b>.
 * 설정을 여기 한 곳에 못 박아두면 그 사고가 구조적으로 불가능해진다.
 *
 * <h2>{@code RANDOM_PORT} 인 이유</h2>
 * 실제 톰캣을 띄우되 포트는 OS 가 비어 있는 것을 골라준다.
 * 8080 같은 고정 포트를 쓰면 개발 중인 애플리케이션이나 다른 테스트와 충돌해
 * "내 코드는 안 건드렸는데 테스트가 깨지는" 상황이 생긴다.
 * 실제 포트는 {@code @LocalServerPort} 로 주입받거나, {@code TestRestTemplate} 이
 * 상대 경로를 자동으로 붙여 처리한다.
 *
 * <p>{@code MOCK} 환경(=서블릿 컨테이너 없이 MockMvc)이 아니라 실제 서버를 띄우는 이유:
 * 우리가 검증하려는 것 중 상당수(401 응답 본문 포맷, 한글 인코딩, Security 필터 체인)가
 * <b>컨트롤러 바깥</b>에서 결정되기 때문이다. 진짜 HTTP 를 태워야 그 구간까지 검증된다.
 *
 * <h2>애너테이션 문법 메모</h2>
 * <ul>
 *   <li>{@code @Target(TYPE)} — 클래스에만 붙일 수 있게 제한</li>
 *   <li>{@code @Retention(RUNTIME)} — 스프링이 실행 중에 리플렉션으로 읽어야 하므로 필수.
 *       기본값(CLASS)이면 런타임에 보이지 않아 아무 일도 일어나지 않는다.</li>
 *   <li>{@code @Inherited} — 상위 클래스에 붙인 설정을 하위 테스트 클래스가 물려받게 한다</li>
 * </ul>
 */
@Documented
@Target(ElementType.TYPE)
@Retention(RetentionPolicy.RUNTIME)
@Inherited
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@Import(TestcontainersConfiguration.class)
public @interface IntegrationTest {
}
