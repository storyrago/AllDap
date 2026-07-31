package com.alldap.api.domain.eval.repository;

import com.alldap.api.domain.eval.entity.EvalResult;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.UUID;

/**
 * eval_results 조회. 쓰기 소유자는 Python 이므로 save/delete 를 호출하지 말 것.
 */
public interface EvalResultRepository extends JpaRepository<EvalResult, UUID> {

    /**
     * 실행 1회의 문항별 채점 결과.
     *
     * <p>화면에서 질문 원문을 함께 보여줘야 하므로 EvalQuestion 을 fetch join 하는 편이 좋다.
     * 그냥 조회하면 결과 건수만큼 질문 조회 쿼리가 나가는 N+1 이 된다.
     * TODO(W3): @EntityGraph 또는 @Query 로 fetch join 을 적용할 것.
     */
    List<EvalResult> findAllByRunIdOrderByCreatedAtAsc(UUID runId);
}
