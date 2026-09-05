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
     * 채널·계정 조건은 이 문장 안에서 전부 끝난다 — 다만 {@code isFallback} 은
     * 호출부({@link com.alldap.api.domain.chat.service.ChatTurnStore#saveAnswer})가
     * 건네는 Java 값이고, {@code messages.is_fallback} 에 쓰는 값과 같은 것을 그대로 쓴다.
     *
     * <p>{@code b.user_id IS NOT NULL} — 주인 없는 봇(V1 시드 {@code pk_local_dev} 등)은
     * 청구할 계정이 없다. 그대로 두면 {@code usage_events.user_id NOT NULL} 제약에 걸려
     * 답변 저장 트랜잭션 전체가 롤백된다 — fallback 이 아닌 정상 답변만 이 경로를 타므로
     * "봇이 제대로 답할 때만 500" 이라는 알아채기 어려운 형태로 터진다.
     *
     * <p>{@code ON CONFLICT ... DO NOTHING} — {@code uq_usage_source} 제약은 두 번째
     * 쓰기를 <b>거부</b>할 뿐 저절로 무시해주지 않는다. 평가 실행 메꾸기가 조회마다
     * 같은 {@code source_ref} 로 재시도하므로, 이게 없으면 두 번째 조회에서 예외가 난다.
     *
     * @return 삽입된 행 수. 과금 대상이 아니거나(fallback·테스트 채팅·주인 없는 봇)
     *         <b>이미 계량된 사건</b>이면 0 이다 — 둘 다 정상이며 오류가 아니다
     */
    @Modifying
    @Query(value = """
            INSERT INTO usage_events (user_id, bot_id, kind, source_ref, occurred_at)
            SELECT b.user_id, c.bot_id, 'chat_answer', :messageId, now()
              FROM conversations c
              JOIN bots b ON b.id = c.bot_id
             WHERE c.id = :conversationId
               AND c.channel = 'widget'
               AND b.user_id IS NOT NULL
               AND :isFallback = false
            ON CONFLICT (kind, source_ref) DO NOTHING
            """, nativeQuery = true)
    int recordChatAnswer(@Param("messageId") UUID messageId,
                         @Param("conversationId") UUID conversationId,
                         @Param("isFallback") boolean isFallback);
}
