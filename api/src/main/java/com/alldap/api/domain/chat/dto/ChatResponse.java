package com.alldap.api.domain.chat.dto;

import java.util.List;
import java.util.UUID;

/**
 * 채팅 응답. 프론트의 {@code ChatResponse}({@code web/lib/types.ts})와 필드명을 맞춘다.
 *
 * <p>Python 응답({@code is_fallback}, {@code latency_ms})을 그대로 흘려보내지 않고
 * camelCase 로 바꾸는 것과 더불어, Spring 만 아는 값 두 개를 채워 넣는다.
 * <ol>
 *   <li>{@code answer} — {@code isFallback} 이 true 면 봇의 {@code fallbackMessage} 로 <b>치환된</b> 문구.
 *       Python 은 봇별 문구를 모르기 때문에 이 치환이 현재 봇별 설정을 반영하는 유일한 수단이다.
 *       ({@code systemPrompt} 는 아직 반영할 방법이 없다 — AiChatRequest 주석 참고)</li>
 *   <li>{@code messageId} — messages 행을 만드는 건 Spring 이므로 Python 은 이 값을 모른다.
 *       이게 없으면 프론트가 {@code POST /api/messages/{msgId}/feedback} 을 호출할 수 없어
 *       👍/👎 UI 자체를 붙일 수 없다.</li>
 * </ol>
 */
public record ChatResponse(
        String answer,
        List<SourceResponse> sources,
        boolean isFallback,
        Integer latencyMs,
        UUID messageId
) {
}
