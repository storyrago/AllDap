package com.alldap.api.domain.billing.client;

/**
 * {@code POST /v1/billing/authorizations/issue} 요청 본문.
 *
 * <p>🔴 {@code customerKey} 는 <b>브라우저가 보낸 값이 아니라 우리 DB 에서 읽은 값</b>이어야 한다.
 * 판단은 {@code BillingService.register} 가 하고, 여기는 실어 나르기만 한다.
 */
public record TossIssueBillingKeyRequest(String authKey, String customerKey) {
}
