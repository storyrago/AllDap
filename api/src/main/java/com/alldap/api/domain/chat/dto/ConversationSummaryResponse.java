package com.alldap.api.domain.chat.dto;

import java.time.Instant;
import java.util.UUID;

/**
 * 대화 로그 목록의 한 줄. 프론트의 {@code ConversationSummary}({@code web/lib/types.ts})와 맞춘다.
 *
 * <p>집계 필드({@code messageCount}, {@code hasFallback}, {@code firstUserMessage})는
 * 엔티티에 없는 값이다. 대화 건마다 messages 를 따로 조회하면 N+1 이 되므로
 * 한 번의 group by 쿼리로 채워야 한다(ConversationRepository TODO 참고).
 */
public record ConversationSummaryResponse(
        UUID id,
        String sessionId,
        /** widget = 실제 엔드유저 / test = 관리자 테스트 채팅 */
        String channel,
        Instant createdAt,
        long messageCount,
        /** 이 세션에 fallback 이 하나라도 있었는가 — 로그 필터의 근거 */
        boolean hasFallback,
        /** 목록에서 미리 보여줄 첫 질문 */
        String firstUserMessage
) {
}
