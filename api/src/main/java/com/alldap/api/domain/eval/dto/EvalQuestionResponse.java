package com.alldap.api.domain.eval.dto;

import com.alldap.api.domain.eval.entity.EvalQuestion;

import java.time.Instant;
import java.util.UUID;

/**
 * 평가 질문 응답. 프론트의 {@code EvalQuestion}({@code web/lib/types.ts})과 맞춘다.
 */
public record EvalQuestionResponse(
        UUID id,
        String question,
        /** 문서 청크에서 뽑아낸 기대 답변 */
        String groundTruth,
        /** 이 질문이 어느 청크에서 생성됐는지 (chunks 엔티티가 없으므로 UUID 값만 전달) */
        UUID sourceChunkId,
        boolean isActive,
        Instant createdAt
) {

    public static EvalQuestionResponse from(EvalQuestion question) {
        return new EvalQuestionResponse(
                question.getId(),
                question.getQuestion(),
                question.getGroundTruth(),
                question.getSourceChunkId(),
                question.isActive(),
                question.getCreatedAt()
        );
    }
}
