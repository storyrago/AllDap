package com.alldap.api.global.crypto;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.mock.env.MockEnvironment;

import java.util.Base64;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 빌링키 암복호화를 테스트로 고정한다.
 *
 * <p><b>왜 이 테스트가 특별한가.</b> 이 저장소에는 "운영에서 공개 기본값이면 죽는다" 가드가
 * 이미 둘 있다({@code JwtService} 의 시크릿 검사, {@code application-prod.yaml} 의 fail-closed).
 * 그런데 <b>테스트로 고정된 것은 하나도 없다.</b> 가드는 조용히 무력해져도 아무도 모른다 —
 * yaml 의 기본값 문자열만 바꾸면 {@code JwtService} 의 블랙리스트 비교가 그냥 빗나간다.
 * {@code shortKeyFailsFast}, {@code unresolvedPlaceholderFailsFast}는 설정 실수(키 길이,
 * 플레이스홀더 미해석)를 검증하고, {@code knownLocalDefaultKeyWithProductionProfileFailsFast},
 * {@code knownLocalDefaultKeyWithoutProfileWarnsButSucceeds}는 운영 환경에 공개된 로컬 기본값이
 * 우연히 쓰이는 것을 검증한다. 이 두 가지가 테스트로 붙은 것은 처음이다.
 *
 * <p>스프링 컨텍스트를 띄우지 않는다. {@link BillingCrypto} 는 프로퍼티와
 * {@code Environment} 만 받는 순수 객체라 그럴 이유가 없고, 컨텍스트를 띄우면
 * 느려지는 만큼 자주 안 돌리게 된다({@code AiServiceCircuitBreakerTest} 와 같은 판단).
 */
@DisplayName("빌링키 암복호화")
class BillingCryptoTest {

    /** Base64("test-only-billing-key-32-bytes!!") — 정확히 32바이트다. */
    private static final String KEY_A = "dGVzdC1vbmx5LWJpbGxpbmcta2V5LTMyLWJ5dGVzISE=";
    /** Base64("another-32-byte-billing-key-here") — 역시 32바이트, 다른 값. */
    private static final String KEY_B = "YW5vdGhlci0zMi1ieXRlLWJpbGxpbmcta2V5LWhlcmU=";

    /** 토스 빌링키를 흉내낸 값. 실제 형식이 중요한 테스트가 아니라 길이만 비슷하게 잡았다. */
    private static final String BILLING_KEY = "bln_20260906_abcdefghijklmnopqrstuvwxyz0123456789";

    /**
     * {@code MockEnvironment} 는 활성 프로파일이 <b>하나도 없는</b> 환경이다.
     * {@code BillingCrypto} 는 그것을 "개발 환경"으로 본다({@code JwtService} 와 같은 판정 기준) —
     * 그래서 여기서는 "저장소 공개 기본값" 가드가 발동하지 않고, 우리가 검사하려는
     * 길이·플레이스홀더 가드만 남는다.
     */
    private BillingCrypto crypto(String key) {
        return new BillingCrypto(new BillingCryptoProperties(key), new MockEnvironment());
    }

    @Test
    @DisplayName("암호화한 값을 다시 복호화하면 원래 빌링키가 나온다")
    void roundTrip() {
        BillingCrypto crypto = crypto(KEY_A);
        assertThat(crypto.decrypt(crypto.encrypt(BILLING_KEY))).isEqualTo(BILLING_KEY);
    }

    @Test
    @DisplayName("같은 값을 두 번 암호화하면 암호문이 다르다 — IV 가 매번 새로 생긴다")
    void sameInputProducesDifferentCiphertext() {
        BillingCrypto crypto = crypto(KEY_A);
        // 같은 평문이 같은 암호문이 되면, DB 만 봐도 "이 둘은 같은 카드다" 가 새어나간다.
        assertThat(crypto.encrypt(BILLING_KEY)).isNotEqualTo(crypto.encrypt(BILLING_KEY));
    }

    @Test
    @DisplayName("🔴 암호문을 한 비트라도 뒤집으면 복호화가 실패한다 — GCM 인증태그가 하는 일")
    void tamperedCiphertextIsRejected() {
        BillingCrypto crypto = crypto(KEY_A);
        byte[] combined = Base64.getDecoder().decode(crypto.encrypt(BILLING_KEY));
        // 인덱스 12 = IV(12바이트) 바로 다음, 즉 암호문의 첫 바이트다.
        // 이게 CBC 였다면 그냥 복호화에 성공하고 우리는 아무것도 눈치채지 못한다.
        combined[12] ^= 0x01;
        String tampered = Base64.getEncoder().encodeToString(combined);

        assertThatThrownBy(() -> crypto.decrypt(tampered))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("복호화하지 못했습니다");
    }

