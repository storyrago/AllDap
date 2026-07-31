package com.alldap.api.domain.chat.repository;

import com.alldap.api.domain.chat.entity.Conversation;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;
import java.util.UUID;

public interface ConversationRepository extends JpaRepository<Conversation, UUID> {

    /**
     * 이어지는 대화를 찾기 위한 조회.
     *
     * <p>{@code (bot_id, session_id)} 인덱스가 이 조회를 위해 존재한다.
     * 같은 세션 키로 여러 행이 생길 수 있으므로(예: 오래된 세션 재사용) 최신 것을 쓴다.
     */
    Optional<Conversation> findFirstByBotIdAndSessionIdOrderByCreatedAtDesc(UUID botId, String sessionId);

    /** 대화 로그 목록 (GET /api/bots/{botId}/logs) */
    Page<Conversation> findAllByBotIdOrderByCreatedAtDesc(UUID botId, Pageable pageable);

    // TODO(W2): 로그 화면의 필터(fallback 포함 / 👎 포함 / 기간)는 messages 를 조인해야 한다.
    //   메서드 이름 규칙으로는 표현이 어려우므로 @Query 또는 Specification 으로 만들 것.
    //   목록 한 줄에 필요한 messageCount·hasFallback·firstUserMessage 를 대화 건수만큼 따로 조회하면
    //   전형적인 N+1 이 된다. group by 로 한 번에 가져오는 프로젝션 쿼리를 쓸 것.
}
