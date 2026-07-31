package com.alldap.api.global.exception;

/**
 * PRD §10.3 공통 에러 응답. 직렬화하면 정확히 아래 모양이 되어야 한다.
 *
 * <pre>
 * {
 *   "error": {
 *     "code": "BOT_NOT_FOUND",
 *     "message": "봇을 찾을 수 없습니다. 삭제되었거나 주소가 잘못되었을 수 있습니다."
 *   }
 * }
 * </pre>
 *
 * <p><b>중첩 구조가 핵심이다.</b> {@code {"code":..., "message":...}} 처럼 평평하게 만들면
 * 프론트({@code web/lib/types.ts} 의 {@code ApiErrorBody})·Python·위젯이 모두 어긋난다.
 * 그래서 바깥 record 는 {@code error} 필드 하나만 갖고, 내용은 중첩 record 에 담는다.
 *
 * @param error 에러 본문
 */
public record ErrorResponse(Error error) {

    /**
     * @param code    기계가 분기할 식별자 (영문 대문자 스네이크)
     * @param message 사용자에게 그대로 보여줄 한국어 문장
     */
    public record Error(String code, String message) {
    }

    public static ErrorResponse of(ErrorCode errorCode) {
        return new ErrorResponse(new Error(errorCode.getCode(), errorCode.getMessage()));
    }

    public static ErrorResponse of(ErrorCode errorCode, String message) {
        return new ErrorResponse(new Error(errorCode.getCode(), message));
    }
}
