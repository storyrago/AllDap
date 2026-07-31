package com.alldap.api.global.client.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.UUID;

/**
 * Python 의 {@code Source} (ai-service/app/schemas.py).
 *
 * <pre>
 * { chunk_id, document_id, filename, score, preview }
 * score   = 0~1 (1 - 코사인거리). 높을수록 관련성 높음
 * preview = 청크 본문 앞 200자
 * </pre>
 *
 * <p>{@code chunk_id} 를 받아오지만 Spring 은 chunks 테이블을 조회하지 않는다.
 * 이 값은 messages.sources(JSONB)에 그대로 저장해 두었다가
 * 나중에 "이 답변이 어느 청크를 근거로 삼았는지" 추적하는 용도로만 쓴다.
 */
public record AiSourceResponse(
        @JsonProperty("chunk_id") UUID chunkId,
        @JsonProperty("document_id") UUID documentId,
        @JsonProperty("filename") String filename,
        @JsonProperty("score") Double score,
        @JsonProperty("preview") String preview
) {
}
