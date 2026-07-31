package com.alldap.api.domain.chat.dto;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotNull;

/**
 * {@code POST /api/messages/{msgId}/feedback} 요청 본문.
 *
 * <p>{@code messages.feedback} 이 SMALLINT 라 타입은 {@code Short} 다.
 *
 * <p>{@code @Min(-1) @Max(1)} 만으로는 0 도 통과한다. 허용값은 1 과 -1 뿐이므로
 * 최종 검증은 {@code Message.applyFeedback()} 안에서 한다 — 어느 경로로 들어와도 지켜지게 하기 위해서다.
 */
public record FeedbackRequest(
        @NotNull(message = "피드백 값을 보내주세요. (도움됨 1, 도움안됨 -1)")
        @Min(value = -1, message = "피드백 값은 1 또는 -1 이어야 합니다.")
        @Max(value = 1, message = "피드백 값은 1 또는 -1 이어야 합니다.")
        Short feedback
) {
}
