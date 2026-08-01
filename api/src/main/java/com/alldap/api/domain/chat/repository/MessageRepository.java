package com.alldap.api.domain.chat.repository;

import com.alldap.api.domain.chat.entity.Message;
import org.springframework.data.jpa.repository.JpaRepository;

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

    // TODO(W3): 품질 대시보드의 "미답변 목록"은 여기서 나온다.
    //   is_fallback = true 인 user 질문을 봇 단위로 모아 비슷한 것끼리 묶고 빈도를 센다.
    //   ⚠️ 이 데이터는 eval_* 테이블에 없다(프론트 타입 UnansweredQuestion 주석 참고).
    //      평가 실행 결과가 아니라 실사용 로그이므로 Spring 이 messages 를 집계해서 만들어야 한다.
    //      "비슷한 질문 묶기"를 무엇으로 할지(문자열 정규화 / 임베딩 클러스터링)는 아직 미정.
}
