package com.alldap.api.domain.plan.dto;

import com.alldap.api.domain.plan.Plan;
import jakarta.validation.constraints.NotNull;

/**
 * {@code PUT /api/plan} 요청 본문.
 *
 * <p>{@code userId} 는 본문에 없다 — {@code @AuthenticationPrincipal} 로만 받는다.
 * 이 저장소의 규칙이고, 받으면 남의 id 를 적어 보내는 것만으로 남의 요금제를 바꿀 수 있다.
 *
 * <p>{@code @NotNull} 이 잡는 것은 {@code {"plan": null}} 과 필드 누락이다.
 * 모르는 문자열({@code "enterprise"})은 여기 오기 전에 {@link Plan#from} 이 막아 400 이 된다.
 */
public record ChangePlanRequest(
        @NotNull(message = "요금제를 선택해주세요. free 또는 pro 중 하나여야 합니다.")
        Plan plan
) {
}
