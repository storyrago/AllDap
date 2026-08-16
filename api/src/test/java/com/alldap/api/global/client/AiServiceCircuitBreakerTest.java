package com.alldap.api.global.client;

import com.alldap.api.global.config.AiServiceProperties;
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
        return new AiServiceCircuitBreaker(props);
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
}
