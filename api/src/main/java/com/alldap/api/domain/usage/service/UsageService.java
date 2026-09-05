package com.alldap.api.domain.usage.service;

import com.alldap.api.domain.usage.dto.UsageResponse;
import com.alldap.api.domain.usage.entity.UsageEvent;
import com.alldap.api.domain.usage.repository.UsageEventRepository;
import com.alldap.api.global.exception.ApiException;
import com.alldap.api.global.exception.ErrorCode;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.DateTimeException;
import java.time.Instant;
import java.time.YearMonth;
import java.time.ZoneId;
import java.util.UUID;

/**
 * 사용량 조회. <b>계정 단위</b>다 — 봇이 아니라 봇의 주인이 청구 대상이다.
 *
 * <p><b>기간 경계를 SQL 이 아니라 여기서 계산하는 이유.</b> 문자열을 이어붙여 날짜를 만드는
 * SQL 은 읽기 어렵고 형변환 오류가 런타임에만 드러난다. 자바에서 계산하면 그 계산만
 * 따로 검증할 수 있다. 저장은 여전히 {@code TIMESTAMPTZ} 이므로 동작은 같다.
 */
@Service
@RequiredArgsConstructor
public class UsageService {

    /**
     * 청구 기간은 <b>한국 시간 달력 월</b>이다. 국내 서비스이고 청구서를 읽는 사람이 한국에 있다.
     *
     * <p>⚠️ {@code occurred_at} 이 {@code TIMESTAMPTZ}(UTC 저장)라 경계만 KST 로 잡으면 된다.
     * 컬럼을 {@code TIMESTAMP} 로 뒀다면 이 계산이 <b>조용히 틀린다</b> —
     * 9월 1일 오전 8시 KST 사건이 8월분으로 세어진다.
     */
    private static final ZoneId BILLING_ZONE = ZoneId.of("Asia/Seoul");

    private final UsageEventRepository usageEventRepository;

    /**
     * @param month {@code "YYYY-MM"} 또는 null(이번 달)
     */
    @Transactional
    public UsageResponse findUsage(UUID userId, String month) {
        MonthRange range = parseMonth(month);

        // 🔴 세기 <전에> 메꾼다. 순서가 반대면 방금 끝난 평가 실행이 다음 조회까지 안 보인다.
        //
        // ⚠️⚠️⚠️ 청구서(invoicing)를 만들 사람은 반드시 읽을 것 — evalRuns 는 "확정된 숫자"가 아니다.
        // 이 메꾸기는 조회할 때마다 계정의 <전체 이력>을 훑으므로, 이미 지나가 정산이 끝났다고
        // 여겨질 법한 달의 evalRuns 도 늦게 완료된 실행이 뒤늦게 메꿔지며 <계속 늘어날 수 있다>.
        // 지금은 청구서가 없어 문제가 안 드러났을 뿐이다. 청구서를 붙일 때 다음 중 하나를 반드시
        // 정할 것: ① 기간이 끝나면 그 달 숫자를 얼려 더 이상 안 바뀌게 하거나,
        // ② 정산 시점에 한 번만 메꾸고 그 뒤로는 늦게 끝난 실행을 다음 달로 넘긴다.
        // chatAnswers 는 발생 즉시 기록되어 이 문제가 없다 — evalRuns 만의 특성이다.
        usageEventRepository.backfillEvalRuns(userId);

        return new UsageResponse(
                range.target().toString(),
                usageEventRepository.countInPeriod(userId, UsageEvent.KIND_CHAT_ANSWER, range.from(), range.to()),
                usageEventRepository.countInPeriod(userId, UsageEvent.KIND_EVAL_RUN, range.from(), range.to()),
                range.from().atZone(BILLING_ZONE).toOffsetDateTime(),
                range.to().atZone(BILLING_ZONE).toOffsetDateTime());
    }

    /**
     * 조회 대상 달과 그 경계를 함께 계산한다.
     *
     * <p>🔴 경계 계산({@code plusMonths(1)} 포함)까지 이 안에서 끝내야 한다. 예전에는
     * {@code target.plusMonths(1)} 이 try 블록 <b>밖</b>에 있어서, {@code +999999999-12} 처럼
     * {@code YearMonth.parse} 자체는 성공하지만(ISO 8601 이 부호 있는 확장 연도를 허용한다)
     * 그 값에 1을 더하는 순간 연도 상한을 넘어 {@code DateTimeException} 이 <b>가드 밖에서</b>
     * 터졌다 — 사용자 입력이 원인인데 500 이 나가는 것이다.
     */
    private MonthRange parseMonth(String month) {
        try {
            YearMonth target = (month == null || month.isBlank())
                    ? YearMonth.now(BILLING_ZONE)
                    : YearMonth.parse(month);
            Instant from = target.atDay(1).atStartOfDay(BILLING_ZONE).toInstant();
            Instant to = target.plusMonths(1).atDay(1).atStartOfDay(BILLING_ZONE).toInstant();
            return new MonthRange(target, from, to);
        } catch (DateTimeException e) {
            // java.time.format.DateTimeParseException 은 DateTimeException 의 하위 클래스라
            // 별도로 잡을 필요가 없다(오히려 멀티캐치로 두면 컴파일 에러다).
            throw new ApiException(ErrorCode.INVALID_INPUT,
                    "조회할 달의 형식이 올바르지 않습니다. 2026-09 처럼 YYYY-MM 으로 보내주세요.");
        }
    }

    private record MonthRange(YearMonth target, Instant from, Instant to) {
    }
}
