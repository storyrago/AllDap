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

    /**
     * 위와 같지만 <b>channel 까지 맞춰</b> 찾는다. 실제 대화 이어붙이기는 이쪽을 쓴다.
     *
     * <p><b>channel 을 빼면 안 되는 이유.</b> sessionId 는 브라우저가 만들어 보내는 값이라
     * 관리자 테스트 화면과 위젯이 같은 값을 보낼 가능성이 0 이 아니다. 그때 channel 을 안 보면
     * 관리자가 돌려본 테스트 대화에 엔드유저 대화가 이어붙어 <b>한 대화 안에 두 채널이 섞인다.</b>
     * 품질 지표에서 테스트 대화를 제외하려고 channel 컬럼을 둔 것인데 그 구분이 무너진다.
     */
    Optional<Conversation> findFirstByBotIdAndSessionIdAndChannelOrderByCreatedAtDesc(
            UUID botId, String sessionId, String channel);

    /** 대화 로그 목록 (GET /api/bots/{botId}/logs) */
    Page<Conversation> findAllByBotIdOrderByCreatedAtDesc(UUID botId, Pageable pageable);

    // TODO(W2): 로그 화면의 필터(fallback 포함 / 👎 포함 / 기간)는 messages 를 조인해야 한다.
    //   메서드 이름 규칙으로는 표현이 어려우므로 @Query 또는 Specification 으로 만들 것.
    //   목록 한 줄에 필요한 messageCount·hasFallback·firstUserMessage 를 대화 건수만큼 따로 조회하면
    //   전형적인 N+1 이 된다. group by 로 한 번에 가져오는 프로젝션 쿼리를 쓸 것.
}
