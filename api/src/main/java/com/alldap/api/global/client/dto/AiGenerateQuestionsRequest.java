package com.alldap.api.global.client.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Python 의 {@code GenerateQuestionsRequest} — {@code { count }}.
 *
 * <p>상한 검사는 <b>Python 이 한다</b>({@code eval_max_questions}, 기본 20).
 * Spring 에 숫자를 복제하지 않는 이유는 업로드의 확장자 목록과 같다 —
 * 두 곳에 두면 반드시 어긋나고, 그때 "Spring 은 통과시켰는데 Python 이 거절"이 된다.
 * 다만 초과했을 때 나오는 Python 의 한국어 안내("한 번에 만들 수 있는 질문은 최대 N개입니다…")는
 * 사용자에게 그대로 전달해야 한다({@code AiServiceClient} 의 eval 4xx 매퍼).
 */
public record AiGenerateQuestionsRequest(
        @JsonProperty("count") int count
) {
}
