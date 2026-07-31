package com.alldap.api.global.exception;

import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.multipart.MaxUploadSizeExceededException;

import java.util.stream.Collectors;

/**
 * 전역 예외 처리기. 어떤 예외가 나든 PRD §10.3 공통 포맷으로 응답을 통일한다.
 *
 * <p>이게 없으면 Spring 기본 에러 응답({@code timestamp/status/error/path})이 나가서
 * 프론트의 {@code ApiErrorBody} 파싱이 깨진다.
 */
@Slf4j
@RestControllerAdvice
public class GlobalExceptionHandler {

    /** 우리가 의도적으로 던진 예외. 예상된 흐름이므로 스택트레이스까지 남기지 않는다. */
    @ExceptionHandler(ApiException.class)
    public ResponseEntity<ErrorResponse> handleApiException(ApiException e) {
        ErrorCode errorCode = e.getErrorCode();
        log.warn("[ApiException] code={} message={}", errorCode.getCode(), e.getMessage());
        return ResponseEntity
                .status(errorCode.getStatus())
                .body(ErrorResponse.of(errorCode, e.responseMessage()));
    }

    /**
     * {@code @Valid} 검증 실패.
     *
     * <p>필드별 메시지를 합쳐서 내려준다. "무엇을 어떻게 고치면 되는지"를 알려주려면
     * 어느 필드가 왜 틀렸는지가 필요하기 때문이다.
     * 그래서 각 DTO 의 검증 애너테이션 message 속성도 한국어로 적어야 한다.
     */
    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ErrorResponse> handleValidationException(MethodArgumentNotValidException e) {
        String detail = e.getBindingResult().getFieldErrors().stream()
                .map(fieldError -> fieldError.getField() + ": " + fieldError.getDefaultMessage())
                .collect(Collectors.joining(", "));

        log.warn("[ValidationException] {}", detail);
        return ResponseEntity
                .status(ErrorCode.INVALID_INPUT.getStatus())
                .body(ErrorResponse.of(ErrorCode.INVALID_INPUT, detail));
    }

    /**
     * multipart 최대 크기 초과.
     *
     * <p>Spring 의 multipart 제한(application.yaml)에 걸리면 요청이 Python 까지 가지도 못한다.
     * 이 경우 기본 500 이 나가므로 413 + 한국어 안내로 바꿔준다.
     */
    @ExceptionHandler(MaxUploadSizeExceededException.class)
    public ResponseEntity<ErrorResponse> handleMaxUploadSize(MaxUploadSizeExceededException e) {
        log.warn("[MaxUploadSizeExceeded] {}", e.getMessage());
        return ResponseEntity
                .status(ErrorCode.FILE_TOO_LARGE.getStatus())
                .body(ErrorResponse.of(ErrorCode.FILE_TOO_LARGE));
    }

    /**
     * 그 외 전부. 예상하지 못한 오류이므로 스택트레이스를 남긴다.
     *
     * <p>내부 예외 메시지를 그대로 내려보내지 않는 이유: 테이블명·SQL·라이브러리 이름 같은
     * 내부 구조가 새어나가면 공격에 힌트가 되고, 사용자에게도 아무 도움이 안 된다.
     */
    @ExceptionHandler(Exception.class)
    public ResponseEntity<ErrorResponse> handleException(Exception e) {
        log.error("[UnhandledException]", e);
        return ResponseEntity
                .status(ErrorCode.INTERNAL_ERROR.getStatus())
                .body(ErrorResponse.of(ErrorCode.INTERNAL_ERROR));
    }

    // TODO(W2): 아래 예외들도 개별 핸들러로 분리할 것.
    //   - ConstraintViolationException (@RequestParam/@PathVariable 검증)
    //   - HttpMessageNotReadableException (JSON 파싱 실패 → "요청 형식이 올바르지 않습니다")
    //   - MethodArgumentTypeMismatchException (UUID 자리에 문자열이 온 경우)
    //   지금은 전부 마지막 handleException 으로 떨어져 500 이 나간다. 실제로는 400 이 맞다.
}
