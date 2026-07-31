package com.alldap.api.global.client.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

/**
 * Python 의 {@code ChatResponse} (ai-service/app/schemas.py).
 *
 * <pre>
 * { answer, sources[], is_fallback, latency_ms }
 * </pre>
 *
 * <p>{@code isFallback} 이 true 라는 것은 <b>문서에서 근거를 찾지 못해 답변을 거절했다</b>는 뜻이다.
 * 환각을 막는 것이 이 제품의 핵심 가치이므로 이 플래그를 무시하거나 완화하지 말 것.
 * Spring 은 이 값을 보고 (1) answer 를 봇의 fallback_message 로 치환하고
 * (2) messages.is_fallback 에 기록해 품질 대시보드의 미답변 집계 근거로 쓴다.
 *
 * <p>{@code latencyMs} 는 Python 내부에서 잰 시간이다. Spring→Python 왕복 시간은 포함되지 않는다.
 */
public record AiChatResponse(
        @JsonProperty("answer") String answer,
        @JsonProperty("sources") List<AiSourceResponse> sources,
        @JsonProperty("is_fallback") boolean isFallback,
        @JsonProperty("latency_ms") Integer latencyMs
) {
}
