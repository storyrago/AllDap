package com.alldap.api.domain.eval.repository;

import com.alldap.api.domain.eval.entity.EvalRun;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

/**
 * eval_runs 조회. 쓰기 소유자는 Python 이므로 save/delete 를 호출하지 말 것.
 */
public interface EvalRunRepository extends JpaRepository<EvalRun, Long> {

    /** 평가 이력 목록 (최신순). W4 의 before/after 비교표가 이 목록에서 나온다. */
    List<EvalRun> findAllByBotIdOrderByCreatedAtDesc(Long botId);

    /** 봇 카드에 보여줄 "가장 최근 평가 점수" 용. */
    Optional<EvalRun> findFirstByBotIdOrderByCreatedAtDesc(Long botId);

    Optional<EvalRun> findByIdAndBotId(Long id, Long botId);
}
