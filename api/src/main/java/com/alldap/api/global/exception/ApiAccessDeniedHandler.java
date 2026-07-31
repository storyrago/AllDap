package com.alldap.api.global.exception;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.web.access.AccessDeniedHandler;
import org.springframework.stereotype.Component;

import java.io.IOException;

/**
 * <b>인증은 됐지만 권한이 없는</b> 요청에 403 을 공통 포맷으로 응답한다.
 *
 * <p>지금은 역할(role) 개념이 없어서 이 핸들러가 탈 일이 거의 없다.
 * 그래도 미리 붙여두는 이유는, 나중에 권한 규칙이 생겼을 때 응답 포맷만 조용히 어긋나는
 * 상황을 막기 위해서다. (Spring Security 기본 403 응답은 우리 포맷이 아니다)
 *
 * <p>참고: 봇 소유권 검사는 이 핸들러가 아니라 서비스 계층에서 404(BOT_NOT_FOUND)로 처리한다.
 * 403 으로 답하면 "그 봇은 존재하지만 네 것이 아니다"가 새어나가기 때문이다
 * ({@code BotService} 주석 참고).
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class ApiAccessDeniedHandler implements AccessDeniedHandler {

    private final ErrorResponseWriter errorResponseWriter;

    @Override
    public void handle(HttpServletRequest request,
                       HttpServletResponse response,
                       AccessDeniedException accessDeniedException) throws IOException {
        log.debug("[인가실패] {} {}", request.getMethod(), request.getRequestURI());
        errorResponseWriter.write(response, ErrorCode.ACCESS_DENIED);
    }
}
