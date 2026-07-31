package com.alldap.api.global.exception;

import lombok.Getter;
import org.springframework.http.HttpStatus;

/**
 * 애플리케이션 전역 에러 코드.
 *
 * <p>PRD §10.3 공통 규약에 따라 응답은 항상
 * {@code {"error":{"code":"...","message":"..."}}} 모양이다.
 *
 * <p><b>메시지 작성 규칙(CLAUDE.md 작업 규칙 4):</b>
 * "무엇이 잘못됐는지"에서 끝내지 말고 <b>"어떻게 하면 되는지"</b>까지 한국어로 적는다.
 * 사용자가 그대로 읽고 다음 행동을 알 수 있어야 한다.
 *
 * <p>코드 문자열을 enum 이름과 별도로 두지 않고 {@code name()} 을 그대로 쓰는 방법도 있지만,
 * enum 이름을 리팩터링하면 API 계약이 조용히 깨지므로 코드 문자열을 명시적으로 갖는다.
 */
@Getter
public enum ErrorCode {

    // ── 인증 · 권한 ──────────────────────────────────────────────────────
    AUTHENTICATION_REQUIRED(HttpStatus.UNAUTHORIZED, "AUTHENTICATION_REQUIRED",
            "로그인이 필요합니다. 다시 로그인한 뒤 시도해주세요."),
    INVALID_CREDENTIALS(HttpStatus.UNAUTHORIZED, "INVALID_CREDENTIALS",
            "이메일 또는 비밀번호가 올바르지 않습니다. 다시 확인해주세요."),
    INVALID_TOKEN(HttpStatus.UNAUTHORIZED, "INVALID_TOKEN",
            "인증 정보가 만료되었거나 올바르지 않습니다. 다시 로그인해주세요."),
    ACCESS_DENIED(HttpStatus.FORBIDDEN, "ACCESS_DENIED",
            "이 리소스에 접근할 권한이 없습니다. 본인 계정의 봇인지 확인해주세요."),
    EMAIL_ALREADY_EXISTS(HttpStatus.CONFLICT, "EMAIL_ALREADY_EXISTS",
            "이미 가입된 이메일입니다. 로그인하거나 다른 이메일로 가입해주세요."),

    // ── 리소스 없음 ──────────────────────────────────────────────────────
    RESOURCE_NOT_FOUND(HttpStatus.NOT_FOUND, "RESOURCE_NOT_FOUND",
            "요청한 데이터를 찾을 수 없습니다. 주소가 올바른지 확인해주세요."),
    BOT_NOT_FOUND(HttpStatus.NOT_FOUND, "BOT_NOT_FOUND",
            "봇을 찾을 수 없습니다. 삭제되었거나 주소가 잘못되었을 수 있습니다."),
    DOCUMENT_NOT_FOUND(HttpStatus.NOT_FOUND, "DOCUMENT_NOT_FOUND",
            "문서를 찾을 수 없습니다. 이미 삭제된 문서일 수 있습니다. 목록을 새로고침해주세요."),
    MESSAGE_NOT_FOUND(HttpStatus.NOT_FOUND, "MESSAGE_NOT_FOUND",
            "대화 메시지를 찾을 수 없습니다. 목록을 새로고침한 뒤 다시 시도해주세요."),

    // ── 입력 검증 ────────────────────────────────────────────────────────
    INVALID_INPUT(HttpStatus.BAD_REQUEST, "INVALID_INPUT",
            "입력값이 올바르지 않습니다. 표시된 항목을 확인한 뒤 다시 시도해주세요."),
    MESSAGE_LENGTH_EXCEEDED(HttpStatus.BAD_REQUEST, "MESSAGE_LENGTH_EXCEEDED",
            "질문은 2000자까지 보낼 수 있습니다. 질문을 나눠서 보내주세요."),

    // ── 파일 ────────────────────────────────────────────────────────────
    UNSUPPORTED_FILE_TYPE(HttpStatus.BAD_REQUEST, "UNSUPPORTED_FILE_TYPE",
            "지원하지 않는 파일 형식입니다. pdf, docx, hwpx, txt, md 파일을 올려주세요."),
    LEGACY_HWP_NOT_SUPPORTED(HttpStatus.BAD_REQUEST, "LEGACY_HWP_NOT_SUPPORTED",
            "구버전 .hwp 는 지원하지 않습니다. 한글에서 .hwpx 로 저장한 뒤 올려주세요."),
    // 413. Spring 7 에서 PAYLOAD_TOO_LARGE 는 deprecated 다 —
    // RFC 9110 이 이 상태 코드의 이름을 "Content Too Large" 로 바꿨기 때문. 숫자는 동일하다.
    FILE_TOO_LARGE(HttpStatus.CONTENT_TOO_LARGE, "FILE_TOO_LARGE",
            "파일이 너무 큽니다. 20MB 이하로 나눠서 올려주세요."),
    EMPTY_FILE(HttpStatus.BAD_REQUEST, "EMPTY_FILE",
            "빈 파일입니다. 내용이 있는 파일인지 확인한 뒤 다시 올려주세요."),

    // ── 위젯(공개 API) ───────────────────────────────────────────────────
    ORIGIN_NOT_ALLOWED(HttpStatus.FORBIDDEN, "ORIGIN_NOT_ALLOWED",
            "이 도메인에서는 위젯을 사용할 수 없습니다. 봇 설정의 허용 도메인에 현재 주소를 추가해주세요."),
    RATE_LIMIT_EXCEEDED(HttpStatus.TOO_MANY_REQUESTS, "RATE_LIMIT_EXCEEDED",
            "요청이 너무 많습니다. 잠시 후 다시 시도해주세요."),

    // ── AI 서비스 연동 ───────────────────────────────────────────────────
    // Python(:8001)이 죽거나 느릴 때. 사용자에게 "AI"라는 내부 구조를 굳이 설명하지 않고
    // "다시 시도"라는 행동만 알려준다.
    AI_SERVICE_UNAVAILABLE(HttpStatus.SERVICE_UNAVAILABLE, "AI_SERVICE_UNAVAILABLE",
            "답변 서비스에 일시적으로 연결할 수 없습니다. 잠시 후 다시 시도해주세요."),
    AI_SERVICE_TIMEOUT(HttpStatus.GATEWAY_TIMEOUT, "AI_SERVICE_TIMEOUT",
            "답변 생성이 예상보다 오래 걸립니다. 질문을 짧게 줄여서 다시 시도해주세요."),
    AI_SERVICE_ERROR(HttpStatus.BAD_GATEWAY, "AI_SERVICE_ERROR",
            "답변 처리 중 문제가 발생했습니다. 잠시 후 다시 시도해주세요."),

    // ── 그 외 ───────────────────────────────────────────────────────────
    INTERNAL_ERROR(HttpStatus.INTERNAL_SERVER_ERROR, "INTERNAL_ERROR",
            "일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요. 계속되면 문의해주세요."),
    NOT_IMPLEMENTED(HttpStatus.NOT_IMPLEMENTED, "NOT_IMPLEMENTED",
            "아직 준비 중인 기능입니다.");

    private final HttpStatus status;
    private final String code;
    private final String message;

    ErrorCode(HttpStatus status, String code, String message) {
        this.status = status;
        this.code = code;
        this.message = message;
    }
}
