package com.alldap.api.domain.chat.repository;

import com.alldap.api.domain.chat.entity.Message;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.UUID;

public interface MessageRepository extends JpaRepository<Message, UUID> {

    /** 대화 상세 화면. 시간순으로 펼친다. */
    List<Message> findAllByConversationIdOrderByCreatedAtAsc(UUID conversationId);

    // TODO(W3): 품질 대시보드의 "미답변 목록"은 여기서 나온다.
    //   is_fallback = true 인 user 질문을 봇 단위로 모아 비슷한 것끼리 묶고 빈도를 센다.
    //   ⚠️ 이 데이터는 eval_* 테이블에 없다(프론트 타입 UnansweredQuestion 주석 참고).
    //      평가 실행 결과가 아니라 실사용 로그이므로 Spring 이 messages 를 집계해서 만들어야 한다.
    //      "비슷한 질문 묶기"를 무엇으로 할지(문자열 정규화 / 임베딩 클러스터링)는 아직 미정.
}
