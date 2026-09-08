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

    // ── 요청 자체가 잘못된 경우 (본문·헤더·메서드) ─────────────────────────
    // 아래 둘은 "클라이언트가 API 를 잘못 호출했다"는 뜻이다. 서버 잘못이 아니므로 5xx 로 답하면 안 된다.
    // 500 으로 답하면 프론트가 "서버 장애니까 재시도하자"는 잘못된 로직을 짜게 되고,
    // 서버 로그에도 가짜 ERROR 가 쌓여 진짜 장애가 묻힌다.
    METHOD_NOT_ALLOWED(HttpStatus.METHOD_NOT_ALLOWED, "METHOD_NOT_ALLOWED",
            "이 주소에서는 지원하지 않는 요청 방식입니다. 응답의 Allow 헤더에 적힌 방식(GET·POST 등)으로 다시 요청해주세요."),
    UNSUPPORTED_MEDIA_TYPE(HttpStatus.UNSUPPORTED_MEDIA_TYPE, "UNSUPPORTED_MEDIA_TYPE",
            "요청 본문 형식을 처리할 수 없습니다. Content-Type 헤더를 application/json 으로 지정하고 JSON 본문을 보내주세요."),

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
            // ⚠️ 화면 이름을 바꾸면 이 문구도 같이 고쳐야 한다. 2026-08-05 에 허용 도메인이
            //    <설정> 에서 <내보내기> 로 옮겨가면서 이 안내가 없는 곳을 가리키고 있었다.
            "이 도메인에서는 위젯을 사용할 수 없습니다. 봇의 [내보내기] 화면에서 '설치할 주소'에 현재 주소를 추가해주세요."),
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

    // 평가를 아직 돌릴 수 없는 상태. <사용자가 고칠 수 있는> 문제이므로 4xx 다.
    // 기본 문구는 거의 쓰이지 않는다 — Python 이 상황별로 더 구체적인 한국어를 주고
    // AiServiceClient 의 eval 매퍼가 그 문구를 그대로 실어 보내기 때문이다.
    // ("처리가 끝난 문서가 없습니다…", "이미 모든 문서 조각으로 질문을 만들었습니다…" 등)
    EVAL_NOT_READY(HttpStatus.BAD_REQUEST, "EVAL_NOT_READY",
            "아직 평가를 실행할 수 없습니다. 문서와 테스트 질문을 먼저 준비해주세요."),

    // ── 결제 수단 (토스 빌링키) ───────────────────────────────────────────
    // 🔴 INVALID_INPUT 하나로 뭉치지 않는 이유: 프론트가 "카드를 바꿔 다시 시도하세요" 와
    //    "우리 쪽 문제라 잠시 후 다시 시도하세요" 를 <다르게> 안내해야 하기 때문이다.
    //    뭉치면 사용자가 카드를 몇 번이나 다시 넣어보게 만든다.
    //
    // ⚠️ BILLING_AUTH_FAILED 의 기본 문구는 실제로는 거의 쓰이지 않는다 —
    //    토스가 상황별로 더 구체적인 한국어를 주고(예: "카드 유효기간이 올바르지 않습니다.")
    //    TossClient 가 그 문구를 그대로 실어 보낸다. 여기 문구는 파싱에 실패했을 때의 보루다.
    BILLING_AUTH_FAILED(HttpStatus.BAD_REQUEST, "BILLING_AUTH_FAILED",
            "카드 등록에 실패했습니다. 카드 정보를 확인한 뒤 다시 시도하거나 다른 카드로 등록해주세요."),
    BILLING_PROVIDER_UNAVAILABLE(HttpStatus.SERVICE_UNAVAILABLE, "BILLING_PROVIDER_UNAVAILABLE",
            "결제 서비스에 일시적으로 연결할 수 없습니다. 잠시 후 다시 시도해주세요."),
    // V7(2026-09-08) 부터 카드는 여러 장이다. 옛 BILLING_METHOD_ALREADY_EXISTS("카드를 바꾸려면 삭제 후 재등록")
    // 는 이제 거짓 안내라 이름·문구를 바꿨다. 이 코드가 나오는 경우는 <동시 첫 등록 둘> 뿐이다 —
    // 부분 유니크 인덱스(기본 카드 1장)가 둘째를 거부한 것이고, 다시 시도하면 된다.
    BILLING_METHOD_CONFLICT(HttpStatus.CONFLICT, "BILLING_METHOD_CONFLICT",
            "카드 등록 요청이 겹쳐 하나만 저장했습니다. 화면을 새로고침해 등록된 카드를 확인한 뒤, 필요하면 다시 등록해주세요."),
    BILLING_METHOD_LIMIT_EXCEEDED(HttpStatus.CONFLICT, "BILLING_METHOD_LIMIT_EXCEEDED",
            "카드는 최대 5장까지 등록할 수 있습니다. 쓰지 않는 카드를 삭제한 뒤 등록해주세요."),
    BILLING_DEFAULT_METHOD_IN_USE(HttpStatus.CONFLICT, "BILLING_DEFAULT_METHOD_IN_USE",
            "기본 카드는 삭제할 수 없습니다. 다른 카드를 기본으로 지정한 뒤 삭제해주세요."),

    // 🔴 아래 둘은 <같은 불변식>("유료 요금제에는 카드가 있어야 한다")을 양쪽 방향에서 막는다.
    //    한쪽만 두면 규칙이 없는 것과 같다 — 유료로 바꾼 뒤 카드를 지우면 그만이기 때문이다.
    //    (PlanService javadoc 참고)
    PLAN_REQUIRES_BILLING_METHOD(HttpStatus.CONFLICT, "PLAN_REQUIRES_BILLING_METHOD",
            "유료 요금제로 바꾸려면 결제 카드가 먼저 필요합니다. 마이페이지에서 카드를 등록한 뒤 다시 선택해주세요."),
    BILLING_METHOD_REQUIRED_BY_PLAN(HttpStatus.CONFLICT, "BILLING_METHOD_REQUIRED_BY_PLAN",
            "유료 요금제를 쓰는 동안에는 마지막 카드를 삭제할 수 없습니다. 다른 카드를 먼저 등록하거나, 요금제를 무료로 바꾼 뒤 삭제해주세요."),
    BILLING_METHOD_NOT_FOUND(HttpStatus.NOT_FOUND, "BILLING_METHOD_NOT_FOUND",
            "그 카드를 찾을 수 없습니다. 이미 삭제됐을 수 있으니 화면을 새로고침해 확인해주세요."),

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
