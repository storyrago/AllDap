package com.alldap.api.domain.eval.dto;

import com.alldap.api.domain.eval.entity.EvalResult;

import java.math.BigDecimal;
import java.util.List;

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
 *
 * <p>JSON 문자열이 아니라 <b>파싱된 목록</b>으로 내려보낸다.
 * {@code MessageResponse.sources} 와 같은 방식이다 — 프론트가 문자열을 다시 파싱하게 만들면
 * 그 파싱 규칙이 두 벌(서버·클라이언트)이 되고, 언젠가 어긋난다.
 * 파싱은 서비스가 하고 <b>실패해도 예외를 던지지 않는다</b>:
 * 결과 한 건의 JSON 이 깨졌다고 리포트 전체가 500 이 되면 안 된다.
 */
public record EvalResultResponse(
        Long id,
        Long questionId,
        String question,
        String groundTruth,
        String generatedAnswer,
        /** 이 답변이 참고한 청크 스냅샷. 파싱 실패 시 빈 목록. */
        List<EvalRetrievedChunkResponse> retrievedChunks,
        BigDecimal faithfulness,
        BigDecimal relevancy
) {

    public static EvalResultResponse from(EvalResult result, List<EvalRetrievedChunkResponse> chunks) {
        return new EvalResultResponse(
                result.getId(),
                result.getQuestion().getId(),
                result.getQuestion().getQuestion(),
                result.getQuestion().getGroundTruth(),
                result.getGeneratedAnswer(),
                chunks,
                result.getFaithfulness(),
                result.getRelevancy()
        );
    }
}
