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
    // 🔴 문구가 "그 계정은" 이나 "비밀번호가" 라고 말하면 안 된다. 이 응답은 <가입되지 않은 이메일>로
    //    실패를 쌓아도 똑같이 나가기 때문이다. 한쪽에만 나가는 순간 로그인 폼이 가입 여부 조회 도구가 된다
    //    (INVALID_CREDENTIALS 가 이메일과 비밀번호를 구분하지 않는 것과 같은 이유).
    //    "15분" 은 AuthService.FAILURE_WINDOW 와 짝이다. 한쪽만 고치면 안내가 거짓이 된다.
    TOO_MANY_LOGIN_FAILURES(HttpStatus.TOO_MANY_REQUESTS, "TOO_MANY_LOGIN_FAILURES",
            "로그인에 여러 번 실패해 잠시 로그인을 제한했습니다. 15분 뒤에 다시 시도해주세요."),

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
    // 구버전 .hwp 도 이 코드로 나간다. 판정은 Python(parsers.py)이 하고, Spring 은 그 400 을
    // 그대로 이 코드로 옮긴다. 사용자에게 보이는 문구는 Python 이 보낸 것이다.
    // (예전에는 LEGACY_HWP_NOT_SUPPORTED 를 따로 뒀지만 아무 데서도 쓰이지 않아 2026-09-13 에 지웠다.
    //  .hwp 지원을 붙이게 되면 그때 판정 자리와 함께 다시 만들 것)
    UNSUPPORTED_FILE_TYPE(HttpStatus.BAD_REQUEST, "UNSUPPORTED_FILE_TYPE",
            "지원하지 않는 파일 형식입니다. pdf, docx, hwpx, txt, md 파일을 올려주세요."),
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

    /**
     * 🔴 <b>재시도로는 절대 안 풀리는 실패</b>라서 위 셋과 갈랐다 (2026-09-09).
     *
     * <p>Python 이 답변을 받긴 했는데 {@code max_tokens} 에 걸려 잘렸거나 비어 있는 경우다
     * ({@code generator.GenerationFailed}). 그전까지는 {@code AI_SERVICE_UNAVAILABLE} 로 뭉개져
     * "잠시 후 다시 시도해주세요" 가 나갔는데, <b>생성은 {@code temperature=0} 이라 다시 물어도
     * 같은 답이 같은 자리에서 잘린다.</b> 안내가 사실과 달랐다.
     *
     * <p><b>왜 4xx 인가.</b> 5xx 는 "우리가 고장났으니 이따 다시 오라"는 뜻이고, 프론트의 재시도
     * 로직과 운영 알림이 그 뜻을 그대로 믿는다. 여기서 결과를 바꿀 수 있는 유일한 행동은
     * <b>사용자가 질문을 좁히는 것</b>이라, 요청은 멀쩡히 받았지만 처리하지 못했다는 뜻의 422 를 쓴다.
     * (같은 이유로 {@code AiServiceClient} 는 이 실패를 서킷브레이커의 실패로도 세지 않는다.
     * Python 은 멀쩡히 응답했다)
     */
    ANSWER_INCOMPLETE(HttpStatus.UNPROCESSABLE_ENTITY, "ANSWER_INCOMPLETE",
            "답변이 길어져 끝까지 완성하지 못했습니다. 같은 질문을 다시 보내도 같은 결과이니, "
                    + "질문을 더 좁혀서(한 번에 한 가지만) 물어봐 주세요."),

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
            "유료 요금제를 쓰는 동안에는 마지막 카드를 삭제할 수 없습니다. 다른 카드를 먼저 등록하거나, 요금제 페이지에서 무료로 바꾼 뒤 삭제해주세요."),
    BILLING_METHOD_NOT_FOUND(HttpStatus.NOT_FOUND, "BILLING_METHOD_NOT_FOUND",
            "그 카드를 찾을 수 없습니다. 이미 삭제됐을 수 있으니 화면을 새로고침해 확인해주세요."),

    /**
     * 🔴 저장된 빌링키를 <b>복호화하지 못했다</b>. {@code INTERNAL_ERROR} 에서 갈라냈다 (2026-09-09).
     *
     * <p>원인은 셋 중 하나다: {@code BILLING_CRYPTO_KEY} 를 잃었거나, {@code billing_key_enc} 가
     * 손상됐거나, 누군가 값을 변조했다({@code BillingCrypto} 참고). 어느 쪽이든 <b>재시도로는
     * 절대 안 풀린다.</b> 그런데 {@code INTERNAL_ERROR} 는 "잠시 후 다시 시도해주세요" 라고 안내했다.
     * 2026-09-07 에 암호문 한 글자를 실제로 변조해 이 경로를 실측했고, 그때 나간 문구가 그것이다.
     *
     * <p><b>안내가 "삭제 후 재등록" 이 아닌 이유.</b> 삭제도 같은 자리에서 막힌다.
     * {@code BillingService.delete} 는 토스를 부르기 <b>전에</b> 복호화하고, 실패하면 토스를 아예
     * 부르지 않는다("모르면 지우지 않는다"). 그래서 이 카드는 사용도 삭제도 안 된다.
     * 사용자가 지금 할 수 있는 일은 <b>다른 카드를 등록해 기본으로 지정하는 것</b>뿐이고,
     * 남은 행 정리는 운영자의 일이다.
     *
     * <p><b>왜 그래도 500 인가.</b> 사용자 잘못이 아니고, 우리 데이터가 깨졌다는 사실 자체가
     * 즉시 알림이 필요한 사건이라 5xx 로 남는 것이 맞다. 대신 문구에서 "잠시 후 재시도" 를 지웠다.
     */
    BILLING_METHOD_UNREADABLE(HttpStatus.INTERNAL_SERVER_ERROR, "BILLING_METHOD_UNREADABLE",
            "이 카드의 결제 정보를 읽을 수 없어 사용할 수도, 삭제할 수도 없습니다. "
                    + "다시 시도해도 같은 결과이니, 다른 카드를 등록해 기본 카드로 지정한 뒤 문의해주세요."),

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
