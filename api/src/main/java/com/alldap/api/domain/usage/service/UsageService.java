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
        YearMonth target = parseMonth(month);

        // 🔴 세기 <전에> 메꾼다. 순서가 반대면 방금 끝난 평가 실행이 다음 조회까지 안 보인다.
        usageEventRepository.backfillEvalRuns(userId);

        Instant from = target.atDay(1).atStartOfDay(BILLING_ZONE).toInstant();
        Instant to = target.plusMonths(1).atDay(1).atStartOfDay(BILLING_ZONE).toInstant();

        return new UsageResponse(
                target.toString(),
                usageEventRepository.countInPeriod(userId, UsageEvent.KIND_CHAT_ANSWER, from, to),
                usageEventRepository.countInPeriod(userId, UsageEvent.KIND_EVAL_RUN, from, to),
                from.atZone(BILLING_ZONE).toOffsetDateTime(),
                to.atZone(BILLING_ZONE).toOffsetDateTime());
    }

    private YearMonth parseMonth(String month) {
        if (month == null || month.isBlank()) {
            return YearMonth.now(BILLING_ZONE);
        }
        try {
            return YearMonth.parse(month);
        } catch (DateTimeException e) {
            // java.time.format.DateTimeParseException 은 DateTimeException 의 하위 클래스라
            // 별도로 잡을 필요가 없다(오히려 멀티캐치로 두면 컴파일 에러다).
            throw new ApiException(ErrorCode.INVALID_INPUT,
                    "조회할 달의 형식이 올바르지 않습니다. 2026-09 처럼 YYYY-MM 으로 보내주세요.");
        }
    }
}
