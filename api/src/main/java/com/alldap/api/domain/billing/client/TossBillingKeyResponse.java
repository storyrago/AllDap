package com.alldap.api.domain.billing.client;

/**
 * {@code POST /v1/billing/authorizations/issue} 성공 응답 중 <b>우리가 쓰는 것만</b>.
 *
 * <p>토스는 {@code mId}·{@code method}·{@code authenticatedAt}·{@code card.acquirerCode}·
 * {@code card.cardType}·{@code card.ownerType} 등을 함께 준다. 선언하지 않은 필드는 무시된다 —
 * <b>Jackson 3 부터 {@code FAIL_ON_UNKNOWN_PROPERTIES} 가 기본 off</b> 라서
 * {@code @JsonIgnoreProperties} 를 붙일 필요가 없다(2.x 에서는 기본 on 이었다).
 * 토스 문서가 "하위호환을 위해 모르는 필드를 무시하도록 설정하라" 고 권고하는 그 요건이
 * 기본 동작으로 이미 충족된다. 통합 테스트의 성공 응답 JSON 이 이걸 못박는다.
 *
 * <p>🔴 <b>{@code cardCompany}·{@code cardNumber} 를 쓰지 않는다.</b>
 * 2024-06-01 버전부터 응답에서 <b>제거된</b> 필드다. 옛 예제를 그대로 붙여넣으면
 * 로컬에서는 값이 null 이라 조용히 지나가고 운영에서 NPE 가 난다.
 * 카드 정보는 반드시 {@code card.issuerCode} / {@code card.number} 에서 읽는다.
 *
 * @param card 카드 상세. 계좌 자동결제였다면 없을 수 있으므로 호출자가 null 을 확인한다.
 */
public record TossBillingKeyResponse(String billingKey, Card card) {

    /**
     * @param issuerCode 카드 발급사 코드("61" 등). 이름은 {@code CardIssuer} 가 붙인다
     * @param number     토스가 마스킹해서 준 번호("43301234****123*").
     *                   <b>우리가 마스킹하는 것이 아니다</b> — 전체 카드번호는 우리 서버에 닿지 않는다
     */
    public record Card(String issuerCode, String number) {
    }
}
