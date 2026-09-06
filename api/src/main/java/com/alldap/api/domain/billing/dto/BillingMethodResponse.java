package com.alldap.api.domain.billing.dto;

import com.alldap.api.domain.billing.service.CardIssuer;

import java.time.OffsetDateTime;

/**
 * 결제 수단 조회·등록 응답.
 *
 * <p>🔴 <b>{@code billingKey} 필드가 없다. 앞으로도 두지 않는다.</b> 필드가 있으면 언젠가 실린다.
 *
 * <p><b>카드가 없어도 {@code customerKey} 는 항상 내려간다.</b> 프론트가 토스 결제창을 열려면
 * 그 값이 필요하기 때문이다 — 카드를 등록하기 <b>전에</b> 알아야 하는 값이라
 * "카드가 없으면 응답이 비어 있다" 로 만들면 등록 자체를 시작할 수 없다.
 *
 * <p>{@code method} 는 카드가 없으면 {@code null} 이다. 필드를 통째로 빼지 않는 이유:
 * 프론트가 "카드가 없다" 와 "아직 안 불러왔다" 를 구별해야 한다.
 *
 * @param method 등록된 카드. 없으면 null
 */
public record BillingMethodResponse(String customerKey, Card method) {

    /**
     * @param issuerName       카드사 <b>이름</b>. 토스는 코드("61")만 주므로 Spring 이 변환한다
     *                         ({@link CardIssuer}). 프론트에 매핑을 두면 {@code web/lib/types.ts} 가
     *                         백엔드 응답과 어긋난다.
     * @param cardNumberMasked 토스가 마스킹해서 준 번호
     * @param registeredAt     우리 {@code created_at} 을 한국 시간 오프셋으로 내려준다.
     *                         토스의 {@code authenticatedAt} 을 저장하지 않은 이유는
     *                         카드를 한 장만 두는 동안 둘을 구별해 쓸 일이 없기 때문이다.
     */
    public record Card(String issuerName, String cardNumberMasked, OffsetDateTime registeredAt) {
    }
}
