package com.alldap.api.domain.usage.repository;

import com.alldap.api.domain.usage.entity.UsageEvent;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.UUID;

public interface UsageEventRepository extends JpaRepository<UsageEvent, UUID> {

    /**
     * 위젯 답변 하나를 계량한다. <b>과금 정책 전체가 이 한 문장 안에 있다.</b>
     *
     * <p>이 문장이 동시에 네 가지를 한다.
     * <ol>
     *   <li><b>청구 대상 해결</b> — 위젯 채팅에는 로그인한 사용자가 없다.
     *       대화 → 봇 → 주인으로 거슬러 올라가 <b>봇의 주인</b>을 찾는다</li>
     *   <li><b>테스트 채팅 제외</b> — {@code channel='test'} 면 SELECT 가 0행이라 아무것도 안 들어간다</li>
     *   <li><b>fallback 제외</b> — 같은 방식으로 0행이 된다</li>
     *   <li><b>원자성</b> — 호출부가 답변 저장과 같은 트랜잭션이라
     *       "답변은 남았는데 계량이 안 된" 상태가 존재할 수 없다</li>
     * </ol>
     *
     * <p>🔴 <b>두 제외 조건을 모두 SQL 안에 둔 것이 핵심이다.</b> 호출부에
     * {@code if (isFallback) return;} 을 두고 채널만 여기서 거르면 <b>과금 정책이
     * Java 와 SQL 두 곳으로 나뉜다.</b> 규칙이 두 곳에 있으면 한쪽만 고쳐진다.
     * <b>"무엇이 과금되는가" 를 알고 싶으면 이 문장 하나만 읽으면 된다.</b>
     *
     * @return 삽입된 행 수. 과금 대상이 아니면 0 이다(정상이며 오류가 아니다)
     */
    @Modifying
    @Query(value = """
            INSERT INTO usage_events (user_id, bot_id, kind, source_ref, occurred_at)
            SELECT b.user_id, c.bot_id, 'chat_answer', :messageId, now()
              FROM conversations c
              JOIN bots b ON b.id = c.bot_id
             WHERE c.id = :conversationId
               AND c.channel = 'widget'
               AND :isFallback = false
            """, nativeQuery = true)
    int recordChatAnswer(@Param("messageId") UUID messageId,
                         @Param("conversationId") UUID conversationId,
                         @Param("isFallback") boolean isFallback);
}
