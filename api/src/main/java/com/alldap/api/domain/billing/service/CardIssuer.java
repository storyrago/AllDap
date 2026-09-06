package com.alldap.api.domain.billing.service;

import java.util.Map;

/**
 * 토스 {@code issuerCode} → 카드사 이름.
 *
 * <p><b>왜 우리가 이걸 들고 있는가.</b> 토스가 <b>2024-06-01 버전부터 응답에서
 * {@code cardCompany}(이름)를 제거</b>했다. 이제 {@code card.issuerCode}("61" 같은 코드)만 온다.
 * 화면에 "61" 을 보여줄 수는 없으니 매핑이 어딘가에는 있어야 한다.
 *
 * <p><b>왜 프론트가 아니라 여기인가.</b> 표기 변환은 Spring 책임이라는 것이 이 저장소의 규칙이다
 * (snake_case → camelCase 와 같은 자리). 프론트에 두면 {@code web/lib/types.ts} 가
 * 백엔드 응답과 어긋나고, 위젯·관리자 화면이 각자 사본을 갖게 된다.
 *
 * <p><b>왜 {@code dto} 가 아니라 {@code service} 패키지인가.</b> 코드→이름 매핑은
 * <b>응답을 만드는 일</b>이라 {@code BillingService} 옆이 맞다.
 * {@code dto} 에 두면 DTO 가 아닌 것이 dto 패키지에 섞인다.
 *
 * <p>⚠️ <b>이 표는 완전하지 않다.</b> 토스 코드표(https://docs.tosspayments.com/reference/codes)에는
 * 해외 카드사·선불 사업자 등이 더 있고, 코드가 추가될 수도 있다. 국내에서 실제로 등록될 법한
 * 카드사만 담았다. <b>모르는 코드는 예외를 던지지 않고 {@code "카드"} 로 답한다</b> —
 * 표에 없는 카드사로 등록했다고 해서 등록 자체가 실패하면 안 된다. 사용자는 마스킹된
 * 카드번호로도 자기 카드를 알아본다.
 */
public final class CardIssuer {

    private static final String UNKNOWN = "카드";

    private static final Map<String, String> NAMES = Map.ofEntries(
            Map.entry("11", "국민"),
            Map.entry("15", "카카오뱅크"),
            Map.entry("21", "하나"),
            Map.entry("24", "토스뱅크"),
            Map.entry("30", "KDB산업"),
            Map.entry("31", "BC"),
            Map.entry("33", "우리BC"),
            Map.entry("34", "수협"),
            Map.entry("35", "전북"),
            Map.entry("36", "씨티"),
            Map.entry("37", "우체국예금보험"),
            Map.entry("38", "새마을"),
            Map.entry("39", "저축은행중앙회"),
            Map.entry("41", "신한"),
            Map.entry("42", "제주"),
            Map.entry("46", "광주"),
            Map.entry("51", "삼성"),
            Map.entry("61", "현대"),
            Map.entry("62", "신협"),
            Map.entry("71", "롯데"),
            Map.entry("91", "NH농협"),
            Map.entry("3A", "케이뱅크"),
            Map.entry("3K", "기업BC"),
            Map.entry("W1", "우리"));

    private CardIssuer() {
    }

    /** 모르는 코드·null 은 {@code "카드"}. 호출자가 null 을 걱정하지 않아도 된다. */
    public static String nameOf(String issuerCode) {
        return NAMES.getOrDefault(issuerCode, UNKNOWN);
    }
}
