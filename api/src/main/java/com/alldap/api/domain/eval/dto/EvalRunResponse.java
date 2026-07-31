package com.alldap.api.domain.eval.dto;

import com.alldap.api.domain.eval.entity.EvalRun;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.UUID;

/**
 * 평가 실행 응답. 프론트의 {@code EvalRun}({@code web/lib/types.ts})과 맞춘다.
 *
 * <p>프론트 타입에서 {@code config} 는 {@code EvalConfig} 객체({@code topK}, {@code maxDistance} …)다.
 * 엔티티는 JSON 문자열로 들고 있으므로 여기서 파싱해 camelCase 객체로 바꿔야 한다.
 * TODO(W3): {@code EvalConfigResponse} record 를 만들고 ObjectMapper 로 변환할 것.
 *   Python 이 쓰는 키는 snake_case({@code top_k}, {@code max_distance})이므로
 *   그 record 에도 {@code @JsonProperty} 매핑이 필요하다. 지금은 원본 문자열을 그대로 둔다.
 */
public record EvalRunResponse(
        UUID id,
        String config,
        /** 충실성 평균 (0~1). NUMERIC(4,3) 이라 BigDecimal 이다. */
        BigDecimal avgFaithfulness,
        /** 관련성 평균 (0~1) */
        BigDecimal avgRelevancy,
        /** 응답률 (0~1) */
        BigDecimal answeredRate,
        /** running | completed | failed */
        String status,
        Instant createdAt
) {

    public static EvalRunResponse from(EvalRun run) {
        return new EvalRunResponse(
                run.getId(),
                run.getConfig(),
                run.getAvgFaithfulness(),
                run.getAvgRelevancy(),
                run.getAnsweredRate(),
                run.getStatus(),
                run.getCreatedAt()
        );
    }
}
