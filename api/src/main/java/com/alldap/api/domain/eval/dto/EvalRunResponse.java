package com.alldap.api.domain.eval.dto;

import com.alldap.api.domain.eval.entity.EvalRun;
import com.alldap.api.global.client.dto.AiEvalRunResponse;
import tools.jackson.databind.ObjectMapper;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.UUID;

/**
 * 평가 실행 응답. 프론트의 {@code EvalRun}({@code web/lib/types.ts})과 맞춘다.
 *
 * <p><b>점수 세 개가 전부 null 을 허용한다.</b> {@code status='running'} 이면 아직 안 나왔고,
 * 답변이 전부 fallback 이거나 채점에 전부 실패하면 평균을 낼 대상이 없다.
 * 0 으로 채우면 <b>"아직 없음"과 "0점"이 구분되지 않아</b> 화면이 거짓말을 하게 된다.
 *
 * <p>{@code config} 는 {@link EvalConfigResponse} 객체다. 엔티티는 JSON 문자열로 들고 있고
 * Python 은 snake_case 로 쓰므로 여기서 camelCase 객체로 바꾼다(AGENTS.md 작업 규칙 5).
 */
public record EvalRunResponse(
        UUID id,
        EvalConfigResponse config,
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

    /** DB 에서 읽은 실행 (이력 조회용). */
    public static EvalRunResponse from(EvalRun run, ObjectMapper mapper) {
        return new EvalRunResponse(
                run.getId(),
                EvalConfigResponse.from(run.getConfig(), mapper),
                run.getAvgFaithfulness(),
                run.getAvgRelevancy(),
                run.getAnsweredRate(),
                run.getStatus(),
                run.getCreatedAt()
        );
    }

    /**
     * Python 이 방금 만든 실행 (시작 응답용).
     *
     * <p>DB 를 다시 읽지 않고 Python 응답을 그대로 쓰는 이유: 방금 만들어진 행이라
     * 점수는 전부 null 이고 status 는 running 이 확정이다. 한 번 더 읽을 이유가 없다.
     *
     * <p>{@code config} 는 Python 이 Map 으로 주므로 문자열로 되돌려 <b>같은 파서를 태운다</b> —
     * 파싱 규칙이 두 벌이 되면 이력 조회와 시작 응답의 모양이 언젠가 어긋난다.
     */
    public static EvalRunResponse from(AiEvalRunResponse run, ObjectMapper mapper) {
        String configJson = run.config() == null ? null : mapper.writeValueAsString(run.config());
        return new EvalRunResponse(
                run.id(),
                EvalConfigResponse.from(configJson, mapper),
                toDecimal(run.avgFaithfulness()),
                toDecimal(run.avgRelevancy()),
                toDecimal(run.answeredRate()),
                run.status(),
                run.createdAt()
        );
    }

    /** null 을 0 으로 바꾸지 않기 위해 감싼다. {@code BigDecimal.valueOf(null)} 은 컴파일도 안 되거나 NPE 다. */
    private static BigDecimal toDecimal(Double v) {
        return v == null ? null : BigDecimal.valueOf(v);
    }
}
