package com.alldap.api.global.client.dto;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * Python 의 {@code PATCH /internal/bots/{bot_id}/eval/questions/{question_id}} 요청 본문.
 *
 * <p>🔴 {@code @JsonInclude(NON_NULL)} 이 <b>이 DTO 의 핵심</b>이다.
 * PATCH 는 "보낸 필드만 고친다" 인데, null 을 그대로 직렬화하면
 * {@code {"question": null}} 이 나가고 Python 의 {@code exclude_unset} 이 그걸
 * <b>"질문을 null 로 바꿔달라"</b> 로 읽는다. 안 보내는 것과 null 로 보내는 것은 다른 뜻이다.
 *
 * <p>필드명이 snake_case 인 이유: Python 컨트랙트를 그대로 따른다.
 * camelCase 변환은 공개 API 경계(EvalController ↔ 프론트)에서만 한다.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record AiUpdateEvalQuestionRequest(
        String question,
        String ground_truth,
        Boolean is_active
) {
}
