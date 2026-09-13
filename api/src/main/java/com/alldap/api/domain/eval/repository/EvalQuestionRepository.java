package com.alldap.api.domain.eval.repository;

import com.alldap.api.domain.eval.entity.EvalQuestion;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;

/**
 * eval_questions 조회. 쓰기 소유자는 Python 이므로 save/delete 를 호출하지 말 것.
 */
public interface EvalQuestionRepository extends JpaRepository<EvalQuestion, Long> {

    List<EvalQuestion> findAllByBotIdOrderByCreatedAtDesc(Long botId);

    /**
     * 활성 질문만.
     *
     * <p>메서드 이름 규칙 대신 JPQL 을 쓴 이유: 필드명이 {@code isActive} 라
     * {@code findAllByBotIdAndIsActiveTrue...} 로 쓰면 이름 파서가 {@code Is} 를 키워드로 볼지
     * 프로퍼티 이름의 일부로 볼지 애매해진다. 애매한 규칙보다 명시적인 쿼리가 낫다.
     */
    @Query("select q from EvalQuestion q where q.bot.id = :botId and q.isActive = true order by q.createdAt desc")
    List<EvalQuestion> findActiveByBotId(@Param("botId") Long botId);
}
