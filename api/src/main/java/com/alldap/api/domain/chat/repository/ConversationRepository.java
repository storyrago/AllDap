package com.alldap.api.domain.chat.repository;

import com.alldap.api.domain.chat.entity.Conversation;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.Instant;
import java.util.Optional;

public interface ConversationRepository extends JpaRepository<Conversation, Long> {

    /**
     * 이어지는 대화를 찾기 위한 조회.
     *
     * <p>{@code (bot_id, session_id)} 인덱스가 이 조회를 위해 존재한다.
     * 같은 세션 키로 여러 행이 생길 수 있으므로(예: 오래된 세션 재사용) 최신 것을 쓴다.
     */
    Optional<Conversation> findFirstByBotIdAndSessionIdOrderByCreatedAtDesc(Long botId, String sessionId);

    /**
     * 위와 같지만 <b>channel 까지 맞춰</b> 찾는다. 실제 대화 이어붙이기는 이쪽을 쓴다.
     *
     * <p><b>channel 을 빼면 안 되는 이유.</b> sessionId 는 브라우저가 만들어 보내는 값이라
     * 관리자 테스트 화면과 위젯이 같은 값을 보낼 가능성이 0 이 아니다. 그때 channel 을 안 보면
     * 관리자가 돌려본 테스트 대화에 엔드유저 대화가 이어붙어 <b>한 대화 안에 두 채널이 섞인다.</b>
     * 품질 지표에서 테스트 대화를 제외하려고 channel 컬럼을 둔 것인데 그 구분이 무너진다.
     */
    Optional<Conversation> findFirstByBotIdAndSessionIdAndChannelOrderByCreatedAtDesc(
            Long botId, String sessionId, String channel);

    /**
     * 대화 로그 목록 ({@code GET /api/bots/{botId}/logs}). 필터는 전부 선택이다.
     *
     * <p><b>필터를 메서드 이름 규칙 대신 {@code @Query} 로 쓴 이유.</b>
     * "fallback 이 하나라도 있는 세션" 은 conversations 가 아니라 <b>messages 의 성질</b>이라
     * 파생 쿼리 이름으로는 표현할 방법이 없다. {@code EXISTS} 서브쿼리가 필요하다.
     *
     * <p><b>{@code EXISTS} 를 쓰고 조인하지 않는 이유.</b> 조인하면 메시지 수만큼 행이 불어나
     * {@code DISTINCT} 가 필요해지고, 그러면 페이지네이션의 {@code totalElements} 가 어긋난다.
     * {@code EXISTS} 는 "하나라도 있으면 참" 이라 대화 한 건이 한 행으로 유지된다.
     *
     * <p><b>기간 파라미터에 {@code IS NULL} 분기를 두지 않는다 (실패해보고 안 것).</b>
     * 처음에는 {@code (:from IS NULL OR c.createdAt >= :from)} 로 짰는데 Postgres 가
     * {@code ERROR: could not determine data type of parameter $4} 로 거절했다.
     * 파라미터가 {@code IS NULL} 비교에만 쓰이면 <b>DB 가 그 자리의 타입을 추론할 근거가 없기</b> 때문이다.
     * 해결은 캐스팅이 아니라 <b>조건을 없애는 것</b>이었다 — "필터 안 함" 을 서비스가
     * 아주 넓은 기간(EPOCH ~ 먼 미래)으로 바꿔 넘기면 여기서는 항상 값이 있는 비교만 남는다.
     * 조건이 두 개 줄어 쿼리도 더 단순해졌다.
     *
     * <p>{@code ORDER BY} 를 쿼리에 넣지 않는다 — {@link Pageable} 의 정렬과 충돌해
     * Hibernate 가 {@code ORDER BY} 를 두 번 붙인다. 기본 정렬은 컨트롤러가 지정한다.
     *
     * @param from 이 시각 <b>이상</b> (포함). 제한 없음은 서비스가 EPOCH 로 바꿔 넘긴다
     * @param to   이 시각 <b>미만</b> (제외). 날짜 → 시각 변환은 서비스가 한다
     */
    @Query("""
            SELECT c FROM Conversation c
            WHERE c.bot.id = :botId
              AND (:onlyFallback = false OR EXISTS (
                    SELECT 1 FROM Message m WHERE m.conversation = c AND m.isFallback = true))
              AND (:onlyThumbsDown = false OR EXISTS (
                    SELECT 1 FROM Message m WHERE m.conversation = c AND m.feedback = -1))
              AND c.createdAt >= :from
              AND c.createdAt < :to
            """)
    Page<Conversation> findLogs(@Param("botId") Long botId,
                                @Param("onlyFallback") boolean onlyFallback,
                                @Param("onlyThumbsDown") boolean onlyThumbsDown,
                                @Param("from") Instant from,
                                @Param("to") Instant to,
                                Pageable pageable);
}
