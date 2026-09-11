package com.alldap.api.global.exception;

import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.HttpMediaTypeNotSupportedException;
import org.springframework.web.HttpRequestMethodNotSupportedException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.multipart.MaxUploadSizeExceededException;
import org.springframework.web.multipart.support.MissingServletRequestPartException;
import org.springframework.web.servlet.resource.NoResourceFoundException;

import java.util.Set;
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
     * 요청 본문(JSON)을 읽지 못한 경우. 예: {@code {"email":} 처럼 잘린 JSON, 본문 자체가 없는 POST.
     *
     * <p>이 예외를 따로 잡지 않으면 마지막 {@link #handleException} 으로 떨어져 <b>500</b> 이 나간다.
     * 그런데 "JSON 을 잘못 보냈다"는 명백한 <b>클라이언트 잘못</b>이라 400 이 맞다.
     *
     * <p>{@code e.getMessage()} 를 사용자에게 그대로 내려보내지 않는 이유:
     * Jackson 의 원본 메시지에는 파서 클래스명·DTO 클래스명·본문 조각이 섞여 나온다.
     * 내부 구조를 노출하는 데다 한국어도 아니라 사용자에게 도움이 되지 않는다.
     * 대신 로그에는 남겨 개발자가 원인을 볼 수 있게 한다(스택트레이스는 불필요하므로 메시지만).
     */
    @ExceptionHandler(HttpMessageNotReadableException.class)
    public ResponseEntity<ErrorResponse> handleNotReadable(HttpMessageNotReadableException e) {
        log.warn("[MalformedRequestBody] {}", e.getMessage());
        return ResponseEntity
                .status(ErrorCode.INVALID_INPUT.getStatus())
                .body(ErrorResponse.of(ErrorCode.INVALID_INPUT,
                        "요청 본문(JSON)을 읽을 수 없습니다. 따옴표·괄호가 빠지지 않았는지 확인한 뒤 올바른 JSON 형식으로 다시 보내주세요."));
    }

    /**
     * Content-Type 이 없거나 우리가 처리할 수 없는 형식인 경우 → 415.
     *
     * <p>{@code curl -d 'email=a'} 처럼 Content-Type 을 지정하지 않으면
     * {@code application/x-www-form-urlencoded} 로 전송되는데, 우리 API 는 JSON 만 받는다.
     *
     * <p>응답에 {@code Accept} 헤더로 지원 형식을 알려주는 방법도 있지만(스프링 기본 핸들러가 그렇게 한다)
     * 이 API 는 <b>모든 엔드포인트가 JSON 하나뿐</b>이라 헤더로 협상할 여지가 없다.
     * 그래서 헤더 대신 에러 메시지에 "application/json 으로 보내라"를 직접 적는 쪽을 택했다.
     */
    @ExceptionHandler(HttpMediaTypeNotSupportedException.class)
    public ResponseEntity<ErrorResponse> handleMediaTypeNotSupported(HttpMediaTypeNotSupportedException e) {
        log.warn("[UnsupportedMediaType] contentType={}", e.getContentType());
        return ResponseEntity
                .status(ErrorCode.UNSUPPORTED_MEDIA_TYPE.getStatus())
                .body(ErrorResponse.of(ErrorCode.UNSUPPORTED_MEDIA_TYPE));
    }

    /**
     * 주소는 맞는데 HTTP 메서드가 틀린 경우 → 405. 예: {@code GET /api/auth/login} (POST 전용).
     *
     * <p>{@code Allow} 헤더를 함께 내려준다. RFC 9110 이 405 응답에 이 헤더를 요구하고,
     * 무엇보다 프론트 개발자가 "그럼 뭘로 불러야 하지"를 응답만 보고 알 수 있다.
     */
    @ExceptionHandler(HttpRequestMethodNotSupportedException.class)
    public ResponseEntity<ErrorResponse> handleMethodNotSupported(HttpRequestMethodNotSupportedException e) {
        log.warn("[MethodNotAllowed] method={} supported={}", e.getMethod(), e.getSupportedHttpMethods());

        HttpHeaders headers = new HttpHeaders();
        Set<HttpMethod> supported = e.getSupportedHttpMethods();
        if (supported != null && !supported.isEmpty()) {
            headers.setAllow(supported);
        }

        return ResponseEntity
                .status(ErrorCode.METHOD_NOT_ALLOWED.getStatus())
                .headers(headers)
                .body(ErrorResponse.of(ErrorCode.METHOD_NOT_ALLOWED));
    }

    /**
     * multipart 요청에 {@code file} 파트가 없는 경우 → 400.
     *
     * <p><b>이 핸들러가 없으면 500 이 나간다.</b> {@code @RequestPart("file")} 바인딩이 실패하면
     * {@link MissingServletRequestPartException} 이 던져지는데, 스프링 기본 처리기가 400 으로 바꿔주기 <b>전에</b>
     * 이 클래스의 마지막 그물 {@link #handleException} 이 먼저 잡아버린다.
     *
     * <p>그러면 이 저장소가 스스로 금지한 상태가 된다 — {@link ErrorCode} 의 METHOD_NOT_ALLOWED 주석에
     * "클라이언트 잘못을 5xx 로 답하면 프론트가 재시도 로직을 잘못 짜고, 로그에 가짜 ERROR 가 쌓여
     * 진짜 장애가 묻힌다"고 적어놓고 업로드 엔드포인트가 정확히 그 상태였다.
     *
     * <p>메시지에 필드명을 박아준다. "파일이 없다"만으로는 필드명을 오타냈다는 걸 알 수 없다.
     */
    @ExceptionHandler(MissingServletRequestPartException.class)
    public ResponseEntity<ErrorResponse> handleMissingPart(MissingServletRequestPartException e) {
        log.warn("[MissingRequestPart] partName={}", e.getRequestPartName());
        return ResponseEntity
                .status(ErrorCode.INVALID_INPUT.getStatus())
                .body(ErrorResponse.of(ErrorCode.INVALID_INPUT,
                        "업로드할 파일을 찾을 수 없습니다. multipart 요청에서 파일 필드 이름을 'file' 로 지정해 다시 보내주세요."));
    }

    /**
     * 경로 변수·쿼리 파라미터의 타입이 맞지 않는 경우 → 400.
     * 예: {@code GET /api/bots/hello/documents} (UUID 자리에 문자열).
     *
     * <p>이것도 없으면 500 + ERROR 스택트레이스가 남는다. 주소를 잘못 친 것은 클라이언트 잘못이고,
     * 무엇보다 <b>로그를 오염시킬 수 있다</b> — 아무 문자열이나 URL 에 넣어 호출하는 것만으로
     * 서버 로그에 ERROR 스택트레이스를 무제한으로 쌓을 수 있게 된다.
     *
     * <p>기대 타입을 응답에 적지 않는 이유: 내부 클래스명({@code java.util.UUID})이 그대로 노출된다.
     * 사용자에게는 "주소가 올바른지 확인하라"로 충분하고, 정확한 원인은 로그에 남긴다.
     */
    @ExceptionHandler(MethodArgumentTypeMismatchException.class)
    public ResponseEntity<ErrorResponse> handleTypeMismatch(MethodArgumentTypeMismatchException e) {
        log.warn("[TypeMismatch] name={} value={} requiredType={}",
                e.getName(), e.getValue(), e.getRequiredType());
        return ResponseEntity
                .status(ErrorCode.INVALID_INPUT.getStatus())
                .body(ErrorResponse.of(ErrorCode.INVALID_INPUT,
                        "주소에 잘못된 값이 들어 있습니다. 목록에서 다시 선택하거나 주소가 올바른지 확인해주세요."));
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
     *
     * <p><b>로그 수준을 나누는 기준.</b> 여기만 {@code log.error} + 스택트레이스다.
     * 위의 핸들러들(검증 실패·잘못된 JSON·잘못된 메서드)은 전부 <b>클라이언트 잘못</b>이라
     * {@code log.warn} + 메시지 한 줄로 끝낸다. 클라이언트 실수까지 ERROR 로 남기면
     * 알림이 울려야 할 진짜 서버 장애가 소음에 묻힌다.
     */
    /**
     * 아직 구현하지 않은 엔드포인트 → 501 Not Implemented.
     *
     * <p><b>왜 필요한가.</b> 이 저장소에서 {@code UnsupportedOperationException} 을 던지는 자리는
     * 지금 <b>둘뿐이고, 둘 다 컨트롤러가 아니다</b>:
     * {@code AiServiceClient.isHealthy}(W2 에 구현 예정)와
     * {@code AiServiceClient.listDocuments}(호출자가 없어 <b>의도적으로 영구 미구현</b>).
     * 처음에는 컨트롤러 뼈대들이 이걸 던졌다. 그대로 두면 마지막 {@code handleException} 으로
     * 떨어져 <b>500 INTERNAL_ERROR</b> 가 나가는데,
     * 이건 두 가지로 해롭다.
     * <ol>
     *   <li><b>거짓말이다.</b> 서버가 고장난 게 아니라 아직 안 만든 것이다.
     *       500 은 "우리 잘못이니 잠시 후 재시도"라는 뜻이라 클라이언트가 재시도 로직을 잘못 짠다.</li>
     *   <li><b>검증을 방해한다.</b> 실제로 인증 슬라이스를 검증할 때
     *       "유효한 토큰으로 보호 경로 접근"이 성공했는지를 응답만으로 구분할 수 없어
     *       서버 로그를 봐야 했다. 501 이면 "인증은 통과했고 기능이 없을 뿐"이 응답에 드러난다.</li>
     * </ol>
     *
     * <p><b>이 핸들러를 지울 트리거는 없다.</b> 예전 주석은 "마지막
     * {@code UnsupportedOperationException} 이 사라지면 이 핸들러도 함께 지울 것" 이라고 적어뒀지만,
     * 남은 둘 중 {@code listDocuments} 는 의도적으로 영원히 미구현이라 그 조건이 발동하지 않는다.
     * 지울지 말지는 그때 따로 판단해야 한다. 남겨두는 대가는 그대로다:
     * 진짜 버그가 {@code UnsupportedOperationException} 으로 튀어나오면 501 로 감춰진다.
     */
    @ExceptionHandler(UnsupportedOperationException.class)
    public ResponseEntity<ErrorResponse> handleNotImplemented(UnsupportedOperationException e) {
        // 서버 잘못이 아니라 '아직 없음'이므로 warn. 스택트레이스는 남기지 않는다.
        log.warn("[NotImplemented] {}", e.getMessage());
        return ResponseEntity
                .status(ErrorCode.NOT_IMPLEMENTED.getStatus())
                .body(ErrorResponse.of(ErrorCode.NOT_IMPLEMENTED));
    }

    /**
     * 매핑도 정적 리소스도 없는 경로 → 404.
     *
     * <p><b>왜 필요한가.</b> 이게 없으면 마지막 그물 {@link #handleException} 이
     * {@link NoResourceFoundException} 까지 잡아 <b>500 INTERNAL_ERROR</b> 를 내보낸다.
     * 그 문구는 "일시적인 오류입니다. 잠시 후 다시 시도해주세요" 인데,
     * <b>없는 주소는 다시 시도해도 영원히 없다.</b> 원인이 다른 두 사실
     * ("서버가 아프다" / "그런 주소가 없다")을 한 값으로 뭉갠 것이라
     * 이 저장소가 {@code ANSWER_INCOMPLETE}·{@code BILLING_METHOD_UNREADABLE} 를 갈라낸 것과 같은 부류다.
     *
     * <p>실제로 운영에서 드러났다. actuator 를 management 포트(8081)로 옮긴 뒤
     * {@code GET /actuator/health} 는 8080 에 <b>존재하지 않는 경로</b>가 됐는데,
     * 응답이 500 이라 <b>서버 장애처럼 보였다.</b> 헬스체크로 쓰는 주소라 더 나빴다.
     *
     * <p><b>정적 리소스는 영향을 받지 않는다.</b> 이 예외는 {@code ResourceHttpRequestHandler} 가
     * 파일을 <b>찾지 못했을 때만</b> 던진다. 실재하는 {@code /widget/alldap-widget.js} 는
     * 예외 없이 그대로 응답되므로 이 핸들러를 지나가지도 않는다
     * ({@code NotFoundIntegrationTest} 가 그 사실을 실제 HTTP 로 재고 있다).
     *
     * <p><b>요청 경로를 응답에 되비추지 않는 이유.</b> 되비추면 응답이
     * "그 주소는 이렇게 생겼다"를 확인해주는 도구가 되고, 반사된 문자열이 그대로 화면에 그려지면
     * 그 자체가 하나의 구멍이다. 이 저장소가 남의 봇에 403 대신 404 를 주는 것과 같은 이유다.
     * 정확한 경로는 로그에만 남긴다.
     *
     * <p>로그는 {@code warn} 이다. 주소를 잘못 부른 것은 <b>클라이언트 잘못</b>이고,
     * 아무 문자열이나 붙여 호출하는 것만으로 ERROR 스택트레이스를 무제한으로 쌓게 두면
     * 진짜 장애가 소음에 묻힌다({@link #handleTypeMismatch} 와 같은 판단).
     */
    @ExceptionHandler(NoResourceFoundException.class)
    public ResponseEntity<ErrorResponse> handleNoResourceFound(NoResourceFoundException e) {
        log.warn("[NoResourceFound] method={} path={}", e.getHttpMethod(), e.getResourcePath());
        return ResponseEntity
                .status(ErrorCode.RESOURCE_NOT_FOUND.getStatus())
                .body(ErrorResponse.of(ErrorCode.RESOURCE_NOT_FOUND));
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<ErrorResponse> handleException(Exception e) {
        log.error("[UnhandledException]", e);
        return ResponseEntity
                .status(ErrorCode.INTERNAL_ERROR.getStatus())
                .body(ErrorResponse.of(ErrorCode.INTERNAL_ERROR));
    }

    // MethodArgumentTypeMismatchException 은 위에 추가했다(문서 API 가 UUID 경로 변수를 쓰기 시작해서).
    // TODO(W2): ConstraintViolationException(@RequestParam/@PathVariable 에 붙인 검증 애너테이션)은
    //   아직 그런 검증을 쓰는 엔드포인트가 없어 남겨둔다. 처음 쓰는 슬라이스에서 함께 추가할 것.
}
