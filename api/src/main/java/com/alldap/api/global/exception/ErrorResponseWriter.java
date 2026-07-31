package com.alldap.api.global.exception;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import tools.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.nio.charset.StandardCharsets;

/**
 * 서블릿 응답에 PRD §10.3 공통 에러 포맷을 직접 써 넣는 도우미.
 *
 * <p><b>왜 필요한가.</b> {@code GlobalExceptionHandler}({@code @RestControllerAdvice})는
 * <b>컨트롤러까지 도달한 요청</b>의 예외만 처리한다.
 * 필터 체인(Spring Security)에서 끝나버리는 요청 — 토큰이 없거나 권한이 없어 막히는 경우 —
 * 은 컨트롤러에 도달하지 못하므로 advice 가 잡을 수 없고, Spring Security 의 기본 응답이 나간다.
 * 그 기본 응답은 우리 포맷이 아니라 프론트({@code web/lib/types.ts} 의 {@code ApiErrorBody})가 깨진다.
 * 그래서 필터 계층 전용으로 응답을 직접 써 주는 지점이 하나 필요하다.
 *
 * <p>이 클래스가 {@code global/exception} 에 있는 이유:
 * "어떤 경로로 실패하든 응답 모양은 하나"라는 규칙을 지키는 코드는 모두 이 패키지에 모은다.
 * {@code GlobalExceptionHandler}(컨트롤러 계층)와 이 클래스(필터 계층)가 같은 목적의 한 쌍이다.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class ErrorResponseWriter {

    /**
     * 필터가 "이 요청은 이 코드로 실패했다"고 남겨두는 요청 속성 키.
     *
     * <p>필터에서 던진 예외는 {@code @RestControllerAdvice} 가 잡지 못하므로,
     * 필터는 예외를 던지는 대신 여기에 {@link ErrorCode} 를 기록만 하고 요청을 계속 흘려보낸다.
     * 그 뒤 인가 단계에서 실제로 막히면 {@code ApiAuthenticationEntryPoint} 가 이 값을 읽어
     * 더 정확한 코드로 응답한다. (자세한 근거는 {@code JwtAuthenticationFilter} 주석 참고)
     */
    public static final String ERROR_CODE_ATTRIBUTE = "com.alldap.api.ERROR_CODE";

    /**
     * 한글이 깨지지 않도록 charset 을 명시한다.
     * charset 을 빼면 컨테이너 기본 인코딩(환경에 따라 ISO-8859-1)이 적용돼
     * "로그인이 필요합니다"가 브라우저에서 깨져 보인다.
     */
    private static final String CONTENT_TYPE_JSON_UTF8 = "application/json;charset=UTF-8";

    /**
     * Spring Boot 4 가 자동 구성하는 Jackson 3 매퍼({@code tools.jackson.databind.json.JsonMapper})가 주입된다.
     *
     * <p>⚠️ Boot 3 까지 쓰던 {@code com.fasterxml.jackson.databind.ObjectMapper} 가 아니다.
     * Jackson 3 에서 databind 패키지가 {@code tools.jackson.databind} 로 옮겨졌다.
     * (애너테이션 {@code @JsonProperty} 만은 여전히 {@code com.fasterxml.jackson.annotation} 이다 —
     * {@code global/client/dto} 의 기존 import 가 그대로 유효한 이유가 이것이다.)
     */
    private final ObjectMapper objectMapper;

    /**
     * 필터가 실패 코드를 기록한다. 응답을 여기서 쓰지 않는 이유는
     * {@code JwtAuthenticationFilter} 주석에 적어두었다.
     */
    public static void record(HttpServletRequest request, ErrorCode errorCode) {
        request.setAttribute(ERROR_CODE_ATTRIBUTE, errorCode);
    }

    /**
     * 필터가 기록해둔 코드가 있으면 그걸로, 없으면 {@code fallback} 으로 응답한다.
     *
     * @param fallback 기록이 없을 때 쓸 기본 코드 (예: 토큰을 아예 안 보낸 경우 AUTHENTICATION_REQUIRED)
     */
    public void writeRecordedOr(HttpServletRequest request, HttpServletResponse response, ErrorCode fallback)
            throws IOException {
        Object recorded = request.getAttribute(ERROR_CODE_ATTRIBUTE);
        write(response, recorded instanceof ErrorCode errorCode ? errorCode : fallback);
    }

    /** 지정한 코드로 공통 포맷 응답을 쓴다. */
    public void write(HttpServletResponse response, ErrorCode errorCode) throws IOException {
        if (response.isCommitted()) {
            // 이미 헤더/본문이 나가버린 뒤에는 손댈 수 없다. 조용히 실패하지 말고 로그로 남긴다.
            log.warn("[ErrorResponseWriter] 응답이 이미 커밋되어 에러 본문을 쓸 수 없다. code={}", errorCode.getCode());
            return;
        }

        response.setStatus(errorCode.getStatus().value());
        // setCharacterEncoding 은 반드시 getWriter() 보다 먼저 호출해야 반영된다.
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        response.setContentType(CONTENT_TYPE_JSON_UTF8);

        objectMapper.writeValue(response.getWriter(), ErrorResponse.of(errorCode));
    }
}
