package com.alldap.api.global.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;

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

    @Bean
    public SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {
        http
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
                        // 브라우저가 본 요청 전에 보내는 프리플라이트는 인증 대상이 아니다.
                        .requestMatchers(HttpMethod.OPTIONS, "/**").permitAll()
                        // ── 그 외 전부 인증 필요 ────────────────────────────────────
                        .anyRequest().authenticated()
                );

        // TODO(W2): JWT 인증 필터를 UsernamePasswordAuthenticationFilter 앞에 끼워 넣을 것.
        //   http.addFilterBefore(jwtAuthenticationFilter, UsernamePasswordAuthenticationFilter.class);
        //   필터가 없는 지금은 보호 경로가 전부 401 로 떨어진다. 이는 의도된 상태다
        //   (인증을 통과시키는 가짜 구현을 두는 것보다 안전하다).

        // TODO(W2): 인증/인가 실패 시에도 PRD §10.3 공통 에러 포맷
        //   {"error":{"code":"...","message":"..."}} 이 나가도록
        //   AuthenticationEntryPoint / AccessDeniedHandler 를 붙일 것.
        //   지금은 Spring Security 기본 응답이라 포맷이 다르다.

        // TODO(W2): CORS 설정. 관리자 화면(Next.js :3000)과 위젯을 심은 고객 도메인(bots.allowed_origins)은
        //   서로 다른 출처다. /api/w/** 는 봇별 allowed_origins 를 동적으로 검사해야 하므로
        //   정적 CorsConfigurationSource 만으로는 부족하다.

        return http.build();
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
