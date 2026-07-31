package com.alldap.api.global.client.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.UUID;

/**
 * Python 의 {@code ChatRequest} (ai-service/app/schemas.py).
 *
 * <pre>
 * { bot_id, message (1~2000자), session_id (≤64자) }
 * </pre>
 *
 * <p><b>⚠️ 알려진 컨트랙트 갭 (PRD §10.2 / CLAUDE.md "알려진 한계").</b>
 * 이 요청에는 {@code system_prompt} 도 {@code fallback_message} 도 없다.
 * 그런데 bots 테이블에는 두 컬럼이 다 있고 PRD F-06 은 봇별 설정을 요구한다. 따라서 현재는:
 * <ul>
 *   <li>{@code fallback_message} — 우회 가능. Spring 이 응답의 {@code is_fallback == true} 를 보고
 *       answer 를 봇의 문구로 <b>치환</b>한다. (ChatService 에서 처리)</li>
 *   <li>{@code system_prompt} — <b>반영할 방법이 없다.</b> 봇 설정 화면에서 저장은 되지만
 *       실제 답변에는 아무 영향이 없다. 이걸 "이미 동작한다"고 말하거나 쓰지 말 것.</li>
 * </ul>
 * TODO(W3 이후): Python 의 {@code ChatRequest} 에 {@code system_prompt} 를 추가하고
 *   {@code generator.py} 가 그것을 쓰도록 고친 뒤, 여기에 필드를 추가해 실어 보낼 것.
 *   대안(Python 이 bots 테이블을 직접 읽기)은 PRD 부록 A #7 에서 결정한다.
 */
public record AiChatRequest(
        @JsonProperty("bot_id") UUID botId,
        @JsonProperty("message") String message,
        @JsonProperty("session_id") String sessionId
) {
}
