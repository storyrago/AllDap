package com.alldap.api.domain.bot.repository;

import com.alldap.api.domain.bot.entity.Bot;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.Optional;

public interface BotRepository extends JpaRepository<Bot, Long> {

    /** 위젯 공개 API 진입점. publicKey 하나로 봇을 찾는다. */
    Optional<Bot> findByPublicKey(String publicKey);

    /** 대시보드 봇 목록. */
    List<Bot> findAllByUserIdOrderByCreatedAtDesc(Long userId);

    /**
     * 소유권까지 함께 검사하는 조회.
     *
     * <p>{@code findById} 로 가져와 나중에 소유자를 비교하는 방식은
     * 검사를 빠뜨리기 쉽다. 조회 자체를 소유자로 좁히면 봇 간 데이터 유출
     * (CLAUDE.md "bot_id 스코프 격리")을 구조적으로 막을 수 있다.
     */
    Optional<Bot> findByIdAndUserId(Long id, Long userId);

    /**
     * 봇 카드(PRD §8)에 얹을 집계를 <b>내 봇 전부에 대해 한 번의 쿼리로</b> 가져온다.
     *
     * <p><b>이 메서드가 존재하는 이유가 N+1 방지다.</b> 봇마다 문서·대화·평가를 세면
     * 봇이 N개일 때 쿼리가 3N+1 번 나간다. 여기서는 봇 개수와 무관하게 <b>1번</b>이고,
     * 목록 조회와 합쳐 총 2번으로 고정된다 (대화 로그 목록과 같은 방식).
     *
     * <p><b>소유권을 검사하지 않고 쿼리에 못박는다</b>({@code b.user_id = :userId}).
     * 봇 id 목록을 받아 {@code IN} 으로 거는 방식도 가능하지만, 그러면 호출부가
     * 소유권을 이미 확인했다는 <b>가정</b>에 기대게 된다. 여기서 다시 좁히면
     * 남의 봇 숫자가 카드에 섞여 나오는 경로가 구조적으로 없다
     * (AGENTS.md "bot_id 스코프 격리").
     *
     * <p><b>왜 JOIN 이 아니라 스칼라 서브쿼리 셋인가.</b> 서로 다른 세 테이블을 한 번에
     * 조인하면 행이 곱해져(문서 3개 × 대화 5개 = 15행) 집계가 부풀어 오른다.
     * {@code count(DISTINCT ...)} 로 막을 수는 있지만 그건 부푼 것을 사후에 걷어내는 것이고,
     * 봇당 한 값을 돌려주는 스칼라 서브쿼리는 애초에 부풀지 않는다.
     *
     * <p><b>documents · eval_runs 는 Python 이 쓰는 테이블이라 읽기만 한다</b>
     * (AGENTS.md 테이블 소유권).
     *
     * <p>별칭에 큰따옴표를 쓴 이유는 {@code MessageRepository.aggregateByConversationIds} 와 같다.
     * 따옴표가 없으면 Postgres 가 컬럼 라벨을 소문자로 바꿔 프로젝션 게터와 매칭되지 않는다.
     *
     * @param since 주간 대화 수의 시작 경계. 이 시각 <b>이후</b>에 시작된 대화만 센다
     */
    @Query(value = """
            SELECT b.id AS "botId",
                   (SELECT count(*) FROM documents d
                     WHERE d.bot_id = b.id) AS "documentCount",
                   (SELECT count(*) FROM conversations c
                     WHERE c.bot_id = b.id
                       AND c.created_at >= :since) AS "weeklyConversationCount",
                   -- 전체 충실성 = avg_faithfulness × scored_count / question_count.
                   -- 평균(avg_faithfulness)을 그대로 쓰면 답을 덜 할수록 올라간다(생존 편향).
                   -- 계산할 수 없는 실행은 아예 고르지 않는다 (0 으로 채우면 "모른다"가 "0점"이 된다).
                   (SELECT round(r.avg_faithfulness * r.scored_count / r.question_count, 3)
                      FROM eval_runs r
                     WHERE r.bot_id = b.id
                       AND r.status = 'completed'
                       AND r.avg_faithfulness IS NOT NULL
                       AND r.scored_count IS NOT NULL
                       AND r.question_count > 0
                     ORDER BY r.created_at DESC
                     LIMIT 1) AS "latestOverallFaithfulness"
              FROM bots b
             WHERE b.user_id = :userId
            """, nativeQuery = true)
    List<BotMetrics> aggregateMetrics(@Param("userId") Long userId, @Param("since") Instant since);

    /**
     * {@link #aggregateMetrics} 결과 한 줄. 인터페이스로 두면 Spring Data 가 구현체를 만들어준다.
     */
    interface BotMetrics {
        Long getBotId();

        long getDocumentCount();

        long getWeeklyConversationCount();

        /** 평가를 한 번도 완주하지 못했으면 null. NUMERIC 이라 BigDecimal 이다. */
        BigDecimal getLatestOverallFaithfulness();
    }
}
