package com.alldap.api.domain.billing.client;

/**
 * 발급 결과 중 <b>우리 도메인이 아는 것만</b> 추린 값.
 *
 * <p>{@code TossBillingKeyResponse}(토스 스키마)를 서비스 계층까지 들여보내지 않는 이유는
 * {@code AiServiceClient} 가 {@code client/dto} 를 밖으로 안 내보내는 것과 같다 —
 * 외부 컨트랙트가 바뀌었을 때 고칠 곳이 {@code client} 패키지 안에서 끝나야 한다.
 *
 * @param billingKey 🔴 <b>평문이다.</b> 이 값을 로그에 찍거나 응답 DTO 에 담지 말 것.
 *                   {@code BillingService} 가 즉시 암호화해 저장하고 그 뒤로는 아무도 보지 않는다.
 */
public record TossBilling(String billingKey, String issuerCode, String cardNumberMasked) {

    /**
     * 🔴 record 의 자동 생성 {@code toString()} 을 그대로 두면 <b>모든 필드가 찍힌다</b> — billingKey 도
     * 포함해서다. javadoc 의 "로그에 찍지 말 것"은 <약속>일 뿐 강제하지 않는데, 이 슬라이스에서 실제로
     * 한 번 샜다({@code TossClient.deleteBillingKey} 의 I/O 실패 로그, 고치기 전). 약속을 구조로
     * 바꾼다 — 이 객체를 통째로 로그에 찍어도 더 이상 새지 않게.
     */
    @Override
    public String toString() {
        return "TossBilling[billingKey=***, issuerCode=%s, cardNumberMasked=%s]"
                .formatted(issuerCode, cardNumberMasked);
    }
}
