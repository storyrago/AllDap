package com.alldap.api.domain.plan.dto;

import com.alldap.api.domain.plan.Plan;

/**
 * {@code GET}/{@code PUT /api/plan} 응답.
 *
 * <p>필드가 하나뿐이라 {@code Plan} 을 그대로 내려보내도 될 것 같지만 그러면 응답이
 * {@code "pro"} 라는 <b>맨 문자열</b>이 된다. 객체로 감싸면 나중에 필드를 더할 때
 * (4번 조각의 다음 청구일·구독 상태 등) 프론트가 파싱을 바꾸지 않아도 된다.
 *
 * <p>🔴 <b>금액이 없다.</b> 서버는 요금제의 <이름>만 알고 값은 모른다 —
 * 이유는 {@link Plan} javadoc 에 적었다.
 */
public record PlanResponse(Plan plan) {
}
