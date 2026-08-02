package com.alldap.api.global.client.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.time.Instant;
import java.util.Map;
import java.util.UUID;

/**
 * Python 의 {@code EvalRunOut} (ai-service/app/schemas.py).
 *
 * <pre>
 * { id, status, config, avg_faithfulness, avg_relevancy, answered_rate, created_at }
 * status ∈ running | completed | failed
 * </pre>
 *
 * <p><b>점수가 전부 {@link Double}(래퍼)이고 {@code double} 이 아닌 이유:</b> null 이 온다.
 * 실행 직후({@code running})에는 아직 점수가 없고, 답변이 전부 fallback 이면 평균을 낼 대상이 없다.
 * {@code double} 로 받으면 Jackson 이 null 을 0.0 으로 바꿔버려
 * <b>"아직 없음"과 "0점"이 구분되지 않는다.</b>
 *
 * <p>{@code config} 를 {@code Map} 으로 받는 이유: Python 이 실행 시점 설정을 통째로 넣는데
 * 그 키 목록이 W4 에서 늘어난다({@code hybrid}, {@code reranker} …).
 * record 로 못박으면 Python 이 키를 하나 추가할 때마다 Spring 이 깨지거나 값을 잃는다.
 * 여기서는 원본을 그대로 들고, 프론트에 줄 때 {@code EvalConfigResponse} 로 정리한다.
 */
public record AiEvalRunResponse(
        @JsonProperty("id") UUID id,
        @JsonProperty("status") String status,
        @JsonProperty("config") Map<String, Object> config,
        @JsonProperty("avg_faithfulness") Double avgFaithfulness,
        @JsonProperty("avg_relevancy") Double avgRelevancy,
        @JsonProperty("answered_rate") Double answeredRate,
        @JsonProperty("created_at") Instant createdAt
) {
}
