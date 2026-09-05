package com.alldap.api.domain.usage.dto;

import java.time.OffsetDateTime;

/**
 * 한 계정의 한 달 사용량.
 *
 * <p><b>금액이 없다.</b> 이 단계는 개수만 센다 — 단가·플랜·포함량·초과 계산은 다음 조각이다.
 * {@code /pricing} 도 아직 "금액이 아직 없다" 고 말하고 있어, 여기서만 금액이 있는 척하면
 * 화면끼리 거짓말을 하게 된다.
 *
 * <p>기간을 함께 내려주는 이유: 화면이 "9월"을 어떻게 해석할지 스스로 정하면
 * 서버와 어긋난다(특히 시간대). <b>경계를 서버가 정해서 그대로 보여주게 한다.</b>
 *
 * @param chatAnswers 위젯에서 실제로 만들어진 답변 수(fallback·테스트 채팅 제외)
 * @param evalRuns    완료된 품질 평가 실행 수(partial·failed 제외)
 * @param periodEnd   다음 달 1일 00:00 KST 의 순간. <b>이 기간에 포함되지 않는다</b>(오른쪽 제외) —
 *                    화면에서 "이 달의 마지막 날"로 그대로 표시하면 하루 밀려 다음 달 1일이 된다
 */
public record UsageResponse(
        String month,
        long chatAnswers,
        long evalRuns,
        OffsetDateTime periodStart,
        OffsetDateTime periodEnd
) {
}
