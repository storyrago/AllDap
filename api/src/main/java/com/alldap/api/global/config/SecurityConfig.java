package com.alldap.api.global.config;

import com.alldap.api.domain.auth.filter.JwtAuthenticationFilter;
import com.alldap.api.domain.auth.service.JwtService;
import com.alldap.api.global.exception.ApiAccessDeniedHandler;
import com.alldap.api.global.exception.ApiAuthenticationEntryPoint;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.CorsConfigurationSource;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;

import java.time.Duration;
import java.util.List;

/**
 * 보안 설정.
 *
 * <p>설계 결정 세 가지:
 * <ol>
 *   <li><b>세션을 쓰지 않는다(STATELESS).</b> 인증 상태를 JWT 에 담기 때문이다.
 *       위젯은 고객 사이트의 iframe 안에서 동작해 쿠키·세션이 서드파티 취급을 받아 신뢰하기 어렵다.</li>
 *   <li><b>CSRF 를 끈다.</b> CSRF 는 브라우저가 쿠키를 자동으로 실어 보내는 것을 악용하는 공격인데,
 *       우리는 쿠키가 아니라 {@code Authorization} 헤더로 인증하므로 해당 공격면이 없다.</li>
 *   <li><b>공개 경로와 보호 경로를 여기서 한 번에 선언한다.</b>
 *       위젯 API({@code /api/w/**})는 엔드유저가 인증 없이 호출하므로 공개다.
 *       대신 그 보호 수단이 publicKey + Origin 검증 + rate limit 이다.</li>
 * </ol>
 */
@Configuration
@EnableWebSecurity
public class SecurityConfig {

    /**
     * @param jwtService                 JWT 필터를 여기서 직접 조립하기 위해 주입받는다.
     *                                   필터를 빈으로 만들지 않는 이유는 {@link JwtAuthenticationFilter} 주석 참고.
     * @param authenticationEntryPoint   인증 실패(401) 응답을 공통 포맷으로 쓰는 컴포넌트
     * @param accessDeniedHandler        인가 실패(403) 응답을 공통 포맷으로 쓰는 컴포넌트
     * @param corsConfigurationSource    어느 오리진의 요청을 허용할지 정하는 규칙 (아래 빈)
     */
    @Bean
    public SecurityFilterChain securityFilterChain(HttpSecurity http,
                                                   JwtService jwtService,
                                                   ApiAuthenticationEntryPoint authenticationEntryPoint,
                                                   ApiAccessDeniedHandler accessDeniedHandler,
                                                   CorsConfigurationSource corsConfigurationSource) throws Exception {
        http
                // CORS 를 Security 필터 체인 안에서 처리한다.
                // 여기 배선하면 스프링 시큐리티가 CorsFilter 를 체인 <b>맨 앞쪽</b>(인가 판단보다 먼저)에 넣어준다.
                // 프리플라이트(OPTIONS)는 이 필터가 직접 응답하고 체인을 더 진행시키지 않는다.
                .cors(cors -> cors.configurationSource(corsConfigurationSource))
                .csrf(csrf -> csrf.disable())
                .httpBasic(basic -> basic.disable())
                .formLogin(form -> form.disable())
                .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .authorizeHttpRequests(auth -> auth
                        // ── 공개 경로 ───────────────────────────────────────────────
                        // 가입·로그인은 당연히 토큰 없이 호출된다.
                        .requestMatchers("/api/auth/signup", "/api/auth/login").permitAll()
                        // 위젯 API. 고객 사이트에 심긴 위젯이 부르므로 JWT 가 없다.
                        // 보호는 publicKey + Origin 검증 + rate limit 으로 한다. TODO(W2)
                        .requestMatchers("/api/w/**").permitAll()
                        // 헬스체크만 공개. 나머지 actuator 엔드포인트는 노출하지 않는다.
                        .requestMatchers("/actuator/health").permitAll()
                        // (예전에 있던 `OPTIONS /** permitAll` 은 지웠다.
                        //  위 .cors(...) 배선으로 프리플라이트는 CorsFilter 가 인가 판단 <b>전에</b> 끝내므로
                        //  더 이상 필요 없고, 남겨두면 모든 경로에 대해 OPTIONS 를 인증 없이 열어두는 셈이라
                        //  "어떤 경로가 존재하는지"를 떠보는 통로만 남는다)
                        // ── 그 외 전부 인증 필요 ────────────────────────────────────
                        .anyRequest().authenticated()
                )
                // 인증·인가 실패도 PRD §10.3 공통 포맷 {"error":{"code":...,"message":...}} 으로 내보낸다.
                // 이 두 줄이 없으면 Spring Security 기본 응답(빈 본문 401 / HTML 403)이 나가
                // 프론트의 ApiErrorBody 파싱이 깨진다. 컨트롤러까지 도달하지 못한 요청이라
                // GlobalExceptionHandler 로는 잡을 수 없는 구간이다.
                .exceptionHandling(handling -> handling
                        .authenticationEntryPoint(authenticationEntryPoint)   // 401
                        .accessDeniedHandler(accessDeniedHandler)             // 403
                )
                // JWT 필터를 UsernamePasswordAuthenticationFilter '앞'에 끼운다.
                // 앞에 두는 이유: 그 지점이 "요청에서 인증 정보를 꺼내 SecurityContext 를 채우는" 자리이고,
                // 뒤쪽의 인가 필터(AuthorizationFilter)가 판단을 내리기 전에 컨텍스트가 채워져 있어야 한다.
                // 우리는 폼 로그인을 쓰지 않으므로 UsernamePasswordAuthenticationFilter 자체는 동작하지 않지만,
                // 체인에서의 '위치 기준점'으로는 그대로 유효하다.
                .addFilterBefore(new JwtAuthenticationFilter(jwtService), UsernamePasswordAuthenticationFilter.class);

        return http.build();
    }

