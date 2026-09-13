package com.alldap.api.domain.auth.filter;

import com.alldap.api.domain.auth.service.JwtService;
import com.alldap.api.global.exception.ApiException;
import com.alldap.api.global.exception.ErrorResponseWriter;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContext;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.authentication.WebAuthenticationDetailsSource;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.List;

/**
 * {@code Authorization: Bearer <token>} 을 읽어 SecurityContext 에 인증 정보를 넣는 필터.
 *
 * <h2>왜 {@code domain/auth/filter} 에 두었나</h2>
 * 선택지는 {@code global/config} 와 여기 둘이었다. {@code global/config} 는 <b>배선(wiring)</b>을 담는 곳이고,
 * 이 클래스는 배선이 아니라 <b>실행 시점에 매 요청을 처리하는 인증 로직</b>이다.
 * 의존 대상도 인증 도메인 서비스({@link JwtService})다.
 * "어디에 끼워 넣을지"는 {@code SecurityConfig}(global/config)가 정하고,
 * "무엇을 하는지"는 인증 도메인인 여기에 둔다 — 이렇게 나누면 나중에 인증 방식을 바꿀 때
 * 고칠 파일이 도메인 안에 모인다.
 *
 * <h2>왜 {@code @Component} 를 붙이지 않았나 (중요)</h2>
 * Spring Boot 는 {@code Filter} 타입 <b>빈</b>을 발견하면 서블릿 컨테이너의 필터 체인에도
 * 자동으로 등록한다. 그러면 이 필터가 Security 체인(우리가 의도한 위치)과
 * 컨테이너 체인(Security 체인 <b>바깥</b>) 두 곳에 걸리게 된다.
 * 바깥에서 실행되는 쪽은 {@code SecurityContextHolderFilter} 가 컨텍스트를 정리한 뒤라
 * 인증을 넣어봐야 인가 판단에 반영되지 않는다.
 * {@code OncePerRequestFilter} 덕분에 실제로 두 번 돌지는 않지만, "어느 쪽이 먼저 도느냐"에
 * 동작이 의존하는 구조는 위험하다. 그래서 빈으로 만들지 않고
 * {@code SecurityConfig} 에서 {@code new} 로 만들어 <b>Security 체인에만</b> 등록한다.
 * (다른 방법으로 {@code FilterRegistrationBean.setEnabled(false)} 도 있지만,
 *  "자동 등록을 켜놓고 다시 끄는" 것보다 아예 빈으로 만들지 않는 쪽이 단순하다.)
 */
@Slf4j
@RequiredArgsConstructor
public class JwtAuthenticationFilter extends OncePerRequestFilter {

    /*
     * ⚠️ 이 필터는 토큰의 '서명이 유효한가'만 본다. sub 에 담긴 사용자가 DB 에 실재하는지는 확인하지 않는다.
     *
     * 그래서 탈퇴했거나 삭제된 사용자의 토큰도 만료(기본 24h)까지는 인증을 통과한다.
     * 이건 버그가 아니라 무상태(stateless) JWT 를 택한 대가다 — 매 요청마다 사용자를 조회하면
     * "토큰만으로 검증된다"는 JWT 의 이점이 사라지고 DB 왕복이 요청 수만큼 늘어난다.
     *
     * 실질적 안전장치는 뒤쪽에 있다. 봇·문서 조회는 어차피 userId 로 소유권을 확인하므로,
     * 없는 사용자의 토큰으로는 어떤 데이터에도 닿지 못한다(빈 결과 또는 403).
     *
     * TODO(배포 준비 단계): 즉시 무효화가 필요해지면 — 예를 들어 탈퇴·비밀번호 변경 시 —
     *   ① 토큰 TTL 을 짧게 줄이고 리프레시 토큰을 도입하거나
     *   ② 무효화된 토큰 목록(deny list)을 Redis 에 두는 방식을 검토할 것.
     *   지금 단계에서 하지 않는 이유는 운영할 것(Redis)이 하나 더 늘기 때문이다.
     */


    private static final String AUTHORIZATION_HEADER = "Authorization";
    private static final String BEARER_PREFIX = "Bearer ";

