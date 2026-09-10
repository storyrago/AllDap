package com.alldap.api.global.client;

import com.alldap.api.global.config.AiServiceProperties;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.time.Duration;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 직접 만든 서킷브레이커의 상태 기계를 고정한다.
 *
 * <p>라이브러리(resilience4j) 대신 손으로 만들었으므로, 그 대가로 <b>동작을 테스트가 붙들고 있어야</b> 한다.
 * 스프링 컨텍스트를 띄우지 않는다 — 이 클래스는 프로퍼티만 받는 순수 객체라 그럴 이유가 없고,
 * 컨텍스트를 띄우면 테스트가 느려지는 만큼 자주 안 돌리게 된다.
 *
 * <p>열림 시간은 운영값(30초)이 아니라 <b>50ms</b> 로 준다. 운영값으로 테스트하면 HALF_OPEN 검증에
 * 30초를 기다려야 한다. 시간을 주입 가능하게 만든 덕에 가능한 일이다.
 */
class AiServiceCircuitBreakerTest {

    private static final Duration OPEN_FOR = Duration.ofMillis(50);

    private SimpleMeterRegistry registry;

    private double gauge() {
        return registry.get(AiServiceCircuitBreaker.STATE_GAUGE).gauge().value();
    }

    private double transitions(String to) {
        return registry.get(AiServiceCircuitBreaker.TRANSITION_COUNTER).tag("to", to).counter().count();
    }

    private AiServiceCircuitBreaker breaker(int threshold) {
        AiServiceProperties props = new AiServiceProperties(
                "http://localhost:8001",
                Duration.ofSeconds(3),
                Duration.ofSeconds(120),
                2,
                Duration.ofMillis(1),
                threshold,
                OPEN_FOR
        );
        registry = new SimpleMeterRegistry();
        return new AiServiceCircuitBreaker(props, registry);
    }

    @Test
    @DisplayName("임계치 미만의 실패로는 열리지 않는다 — 일시적 흔들림에 과민반응하면 안 된다")
    void staysClosedBelowThreshold() {
        AiServiceCircuitBreaker cb = breaker(3);

        cb.recordFailure();
        cb.recordFailure();

        assertThat(cb.allowRequest()).isTrue();
    }

    @Test
    @DisplayName("연속 실패가 임계치에 닿으면 열리고, 그 뒤 호출은 막힌다")
    void opensAtThreshold() {
        AiServiceCircuitBreaker cb = breaker(3);

        cb.recordFailure();
        cb.recordFailure();
        cb.recordFailure();

        assertThat(cb.allowRequest()).isFalse();
    }

    @Test
    @DisplayName("🔴 실패는 <연속>이어야 한다 — 사이에 성공이 끼면 카운터가 0 으로 돌아간다")
    void successResetsTheStreak() {
        AiServiceCircuitBreaker cb = breaker(3);

        cb.recordFailure();
        cb.recordFailure();
        cb.recordSuccess();     // 여기서 끊긴다
        cb.recordFailure();
        cb.recordFailure();

        // 총 실패는 4회지만 <연속>은 2회뿐이라 아직 닫혀 있어야 한다.
        // 이 구분이 없으면 하루 종일 드문드문 난 실패가 쌓여 멀쩡한 서비스를 차단한다.
        assertThat(cb.allowRequest()).isTrue();
    }

    @Test
    @DisplayName("열린 뒤 시간이 지나면 다시 통과시킨다 (HALF_OPEN — 살아났는지 두드려 본다)")
    void allowsProbeAfterOpenDuration() throws InterruptedException {
        AiServiceCircuitBreaker cb = breaker(1);

        cb.recordFailure();
        assertThat(cb.allowRequest()).isFalse();

        Thread.sleep(OPEN_FOR.toMillis() + 20);

        assertThat(cb.allowRequest()).isTrue();
    }

