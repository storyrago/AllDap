package com.alldap.api.domain.usage.repository;

import com.alldap.api.domain.usage.entity.UsageEvent;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.Instant;
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

    /**
     * 완료된 평가 실행을 원장에 <메꾼다>. 이미 있는 것은 건너뛴다.
     *
     * <p><b>왜 메꾸는가 — 기록 시점을 우리가 정할 수 없기 때문이다.</b>
     * 평가 실행이 끝나는 것은 <b>Python 이 안다</b>({@code eval_runs.status} 를 Python 이 갱신한다).
     * 그런데 과금은 Spring 소유다. Python 이 {@code usage_events} 에 쓰면
     * 테이블 소유권 원칙이 깨진다(AGENTS.md 소유권 표).
     *
     * <p><b>왜 폴링에 얹지 않는가.</b> 화면이 실행 상태를 폴링하니 거기서 기록할 수도 있지만,
     * 그러면 <b>아무도 대시보드를 안 열면 계량이 안 된다.</b> 조회 직전에 한 번 도는 쪽이 안전하다.
     *
     * <p>🔴 {@code occurred_at} 이 {@code r.created_at} 인 것이 중요하다. <b>메꾼 시각이 아니라
     * 실행이 시작된 시각</b>이 청구 기간을 가른다. 8월 31일에 시작한 실행을 9월에 메꿨다고
     * 9월분으로 청구하면 안 된다.
     *
     * <p>{@code ON CONFLICT DO NOTHING} 이 멱등성의 전부다 — 몇 번을 돌려도 결과가 같다.
     *
     * <p>{@code b.user_id IS NOT NULL} — 사실 <b>이 쿼리에서는 중복이다.</b> 바로 위
     * {@code WHERE b.user_id = :userId} 가 이미 {@code user_id IS NULL} 인 행을 걸러낸다
     * (SQL 에서 {@code NULL = x} 는 UNKNOWN 이라 그런 행은 절대 매치되지 않는다).
     * {@link #recordChatAnswer} 에는 사용자 동등 조건이 없어 이 가드가 진짜 방어선이지만,
     * 여기서는 그 코드와 <b>짝을 맞추고</b>, 나중에 이 {@code WHERE} 절이
     * (예: 전 계정을 훑는 일괄 메꾸기로) 바뀌어도 안전하도록 남겨둔 것뿐이다.
     */
    @Modifying
    @Query(value = """
            INSERT INTO usage_events (user_id, bot_id, kind, source_ref, occurred_at)
            SELECT b.user_id, r.bot_id, 'eval_run', r.id, r.created_at
              FROM eval_runs r
              JOIN bots b ON b.id = r.bot_id
             WHERE b.user_id = :userId
               AND b.user_id IS NOT NULL
               AND r.status = 'completed'
            ON CONFLICT (kind, source_ref) DO NOTHING
            """, nativeQuery = true)
    int backfillEvalRuns(@Param("userId") UUID userId);

    /**
     * 기간 안의 사건 수. <b>경계는 왼쪽 포함 · 오른쪽 제외</b>({@code >= from}, {@code < to})다.
     * 양쪽을 포함하면 8월 마지막 순간과 9월 첫 순간이 <b>양쪽 달에 모두</b> 세어진다.
     */
    @Query("""
            SELECT count(e) FROM UsageEvent e
             WHERE e.userId = :userId
               AND e.kind = :kind
               AND e.occurredAt >= :from
               AND e.occurredAt < :to
            """)
    long countInPeriod(@Param("userId") UUID userId,
                       @Param("kind") String kind,
                       @Param("from") Instant from,
                       @Param("to") Instant to);
}
