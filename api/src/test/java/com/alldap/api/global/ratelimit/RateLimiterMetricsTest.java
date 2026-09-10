package com.alldap.api.global.ratelimit;

import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.search.MeterNotFoundException;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.time.Duration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.assertj.core.api.Assertions.catchThrowable;

/**
 * 요청 제한기의 지표를 테스트로 고정한다.
 *
 * <p><b>왜 고정하는가.</b> 부하테스트 S3(rate limit 정확성)가 "429 가 제한기에서 나왔다" 를
 * 증명하는 근거가 이 지표다. 그런데 지표는 조용히 사라질 수 있다: 호출을 빼먹어도,
 * 이름을 오타로 바꿔도 컴파일은 통과하고 테스트도 전부 초록불이다.
 * 이 저장소는 "짜둔 검사가 아무 데서도 안 도는" 사고를 이미 두 번 겪었다
 * (오픈 리다이렉트, 배포 점검 명령). 그래서 호출되는 것 자체를 검사로 남긴다.
 *
 * <p>가장 중요한 것은 {@code mode} 태그다. {@code check} 의 거절과 {@code isBlocked} 의 거절은
 * <b>차단 연장 여부가 다른 서로 다른 사실</b>인데, 지표에서 한 값으로 뭉개지면 구별할 방법이
 * 아예 없어진다({@code rejectionModesAreSeparateSeries}).
 *
 * <p>스프링 컨텍스트를 띄우지 않는다. {@link RateLimiter} 는 {@link MeterRegistry} 하나만 받는
 * 순수 객체다({@code BillingCryptoTest}, {@code AiServiceCircuitBreakerTest} 와 같은 판단).
 */
@DisplayName("요청 제한기 지표")
class RateLimiterMetricsTest {

    private static final Duration WINDOW = Duration.ofMinutes(1);

    private MeterRegistry registry;
    private RateLimiter rateLimiter;

    @BeforeEach
    void setUp() {
        registry = new SimpleMeterRegistry();
        rateLimiter = new RateLimiter(registry);
    }

    private double rejected(String bucket, String mode) {
        try {
            return registry.get("alldap.ratelimit.rejected")
                    .tags("bucket", bucket, "mode", mode)
                    .counter().count();
        } catch (MeterNotFoundException e) {
            // 아직 거절이 한 번도 없으면 시계열 자체가 없다. 0 과 같은 뜻이다.
            // (Micrometer 는 태그 조합이 처음 쓰일 때 미터를 만든다)
            return 0.0;
        }
    }

    @Test
    @DisplayName("한도 안에서는 거절 지표가 생기지 않는다")
    void noRejectionWithinLimit() {
        rateLimiter.check("widget-chat", "1.2.3.4|pk_a", 3, WINDOW);
        rateLimiter.check("widget-chat", "1.2.3.4|pk_a", 3, WINDOW);
        rateLimiter.check("widget-chat", "1.2.3.4|pk_a", 3, WINDOW);

        assertThat(rejected("widget-chat", "check")).isZero();
    }

    @Test
    @DisplayName("check 의 거절은 mode=check 로 버킷 태그와 함께 센다")
    void checkRejectionIsCounted() {
        for (int i = 0; i < 2; i++) {
            rateLimiter.check("widget-chat", "1.2.3.4|pk_a", 2, WINDOW);
        }

        // 3번째와 4번째는 거절된다.
        assertThatThrownBy(() -> rateLimiter.check("widget-chat", "1.2.3.4|pk_a", 2, WINDOW))
                .isInstanceOf(com.alldap.api.global.exception.ApiException.class);
        catchThrowable(() -> rateLimiter.check("widget-chat", "1.2.3.4|pk_a", 2, WINDOW));

        assertThat(rejected("widget-chat", "check")).isEqualTo(2.0);
        // 다른 버킷으로 새지 않는다.
        assertThat(rejected("widget-config", "check")).isZero();
    }

    @Test
    @DisplayName("버킷이 다르면 시계열도 다르다")
    void bucketsAreSeparateSeries() {
        catchThrowable(() -> rateLimiter.check("widget-chat", "ip|pk", 0, WINDOW));
        catchThrowable(() -> rateLimiter.check("widget-config", "ip|pk", 0, WINDOW));
        catchThrowable(() -> rateLimiter.check("login", "ip", 0, WINDOW));

        assertThat(rejected("widget-chat", "check")).isEqualTo(1.0);
        assertThat(rejected("widget-config", "check")).isEqualTo(1.0);
        assertThat(rejected("login", "check")).isEqualTo(1.0);
    }

    @Test
    @DisplayName("🔴 check 의 거절과 isBlocked 의 거절은 같은 값으로 뭉개지지 않는다")
    void rejectionModesAreSeparateSeries() {
        // 로그인 실패 경로: record 로 쌓고, isBlocked 가 판정한다.
        rateLimiter.record("login-failure", "1.2.3.4|a@b.com", WINDOW);
        rateLimiter.record("login-failure", "1.2.3.4|a@b.com", WINDOW);

        assertThat(rateLimiter.isBlocked("login-failure", "1.2.3.4|a@b.com", 2, WINDOW)).isTrue();
        assertThat(rateLimiter.isBlocked("login-failure", "1.2.3.4|a@b.com", 2, WINDOW)).isTrue();

        // 막힌 뒤 두 번 더 두드렸으니 거절은 2건이다.
        assertThat(rejected("login-failure", "blocked")).isEqualTo(2.0);
        // 🔴 그런데 그 2건은 카운터를 올리지 않았다 = 차단이 연장되지 않았다.
        //    check 의 거절과 섞이면 이 사실을 지표에서 되물을 수 없다.
        assertThat(rejected("login-failure", "check")).isZero();
    }

