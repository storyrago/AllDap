package com.alldap.api.domain.eval.dto;

import com.alldap.api.domain.eval.entity.EvalResult;

import java.math.BigDecimal;
import java.util.UUID;

/**
 * 질문 하나의 채점 결과. 프론트의 {@code EvalResult}({@code web/lib/types.ts})와 맞춘다.
 *
 * <p><b>{@code faithfulness}/{@code relevancy} 가 null 이면 "채점하지 못했다"이지 0점이 아니다.</b>
 * 두 경우가 있다:
 * <ul>
 *   <li>답변이 fallback 이라 <b>채점 대상이 아니었다</b> — "모르겠다"를 1.0 으로 세면 평균이
 *       거짓말이 되고, 0 으로 세면 정직한 거절이 벌점이 된다. 그래서 응답률로만 센다.</li>
 *   <li>채점 호출 자체가 실패했다 — 이걸 0 으로 처리하면 <b>채점 실패가 품질 저하로 둔갑</b>한다.</li>
 * </ul>
 * 화면은 이 둘을 "—" 처럼 <b>점수 아닌 표시</b>로 그려야 한다.
 *
 * <p>{@code retrievedChunks} 를 함께 주는 이유: 점수가 낮을 때 원인이
 * "검색이 엉뚱한 걸 가져왔다"인지 "근거는 맞는데 생성이 틀렸다"인지 구분해야 하기 때문이다.
 * 이 구분이 W4 에서 <b>무엇을 고칠지</b>를 결정한다.
 * JSON 원문 그대로 내보낸다 — 구조가 Python 소관이라 Spring 이 record 로 못박으면
 * Python 이 필드를 하나 추가할 때마다 값을 잃는다.
 */
public record EvalResultResponse(
        UUID id,
        UUID questionId,
        String question,
        String groundTruth,
        String generatedAnswer,
        /** 이 답변이 참고한 청크 스냅샷 (JSON 원문) */
        String retrievedChunks,
        BigDecimal faithfulness,
        BigDecimal relevancy
) {

    public static EvalResultResponse from(EvalResult result) {
        return new EvalResultResponse(
                result.getId(),
                result.getQuestion().getId(),
                result.getQuestion().getQuestion(),
                result.getQuestion().getGroundTruth(),
                result.getGeneratedAnswer(),
                result.getRetrievedChunks(),
                result.getFaithfulness(),
                result.getRelevancy()
        );
    }
}
