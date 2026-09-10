package com.alldap.api.global.client;

import com.alldap.api.global.config.AiServiceProperties;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.MeterRegistry;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.concurrent.atomic.AtomicInteger;

/**
 * Python AI 서비스가 죽었을 때 <계속 두드리지 않도록> 호출을 끊는다.
 *
 * <p><b>왜 필요한가.</b> 이 아키텍처의 알려진 약점이 "Spring 이 Python 을 동기 호출하므로
 * Python 이 죽으면 채팅이 죽는다" 이다. 타임아웃(RestClientConfig)이 <b>한 요청</b>을 구해주지만,
 * Python 이 완전히 죽은 상태에서 요청이 계속 들어오면 매 요청이 3초(연결 타임아웃)씩 스레드를
 * 붙잡는다. 초당 수십 건이면 톰캣 스레드 풀이 마르고, <b>Python 장애가 Spring 장애로 번진다.</b>
 * 서킷브레이커는 그 전파를 끊는다 — 죽은 걸 알면 시도조차 하지 않고 즉시 안내한다.
 *
 * <p><b>왜 resilience4j 를 안 썼나.</b> 이 프로젝트는 Boot 4.0.7 인데 resilience4j 의
 * Spring Boot 스타터는 Boot 3 계열 기준이라 호환이 확인되지 않았다. 그리고 우리가 필요한 것은
 * 상태 3개짜리 카운터 하나뿐이다. 라이브러리 하나를 더 얹어 기동이 막히는 위험보다
 * 이 40줄을 직접 갖고 있는 편이 낫다고 봤다. 대신 <b>동작을 테스트로 고정</b>했다.
 *
 * <p><b>무엇을 "실패"로 세는가 — 이게 이 클래스에서 가장 중요하다.</b>
 * <ul>
 *   <li>✅ 연결 실패 · 읽기 타임아웃 · Python 5xx · 응답 도중 끊김 → <b>Python 이 아프다</b></li>
 *   <li>❌ Python 4xx → <b>우리가 잘못 호출했다.</b> Python 은 멀쩡히 판단해서 거절한 것이다</li>
 *   <li>❌ 응답 해석 실패(DTO 불일치) → 우리 코드가 낡은 것이다</li>
 * </ul>
 * 뒤 두 가지를 세면 <b>우리 버그 때문에 멀쩡한 Python 을 차단</b>하게 된다.
 * 그러면 원인은 그대로인 채 증상만 "AI 서비스 점검 중" 으로 바뀌어 조사가 엉뚱한 데로 간다.
 *
 * <p><b>스레드 안전성.</b> 여러 요청 스레드가 동시에 부른다. 연속 실패 수는 {@link AtomicInteger},
 * 열린 시각은 {@code volatile} 로 둔다.
 * ⚠️ HALF_OPEN 에서 <b>동시에 여러 요청이 통과할 수 있다.</b> 엄밀한 구현은 한 건만 흘려보내지만,
 * 여기서는 그게 문제되지 않는다 — Python 이 살아났으면 전부 성공하고, 아직 죽었으면 전부 실패해
 * 곧바로 다시 열린다. 정확히 한 건만 보내려면 락이 필요한데 그 복잡도를 살 이유가 없다.
 */
@Slf4j
@Component
public class AiServiceCircuitBreaker {

    /** {@code openedAtNanos} 가 이 값이면 닫힘(정상). {@code nanoTime()} 이 0 일 수도 있어 0 을 안 쓴다. */
    private static final long NOT_OPEN = Long.MIN_VALUE;

    static final String STATE_GAUGE = "alldap.ai.circuit.state";
    static final String TRANSITION_COUNTER = "alldap.ai.circuit.transition";

    /**
     * 서킷이 지금 어느 모드인가. <b>필드로 저장하지 않는다</b> — OPEN 과 HALF_OPEN 은
     * "열린 시각" 하나에서 시간으로 파생되는 값이라, 따로 들고 있으면 두 사실이 어긋날 수 있다.
     *
     * <p>{@code code} 는 지표에 실어 보내는 숫자다. <b>커질수록 나쁜 쪽</b>으로 순서를 맞췄다 —
     * 그래야 Grafana 에서 {@code max_over_time(...)} 한 줄로 "이 구간에 제일 나빴던 상태" 를 뽑는다.
     */
    public enum State {
        CLOSED(0),
        HALF_OPEN(1),
        OPEN(2);

        private final int code;

        State(int code) {
            this.code = code;
        }

        public int code() {
            return code;
        }
    }

    private final AiServiceProperties properties;
    private final Counter openedCounter;
    private final Counter closedCounter;

    private final AtomicInteger consecutiveFailures = new AtomicInteger();
    private volatile long openedAtNanos = NOT_OPEN;

