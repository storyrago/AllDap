package com.alldap.api.domain.conflict.dto;

import com.alldap.api.global.client.dto.AiConflictResponse;

import java.time.Instant;
import java.util.UUID;

/**
 * 문서 간 사실 충돌 1건 (프론트 응답).
 *
 * <p>Python 은 {@code snake_case}({@code a_says}), 프론트는 {@code camelCase}({@code aSays})를
 * 본다. <b>변환은 Spring 책임이다</b>(AGENTS.md 작업 규칙 5) — Python 응답을 그대로 흘려보내면
 * {@code web/lib/types.ts} 의 타입이 전부 거짓이 된다.
 *
 * @param topic  무엇에 대한 충돌인가 (예: "노트북 교체 주기")
 * @param aSays  문서 A 의 주장 (예: "3년")
 * @param bSays  문서 B 의 주장 (예: "4년")
 * @param aContent 청크 원문. 관리자가 <b>판정을 검증</b>할 수 있어야 하므로 요약과 함께 준다
 * @param distance 후보 선별에 쓴 임베딩 거리. 판정 근거가 아니라 튜닝용 기록이라 null 가능
 */
public record ConflictResponse(
        UUID id,
        String topic,
        String aSays,
        String bSays,
        String aFilename,
        String bFilename,
        String aContent,
        String bContent,
        Double distance,
        String status,
        Instant createdAt
) {
    public static ConflictResponse from(AiConflictResponse ai) {
        return new ConflictResponse(
                ai.id(), ai.topic(), ai.aSays(), ai.bSays(),
                ai.aFilename(), ai.bFilename(), ai.aContent(), ai.bContent(),
                ai.distance(), ai.status(), ai.createdAt()
        );
    }
}
