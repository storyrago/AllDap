package com.alldap.api.domain.eval.repository;

import com.alldap.api.domain.eval.entity.EvalResult;
import org.springframework.data.jpa.repository.EntityGraph;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

/**
 * eval_results 조회. 쓰기 소유자는 Python 이므로 save/delete 를 호출하지 말 것.
 */
public interface EvalResultRepository extends JpaRepository<EvalResult, Long> {

    /**
     * 실행 1회의 문항별 채점 결과.
     *
     * <p>화면이 문항마다 질문 원문과 정답을 함께 보여주므로 {@code question} 을
     * <b>같은 쿼리에서 함께 읽는다</b>. 그냥 조회하면 {@code EvalResult.question} 이 LAZY 라
     * 결과 건수만큼 질문 조회가 따로 나가는 N+1 이 된다.
     *
     * <p><b>실측(Hibernate {@code Statistics}): 문항 16건에 19번 → 3번.</b>
     * 3번은 봇 소유권 + 실행 소유권 + 결과 조회이고 문항 수와 무관하다.
     * {@code EvalIntegrationTest} 의 N+1 테스트가 이 수를 눌러둔다.
     *
     * <p><b>{@code @Query} 대신 {@code @EntityGraph} 를 쓴 이유:</b> 메서드 이름이 만들어주는
     * 조건과 정렬을 그대로 두고 <b>가져오는 방식만</b> 바꾸면 되기 때문이다.
     * JPQL 을 직접 쓰면 {@code run_id} 조건과 정렬까지 손으로 다시 적게 되고,
     * 그러면 메서드 이름과 쿼리가 어긋날 여지가 생긴다.
     *
     * <p>{@code question} 은 {@code @ManyToOne} 이라 조인해도 <b>행이 늘지 않는다.</b>
     * 컬렉션을 fetch join 할 때 생기는 중복 행이나 페이징 문제는 여기에 없다
     * (그래서 {@code distinct} 도, {@code Pageable} 주의사항도 필요 없다).
     */
    @EntityGraph(attributePaths = "question")
    List<EvalResult> findAllByRunIdOrderByCreatedAtAsc(Long runId);
}
