package com.alldap.api.domain.chat.dto;

import java.time.Instant;
import java.util.List;

/**
 * 대화 상세의 메시지 한 건. 프론트의 {@code ChatMessage}({@code web/lib/types.ts})와 맞춘다.
 *
 * <p>{@code sources} 는 엔티티에서 JSON 문자열로 들고 있으므로 파싱해서 넣는다.
 * 파싱은 {@code ConversationLogService} 가 하고, <b>실패해도 예외를 던지지 않는다</b> —
 * 과거 로그 한 건의 JSON 이 깨졌다고 대화 전체가 500 이 되면 안 된다(Message.sources 주석).
 */
public record MessageResponse(
        Long id,
        /** user | assistant */
        String role,
        String content,
        /** assistant 메시지일 때만 값이 있다 */
        List<SourceResponse> sources,
        boolean isFallback,
        /** 1(👍) / -1(👎) / null(무응답) */
        Short feedback,
        Integer latencyMs,
        Instant createdAt
) {
}
