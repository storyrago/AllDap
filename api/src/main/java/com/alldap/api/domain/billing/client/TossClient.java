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
 * <p><b>코드를 나누는 기준도 같다 — "누구 잘못인가".</b>
 * <ul>
 *   <li>토스 4xx(카드 거절·유효기간·정지) → 400 {@code BILLING_AUTH_FAILED} + <b>토스의 한국어 문구 그대로</b></li>
 *   <li>토스 401 → 503. 이건 사용자 잘못이 아니라 <b>우리 키 설정 문제</b>다. 아래 참고</li>
 *   <li>토스 5xx·타임아웃·연결 실패 → 503 {@code BILLING_PROVIDER_UNAVAILABLE}</li>
 * </ul>
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

    // TODO(Task 3): deleteBillingKey(String billingKey) — DELETE /v1/billing/{billingKey}.
    //   지금 만들지 않는 이유는 호출자가 없기 때문이다. 이 저장소는 호출자 없는 메서드가
    //   "검증되지 않은 채 동작한다는 인상만 남긴다" 는 것을 AiServiceClient.listDocuments 에서
    //   이미 문서화했다.
}
