package com.alldap.api.domain.eval.dto;

import com.alldap.api.domain.chat.repository.MessageRepository.UnansweredAggregate;

import java.time.Instant;

/**
 * 봇이 근거를 못 찾아 거절한 질문 1건.
 *
 * <p>관리자에게 <b>"이 내용을 문서에 추가하세요"</b> 를 알려주는 것이 목적이다.
 *
 * @param question    같은 문장끼리 묶은 대표 질문
 * @param count       같은 문장이 몇 번 들어왔는지
 * @param suggestion  "이런 문서를 추가하세요" 류의 제안. <b>지금은 항상 null 이다</b> —
 *                    만들려면 LLM 을 불러야 하는데, 목록을 여는 것만으로 비용이 나가면 안 된다.
 *                    프론트 타입도 {@code string | null} 로 약속돼 있다(web/lib/types.ts).
 */
public record UnansweredQuestionResponse(
        String question,
        long count,
        Instant lastAskedAt,
        String suggestion
) {
    public static UnansweredQuestionResponse from(UnansweredAggregate a) {
        return new UnansweredQuestionResponse(a.getQuestion(), a.getCount(), a.getLastAskedAt(), null);
    }
}
