package com.alldap.api.global.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 위젯 공개 API 설정. {@code application.yaml} 의 {@code app.widget.*} 를 바인딩한다.
 *
 * <p>숫자를 코드에 박지 않고 설정으로 뺀 이유: 이 값들은 <b>운영하면서 조정하게 되는</b> 종류다.
 * 실제 사용량을 보기 전까지는 어떤 값이 맞는지 알 수 없고, 값을 바꾸려고 재빌드하고 싶지 않다.
 *
 * @param chatPerMinute   같은 IP·같은 봇 기준 분당 채팅 허용 횟수.
 *                        채팅은 건당 LLM 비용이 들어 낮게 잡는다
 * @param configPerMinute 설정 조회 허용 횟수. 비용은 없지만 무제한이면
 *                        publicKey 를 무작위로 넣어 <b>존재하는 봇을 훑을 수</b> 있다
 */
@ConfigurationProperties(prefix = "app.widget")
public record WidgetProperties(
        int chatPerMinute,
        int configPerMinute
) {
}
