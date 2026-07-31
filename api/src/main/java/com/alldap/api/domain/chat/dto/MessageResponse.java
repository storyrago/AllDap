package com.alldap.api.domain.chat.dto;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

/**
 * 대화 상세의 메시지 한 건. 프론트의 {@code ChatMessage}({@code web/lib/types.ts})와 맞춘다.
 *
 * <p>{@code sources} 는 엔티티에서 JSON 문자열로 들고 있으므로 여기서 파싱해 넣어야 한다.
 * TODO(W2): {@code Message.getSources()} 문자열 → {@code List<SourceResponse>} 변환기를 만들 것.
 *   변환 실패 시 예외를 던지지 말고 빈 목록으로 처리한다(Message.sources 주석 참고).
 */
public record MessageResponse(
        UUID id,
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
