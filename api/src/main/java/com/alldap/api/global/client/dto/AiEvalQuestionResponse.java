package com.alldap.api.global.client.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.time.Instant;
import java.util.UUID;

/**
 * Python 의 {@code EvalQuestionOut} (ai-service/app/schemas.py).
 *
 * <pre>
 * { id, question, ground_truth, source_chunk_id, is_active, created_at }
 * </pre>
 *
 * <p>{@link AiDocumentResponse} 와 같은 이유로 여기가 snake_case ↔ camelCase 경계다.
 * 전역 네이밍 전략을 바꾸면 우리 공개 API 까지 snake_case 가 되어 프론트가 깨진다.
 *
 * <p>{@code source_chunk_id} 는 null 일 수 있다 —
 * 출처 청크가 삭제되면 FK 가 {@code ON DELETE SET NULL} 로 비워진다(V1__init.sql).
 * 즉 "출처 없는 정답"이 정상적으로 존재한다. 화면에서 null 분기를 잊지 말 것.
 */
public record AiEvalQuestionResponse(
        @JsonProperty("id") UUID id,
        @JsonProperty("question") String question,
        @JsonProperty("ground_truth") String groundTruth,
        @JsonProperty("source_chunk_id") UUID sourceChunkId,
        @JsonProperty("is_active") boolean isActive,
        @JsonProperty("created_at") Instant createdAt
) {
}
