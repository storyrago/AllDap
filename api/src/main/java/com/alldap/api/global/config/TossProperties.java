package com.alldap.api.global.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.time.Duration;

/**
 * 토스페이먼츠 API 호출 설정. {@code application.yaml} 의 {@code app.toss.*} 를 바인딩한다.
 *
 * <p>{@code AiServiceProperties} 와 <b>따로 두는 이유는 타임아웃이 정반대이기 때문</b>이다.
 * 그쪽은 읽기 120초(LLM 이 수십 초 걸린다), 이쪽은 10초(사용자가 카드 등록 화면 앞에서 기다린다).
 * 한 record 에 묶으면 둘 중 하나가 반드시 틀린 값을 갖게 된다.
 *
 * @param baseUrl        토스 API 주소. 운영은 {@code https://api.tosspayments.com}
 * @param secretKey      🔴 <b>API 개별 연동 키</b>({@code test_sk_} / {@code live_sk_})다.
 *                       결제위젯 키({@code test_gsk_})를 넣으면 토스가 {@code INVALID_API_KEY} 로 거절한다 —
 *                       토스는 서비스마다 다른 MID 에 각각 키를 발급하고, 세트가 아닌 키를 섞으면 안 받는다.
 * @param connectTimeout TCP 연결 타임아웃
 * @param readTimeout    응답 대기 타임아웃 (근거는 TossClientConfig 주석)
 */
@ConfigurationProperties(prefix = "app.toss")
public record TossProperties(
        String baseUrl,
        String secretKey,
        Duration connectTimeout,
        Duration readTimeout
) {
}
