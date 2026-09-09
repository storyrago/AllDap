package com.alldap.api.global.crypto;

import com.alldap.api.global.exception.ApiException;
import com.alldap.api.global.exception.ErrorCode;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.env.Environment;
import org.springframework.security.crypto.encrypt.AesBytesEncryptor;
import org.springframework.security.crypto.keygen.KeyGenerators;
import org.springframework.stereotype.Service;

import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Base64;
import java.util.Locale;
import java.util.Set;

/**
 * 토스 빌링키를 DB 에 넣기 전에 암호화하고, 읽을 때 복호화한다.
 *
 * <h2>왜 암호화하는가</h2>
 * 빌링키는 "이 카드에 청구해도 된다"는 <b>열쇠 그 자체</b>다. 그리고 토스에는
 * <b>발급된 빌링키를 조회하는 API 가 없다</b> — 우리 DB 가 유일한 사본이다.
 * 그래서 두 방향이 모두 치명적이다: DB 덤프가 새면 그대로 결제 수단 유출이고,
 * 우리가 키를 잃으면 전 고객이 카드를 다시 등록해야 한다.
 *
 * <h2>왜 새 의존성이 없는가</h2>
 * {@code spring-boot-starter-security} 가 이미 전이로 끌고 오는
 * {@code spring-security-crypto} 의 {@link AesBytesEncryptor} 를 <b>원시 키 생성자</b>로 쓴다.
 * Bouncy Castle 은 클래스패스에 없고, 넣을 이유도 없다.
 *
 * <h2>왜 {@code Encryptors.text()} / {@code delux()} 가 아닌가 (7.0.6 소스로 확인함)</h2>
 * <ul>
 *   <li>{@code Encryptors.text()} 는 GCM 이 아니라 {@code AES/CBC/PKCS5Padding} 이다.
 *       CBC 는 <b>인증이 없어</b> 암호문을 한 바이트 뒤집어도 복호화가 그냥 성공한다.
 *       DB 를 만질 수 있는 공격자가 남의 빌링키로 바꿔치기해도 우리가 눈치채지 못한다.</li>
 *   <li>{@code delux()} 는 GCM 은 맞지만 키를 {@code PBKDF2WithHmacSHA1} <b>1024회</b>로 유도한다.
 *       우리는 이미 32바이트 난수를 환경변수로 갖고 있어 유도할 이유가 없고, 1024회는 2026년 기준으로 낮다.</li>
 * </ul>
 *
 * <h2>키 회전은 만들지 않는다</h2>
 * 막다른 길은 아니다 — 나중에 새 키를 도입할 때 저장값에 {@code v2:} 접두사를 붙이면
 * <b>접두사 없는 행 = 옛 키</b>로 소급 판별된다. 지금 미리 그 문법을 만들 이유가 없다.
 */
@Slf4j
@Service
public class BillingCrypto {

    /**
     * {@code application.yaml} 에 박혀 있는(= 저장소에 공개된) 로컬 개발용 기본 키.
     *
     * <p>여기에 값을 <b>복사해두는 것 자체가 목적</b>이다. "이 값은 이미 공개됐으니 운영에서 쓰면 안 된다"는
     * 블랙리스트이기 때문이다. {@code JwtService.KNOWN_LOCAL_DEFAULT_SECRET} 과 똑같은 약한 고리를
     * 공유한다 — yaml 의 기본값만 바꾸면 이 가드는 아무 말 없이 무력해진다.
     * 그래서 yaml 쪽에도 "이 값을 바꾸면 여기도 함께 바꾸라"는 주석을 남겨뒀다.
     *
     * <p>값은 Base64("alldap-local-dev-billing-key-32b") 로, 디코딩하면 정확히 32바이트다.
     */
    private static final String KNOWN_LOCAL_DEFAULT_KEY = "YWxsZGFwLWxvY2FsLWRldi1iaWxsaW5nLWtleS0zMmI=";

    /**
     * "여긴 개발 환경이다"로 인정할 프로파일 이름들. {@code JwtService} 와 같은 목록·같은 근거다 —
     * 반대로(운영 프로파일을 나열해서) 판단하면 {@code staging} 같은 이름이 생길 때마다 가드가 조용히 뚫린다.
     */
    private static final Set<String> DEVELOPMENT_PROFILES = Set.of("local", "dev", "development", "test");

    private static final int AES_256_KEY_BYTES = 32;

