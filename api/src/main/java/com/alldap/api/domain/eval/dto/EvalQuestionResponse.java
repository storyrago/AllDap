package com.alldap.api.domain.eval.dto;

import com.alldap.api.domain.eval.entity.EvalQuestion;
import com.alldap.api.global.client.dto.AiEvalQuestionResponse;

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

    /** DB 에서 읽은 질문 (목록 조회용). */
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

    /**
     * Python 이 방금 만든 질문 (생성 응답용).
     *
     * <p>DB 를 다시 읽지 않고 Python 응답을 그대로 쓴다. 방금 INSERT 된 행이라 값이 같고,
     * 한 번 더 읽으면 <b>같은 요청 안에서 목록이 두 번 조회</b>되는 셈이다.
     *
     * <p>같은 이름의 메서드가 두 개인 이유(오버로딩): 들어오는 타입이 다르다.
     * {@link EvalQuestion} 은 JPA 엔티티, {@link AiEvalQuestionResponse} 는 Python 응답 DTO 다.
     * 호출부는 둘 다 {@code EvalQuestionResponse::from} 으로 쓰고 컴파일러가 타입으로 고른다.
     */
    public static EvalQuestionResponse from(AiEvalQuestionResponse question) {
        return new EvalQuestionResponse(
                question.id(),
                question.question(),
                question.groundTruth(),
                question.sourceChunkId(),
                question.isActive(),
                question.createdAt()
        );
    }
}