    private final JwtService jwtService;

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain filterChain) throws ServletException, IOException {
        String token = resolveToken(request);

        // ① 토큰이 없으면 아무것도 하지 않고 통과시킨다.
        //    여기서 401 을 던지면 공개 경로(/api/auth/**, /api/w/**, /actuator/health)까지 막힌다.
        //    "인증했는가"와 "인증이 필요한가"는 다른 질문이다.
        //    필터는 앞의 질문에만 답하고, 뒤의 판단은 SecurityConfig 의 인가 규칙에 맡긴다.
        if (token == null) {
            filterChain.doFilter(request, response);
            return;
        }

        try {
            Long userId = jwtService.parseUserId(token);
            authenticate(request, userId);

        } catch (ApiException e) {
            // ② 토큰이 있는데 유효하지 않은 경우 — 여기서 응답을 직접 쓰지 않고,
            //    "실패했다"는 사실만 요청에 기록한 뒤 계속 흘려보낸다. 이유 두 가지.
            //
            //    (a) 필터에서 던진 예외는 @RestControllerAdvice(GlobalExceptionHandler)가 못 잡는다.
            //        DispatcherServlet 에 도달하기 전이기 때문이다. 그래서 "던지기"는 선택지가 아니다.
            //    (b) 그렇다고 여기서 바로 401 을 써버리면, 만료된 토큰을 달고 온 요청이
            //        공개 경로(/api/w/{publicKey}/chat)까지 거절된다.
            //        위젯은 애초에 인증이 필요 없는데, 브라우저에 남아 있던 낡은 토큰 하나 때문에
            //        고객 사이트의 챗봇이 죽는 셈이다.
            //
            //    그래서 기록만 남기고 통과시킨다. 공개 경로면 익명으로 정상 처리되고,
            //    보호 경로면 인가 단계에서 막혀 ApiAuthenticationEntryPoint 가 이 기록을 읽어
            //    AUTHENTICATION_REQUIRED 대신 INVALID_TOKEN 으로 응답한다.
            //    → 응답을 쓰는 지점은 한 곳으로 유지하면서 실패 사유는 잃지 않는다.
            SecurityContextHolder.clearContext();
            ErrorResponseWriter.record(request, e.getErrorCode());
        }

        filterChain.doFilter(request, response);
    }

    /**
     * SecurityContext 에 인증 객체를 넣는다.
     *
     * <p><b>principal 에 {@code Long}(사용자 id)를 넣는 이유.</b>
     * 뒤에 올 봇 소유권 검사가 필요로 하는 값이 정확히 이것 하나다
     * ({@code botService.findMyBot(userId, botId)}).
     * 컨트롤러에서 {@code @AuthenticationPrincipal Long userId} 로 바로 꺼내 쓸 수 있어
     * 중간 타입을 하나 더 만들 이유가 없다.
     *
     * <p>흔한 대안인 {@code UserDetails} 구현체를 쓰지 않은 이유:
     * {@code UserDetails} 는 비밀번호·권한 목록을 담는 계약인데
     * 우리는 요청마다 DB 를 조회하지 않으므로 채울 값이 없고(JWT 에는 id 뿐이다),
     * 빈 껍데기를 만들어 넣으면 "여기 사용자 정보가 있다"는 잘못된 인상을 준다.
     *
     * <p>권한 목록을 비워두는 것도 의도다. 이 서비스에는 역할 구분이 없고
     * ({@code users} 테이블에 role 컬럼이 없다) 인가는 전부 "내 것인가"로 판단한다.
     *
     * <p>TODO(W2 이후): 역할이나 이메일이 인가 판단에 필요해지면
     *   {@code record AuthPrincipal(Long userId, ...)} 로 승격할 것.
     *   그때 컨트롤러 시그니처가 함께 바뀐다.
     */
    private void authenticate(HttpServletRequest request, Long userId) {
        UsernamePasswordAuthenticationToken authentication = UsernamePasswordAuthenticationToken.authenticated(
                userId,       // principal
                null,         // credentials — 검증이 끝난 토큰을 메모리에 계속 들고 있을 이유가 없다
                List.of()     // authorities — 역할 없음
        );
        // 클라이언트 IP 등 부가 정보. 나중에 로그인 이상 탐지·감사 로그에 쓰인다.
        authentication.setDetails(new WebAuthenticationDetailsSource().buildDetails(request));

        // 기존 컨텍스트를 그대로 수정하지 않고 빈 컨텍스트를 새로 만들어 넣는다(Spring Security 6+ 권장).
        // 스레드에 남아 있던 이전 요청의 인증 정보를 물려받는 사고를 구조적으로 막는다.
        SecurityContext context = SecurityContextHolder.createEmptyContext();
        context.setAuthentication(authentication);
        SecurityContextHolder.setContext(context);

        log.debug("[인증성공] userId={} {} {}", userId, request.getMethod(), request.getRequestURI());
    }

    /** {@code Authorization: Bearer xxx} 에서 토큰만 잘라낸다. 없거나 형식이 다르면 null. */
    private String resolveToken(HttpServletRequest request) {
        String header = request.getHeader(AUTHORIZATION_HEADER);
        if (header == null || !header.startsWith(BEARER_PREFIX)) {
            return null;
        }
        String token = header.substring(BEARER_PREFIX.length()).trim();
        // "Bearer " 만 보내는 경우를 토큰 없음과 같이 취급한다.
        // 빈 문자열을 파서에 넘기면 예외가 나고, 그건 "잘못된 토큰"이 아니라 "토큰 없음"에 가깝다.
        return token.isEmpty() ? null : token;
    }
}
