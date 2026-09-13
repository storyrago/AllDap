package com.alldap.api.domain.eval.dto;

import com.alldap.api.domain.eval.entity.EvalRun;
import com.alldap.api.global.client.dto.AiEvalRunResponse;
import tools.jackson.databind.ObjectMapper;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.Instant;

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
        Long id,
        EvalConfigResponse config,
        /** 충실성 평균 (0~1). NUMERIC(4,3) 이라 BigDecimal 이다. */
        BigDecimal avgFaithfulness,
        /** 관련성 평균 (0~1) */
        BigDecimal avgRelevancy,
        /** 응답률 (0~1) */
        BigDecimal answeredRate,
        /**
         * running | completed | failed | partial
         *
         * <p>{@code partial} 은 <b>일부</b> 질문만 처리되거나 채점됐다는 뜻이다
         * ({@code processed > 0} 인데 {@code scoredCount < questionCount} 인 경우 등,
         * 예: 채점 응답 JSON 파싱 실패 1건). {@code processed == 0}(전부 실패)이면 {@code failed} 다.
         * 🔴 {@code partial} 실행은 <b>다른 설정과 비교하면 안 된다</b> —
         * 분모가 달라 {@code overallFaithfulness} 가 있어도 다른 실행과 같은 기준이 아니다.
         */
        String status,
        /** 이 실행의 대상 질문 수. avg_* 를 해석하려면 반드시 필요한 분모. 옛 실행은 null. */
        Integer questionCount,
        /** 실제로 채점된 질문 수. avg_* 의 진짜 분모. */
        Integer scoredCount,
        /**
         * <b>설정 비교(W4 before/after)에는 이 값을 써야 한다.</b>
         *
         * <p>{@code avgFaithfulness} 는 <b>답을 덜 할수록 저절로 올라간다.</b>
         * fallback 은 채점에서 빠지므로, 어려운 질문이 fallback 되면
         * 남은 쉬운 질문들만 평균에 남는다(생존 편향).
         *
         * <p>실제로 속았다 — 리랭커 before/after 에서 충실성이 0.714 → 0.789 로 올랐는데,
         * 0점짜리 2건이 fallback 된 결과였고 그 2건을 0으로 환산하면 0.714 로 동일했다.
         *
         * <p>그래서 분모를 전체 질문 수로 되돌린다:
         * {@code avgFaithfulness × scoredCount / questionCount}.
         * 답을 덜 하면 이 값도 같이 내려가므로 편향에 넘어가지 않는다.
         *
         * <p>분모를 모르는 옛 실행은 null 이다. 화면은 "표본 미기록"으로 표시하고
         * 비교 대상에서 빼야 한다 — 모르는 걸 0 이나 avgFaithfulness 로 채우면 또 속는다.
         */
        BigDecimal overallFaithfulness,
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
                run.getQuestionCount(),
                run.getScoredCount(),
                overall(run.getAvgFaithfulness(), run.getScoredCount(), run.getQuestionCount()),
                run.getCreatedAt()
        );
    }

    /**
     * 생존 편향을 걷어낸 충실성. 계산할 수 없으면 null 이다.
     *
     * <p>null 을 돌려주는 경우: 아직 점수가 없거나(running), 옛 실행이라 분모를 모르거나,
     * 질문이 0건인 경우. <b>0 으로 채우지 않는다</b> — "모른다"와 "0점"은 다르다.
     */
    private static BigDecimal overall(BigDecimal avg, Integer scored, Integer total) {
        if (avg == null || scored == null || total == null || total == 0) {
            return null;
        }
        return avg.multiply(BigDecimal.valueOf(scored))
                .divide(BigDecimal.valueOf(total), 3, RoundingMode.HALF_UP);
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
                // Python 이 실행을 <시작할 때> 주는 응답에는 아직 집계가 없다.
                // 화면은 폴링해서 완료된 실행을 다시 읽으므로 여기서 채울 필요가 없다.
                null, null, null,
                run.createdAt()
        );
    }

    /** null 을 0 으로 바꾸지 않기 위해 감싼다. {@code BigDecimal.valueOf(null)} 은 컴파일도 안 되거나 NPE 다. */
    private static BigDecimal toDecimal(Double v) {
        return v == null ? null : BigDecimal.valueOf(v);
    }
}
