package com.alldap.api.domain.billing.dto;

import jakarta.validation.constraints.NotBlank;

/**
 * {@code POST /api/billing/methods} 요청 본문.
 *
 * <p>🔴 <b>{@code customerKey} 를 받으면서도 신뢰하지 않는다.</b> 토스가 리다이렉트 쿼리로
 * 돌려준 값을 브라우저가 그대로 실어 보내는 것이라, 신뢰하면 남의 {@code customerKey} 를
 * 적어 보내는 것만으로 <b>카드가 남에게 붙는다.</b>
 * 서버는 JWT 사용자의 것을 DB 에서 읽어 토스에 넘기고, 이 값은 <b>대조에만</b> 쓴다.
 *
 * <p>그럼 왜 받는가: 대조가 있어야 <b>결제창을 연 계정과 지금 로그인한 계정이 다르다</b>는
 * 상황(브라우저 탭 두 개, 세션 만료 후 재로그인)을 잡아낼 수 있다.
 * 안 받으면 그 경우 엉뚱한 계정에 조용히 등록된다.
 *
 * <p>{@code userId} 는 본문에 없다 — {@code @AuthenticationPrincipal} 로만 받는다.
 * 이 저장소의 규칙이자, 위 사고를 막는 같은 원리다.
 */
public record RegisterBillingMethodRequest(

        @NotBlank(message = "카드 인증 정보가 없습니다. 카드 등록을 처음부터 다시 진행해주세요.")
        String authKey,

        @NotBlank(message = "고객 식별 정보가 없습니다. 카드 등록을 처음부터 다시 진행해주세요.")
        String customerKey
) {
}
