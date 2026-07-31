package com.alldap.api.global.exception;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.core.AuthenticationException;
import org.springframework.security.web.AuthenticationEntryPoint;
import org.springframework.stereotype.Component;

import java.io.IOException;

/**
 * <b>인증되지 않은</b> 요청이 보호 경로에 닿았을 때 401 을 공통 포맷으로 응답한다.
 *
 * <p>Spring Security 는 실패를 두 갈래로 나눈다.
 * <ul>
 *   <li>누구인지 모르는 요청 → {@code AuthenticationEntryPoint} (여기, 401)</li>
 *   <li>누구인지는 알지만 권한이 없는 요청 → {@code AccessDeniedHandler} (403)</li>
 * </ul>
 * 이 구분을 지켜야 프론트가 "로그인 화면으로 보낼지" / "권한 없음 안내를 띄울지" 를 판단할 수 있다.
 *
 * <p>기본 코드는 {@link ErrorCode#AUTHENTICATION_REQUIRED}(토큰을 아예 안 보낸 경우)지만,
 * {@code JwtAuthenticationFilter} 가 "토큰은 왔는데 유효하지 않다"고 기록해둔 경우에는
 * {@link ErrorCode#INVALID_TOKEN} 이 대신 나간다.
 * 둘 다 401 이지만 코드가 달라야 프론트가 "저장된 토큰을 지우고 다시 로그인" 을 판단할 수 있다.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class ApiAuthenticationEntryPoint implements AuthenticationEntryPoint {

    private final ErrorResponseWriter errorResponseWriter;

    @Override
    public void commence(HttpServletRequest request,
                         HttpServletResponse response,
                         AuthenticationException authException) throws IOException {
        log.debug("[인증실패] {} {}", request.getMethod(), request.getRequestURI());
        errorResponseWriter.writeRecordedOr(request, response, ErrorCode.AUTHENTICATION_REQUIRED);
    }
}