    @Test
    @DisplayName("🔴 다른 키로는 복호화할 수 없다 — 키를 잃으면 재등록뿐이라는 말의 실증")
    void otherKeyCannotDecrypt() {
        String stored = crypto(KEY_A).encrypt(BILLING_KEY);
        BillingCrypto other = crypto(KEY_B);

        // 토스에는 발급된 빌링키를 조회하는 API 가 없다. 우리 DB 가 유일한 사본이라
        // 키를 잃으면 전 고객이 카드를 다시 등록해야 한다 — 그 대가가 실재함을 여기서 못박는다.
        assertThatThrownBy(() -> other.decrypt(stored))
                .isInstanceOf(IllegalStateException.class);
    }

    @Test
    @DisplayName("🔴 키가 32바이트가 아니면 기동이 실패한다 — JCE 는 16바이트를 주면 말없이 AES-128 로 돈다")
    void shortKeyFailsFast() {
        // Base64("sixteen-byte-key") — 16바이트. 이 검사가 없으면 아무 오류 없이 AES-128 로 돌고,
        // 우리는 "AES-256 으로 저장합니다" 라고 말할 근거를 잃는다.
        assertThatThrownBy(() -> crypto("c2l4dGVlbi1ieXRlLWtleQ=="))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("32바이트");
    }

    @Test
    @DisplayName("🔴 ${...} 리터럴이 그대로 들어오면 기동이 실패한다")
    void unresolvedPlaceholderFailsFast() {
        // @ConfigurationProperties 는 해석하지 못한 플레이스홀더를 <예외 없이 리터럴로> 바인딩한다
        // (@Value 와 다르다). 그대로 두면 "${BILLING_CRYPTO_KEY}" 라는 문자열이 Base64 디코딩에
        // 걸려 알 수 없는 영어 예외만 남는다. 무엇을 어떻게 고칠지 한국어로 알려주려면 여기서 잡아야 한다.
        assertThatThrownBy(() -> crypto("${BILLING_CRYPTO_KEY}"))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("BILLING_CRYPTO_KEY");
    }

    @Test
    @DisplayName("🔴 운영 프로파일 + 저장소 공개 기본 키 → 기동이 실패한다")
    void knownLocalDefaultKeyWithProductionProfileFailsFast() {
        // MockEnvironment 는 기본으로 활성 프로파일이 없어 항상 개발 환경으로 인식되기 때문에,
        // 운영 환경에서 공개된 로컬 기본 키가 거부되는 분기를 실행하려면 프로파일을 명시해야 한다.
        // BillingCrypto.DEVELOPMENT_PROFILES 에 없는 이름을 쓸 것("prod", "production" 등).
        MockEnvironment environment = new MockEnvironment();
        environment.setActiveProfiles("prod");

        // BillingCrypto.KNOWN_LOCAL_DEFAULT_KEY = "YWxsZGFwLWxvY2FsLWRldi1iaWxsaW5nLWtleS0zMmI="
        // (Base64 로 "alldap-local-dev-billing-key-32b", 정확히 32바이트)
        String knownLocalDefaultKey = "YWxsZGFwLWxvY2FsLWRldi1iaWxsaW5nLWtleS0zMmI=";

        assertThatThrownBy(() -> new BillingCrypto(
                new BillingCryptoProperties(knownLocalDefaultKey),
                environment))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("저장소에 공개된 로컬 기본값");
    }

    @Test
    @DisplayName("저장소 공개 기본 키도 프로파일 없이는 정상 생성된다 — 경고만 나간다")
    void knownLocalDefaultKeyWithoutProfileWarnsButSucceeds() {
        // 프로파일이 하나도 없으면 개발 환경으로 인정하는 트레이드오프다 —
        // 로컬 bootRun·IDE 실행·통합 테스트가 전부 프로파일 없이 돈다(JwtService 와 같은 논리).
        // 그래서 같은 기본 키라도 프로파일이 없으면 예외 없이 통과한다(경고는 로그에 남는다).
        MockEnvironment environment = new MockEnvironment();
        // 프로파일을 명시하지 않으면 기본값(없음)이 쓰인다 → 개발 환경으로 인정.

        String knownLocalDefaultKey = "YWxsZGFwLWxvY2FsLWRldi1iaWxsaW5nLWtleS0zMmI=";

        // 예외가 안 나야 한다는 것이 핵심이다. 그 객체를 만들 수 있고,
        // 그 뒤 encrypt/decrypt 도 정상적으로 돈다는 뜻이다.
        BillingCrypto crypto = new BillingCrypto(
                new BillingCryptoProperties(knownLocalDefaultKey),
                environment);

        // 진짜로 동작하는지 간단히 확인한다.
        String encrypted = crypto.encrypt(BILLING_KEY);
        assertThat(crypto.decrypt(encrypted)).isEqualTo(BILLING_KEY);
    }
}
