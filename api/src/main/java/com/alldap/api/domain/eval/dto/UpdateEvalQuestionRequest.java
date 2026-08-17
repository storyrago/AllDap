package com.alldap.api.domain.eval.dto;

import jakarta.validation.constraints.Size;

/**
 * 테스트 질문 수정 요청 (공개 API). 셋 다 선택적이다 — 보낸 것만 바뀐다.
 *
 * <p><b>왜 {@code Boolean} 인가(원시 타입 {@code boolean} 이 아니라).</b>
 * 원시 타입은 안 보내면 {@code false} 가 되어, <b>"안 보냈다"와 "false 로 바꿔달라"가
 * 같은 값으로 뭉개진다.</b> 그러면 질문 문장만 고치려던 요청이 문항을 비활성화해버린다.
 * 래퍼 타입이라야 null(안 보냄)과 false(끄기)를 구분할 수 있다.
 *
 * <p>🔴 <b>{@code groundTruth} 를 고치면 과거 실행과 비교할 수 없게 된다.</b>
 * {@code eval_results} 는 그때의 정답으로 채점된 값이다. 채점 기준을 바꿔놓고 이전 숫자와
 * 나란히 놓으면 설정 때문인지 기준 때문인지 구분할 수 없다.
 * 문항이 마음에 안 들면 고치기보다 {@code isActive=false} 로 빼는 편이 안전하다.
 *
 * @param question    질문 문장
 * @param groundTruth 정답 — 채점 기준이다
 * @param isActive    false 면 앞으로의 평가에서 제외한다 (지우지는 않는다)
 */
public record UpdateEvalQuestionRequest(
        @Size(min = 1, max = 500, message = "질문은 1~500자로 입력해주세요.")
        String question,

        @Size(min = 1, max = 2000, message = "정답은 1~2000자로 입력해주세요.")
        String groundTruth,

        Boolean isActive
) {
    /** 아무것도 안 보냈는가. 그렇다면 "고쳤다"는 오해를 주지 않도록 400 으로 막는다. */
    public boolean isEmpty() {
        return question == null && groundTruth == null && isActive == null;
    }
}