    @Test
    @DisplayName("isBlocked 가 통과시키면 거절로 세지 않는다")
    void passingIsBlockedIsNotCounted() {
        rateLimiter.record("login-failure", "1.2.3.4|a@b.com", WINDOW);

        assertThat(rateLimiter.isBlocked("login-failure", "1.2.3.4|a@b.com", 5, WINDOW)).isFalse();
        assertThat(rejected("login-failure", "blocked")).isZero();
    }

    @Test
    @DisplayName("record 는 누적으로 따로 세고 거절로 세지 않는다")
    void recordIsCountedSeparately() {
        rateLimiter.record("login-failure", "1.2.3.4|a@b.com", WINDOW);
        rateLimiter.record("login-failure", "5.6.7.8|c@d.com", WINDOW);

        assertThat(registry.get("alldap.ratelimit.recorded")
                .tag("bucket", "login-failure").counter().count()).isEqualTo(2.0);
        assertThat(rejected("login-failure", "blocked")).isZero();
        assertThat(rejected("login-failure", "check")).isZero();
    }

    @Test
    @DisplayName("키 수 게이지가 들고 있는 카운터 수를 따라간다")
    void keysGaugeFollowsMapSize() {
        assertThat(registry.get("alldap.ratelimit.keys").gauge().value()).isZero();

        rateLimiter.check("widget-chat", "1.1.1.1|pk_a", 10, WINDOW);
        rateLimiter.check("widget-chat", "2.2.2.2|pk_a", 10, WINDOW);
        rateLimiter.check("widget-chat", "1.1.1.1|pk_a", 10, WINDOW); // 같은 키라 늘지 않는다

        assertThat(registry.get("alldap.ratelimit.keys").gauge().value()).isEqualTo(2.0);
    }

    @Test
    @DisplayName("어떤 태그에도 IP·publicKey·이메일이 들어가지 않는다 (카디널리티·개인정보)")
    void clientIdentifiersNeverBecomeTags() {
        catchThrowable(() -> rateLimiter.check("widget-chat", "1.2.3.4|pk_secret", 0, WINDOW));
        rateLimiter.record("login-failure", "5.6.7.8|a@b.com", WINDOW);

        assertThat(registry.getMeters())
                .filteredOn(m -> m.getId().getName().startsWith("alldap.ratelimit"))
                .isNotEmpty()
                .allSatisfy(meter -> assertThat(meter.getId().getTags())
                        .allSatisfy(tag -> assertThat(tag.getValue())
                                .doesNotContain("1.2.3.4")
                                .doesNotContain("5.6.7.8")
                                .doesNotContain("pk_secret")
                                .doesNotContain("a@b.com")));
    }

    /**
     * MAX_KEYS 초과 clear 가 지표로 보이는지 확인한다.
     *
     * <p>🔴 <b>이 테스트가 동시에 폭발 반경을 증명한다</b>: 위젯 키만 10만 개 넣었는데
     * 먼저 쌓아둔 {@code login-failure} 누적까지 사라진다. clear 가 버킷을 안 가린다는 뜻이다.
     * 이번 슬라이스에서 고치지 않기로 한 것이므로, 고치면 <b>이 테스트가 깨지는 것이 정상</b>이다.
     *
     * <p>키 10만 개를 실제로 넣는다. ConcurrentHashMap 에 문자열 키를 넣는 것뿐이라 1초 안에 끝난다.
     */
    @Test
    @DisplayName("MAX_KEYS 초과로 비우면 clear 지표가 오르고, 다른 버킷 누적도 함께 날아간다")
    void clearIsObservableAndWipesOtherBuckets() {
        rateLimiter.record("login-failure", "1.2.3.4|a@b.com", Duration.ofMinutes(15));
        rateLimiter.record("login-failure", "1.2.3.4|a@b.com", Duration.ofMinutes(15));
        rateLimiter.record("login-failure", "1.2.3.4|a@b.com", Duration.ofMinutes(15));
        rateLimiter.record("login-failure", "1.2.3.4|a@b.com", Duration.ofMinutes(15));
        rateLimiter.record("login-failure", "1.2.3.4|a@b.com", Duration.ofMinutes(15));
        assertThat(rateLimiter.isBlocked("login-failure", "1.2.3.4|a@b.com", 5, Duration.ofMinutes(15)))
                .isTrue();

        assertThat(registry.get("alldap.ratelimit.keys.cleared").counter().count()).isZero();

        // 요청마다 다른 publicKey 를 넣는 공격 모양. 100_001 개를 넘기는 순간 clear 가 돈다.
        for (int i = 0; i < 100_002; i++) {
            rateLimiter.check("widget-chat", "1.2.3.4|pk_" + i, 20, WINDOW);
        }

        assertThat(registry.get("alldap.ratelimit.keys.cleared").counter().count()).isEqualTo(1.0);
        assertThat(registry.get("alldap.ratelimit.keys").gauge().value())
                .isLessThan(100_000.0);

        // 🔴 폭발 반경: 위젯 트래픽만으로 15분짜리 로그인 실패 차단이 풀렸다.
        assertThat(rateLimiter.isBlocked("login-failure", "1.2.3.4|a@b.com", 5, Duration.ofMinutes(15)))
                .isFalse();
    }
}
