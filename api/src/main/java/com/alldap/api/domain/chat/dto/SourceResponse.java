package com.alldap.api.domain.chat.dto;

import com.alldap.api.global.client.dto.AiSourceResponse;


/**
 * 답변 근거 청크 하나. 프론트의 {@code Source}({@code web/lib/types.ts})와 필드명을 맞춘다.
 *
 * <p>Python 의 snake_case({@code chunk_id}, {@code document_id})를 camelCase 로 바꾸는 지점이다.
 */
public record SourceResponse(
        Long chunkId,
        Long documentId,
        String filename,
        /** 0~1. 1에 가까울수록 관련성 높음 (1 - 코사인거리) */
        Double score,
        /** 청크 본문 앞 200자 */
        String preview
) {

    public static SourceResponse from(AiSourceResponse ai) {
        return new SourceResponse(ai.chunkId(), ai.documentId(), ai.filename(), ai.score(), ai.preview());
    }
}
