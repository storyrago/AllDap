package com.alldap.api.domain.billing.dto;

import com.alldap.api.domain.billing.service.CardIssuer;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.time.OffsetDateTime;
import java.util.List;

/**
 * 결제 수단 목록 응답. 조회·추가·기본 지정이 <b>전부 이 모양</b>을 돌려준다 —
 * 화면에 보이는 카드의 출처가 응답 하나로 고정되고, 프론트가 "쓰기 직후 재조회" 를 할 필요가 없다.
 *
 * <p>🔴 <b>{@code billingKey} 필드가 없다. 앞으로도 두지 않는다.</b> 필드가 있으면 언젠가 실린다.
 *
 * <p><b>카드가 없어도 {@code customerKey} 는 항상 내려간다.</b> 프론트가 토스 결제창을 열려면
 * 그 값이 필요하기 때문이다 — 카드를 등록하기 <b>전에</b> 알아야 하는 값이다.
 *
 * <p>{@code methods} 는 카드가 없으면 <b>빈 목록</b>이다({@code null} 이 아니다). V6 때는 단건이라
 * {@code method: null} 로 "없음" 을 표현했지만, 목록은 비어 있음이 곧 없음이다.
 *
 * @param methods 등록 순서대로. 기본 카드는 {@code isDefault = true} 인 <b>정확히 하나</b>(카드가 있을 때)
 */
public record BillingMethodsResponse(String customerKey, List<Card> methods) {

    /**
     * @param id               삭제·기본 지정 때 경로에 실을 식별자
     * @param issuerCode       토스가 준 발급사 코드("61"). <b>표시용이 아니라 프론트가 카드 면 색을
     *                         고르는 키</b>다({@code web/lib/cardBrand.ts}). 이름을 키로 쓰면 우리가
     *                         문구를 "현대" → "현대카드" 로 다듬는 순간 모든 현대 카드가 조용히
     *                         회색이 된다 — 코드는 토스가 정한 값이라 우리 사정으로 바뀌지 않는다.
     *                         ⚠️ 코드→<b>이름</b> 변환은 여전히 Spring 책임이다(아래 issuerName).
     * @param issuerName       카드사 <b>이름</b>. 토스는 코드("61")만 주므로 Spring 이 변환한다
     *                         ({@link CardIssuer}). 프론트에 <b>이름</b> 매핑을 두면
     *                         {@code web/lib/types.ts} 가 백엔드 응답과 어긋난다.
     * @param cardNumberMasked 토스가 마스킹해서 준 번호
     * @param registeredAt     우리 {@code created_at} 을 한국 시간 오프셋으로
     * @param isDefault        청구에 쓰는 카드인가. ⚠️ {@code @JsonProperty} 를 붙인 이유: 접근자가
     *                         {@code isDefault()} 라 Jackson 의 빈 규칙으로는 "default" 라는 이름이 될 수 있다.
     *                         프론트 {@code types.ts} 가 {@code isDefault} 를 전제하므로 이름을 못박는다.
     */
    public record Card(Long id,
                       String issuerCode,
                       String issuerName,
                       String cardNumberMasked,
                       OffsetDateTime registeredAt,
                       @JsonProperty("isDefault") boolean isDefault) {
    }
}