    /**
     * GCM 의 IV(논스) 길이. 12바이트는 NIST SP 800-38D 권장값이다.
     *
     * <p>⚠️ {@code CipherAlgorithm.GCM} 의 <b>기본 IV 생성기는 16바이트</b>다
     * ({@code KeyGenerators.secureRandom(16)}). 기본값에 맡기지 않고 명시하는 이유는
     * 저장 크기를 우리가 계산해 컬럼 폭을 정했기 때문이다 — {@code V6__billing_method.sql} 의
     * {@code billing_key_enc VARCHAR(512)} 주석이 12바이트를 전제로 한다.
     * <b>이 값을 바꾸면 이미 저장된 행을 복호화할 수 없다</b>(IV 를 잘라 읽는 길이가 달라진다).
     */
    private static final int GCM_IV_BYTES = 12;

    /**
     * {@code AesBytesEncryptor} 는 {@code encrypt}/{@code decrypt} 안에서 Cipher 를
     * {@code synchronized} 로 감싸므로 여러 스레드가 공유해도 안전하다. 요청마다 만들지 않는다.
     */
    private final AesBytesEncryptor encryptor;

    /**
     * Lombok {@code @RequiredArgsConstructor} 를 쓰지 않는 이유는 {@code JwtService} 와 같다:
     * {@code encryptor} 는 주입받는 값이 아니라 <b>주입값에서 파생되는 값</b>이다.
     *
     * <p>검증을 생성자에서 하는 것이 핵심이다. 여기서 예외가 나면 스프링 컨텍스트 초기화가 실패해
     * <b>톰캣이 요청을 받기 전에</b> 죽는다. 설정 실수가 "조용히 잘 도는 것"이 최악이다 —
     * 결제에서는 몇 달 뒤 "복호화가 안 된다"로 드러나고, 그때는 되돌릴 방법이 없다.
     */
    public BillingCrypto(BillingCryptoProperties properties, Environment environment) {
        byte[] keyBytes = decodeAndValidate(properties.key(), environment);
        this.encryptor = new AesBytesEncryptor(
                new SecretKeySpec(keyBytes, "AES"),
                KeyGenerators.secureRandom(GCM_IV_BYTES),
                AesBytesEncryptor.CipherAlgorithm.GCM);
    }

    private byte[] decodeAndValidate(String key, Environment environment) {
        // ① 미주입 / 공백 / 해석 안 된 플레이스홀더.
        //    @ConfigurationProperties 는 해석 못 한 ${BILLING_CRYPTO_KEY} 를 예외 없이
        //    <리터럴 문자열로> 바인딩한다(@Value 와 다르다). 그대로 두면 알 수 없는 영어 예외만 남는다.
        if (key == null || key.isBlank() || key.startsWith("${")) {
            throw new IllegalStateException(
                    "결제 수단 암호화 키(app.billing-crypto.key)가 설정되지 않았습니다. "
                            + "BILLING_CRYPTO_KEY 환경변수에 Base64 로 인코딩한 32바이트 난수를 넣어주세요. "
                            + "예: openssl rand -base64 32");
        }

        // ② Base64 로 읽을 수 있는가.
        byte[] decoded;
        try {
            decoded = Base64.getDecoder().decode(key.trim());
        } catch (IllegalArgumentException e) {
            throw new IllegalStateException(
                    "결제 수단 암호화 키(app.billing-crypto.key)가 Base64 형식이 아닙니다. "
                            + "openssl rand -base64 32 의 출력을 그대로 넣어주세요.", e);
        }

        // ③ 저장소에 공개된 로컬 기본값인가. 개발이면 경고, 아니면 기동 중단.
        if (KNOWN_LOCAL_DEFAULT_KEY.equals(key.trim())) {
            String[] activeProfiles = environment.getActiveProfiles();
            // 프로파일이 하나도 없는 경우를 '개발'로 보는 트레이드오프는 JwtService 와 동일하다 —
            // 로컬 bootRun·IDE 실행·통합 테스트가 전부 프로파일 없이 돈다. 잔여 위험도 같이 상속한다.
            boolean development = activeProfiles.length == 0
                    || Arrays.stream(activeProfiles)
                    .anyMatch(profile -> DEVELOPMENT_PROFILES.contains(profile.toLowerCase(Locale.ROOT)));
            if (!development) {
                throw new IllegalStateException("""
                        결제 수단 암호화 키(app.billing-crypto.key)가 저장소에 공개된 로컬 기본값 그대로입니다. \
                        이 값을 아는 사람은 DB 만 손에 넣으면 전 고객의 빌링키를 복호화해 결제를 일으킬 수 있으므로 기동을 중단합니다.
                        → 배포 환경이라면: BILLING_CRYPTO_KEY 환경변수를 설정한 뒤 다시 실행하세요. (openssl rand -base64 32)
                        → 로컬 개발이라면: SPRING_PROFILES_ACTIVE=local 로 실행하거나 프로파일 없이 실행하세요.
                        현재 활성 프로파일: %s""".formatted(Arrays.toString(activeProfiles)));
            }
            log.warn("[BILLING] 저장소에 공개된 로컬 기본 암호화 키로 기동한다. 배포 환경에서는 반드시 BILLING_CRYPTO_KEY 를 설정할 것.");
        }

        // ④ 길이가 정확히 32바이트인가.
        //    🔴 이 검사가 가장 조용한 실패를 막는다 — JCE 는 16바이트 키를 주면 아무 말 없이
        //       AES-128 로 돈다. 확인하지 않으면 "AES-256 으로 저장합니다" 라고 말할 근거가 없다.
        if (decoded.length != AES_256_KEY_BYTES) {
            throw new IllegalStateException(
                    "결제 수단 암호화 키(app.billing-crypto.key)의 길이가 %d바이트입니다. AES-256 은 정확히 32바이트를 요구합니다. "
                            .formatted(decoded.length)
                            + "openssl rand -base64 32 로 새로 만들어 BILLING_CRYPTO_KEY 에 넣어주세요.");
        }
        return decoded;
    }

