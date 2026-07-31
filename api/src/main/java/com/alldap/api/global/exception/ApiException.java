package com.alldap.api.global.exception;

import lombok.Getter;

/**
 * 애플리케이션이 의도적으로 던지는 예외. {@link ErrorCode} 하나를 감싼다.
 *
 * <p>{@code RuntimeException}(unchecked)을 상속한 이유:
 * checked 예외로 두면 서비스·컨트롤러 시그니처마다 {@code throws} 가 번지고,
 * {@code @Transactional} 의 기본 롤백 규칙도 unchecked 예외 기준이라
 * checked 예외는 롤백되지 않는 함정이 있다.
 *
 * <p>{@link #detailMessage} 는 기본 메시지 대신 상황별로 더 구체적인 안내를 주고 싶을 때 쓴다.
 * (예: 파일 형식 오류에 실제 확장자를 포함시키기)
 */
@Getter
public class ApiException extends RuntimeException {

    private final ErrorCode errorCode;

    /** null 이면 {@link ErrorCode} 의 기본 메시지를 쓴다. */
    private final String detailMessage;

    public ApiException(ErrorCode errorCode) {
        this(errorCode, null);
    }

    public ApiException(ErrorCode errorCode, String detailMessage) {
        // 로그·스택트레이스에 찍힐 메시지. 사용자에게 나가는 문구는 responseMessage() 가 결정한다.
        super(detailMessage != null ? detailMessage : errorCode.getMessage());
        this.errorCode = errorCode;
        this.detailMessage = detailMessage;
    }

    /** 실제로 사용자에게 내려줄 한국어 문구. */
    public String responseMessage() {
        return detailMessage != null ? detailMessage : errorCode.getMessage();
    }
}