    /**
     * <p><b>지표를 왜 게이지 하나로 내는가.</b> Prometheus 관례로는 상태를
     * {@code state="open"} 같은 태그로 갈라 0/1 을 내는 방식(state set)도 있다. 여기서는
     * <b>숫자 하나</b>로 낸다. 이 값의 쓸모가 "부하 곡선과 같은 시간축에 언제 모드가 바뀌었는지를
     * 겹쳐 보는 것" 이라서다 — 한 줄이 0 → 2 → 1 → 0 으로 계단을 그리는 편이 세 줄을 겹쳐
     * 읽는 것보다 낫다. 부하테스트 PR 3 이 {@code process_start_time_seconds} 로 재시작 경계를
     * 그림에 표시한 것과 같은 역할이다.
     *
     * <p><b>게이지만으로는 부족해서 전이 카운터를 함께 낸다.</b> 게이지는 스크레이프 순간의 값만
     * 남긴다. 서킷은 30초만 열려 있으므로 <b>스크레이프 간격이 그보다 길거나 운 나쁘게 어긋나면
     * 열렸던 사실이 통째로 사라진다.</b> 카운터는 단조 증가라 그 사이에 일어난 일도 남는다.
     * 즉 게이지는 "지금·언제", 카운터는 "몇 번" 을 맡는다.
     */
    public AiServiceCircuitBreaker(AiServiceProperties properties, MeterRegistry registry) {
        this.properties = properties;
        this.openedCounter = Counter.builder(TRANSITION_COUNTER)
                .description("서킷 상태가 바뀐 횟수")
                .tag("to", "open")
                .register(registry);
        this.closedCounter = Counter.builder(TRANSITION_COUNTER)
                .description("서킷 상태가 바뀐 횟수")
                .tag("to", "closed")
                .register(registry);
        Gauge.builder(STATE_GAUGE, this, cb -> cb.state().code())
                .description("AI 서비스 서킷 상태 (0=닫힘 1=탐색 2=열림)")
                .register(registry);
    }

    /** 지금 상태. 읽기만 하며 아무것도 바꾸지 않는다(게이지가 스크레이프마다 부른다). */
    public State state() {
        long openedAt = openedAtNanos;
        if (openedAt == NOT_OPEN) {
            return State.CLOSED;
        }
        return System.nanoTime() - openedAt < properties.circuitOpenDuration().toNanos()
                ? State.OPEN
                : State.HALF_OPEN;
    }

    /**
     * 지금 Python 을 호출해도 되는가.
     *
     * @return 닫힘(정상)이거나 열린 지 충분히 지났으면(=탐색해볼 때) true
     */
    public boolean allowRequest() {
        // OPEN 이면 막고, CLOSED(정상)·HALF_OPEN(살아났는지 두드려 본다)이면 통과시킨다.
        return state() != State.OPEN;
    }

    /** 호출이 성공했다. 서킷을 닫고 카운터를 리셋한다. */
    public void recordSuccess() {
        if (openedAtNanos != NOT_OPEN) {
            log.info("[AI 서킷] 닫힘 — Python 이 응답했다.");
            closedCounter.increment();
        }
        consecutiveFailures.set(0);
        openedAtNanos = NOT_OPEN;
    }

    /** <b>Python 장애로 판단되는</b> 실패가 났다 (클래스 주석의 판정 기준 참고). */
    public void recordFailure() {
        int failures = consecutiveFailures.incrementAndGet();
        if (failures >= properties.circuitFailureThreshold()) {
            // 열려 있지 <않던> 상태에서 열리는 것만 전이로 센다. HALF_OPEN 탐색이 실패해
            // 다시 쉬는 것도 여기 포함된다 — 그것도 "다시 막기 시작했다" 는 별개의 사건이다.
            // ⚠️ 동시에 여러 스레드가 임계치를 넘기면 드물게 두 번 셀 수 있다. 이 값은
            //    "몇 번 열렸나" 의 눈금이지 정산 대상이 아니라, 락을 걸어 살 만한 정확도가 아니다.
            if (state() != State.OPEN) {
                openedCounter.increment();
            }
            // 이미 열려 있어도 시각을 갱신한다 = HALF_OPEN 탐색이 실패하면 다시 그 시점부터 쉰다.
            openedAtNanos = System.nanoTime();
            log.error("[AI 서킷] 열림 — 연속 {}회 실패. {} 동안 호출하지 않고 즉시 안내한다.",
                    failures, properties.circuitOpenDuration());
        }
    }

    /** 테스트에서 실행 간 상태가 새는 것을 막는다. 운영 코드에서는 부르지 않는다. */
    public void reset() {
        consecutiveFailures.set(0);
        openedAtNanos = NOT_OPEN;
    }
}