    /**
     * 평문 빌링키 → 저장 문자열.
     *
     * <p>결과는 {@code Base64(IV 12B ‖ 암호문 ‖ GCM 인증태그 16B)} 한 덩어리다.
     * IV 컬럼을 따로 두지 않는 이유는 {@code V6__billing_method.sql} 주석에 적어뒀다 —
     * IV 는 비밀이 아니고 암호문과 반드시 짝이라, 나누면 한쪽만 갱신·복사되어 어긋날 수 있다.
     */
    public String encrypt(String plaintext) {
        byte[] combined = encryptor.encrypt(plaintext.getBytes(StandardCharsets.UTF_8));
        return Base64.getEncoder().encodeToString(combined);
    }

    /**
     * 저장 문자열 → 평문 빌링키.
     *
     * <p>실패를 <b>한 종류로 뭉쳐서</b> 던진다. 이건 이 저장소가 반복해 낸 "서로 다른 사실을 같은 값으로
     * 뭉개는" 실수와는 성격이 다르다 — 여기서 갈라지는 원인(키가 다르다 · 데이터가 손상됐다 ·
     * Base64 가 깨졌다)은 <b>운영자가 할 일이 전부 같다</b>(고객에게 재등록 안내).
     * 오히려 라이브러리의 영어 {@code IllegalStateException("bad padding")} 을 그대로 흘리면
     * 무엇을 해야 하는지 알 수 없다.
     *
     * <p>🔴 <b>{@link ApiException} 으로 던지는 이유</b> (2026-09-09에 바꿨다). 예전의
     * {@code IllegalStateException} 은 {@code GlobalExceptionHandler} 의 마지막 그물에 걸려
     * <b>{@code INTERNAL_ERROR} 500 + "잠시 후 다시 시도해주세요"</b> 가 나갔다. 그런데 이 실패는
     * <b>재시도로 절대 안 풀린다.</b> 키를 잃었거나 행이 깨졌거나 변조된 것이다.
     * 2026-09-07 에 암호문 한 글자를 실제로 변조해 그 거짓 안내를 확인했다.
     * 무엇을 하면 되는지는 {@link ErrorCode#BILLING_METHOD_UNREADABLE} 에 적혀 있다.
     *
     * <p>⚠️ 대신 {@code log.error} 를 <b>여기서</b> 남긴다. {@code ApiException} 은 핸들러가
     * {@code log.warn} 한 줄로만 남기는데, 이 사건은 스택트레이스가 필요한 부류다.
     * (원인 예외가 GCM 태그 불일치인지 Base64 파손인지가 조사의 출발점이다)
     */
    public String decrypt(String stored) {
        try {
            byte[] combined = Base64.getDecoder().decode(stored);
            return new String(encryptor.decrypt(combined), StandardCharsets.UTF_8);
        } catch (RuntimeException e) {
            // GCM 인증태그 불일치는 AEADBadTagException → BadPaddingException 을 거쳐
            // spring-security-crypto 의 CipherUtils 가 IllegalStateException 으로 바꿔 던진다.
            // Base64 가 깨졌으면 IllegalArgumentException 이다. 둘 다 RuntimeException 이라 한 번에 받는다.
            //
            // 🔴 stored(암호문)를 로그에 남기지 않는다. 우리 DB 가 유일한 사본이라는 말은
            //    <로그로 새면 그것도 사본이 된다>는 뜻이다 (BillingService 의 같은 규칙).
            log.error("[BILLING] 저장된 결제 수단을 복호화하지 못했다. "
                    + "BILLING_CRYPTO_KEY 가 등록 당시와 다르거나 billing_key_enc 가 손상·변조됐다.", e);
            throw new ApiException(ErrorCode.BILLING_METHOD_UNREADABLE);
        }
    }
}
