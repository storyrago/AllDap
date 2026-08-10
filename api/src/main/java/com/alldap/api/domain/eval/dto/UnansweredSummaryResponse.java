package com.alldap.api.domain.eval.dto;

import java.util.List;

/**
 * 미답변 집계 결과.
 *
 * <h2>🔴 왜 배열이 아니라 객체인가</h2>
 * {@code failedTurns} 를 함께 내려야 하기 때문이다.
 *
 * <p>AGENTS.md 가 이 집계를 위해 미리 남긴 경고가 있다 —
 * <blockquote>Python 호출이 실패하면 <b>질문만 남고 답변 행이 없다.</b>
 * 이건 fallback 과 다른 상태다 — 미답변을 집계할 때 섞지 말 것.</blockquote>
 *
 * <p>섞지 않는 것만으로는 부족하다. <b>따로 보여줘야 한다.</b>
 * 목록만 주면 화면은 "미답변 0건 = 문서가 충분하다"로 읽는데,
 * 실제로는 "그날 Python 이 죽어서 아무것도 못 물어봤다" 일 수 있다.
 * <b>"없어서 0"과 "못 재서 0"은 다른 사실이다</b> — 이 프로젝트가 그 부류의 버그를 네 번 냈다.
 *
 * @param items       거절당한 질문들 (자주 물어본 순)
 * @param failedTurns 답변 행이 아예 없는 질문 수. <b>미답변이 아니라 우리 인프라의 실패다</b>
 */
public record UnansweredSummaryResponse(
        List<UnansweredQuestionResponse> items,
        long failedTurns
) {
}
