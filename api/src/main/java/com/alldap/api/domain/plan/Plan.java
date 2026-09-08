package com.alldap.api.domain.plan;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonValue;
import jakarta.persistence.AttributeConverter;
import jakarta.persistence.Converter;

import java.util.Arrays;

/**
 * 계정의 요금제. 요금제 연동 4조각 중 <b>2번</b>이다.
 *
 * <p>🔴 <b>여기에 금액도 포함량도 없다. 일부러 없다.</b> 이 enum 이 아는 것은 "어느 요금제인가" 와
 * "그게 유료인가" 둘뿐이다. 금액(29,000원)과 포함량(월 3,000건)은 <b>화면에만</b> 있고
 * ({@code web/lib/plans.ts}) 서버는 모른다 — 서버가 그 숫자로 <b>하는 일이 아직 없기 때문</b>이다.
 * 한도 검사도 청구도 4번 조각이고, 그때는 금액·기간·청구서를 함께 설계해야 한다.
 * 지금 서버에 숫자를 넣어두면 <b>쓰이지 않는 채 프론트의 숫자와 갈라질 자리</b>만 만든다.
 * (⚠️ {@code decisions.md} 2026-09-07 항목이 "2번을 만들 때 Spring 이 값을 갖게 되면 프론트는
 *  API 에서 받아야 한다" 고 적었는데, 실제로 만들어 보니 <b>서버가 가질 값이 없었다.</b>
 *  그 정정을 2026-09-08 항목에 남겼다.)
 *
 * <p><b>표기가 전부 소문자다</b> — DB 값·JSON 값·프론트 {@code Plan["id"]} 가 모두 {@code "free"}·
 * {@code "pro"} 다. 한 값이 계층마다 다른 모양이면(DB 는 {@code FREE}, API 는 {@code free})
 * 로그를 볼 때도 SQL 을 짤 때도 매번 어느 쪽인지 따져야 한다. 그걸 없애려고
 * {@link JsonValue}(직렬화)·{@link JsonCreator}(역직렬화)·{@link JpaConverter}(DB) 셋을 두었다.
 * Java 상수 이름만 관례대로 대문자다.
 */
public enum Plan {

    FREE("free"),
    PRO("pro");

    private final String code;

    Plan(String code) {
        this.code = code;
    }

    /** JSON 으로 나갈 때의 값. DB 에 저장되는 값도 같다({@link JpaConverter}). */
    @JsonValue
    public String code() {
        return code;
    }

    /** 유료 요금제인가. 지금 이 값에 걸린 규칙은 하나 — <b>유료로 바꾸려면 카드가 있어야 한다.</b> */
    public boolean isPaid() {
        return this != FREE;
    }

    /**
     * 요청 본문의 문자열 → enum. 모르는 값이면 예외를 던져 <b>400</b> 으로 나간다
     * (Jackson 역직렬화 실패는 {@code GlobalExceptionHandler} 가 잡는다).
     * 조용히 {@code FREE} 로 떨어뜨리지 않는 것이 중요하다 — 오타 하나가
     * "요금제를 바꿨는데 무료가 됐다" 로 끝나면 사용자는 무슨 일이 났는지 알 수 없다.
     */
    @JsonCreator
    public static Plan from(String code) {
        return Arrays.stream(values())
                .filter(p -> p.code.equals(code))
                .findFirst()
                .orElseThrow(() -> new IllegalArgumentException(
                        "알 수 없는 요금제입니다: " + code + " (free, pro 중 하나여야 합니다)"));
    }

    /**
     * DB 저장 형식. {@code @Enumerated(EnumType.STRING)} 을 쓰면 상수 이름 그대로 {@code "FREE"} 가
     * 저장되는데, 그러면 위에서 없애려던 <b>계층별 표기 차이</b>가 그대로 생긴다.
     *
     * <p>{@code autoApply = true} 라 {@code Plan} 타입 필드는 별도 표시 없이 이 변환을 탄다.
     */
    @Converter(autoApply = true)
    public static class JpaConverter implements AttributeConverter<Plan, String> {

        @Override
        public String convertToDatabaseColumn(Plan plan) {
            return plan == null ? null : plan.code;
        }

        @Override
        public Plan convertToEntityAttribute(String code) {
            return code == null ? null : from(code);
        }
    }
}
