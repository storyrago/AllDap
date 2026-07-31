package com.alldap.api.domain.chat.service;

import com.alldap.api.domain.bot.repository.BotRepository;
import com.alldap.api.domain.chat.dto.ConversationSummaryResponse;
import com.alldap.api.domain.chat.dto.MessageResponse;
import com.alldap.api.domain.chat.repository.ConversationRepository;
import com.alldap.api.domain.chat.repository.MessageRepository;
import com.alldap.api.global.common.PageResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.UUID;

/**
 * 대화 로그 조회 서비스.
 *
 * <p>{@link ChatService} 와 분리한 이유: 채팅은 외부 호출이 섞인 쓰기 흐름이고,
 * 로그는 순수한 읽기 흐름이라 트랜잭션 성격이 정반대다.
 * 한 클래스에 두면 {@code @Transactional} 설정이 서로 발목을 잡는다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class ConversationLogService {

    private final BotRepository botRepository;
    private final ConversationRepository conversationRepository;
    private final MessageRepository messageRepository;

    /**
     * 대화 로그 목록. {@code GET /api/bots/{botId}/logs}
     *
     * <p>TODO(W2): 구현. 필터(onlyFallback / onlyThumbsDown / from / to)를 파라미터로 받을 것.
     *   프론트의 {@code LogsQuery} 타입이 이미 그 항목들을 전제로 작성돼 있다.
     *   메서드 이름 규칙으로는 표현이 안 되므로 @Query 또는 Specification 이 필요하다.
     */
    public PageResponse<ConversationSummaryResponse> findLogs(UUID userId, UUID botId, Pageable pageable) {
        throw new UnsupportedOperationException("ConversationLogService.findLogs 미구현 (W2)");
    }

    /**
     * 대화 한 건의 메시지 전체.
     *
     * <p>TODO(W2): 이 API 의 경로를 확정할 것. PRD §10.1 표에는 로그 목록만 있고
     *   상세 조회 경로가 없다. 후보: {@code GET /api/bots/{botId}/logs/{conversationId}}.
     *   추가하기로 하면 PRD 도 함께 갱신한다.
     */
    public List<MessageResponse> findMessages(UUID userId, UUID botId, UUID conversationId) {
        throw new UnsupportedOperationException("ConversationLogService.findMessages 미구현 (W2)");
    }
}
