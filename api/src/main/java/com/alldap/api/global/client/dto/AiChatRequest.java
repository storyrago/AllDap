package com.alldap.api.global.client.dto;

import com.fasterxml.jackson.annotation.JsonProperty;


/**
 * Python 의 {@code ChatRequest} (ai-service/app/schemas.py).
 *
 * <pre>
 * { bot_id, message (1~2000자), session_id (≤64자) }
 * </pre>
 *
 * <p><b>봇별 설정(system_prompt · fallback_message)은 이 요청에 실리지 않는다.</b>
 * 그래도 <b>둘 다 실제로 반영된다.</b> 반영 경로가 서로 다를 뿐이다.
 * <ul>
 *   <li>{@code fallback_message} : Spring 이 응답의 {@code is_fallback == true} 를 보고
 *       answer 를 봇의 문구로 <b>치환</b>한다. (ChatService.resolveAnswer)</li>
 *   <li>{@code system_prompt} : <b>Python 이 bots 테이블에서 직접 읽는다.</b>
 *       ({@code ai-service/app/generator.py} 의 {@code fetch_bot_prompt} 와
 *        {@code build_system_prompt}, 호출 지점은 {@code main.py} 의 chat 경로)</li>
 * </ul>
 *
 * <p>🔴 <b>왜 Spring 이 실어 보내지 않고 Python 이 직접 읽는가</b> (2026-08-13 결정).
 * 성능이 아니라 <b>평가</b> 때문이다. {@code evalrun} 은 Spring 을 거치지 않으므로,
 * Spring 이 실어 보내는 방식이면 평가만 기본 프롬프트로 돌아
 * "평가에서는 좋았는데 실사용은 다르다"가 된다. 평가가 실제 파이프라인을 그대로 태워야 한다는
 * 원칙이 여기서 갈렸다. 부수 효과로 Spring 은 한 줄도 고치지 않았다.
 *
 * <p>따라서 <b>여기에 {@code system_prompt} 필드를 추가하지 말 것.</b> 추가하면 반영 경로가
 * 둘이 되어 어느 쪽이 이겼는지 알 수 없어지고, 평가와 실사용이 다시 갈라진다.
 */
public record AiChatRequest(
        @JsonProperty("bot_id") Long botId,
        @JsonProperty("message") String message,
        @JsonProperty("session_id") String sessionId
) {
}