    @Test
    @DisplayName("탐색이 성공하면 완전히 닫힌다")
    void closesAfterSuccessfulProbe() throws InterruptedException {
        AiServiceCircuitBreaker cb = breaker(1);
        cb.recordFailure();
        Thread.sleep(OPEN_FOR.toMillis() + 20);

        cb.recordSuccess();     // 탐색 성공

        assertThat(cb.allowRequest()).isTrue();
        // 그리고 카운터도 리셋됐어야 한다 — 임계치가 1 이므로 한 번 더 실패하면 다시 열린다.
        cb.recordFailure();
        assertThat(cb.allowRequest()).isFalse();
    }

    @Test
    @DisplayName("🔴 탐색이 실패하면 <그 시점부터> 다시 쉰다 — 열린 시각이 갱신되어야 한다")
    void reopensFromProbeFailure() throws InterruptedException {
        AiServiceCircuitBreaker cb = breaker(1);
        cb.recordFailure();
        Thread.sleep(OPEN_FOR.toMillis() + 20);
        assertThat(cb.allowRequest()).isTrue();      // HALF_OPEN

        cb.recordFailure();                          // 탐색 실패

        // 시각을 갱신하지 않으면 이미 만료된 상태라 <곧바로 또 통과>한다.
        // 그러면 죽은 Python 을 계속 두드리게 되어 서킷의 존재 이유가 사라진다.
        assertThat(cb.allowRequest()).isFalse();
    }

    @Test
    @DisplayName("reset 은 열린 서킷도 닫는다 (테스트 간 오염 방지용)")
    void resetClosesEverything() {
        AiServiceCircuitBreaker cb = breaker(1);
        cb.recordFailure();
        assertThat(cb.allowRequest()).isFalse();

        cb.reset();

        assertThat(cb.allowRequest()).isTrue();
    }

    // ── 관측 (2026-09-11) ────────────────────────────────────────────────
    // 서킷 상태를 밖에서 볼 수 없던 것을 고쳤다. 지표는 <동작이 아니라 보임>이라 깨져도
    // 사용자에게 아무 일도 안 일어난다 = 아무도 모르게 죽는다. 그래서 테스트로 붙들어 둔다.

    @Test
    @DisplayName("[지표] 게이지가 닫힘(0) → 열림(2) → 탐색(1) 을 그대로 따라간다")
    void 게이지가_상태를_따라간다() throws InterruptedException {
        AiServiceCircuitBreaker cb = breaker(1);
        assertThat(gauge()).isZero();

        cb.recordFailure();
        assertThat(gauge()).isEqualTo(2);       // OPEN

        Thread.sleep(OPEN_FOR.toMillis() + 20);
        assertThat(gauge()).isEqualTo(1);       // HALF_OPEN — 시간이 지나 파생된 값이다

        cb.recordSuccess();
        assertThat(gauge()).isZero();
    }

    @Test
    @DisplayName("[지표] 🔴 30초짜리 열림을 스크레이프가 놓쳐도 전이 카운터에는 남는다")
    void 전이는_카운터로_남는다() throws InterruptedException {
        AiServiceCircuitBreaker cb = breaker(1);

        cb.recordFailure();                     // 닫힘 → 열림
        Thread.sleep(OPEN_FOR.toMillis() + 20);
        cb.allowRequest();                      // HALF_OPEN 탐색
        cb.recordFailure();                     // 탐색 실패 → 다시 막기 시작
        Thread.sleep(OPEN_FOR.toMillis() + 20);
        cb.recordSuccess();                     // 탐색 성공 → 닫힘

        // 게이지만 있었다면 이 시점에 0 하나만 보이고 그 사이 일은 전부 사라진다.
        assertThat(transitions("open")).isEqualTo(2);
        assertThat(transitions("closed")).isEqualTo(1);
    }

    @Test
    @DisplayName("[지표] 닫혀 있는 동안의 성공은 전이로 세지 않는다 — 안 그러면 카운터가 요청 수가 된다")
    void 닫힌_상태의_성공은_전이가_아니다() {
        AiServiceCircuitBreaker cb = breaker(3);

        cb.recordSuccess();
        cb.recordSuccess();

        assertThat(transitions("closed")).isZero();
    }
}
