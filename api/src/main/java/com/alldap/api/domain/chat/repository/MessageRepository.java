package com.alldap.api.domain.chat.repository;

import com.alldap.api.domain.chat.entity.Message;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.Collection;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface MessageRepository extends JpaRepository<Message, UUID> {

    /** 대화 상세 화면. 시간순으로 펼친다. */
    List<Message> findAllByConversationIdOrderByCreatedAtAsc(UUID conversationId);

    /**
     * 메시지 → 대화 → 봇 → 소유자까지 <b>한 번의 쿼리로</b> 거슬러 올라간다.
     * {@code POST /api/messages/{msgId}/feedback} 은 경로에 botId 가 없어서 이게 필요하다.
     *
     * <p>{@code ConversationBotUser} 를 Spring Data 가 {@code message.conversation.bot.user.id} 로
     * 해석해 조인 세 번을 만들어준다. 봇·문서와 같은 규칙이다 —
     * <b>소유권을 검사하지 않고 조회 쿼리에 못박는다.</b>
     */
    Optional<Message> findByIdAndConversationBotUserId(UUID id, UUID userId);

    /**
     * 로그 목록 한 줄에 필요한 집계를 <b>대화 여러 건에 대해 한 번의 쿼리로</b> 가져온다.
     *
     * <p><b>이 메서드가 존재하는 이유가 N+1 방지다.</b> 목록에 20건이 있을 때
     * 대화마다 메시지를 조회하면 쿼리가 21번 나간다. 여기서는 페이지 크기와 무관하게 <b>1번</b>이다.
     *
     * <p><b>왜 네이티브 쿼리인가.</b> {@code firstUserMessage}(가장 이른 user 메시지 본문)를
     * JPQL 로는 표현할 수 없다. 아래 Postgres 문법이 필요하다.
     * <ul>
     *   <li>{@code bool_or(...)} — 하나라도 true 면 true. "이 세션에 fallback 이 있었나"</li>
     *   <li>{@code array_agg(... ORDER BY ...) FILTER (WHERE ...)} — user 메시지만 시간순으로 모은 뒤
     *       {@code [1]} 로 첫 번째를 꺼낸다. user 메시지가 없으면 배열이 비어 null 이 된다</li>
     * </ul>
     * 이 프로젝트는 이미 pgvector·JSONB·TEXT[] 로 Postgres 에 묶여 있어
     * 여기서 DB 중립성을 지켜봐야 얻는 것이 없다.
     *
     * <p><b>별칭에 큰따옴표를 쓴 이유.</b> Postgres 는 따옴표 없는 식별자를 소문자로 바꾼다.
     * {@code AS messageCount} 라고 쓰면 컬럼 라벨이 {@code messagecount} 가 되어
     * 프로젝션 인터페이스의 {@code getMessageCount()} 와 매칭되지 않는다.
     */
    @Query(value = """
            SELECT m.conversation_id AS "conversationId",
                   count(*)          AS "messageCount",
                   bool_or(m.is_fallback) AS "hasFallback",
                   (array_agg(m.content ORDER BY m.created_at)
                        FILTER (WHERE m.role = 'user'))[1] AS "firstUserMessage"
            FROM messages m
            WHERE m.conversation_id IN (:conversationIds)
            GROUP BY m.conversation_id
            """, nativeQuery = true)
    List<ConversationAggregate> aggregateByConversationIds(
            @Param("conversationIds") Collection<UUID> conversationIds);

    /**
     * <b>미답변 질문 집계</b> — 사용자가 물었는데 봇이 근거를 못 찾아 거절한 질문들.
     *
     * <p>관리자에게 <b>"이 내용을 문서에 추가하세요"</b> 를 알려주는 것이 목적이다.
     * 품질 대시보드가 "지금 얼마나 좋은가"라면 이건 "무엇이 비어 있나"다.
     *
     * <h2>🔴 fallback 과 "답변 행이 아예 없음" 을 반드시 갈라야 한다</h2>
     * AGENTS.md 가 이 집계를 위해 미리 남긴 경고다:
     * <blockquote>Python 호출이 실패하면 <b>질문만 남고 답변 행이 없다.</b>
     * 이건 fallback 과 다른 상태다 — 미답변을 집계할 때 섞지 말 것.</blockquote>
     *
     * <ul>
     *   <li><b>fallback</b> = 물어봤고 답했는데 "문서에 없다" 였다 → <b>진짜 미답변.</b> 여기서 센다</li>
     *   <li><b>답변 행 없음</b> = 우리 인프라가 실패해 <b>물어보지도 못했다</b> → 다른 사실. 따로 센다
     *       ({@link #countFailedTurns})</li>
     * </ul>
     * 둘을 합치면 "우리 서버가 죽은 날"이 "문서가 부실한 날"로 둔갑한다.
     *
     * <p>같은 문장을 GROUP BY 로 묶어 횟수를 센다. <b>비슷한 질문</b>(표현만 다른 것)을 묶으려면
     * 임베딩이 필요하고 그건 Python 의 일이 된다 — 지금은 <b>정확히 같은 문장만</b> 묶는다.
     *
     * <p>⚠️ 관리자 테스트 채팅({@code channel='test'})도 함께 집계한다.
     * 거기서 난 fallback 도 "문서에 없다"는 신호는 맞기 때문이다. 화면이 그 사실을 안내한다.
     */
    @Query(value = """
            WITH turns AS (
                SELECT m.content,
                       m.created_at,
                       -- 같은 대화에서 이 질문 <다음>에 온 첫 assistant 메시지의 fallback 여부.
                       -- 행이 없으면 NULL 이고, 그건 "답변을 못 받았다"는 뜻이다(아래 WHERE 참고).
                       (SELECT a.is_fallback
                          FROM messages a
                         WHERE a.conversation_id = m.conversation_id
                           AND a.role = 'assistant'
                           AND a.created_at > m.created_at
                         ORDER BY a.created_at
                         LIMIT 1) AS answered_with_fallback
                  FROM messages m
                  JOIN conversations c ON c.id = m.conversation_id
                 WHERE c.bot_id = :botId
                   AND m.role = 'user'
            )
            SELECT content                 AS "question",
                   count(*)                AS "count",
                   max(created_at)         AS "lastAskedAt"
              FROM turns
             -- IS TRUE 를 쓴다. `= true` 로 두면 NULL(답변 행 없음)이 조용히 빠지는 것은 같지만,
             -- <의도가 코드에 안 드러난다.> 여기서 NULL 을 빼는 것은 실수가 아니라 결정이다.
             WHERE answered_with_fallback IS TRUE
             GROUP BY content
             -- 자주 물어본 것부터. 같으면 최근 것부터 — 관리자가 위에서부터 처리하면 된다.
             ORDER BY count(*) DESC, max(created_at) DESC
             LIMIT :limit
            """, nativeQuery = true)
    List<UnansweredAggregate> aggregateUnanswered(@Param("botId") UUID botId,
                                                  @Param("limit") int limit);

    /** {@link #aggregateUnanswered} 의 결과 한 줄. */
    interface UnansweredAggregate {
        String getQuestion();
        long getCount();
        java.time.Instant getLastAskedAt();
    }

    /**
     * <b>답변 행이 아예 없는 질문 수</b> — 미답변이 아니라 <b>처리 실패</b>다.
     *
     * <p>Python 이 죽었거나 타임아웃이라 <b>물어보지도 못한</b> 경우다.
     * 이걸 미답변에 섞으면 "우리 서버가 죽은 날"이 "문서가 부실한 날"로 둔갑한다.
     * 그래서 따로 세서 화면이 별도로 안내한다.
     */
    @Query(value = """
            SELECT count(*)
              FROM messages m
              JOIN conversations c ON c.id = m.conversation_id
             WHERE c.bot_id = :botId
               AND m.role = 'user'
               AND NOT EXISTS (
                   SELECT 1 FROM messages a
                    WHERE a.conversation_id = m.conversation_id
                      AND a.role = 'assistant'
                      AND a.created_at > m.created_at
               )
            """, nativeQuery = true)
    long countFailedTurns(@Param("botId") UUID botId);

    /**
     * 위 집계 쿼리의 결과 한 줄.
     *
     * <p>인터페이스로 두면 스프링 데이터가 구현체를 만들어준다(프로젝션).
     * 별도 클래스를 만들 필요도, {@code Object[]} 를 인덱스로 꺼내 쓸 필요도 없다.
     */
    interface ConversationAggregate {
        UUID getConversationId();

        long getMessageCount();

        boolean getHasFallback();

        /** user 메시지가 하나도 없으면 null */
        String getFirstUserMessage();
    }

    // TODO(W3): 품질 대시보드의 "미답변 목록"은 여기서 나온다.
    //   is_fallback = true 인 user 질문을 봇 단위로 모아 비슷한 것끼리 묶고 빈도를 센다.
    //   ⚠️ 이 데이터는 eval_* 테이블에 없다(프론트 타입 UnansweredQuestion 주석 참고).
    //      평가 실행 결과가 아니라 실사용 로그이므로 Spring 이 messages 를 집계해서 만들어야 한다.
    //      "비슷한 질문 묶기"를 무엇으로 할지(문자열 정규화 / 임베딩 클러스터링)는 아직 미정.
}
