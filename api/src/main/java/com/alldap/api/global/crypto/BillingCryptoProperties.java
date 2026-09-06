package com.alldap.api.global.crypto;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 빌링키 암호화 설정. {@code application.yaml} 의 {@code app.billing-crypto.*} 를 바인딩한다.
 *
 * <p>record 로 둔 이유는 {@code AiServiceProperties}·{@code JwtProperties} 와 같다 —
 * 설정값은 기동 시점에 정해지고 이후 바뀌지 않으므로 불변이 맞다.
 * 별도 등록은 필요 없다. {@code ApiApplication} 의 {@code @ConfigurationPropertiesScan} 이 찾아준다.
 *
 * @param key AES-256 키. <b>Base64 로 인코딩된 32바이트</b>여야 한다.
 *            생성: {@code openssl rand -base64 32}
 *            검증(길이·플레이스홀더·공개 기본값)은 {@link BillingCrypto} 생성자가 한다 —
 *            여기서 하지 않는 이유는 record 의 compact 생성자에서 던지면
 *            바인딩 실패 예외에 묻혀 <b>우리가 쓴 한국어 안내가 사용자에게 안 보이기</b> 때문이다.
 */
@ConfigurationProperties(prefix = "app.billing-crypto")
public record BillingCryptoProperties(String key) {
}
