package com.alldap.api.domain.chat.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

/**
 * {@code POST /api/bots/{botId}/chat} · {@code POST /api/w/{publicKey}/chat} 요청 본문.
 *
 * <p>길이 제한은 Python 의 {@code ChatRequest}(message 1~2000, session_id ≤64)와 <b>같은 값</b>이다.
 * 여기서 먼저 막는 이유: Python 까지 갔다가 422 로 튕기면 사용자에게 보여줄 한국어 안내를 만들 수 없다.
 *
 * <p>botId 는 경로에서 오므로 본문에 넣지 않는다.
 * 본문으로 받으면 경로와 다른 값을 보낼 수 있어 권한 검사를 우회할 여지가 생긴다.
 */
public record ChatRequest(
        @NotBlank(message = "질문을 입력해주세요.")
        @Size(max = 2000, message = "질문은 2000자까지 보낼 수 있습니다. 질문을 나눠서 보내주세요.")
        String message,

        @NotBlank(message = "세션 정보가 없습니다. 페이지를 새로고침한 뒤 다시 시도해주세요.")
        @Size(max = 64, message = "세션 정보가 올바르지 않습니다. 페이지를 새로고침해주세요.")
        String sessionId
) {
}
