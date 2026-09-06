package com.alldap.api.domain.billing.client;

import com.alldap.api.global.config.TossProperties;
import com.alldap.api.global.exception.ApiException;
import com.alldap.api.global.exception.ErrorCode;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestClientResponseException;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.time.Duration;
import java.util.UUID;

/**
 * 토스페이먼츠 호출 담당. <b>토스 컨트랙트를 아는 코드는 이 파일과 같은 패키지의 DTO 뿐이다.</b>
 *
 * <p><b>실패 변환을 여기서 끝낸다.</b> 호출 지점마다 try-catch 를 적으면 반드시 한 곳이 빠지고,
 * 빠진 곳에서 {@code RestClientException} 이 그대로 올라가 <b>500</b> 이 나간다 —
 * "토스가 카드를 거절했다" 가 "우리 서버가 고장났다" 로 둔갑한다.
 * {@code AiServiceClient} 가 같은 이유로 같은 모양을 하고 있다.
 *
 * <p><b>코드를 나누는 기준도 같다 — "누구 잘못인가".</b> 아래는 {@link #issueBillingKey} (발급) 규칙이다.
 * <ul>
 *   <li>토스 4xx(카드 거절·유효기간·정지) → 400 {@code BILLING_AUTH_FAILED} + <b>토스의 한국어 문구 그대로</b></li>
 *   <li>토스 401 → 503. 이건 사용자 잘못이 아니라 <b>우리 키 설정 문제</b>다. 아래 참고</li>
 *   <li>토스 5xx·타임아웃·연결 실패 → 503 {@code BILLING_PROVIDER_UNAVAILABLE}</li>
 * </ul>
 *
 * <p>🔴 <b>{@link #deleteBillingKey}(폐기)는 이 4xx 규칙을 따르지 않는다</b> — 삭제는
 * "카드가 거절됐다" 같은 사용자 잘못이 없고, 대신 "토스 쪽에 이미 없다(404)" 와
 * "모른다(그 밖의 4xx)" 를 갈라야 한다. 정확한 규칙은 그 메서드의 javadoc 을 볼 것.
 *
 * <p>🔴 <b>서킷브레이커를 달지 않는다.</b> {@code AiServiceCircuitBreaker} 를 재사용하면
 * 토스 장애가 채팅을 끊는다. 그렇다고 결제용을 새로 만들 근거도 아직 없다 —
 * 서킷의 목적은 "죽은 상대를 계속 두드려 우리 스레드를 소모하는 것"을 막는 건데,
 * 카드 등록은 <b>사용자가 버튼을 눌러야만</b> 일어나 트래픽이 구조적으로 낮다.
 * 자동 청구(4번 조각)가 붙어 배치가 토스를 두드리기 시작하면 그때 필요해진다.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class TossClient {

    /**
     * 총 시도 횟수(재시도 횟수가 아니다). 2 = 최초 1회 + 재시도 1회.
     *
     * <p>설정으로 빼지 않았다. 튜닝할 값이 아니라 <b>"한 번만 더"</b> 라는 결정 자체이고,
     * 늘리면 고아 빌링키가 늘 위험만 커진다(멱등키 유효기간 15일 안에서는 안전하지만,
     * 시도가 늘수록 사용자 대기 시간이 그대로 길어진다).
     */
    private static final int MAX_ATTEMPTS = 2;
    private static final Duration RETRY_DELAY = Duration.ofMillis(300);

    private final RestClient tossRestClient;

    /** 토스 에러 본문 {@code {"code","message"}} 를 읽는 데만 쓴다. Boot 4 가 자동 구성하는 Jackson 3 매퍼다. */
    private final ObjectMapper objectMapper;

    /** 실패 로그에 "어디로 못 붙었는지" 를 남긴다. 주소를 모르면 로그만 보고 원인을 못 좁힌다. */
    private final TossProperties tossProperties;

    /**
     * 카드 등록 인증({@code authKey})을 <b>빌링키</b>로 바꾼다.
     *
     * <p>🔴 <b>이 프로젝트에서 유일하게 "실패가 복구 불가능한" 호출이다.</b>
     * 토스에는 <b>빌링키를 조회하는 API 가 없다.</b> 발급은 됐는데 우리가 응답을 못 받으면
     * 그 키는 영원히 회수할 수 없다(폐기하려면 키를 알아야 하는데 알아낼 방법이 없다).
     *
     * @param customerKey 🔴 <b>반드시 우리 DB 에서 읽은 값</b>이어야 한다. 브라우저가 준 값을
     *                    그대로 넘기면 남의 계정에 카드를 붙일 수 있다. 검증은 {@code BillingService} 가 한다.
     */
    public TossBilling issueBillingKey(String authKey, String customerKey) {
        // 🔴 멱등키는 <루프 밖에서> 한 번만 만든다. 안에서 만들면 재시도가 새 키를 쓰게 되고,
        //    그러면 토스는 이걸 <다른 요청>으로 보고 빌링키를 하나 더 발급한다 = 고아가 하나 더 는다.
        String idempotencyKey = UUID.randomUUID().toString();

        TossBillingKeyResponse response = issue(idempotencyKey,
                new TossIssueBillingKeyRequest(authKey, customerKey));

        // 200 인데 우리가 필요한 값이 없는 경우. 🔴 여기 오면 이미 발급된 키를 잃은 것이다.
        // 조용히 넘기면 "등록됐다는데 카드가 안 보인다" 가 되므로 크게 남기고 실패시킨다.
        if (response == null || response.billingKey() == null || response.billingKey().isBlank()) {
            log.error("[토스] 발급 응답에 billingKey 가 없다. 발급된 키를 잃었을 수 있다(조회 API 없음). "
                    + "idempotencyKey={} customerKey={}", idempotencyKey, customerKey);
            throw new ApiException(ErrorCode.BILLING_PROVIDER_UNAVAILABLE);
        }
        if (response.card() == null) {
            // 계좌 자동결제 등 카드가 아닌 수단. 이 조각은 카드만 다룬다(설계 §범위).
            log.error("[토스] 발급 응답에 card 가 없다. 카드가 아닌 수단으로 등록됐을 수 있다. "
                    + "idempotencyKey={}", idempotencyKey);
            throw new ApiException(ErrorCode.BILLING_AUTH_FAILED,
                    "카드로만 등록할 수 있습니다. 결제 수단을 카드로 선택한 뒤 다시 시도해주세요.");
        }

        return new TossBilling(response.billingKey(),
                response.card().issuerCode(), response.card().number());
    }

    /**
     * 🔴 <b>I/O 실패에만, 같은 멱등키로, 한 번 재시도한다.</b>
     *
     * <p>⚠️ <b>{@code AiServiceClient} 의 재시도 논리를 그대로 가져오면 안 된다.</b>
     * 그쪽은 <i>"재시도의 전제는 직전 시도가 아무 일도 하지 않았다는 것"</i> 이라
     * <b>연결 실패에만</b> 재시도하고 읽기 타임아웃은 제외한다. 결제에서는 그 전제가 안 선다 —
     * <b>읽기 타임아웃이어도 토스는 이미 빌링키를 발급했을 수 있고</b>, 조회 API 가 없어
     * 그 키는 영원히 회수할 수 없다. 즉 "재시도하지 않는 것" 이 더 안전한 선택이 아니다.
     *
     * <p>그 전제를 <b>멱등키가 대신 세워준다.</b> 같은 (멱등키·API 키·주소·메서드) 조합이면
     * 토스가 같은 응답을 돌려준다(처음 쓴 날부터 15일 유효). 그래서 여기서는
     * 연결 실패든 읽기 타임아웃이든 응답 도중 끊김이든 <b>I/O 실패 전부</b> 재시도한다.
     * <b>멱등키 없이 이 정책을 쓰면 고아 빌링키가 하나 더 늘 뿐이다.</b>
     *
     * <p>반대로 <b>HTTP 응답이 온 경우(4xx·5xx)는 재시도하지 않는다.</b> 토스가 판단해서 답한 것이라
     * 같은 요청은 같은 답을 받는다. 5xx 도 마찬가지다 — 응답이 왔다는 것 자체가 요청이 도달했다는 뜻이다.
     */
    private TossBillingKeyResponse issue(String idempotencyKey, TossIssueBillingKeyRequest body) {
        for (int attempt = 1; ; attempt++) {
            try {
                return tossRestClient.post()
                        .uri("/v1/billing/authorizations/issue")
                        .header("Idempotency-Key", idempotencyKey)
                        .contentType(MediaType.APPLICATION_JSON)
                        .body(body)
                        .retrieve()
                        .body(TossBillingKeyResponse.class);

            } catch (RestClientResponseException e) {
                // ⚠️ RestClientResponseException 은 RestClientException 의 하위 타입이다.
                //    순서를 바꾸면 4xx·5xx 까지 아래 I/O 분기로 들어가 <재시도>하게 된다.
                throw translateHttpFailure(e);

            } catch (RestClientException e) {
                boolean ioFailure = e instanceof ResourceAccessException
                        || e.getCause() instanceof IOException;

                if (!ioFailure) {
                    // 응답은 멀쩡히 받았는데 JSON 을 우리 DTO 로 해석하지 못한 경우 =
                    // 토스가 스키마를 바꿨거나 우리 DTO 가 낡았다.
                    // 🔴 재시도하면 안 된다. 요청은 성공했고 <다시 보내도 똑같이 못 읽는다>.
                    //    그리고 이 경우 발급된 키를 이미 잃었다.
                    log.error("[토스] 발급 응답을 해석하지 못했다. 발급된 키를 잃었을 수 있다(조회 API 없음). "
                            + "idempotencyKey={}", idempotencyKey, e);
                    throw new ApiException(ErrorCode.BILLING_PROVIDER_UNAVAILABLE);
                }

                if (attempt >= MAX_ATTEMPTS) {
                    log.error("[토스] 발급 실패 — {} 와의 통신에 {}회 실패했다. "
                                    + "빌링키가 발급됐는데 우리가 못 받았을 수 있다(조회 API 없음). idempotencyKey={}",
                            tossProperties.baseUrl(), attempt, idempotencyKey, e);
                    throw new ApiException(ErrorCode.BILLING_PROVIDER_UNAVAILABLE);
                }

                log.warn("[토스] 발급 통신 실패. {} 뒤 <같은 멱등키로> 재시도 ({}/{}). idempotencyKey={}",
                        RETRY_DELAY, attempt + 1, MAX_ATTEMPTS, idempotencyKey);
                sleep();
            }
        }
    }

    /** 상태 코드를 "누구 잘못인가" 로 번역한다. */
    private ApiException translateHttpFailure(RestClientResponseException e) {
        HttpStatusCode status = e.getStatusCode();

        // 🔴 401 만 따로 뗀다. 4xx 라고 사용자에게 "카드를 확인하세요" 라고 하면 <거짓말>이다 —
        //    사용자는 손쓸 수 없고, 고칠 사람은 TOSS_SECRET_KEY 를 넣을 우리다.
        //    (INVALID_API_KEY 는 결제위젯 키를 넣었을 때 나온다. 자동결제는 API 개별 연동 키다)
        if (status.isSameCodeAs(HttpStatus.UNAUTHORIZED)) {
            log.error("[토스] 인증 키가 거절됐다. TOSS_SECRET_KEY 가 <API 개별 연동 키>(test_sk_/live_sk_)인지, "
                    + "앞뒤에 공백·BOM 이 섞이지 않았는지 확인할 것. body={}", e.getResponseBodyAsString());
            return new ApiException(ErrorCode.BILLING_PROVIDER_UNAVAILABLE);
        }

        if (status.is4xxClientError()) {
            // 토스의 문구를 그대로 내려보낸다. 여기 오는 말은 애초에 <구매자에게 보여주려고 쓴 한국어>다.
            // 예: "카드 유효기간이 올바르지 않습니다." · "정지된 카드입니다."
            // 우리 기본 문구로 뭉개면 사용자가 다음에 뭘 해야 하는지를 잃는다(AGENTS.md 작업 규칙 4).
            log.warn("[토스] 발급 거절 status={} body={}", status, e.getResponseBodyAsString());
            return new ApiException(ErrorCode.BILLING_AUTH_FAILED, extractTossMessage(e));
        }

        log.error("[토스] 발급 실패 — 토스가 {} 응답. body={}", status, e.getResponseBodyAsString());
        return new ApiException(ErrorCode.BILLING_PROVIDER_UNAVAILABLE);
    }

    /**
     * 토스 v1 에러 본문 {@code {"code":"...","message":"..."}} 에서 문구만 꺼낸다.
     *
     * <p>꺼내지 못하면 null 을 돌려주고, 그러면 {@link ApiException} 이 {@link ErrorCode} 의
     * 기본 문구를 쓴다 — 실패해도 사용자 응답은 여전히 온전하다.
     * <b>파싱 실패로 예외를 던지면 "에러를 만들다가 에러가 나는" 최악의 모양</b>이 된다
     * ({@code AiServiceClient.extractDetail} 과 같은 이유).
     */
    private String extractTossMessage(RestClientResponseException e) {
        try {
            JsonNode message = objectMapper.readTree(e.getResponseBodyAsString()).path("message");
            // ⚠️ Jackson 3 에서 isTextual() 이 isString() 으로 바뀌었다. 2.x 예제를 그대로 쓰면 deprecated 다.
            return message.isString() && !message.asString().isBlank() ? message.asString() : null;
        } catch (RuntimeException ignored) {
            return null;
        }
    }

    private void sleep() {
        try {
            Thread.sleep(RETRY_DELAY.toMillis());
        } catch (InterruptedException ie) {
            // 인터럽트를 삼키면 상위(요청 취소·종료)가 신호를 잃는다. 복원하고 즉시 포기한다.
            Thread.currentThread().interrupt();
            throw new ApiException(ErrorCode.BILLING_PROVIDER_UNAVAILABLE);
        }
    }

    /**
     * 빌링키 폐기. {@code DELETE {base}/v1/billing/{billingKey}}
     *
     * <h2>🔴 반환값이 {@code void} 인 것이 이 메서드의 설계다</h2>
     * 404 와 그 밖의 실패를 호출부에 구분해 넘겨야 할 것 같지만, 실제로 <b>호출부가 두 경우에 하는 일이 같다</b> —
     * 둘 다 우리 행을 지운다.
     * <ul>
     *   <li><b>200</b> — 토스가 지웠다 → 우리 행도 지운다</li>
     *   <li><b>404</b> — 토스 쪽엔 <b>이미 없다</b>. 치울 게 없으니 우리 행만 지운다</li>
     *   <li><b>그 밖의 4xx(401·429 등) · 5xx · I/O</b> — <b>지워졌는지, 심지어 토스가 요청을 보기나
     *       했는지도 모른다</b> → 예외를 던진다. 우리 행이 남아야 다시 시도할 수 있다</li>
     * </ul>
     * 즉 호출부가 필요한 신호는 "지워도 되는가 / 아직 아닌가" 하나뿐이고, 그건 <b>예외를 던지느냐</b>로
     * 이미 표현된다. {@code boolean} 을 돌려주는 안도 검토했지만, 호출부가 그 값으로 분기할 일이
     * 없는데 반환값이 있으면 <b>"여기서 뭔가 갈라져야 하는 것 아닌가"</b> 하는 잘못된 인상만 남긴다.
     *
     * <h2>404 만 "이미 없다"로 보는 것도 우리 <b>추측</b>이다</h2>
     * 토스 문서에 이 API 의 에러 코드표가 없다 — 없는 빌링키를 지울 때 무슨 코드가 오는지 모른다.
     * 추측이 틀리면(예: 없는 빌링키에도 404 가 아닌 다른 코드가 온다면) 토스 쪽에 고아 빌링키가
     * 남는다. 그래도 404 로 좁힌 이유는 <b>"모르면 지우지 않는다"</b> 다 — 401·429 같은 그 밖의
     * 4xx 는 "없다" 는 뜻이 아니라 <b>토스가 우리 요청을 제대로 보기나 했는지조차 모른다</b>는
     * 뜻이다(예: 시크릿 키가 잘못돼 401 이면 토스는 빌링키를 쳐다보지도 않았다). 그런 경우까지
     * 삼키면 <b>모든 삭제 요청이 걸리는 동안</b> 지워지는 카드가 전부 고아가 된다 — "4xx 도 유지"
     * 했을 때의 "사용자가 카드를 영영 못 지운다" 는 대가보다, 되돌릴 수 없는 이 대가가 더 크다.
     * 그래서 삼키되 <b>반드시 WARN 으로 남긴다</b> — 고아가 생겼다면 이 로그가 유일한 흔적이다.
     *
     * <h2>멱등키를 붙이지 않는다</h2>
     * 발급({@code issueBillingKey})에는 붙였지만 여기는 아니다. <b>DELETE 는 메서드 자체가 멱등</b>이라
     * (같은 키를 두 번 지워도 결과가 같다) 중복 실행이 새 부작용을 만들지 않는다.
     * 발급이 멱등키를 필요로 했던 이유는 정확히 반대다 — POST 는 부를 때마다 빌링키가
     * <b>하나씩 더 생기고</b>, 조회 API 가 없어 회수할 방법이 없다.
     *
     * <h2>응답 본문을 읽지 않는다</h2>
     * <b>토스 문서가 자기모순이다.</b> API 레퍼런스는 "비어있는 body 에 200 응답만 내려갑니다" 라고
     * 하는데 연동 가이드 FAQ 는 {@code {"billingKey":"..."}} 를 보여준다. 어느 쪽이 맞는지 우리가
     * 정할 수 없으므로 <b>HTTP 상태로만 판정한다.</b> {@code toBodilessEntity()} 가 그 결정을 코드로
     * 못박은 것이다 — 본문을 DTO 로 받게 해두면 언젠가 "그 필드를 쓰는" 코드가 붙고, 그날 토스가
     * 레퍼런스대로 빈 본문을 주면 조용히 깨진다.
     *
     * <p>재시도하지 않는다. 실패해도 <b>우리 행이 남으므로</b> 사용자가 버튼을 다시 누르면 된다 —
     * 그게 "토스 먼저, 우리 나중" 순서가 사주는 것이다.
     */
    public void deleteBillingKey(String billingKey) {
        try {
            tossRestClient.delete()
                    // ⚠️ 문자열로 이어붙이지 말 것. 토스의 빌링키는 base64 라 '/' 와 '+' 가 들어온다
                    //    (문서 예시: "IuLQlvcbmS/5jVDkbnRnAmCn88YZLfnGpVBGpLJ+abU=").
                    //    URI 템플릿 변수로 넘겨야 스프링이 경로 세그먼트 규칙대로 인코딩한다.
                    .uri("/v1/billing/{billingKey}", billingKey)
                    .retrieve()
                    .toBodilessEntity();

        } catch (RestClientResponseException e) {
            // 🔴 404 만 삼킨다. "모르면 지우지 않는다" 가 원칙이다.
            //  - 404 = "그런 빌링키 없다" → 치울 게 없다 → 우리 행만 지워도 안전하다.
            //  - 그 밖의 4xx(401·429 등) = 토스가 우리 요청을 <제대로 보기나 했는지조차 모른다>.
            //    예를 들어 시크릿 키가 잘못됐거나 회전돼 401 이 나면 토스는 빌링키를 쳐다보지도
            //    않았는데, 여기서 삼키면 우리 유일한 사본을 지우고 토스에는 영영 회수 못 할
            //    빌링키가 남는다 — "토스 먼저, 그다음 우리" 순서가 막으려던 바로 그 결과다.
            //    게다가 401 은 특정 사용자가 아니라 <모든 삭제 요청에> 걸리므로, 키가 잘못
            //    설정된 채로 도는 동안 삭제되는 카드가 전부 고아가 된다. 429(레이트리밋)도
            //    "없다" 는 뜻이 전혀 아니다. 되돌릴 수 있는 실패(행을 남겨 재시도)를 고른다.
            //  ⚠️ 대가: 토스가 "없는 빌링키" 에 404 가 아닌 다른 4xx 를 줄 수도 있다 — 그러면
            //    사용자가 카드를 못 지우고 503 을 본다. 토스 문서에 이 API 의 에러 코드표가
            //    없어 확인할 수 없다. 그래도 "지웠는데 안 지워졌다" 보다 이쪽이 안전한 실패다.
            if (e.getStatusCode().isSameCodeAs(HttpStatus.NOT_FOUND)) {
                log.warn("[토스] 빌링키 폐기를 404 로 거절당했다. 이미 없는 키로 보고 우리 행만 지운다. body={}",
                        e.getResponseBodyAsString());
                return;   // 삼킨다 = "토스 쪽엔 이미 없다"
            }
            log.error("[토스] 빌링키 폐기 실패 — 토스가 {} 응답. body={}",
                    e.getStatusCode(), e.getResponseBodyAsString());
            throw new ApiException(ErrorCode.BILLING_PROVIDER_UNAVAILABLE);

        } catch (RestClientException e) {
            // 연결 실패·타임아웃·응답 도중 끊김. 전부 <지워졌는지 모르는> 상태다.
            //
            // AiServiceClient 는 여기서 연결 실패(503)와 읽기 타임아웃(504)을 갈랐지만, 그건
            // 사용자가 할 수 있는 행동이 달랐기 때문이다("기다려라" vs "질문을 줄여라").
            // 삭제에는 그런 차이가 없다 — 어느 쪽이든 답은 "잠시 후 다시 눌러주세요" 하나라
            // 나누면 코드만 늘고 안내는 같아진다. ResourceAccessException 도 RestClientException 의
            // 하위 타입이라 이 한 블록이 다 받는다.
            //
            // 🔴 e 도 e.getMessage() 도 로그에 넘기지 않는다 — RestClientException 메시지는
            //    스프링이 `I/O error on DELETE request for "<URL>": <원인>` 으로 만드는데,
            //    이 메서드는 <빌링키를 URL 경로에 싣는다>. e 를 그대로 찍으면 읽기 타임아웃
            //    한 번에 평문 빌링키가 로그로 샌다 — Task 1 에서 DB 에 AES-256-GCM 으로
            //    암호화해 저장한 이유가 무효가 된다(로그 수집기는 보통 DB 보다 접근 범위가
            //    넓고 보존 기간도 길다). 그래서 <원인(cause)만> 꺼낸다 — cause 에는 URI 가
            //    실리지 않는다. (issueBillingKey 의 같은 모양 로그는 안전하다 — 그쪽 URI 는
            //    "/v1/billing/authorizations/issue" 라 비밀이 없다. 그래서 고치지 않았다)
            log.error("[토스] 빌링키 폐기 실패 — {} 와 통신하지 못했다. cause={}",
                    tossProperties.baseUrl(),
                    e.getCause() != null ? e.getCause().toString() : e.getClass().getSimpleName(),
                    e.getCause());
            throw new ApiException(ErrorCode.BILLING_PROVIDER_UNAVAILABLE);
        }
    }
}