    /**
     * CORS 규칙.
     *
     * <p><b>왜 필요한가.</b> 관리자 화면은 Next.js(:3000), API 는 Spring(:8080)이다.
     * 포트가 다르면 브라우저는 <b>다른 출처</b>로 본다. 서버가 "이 출처는 괜찮다"고 응답 헤더로
     * 말해주지 않으면 브라우저가 응답을 자바스크립트에 넘기지 않는다.
     * (요청 자체는 서버에 도착한다 — 막는 주체는 서버가 아니라 브라우저다)
     *
     * <p><b>설정 하나하나의 근거</b>
     * <ul>
     *   <li>{@code allowedOrigins} — 설정값에서 읽는다. {@code allowedOriginPatterns} 로
     *       와일드카드를 쓰지 않는다. 오리진 허용은 "정확히 이 주소만"이어야 한다.</li>
     *   <li>{@code allowedHeaders} — {@code Authorization}(JWT)과 {@code Content-Type}(JSON) 둘뿐이다.
     *       {@code *} 로 열지 않는 이유는, 나중에 어떤 헤더가 오가는지 이 목록만 보면 알 수 있게 하기 위해서다.
     *       ⚠️ {@code Authorization} 은 브라우저가 '단순 요청'으로 안 봐서 <b>프리플라이트를 유발</b>한다.
     *       이 목록에 없으면 로그인 후 모든 API 호출이 막힌다.</li>
     *   <li>{@code allowCredentials(false)} — 우리는 쿠키·세션을 쓰지 않고 토큰을 헤더에 실어 보낸다
     *       (SecurityConfig 설계 결정 ①). credentials 는 <b>쿠키</b>를 위한 스위치라 켤 이유가 없다.
     *       켜면 오리진에 {@code *} 를 못 쓰는 등 제약만 늘고, 실수로 쿠키 인증이 섞여 들어올 여지가 생긴다.</li>
     *   <li>{@code maxAge} — 프리플라이트 응답을 브라우저가 1시간 캐시한다. 이게 없으면
     *       API 호출마다 OPTIONS 가 한 번씩 더 붙는다(요청 수가 두 배).</li>
     * </ul>
     *
     * <h2>위젯({@code /api/w/**})은 <b>모든 오리진에 열어두고</b> 검사는 애플리케이션이 한다</h2>
     * 처음에는 봇의 {@code allowed_origins} 를 CORS 응답에 그대로 실어 브라우저가 막게 만들었다.
     * <b>동작은 했지만 잘못된 설계였다.</b> 두 가지 이유로 되돌렸다.
     *
     * <ol>
     *   <li><b>CORS 는 인가 수단이 아니다.</b> 브라우저에게 "이 응답을 스크립트에 넘겨도 되나" 를
     *       알려주는 정책일 뿐이고, 브라우저가 아닌 호출자(curl·서버)는 아예 신경 쓰지 않는다.
     *       즉 CORS 로 막아도 <b>요청은 그대로 처리되고 LLM 비용도 그대로 나간다.</b></li>
     *   <li><b>우리 에러 메시지를 읽을 수 없게 만든다.</b> CORS 필터가 먼저 끊으면
     *       응답 본문이 {@code Invalid CORS request} 평문이 되어
     *       PRD §10.3 의 {@code {"error":{...}}} 포맷이 깨진다. 그러면 위젯은
     *       "허용 도메인에 이 주소를 추가하세요" 라는 <b>해결 방법을 사용자에게 보여줄 수 없다.</b></li>
     * </ol>
     *
     * <p>그래서 브라우저에게는 열어주고, <b>진짜 판단은 {@code WidgetController} 가</b> 한다.
     * 거기서 403 + 한국어 안내를 공통 포맷으로 내려준다.
     * 이 순서 덕분에 위젯은 실패 사유를 화면에 그대로 띄울 수 있다.
     *
     * <p>{@code UrlBasedCorsConfigurationSource} 는 등록 순서대로 훑다가 처음 일치하는 규칙을 쓰므로
     * {@code "/api/w/**"} 를 {@code "/api/**"} 보다 <b>먼저</b> 등록해야 한다.
     */
    @Bean
    public CorsConfigurationSource corsConfigurationSource(CorsProperties corsProperties) {
        CorsConfiguration adminApi = new CorsConfiguration();
        adminApi.setAllowedOrigins(corsProperties.allowedOrigins());
        // OPTIONS 는 넣지 않아도 된다. 프리플라이트에서 검사하는 대상은 OPTIONS 자체가 아니라
        // Access-Control-Request-Method 에 적힌 "진짜 보낼 메서드"이기 때문이다.
        adminApi.setAllowedMethods(List.of("GET", "POST", "PATCH", "PUT", "DELETE"));
        adminApi.setAllowedHeaders(List.of("Authorization", "Content-Type"));
        adminApi.setAllowCredentials(false);
        adminApi.setMaxAge(Duration.ofHours(1));

        CorsConfiguration widgetApi = new CorsConfiguration();
        // 위젯은 고객 도메인이 무엇이든 설치될 수 있다. 목록을 미리 알 수 없으므로 전부 허용하고,
        // "이 봇을 이 도메인에서 써도 되는가" 는 WidgetController 가 판단한다.
        widgetApi.setAllowedOrigins(List.of("*"));
        widgetApi.setAllowedMethods(List.of("GET", "POST"));
        // 위젯은 JWT 를 쓰지 않는다. Content-Type 만 있으면 된다.
        widgetApi.setAllowedHeaders(List.of("Content-Type"));
        // ⚠️ 오리진을 * 로 여는 이상 credentials 는 절대 켜면 안 된다(브라우저도 거부한다).
        // 우리는 쿠키를 쓰지 않으므로 켤 이유도 없다.
        widgetApi.setAllowCredentials(false);
        widgetApi.setMaxAge(Duration.ofHours(1));

        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/api/w/**", widgetApi);   // ← 반드시 먼저
        source.registerCorsConfiguration("/api/**", adminApi);
        return source;
    }

    /**
     * 비밀번호 해시. {@code users.password_hash} 에 저장된다.
     *
     * <p>BCrypt 를 쓰는 이유: 의도적으로 느린 해시(work factor)라 무차별 대입에 강하고,
     * salt 가 해시 문자열 안에 함께 저장돼 별도 컬럼이 필요 없다.
     * (스키마에도 salt 컬럼이 없다 — password_hash 하나뿐이다.)
     */
    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }
}
