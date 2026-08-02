package com.alldap.api.domain.eval.dto;

import jakarta.validation.constraints.Min;

/**
 * 테스트 질문 자동 생성 요청. 프론트의 {@code generateQuestions(botId, count)} 와 맞춘다.
 *
 * <p><b>상한을 여기에 두지 않는 이유.</b> 상한은 Python 의 설정값
 * ({@code eval_max_questions}, 기본 20)이고, Spring 에 숫자를 복제하면 두 곳이 반드시 어긋난다.
 * 그때 "Spring 은 통과시켰는데 Python 이 거절"이 되고, 사용자는 왜 거절됐는지 모른다.
 * 업로드에서 확장자 목록을 복제하지 않은 것과 같은 판단이다.
 *
 * <p>대신 하한만 막는다 — 0 이나 음수는 <b>어떤 설정에서도 무의미</b>하고,
 * 여기서 막으면 왕복 한 번을 아낀다.
 */
public record GenerateQuestionsRequest(
        @Min(value = 1, message = "질문은 1개 이상 만들어야 합니다.")
        Integer count
) {

    /** 프론트가 개수를 안 보내면 10개. 화면에서 매번 고르게 하지 않으려는 기본값이다. */
    private static final int DEFAULT_COUNT = 10;

    public int countOrDefault() {
        return count == null ? DEFAULT_COUNT : count;
    }
}
