package com.alldap.api.global.client;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import org.springframework.stereotype.Component;

import java.time.Duration;

/**
 * Python AI 서비스 호출을 <b>밖에서 볼 수 있게</b> 만든다. 동작은 하나도 바꾸지 않는다.
 *
 * <p><b>왜 만들었나 — 지금 지표에서 뭉개지는 사실이 있다.</b>
 * {@link AiServiceClient} 는 실패를 이미 꼼꼼히 갈라 놓았는데(연결 실패 503 · 타임아웃 504 ·
 * Python 5xx 503 · 서킷 급속 거절 503), <b>밖에서 보면 그게 전부 같은 값이다.</b>
 * {@code http_server_requests_seconds_count{status="503"}} 한 줄에 셋이 겹쳐 있다.
 * 그중 둘은 원인도 대응도 완전히 다르다:
 * <ul>
 *   <li><b>서킷이 막은 503</b> — 수 ms 에 돌아온다. Python 을 부르지도 않았다.
 *       "이미 죽은 줄 알고 있었다" 는 뜻이라 볼 곳은 <b>그 앞의 실패들</b>이다.</li>
 *   <li><b>연결 실패 503</b> — 연결 타임아웃(3초)에 재시도까지 붙어 수 초를 쓴다.
 *       톰캣 스레드를 그만큼 붙잡는다. 볼 곳은 <b>지금 이 순간의 Python</b> 이다.</li>
 * </ul>
 * 이 저장소가 반복해서 낸 버그가 정확히 이 모양이다(AGENTS.md "낸 버그 7건: 전부 같은 부류다").
 * 원인이 다른 사실을 같은 값으로 뭉개는 것. 그래서 <b>새 신호를 만들 때마다</b> 같은 질문을 한다:
 * "여기서 뭉개지는 서로 다른 사실이 있는가."
 *
 * <p><b>왜 ErrorCode 를 나누지 않고 지표만 나눴는가.</b> 이 저장소는 2026-09-09 에
 * {@code ANSWER_INCOMPLETE} · {@code BILLING_METHOD_UNREADABLE} 로 응답 코드를 가른 전례가 있다.
 * 그때의 기준은 <b>"안내 문구가 거짓말이 되는가"</b> 였다 — 재시도로 안 풀리는데 "잠시 후 다시
 * 시도해주세요" 라고 말하는 것이 문제였다. 그 기준을 여기 대보면 <b>가를 이유가 없다.</b>
 * 서킷은 30초 뒤에 스스로 닫히므로 "잠시 후 다시 시도해주세요" 가 <b>정확히 맞는 안내</b>고,
 * 사용자가 할 수 있는 행동도 연결 실패일 때와 똑같다. 사용자에게는 같은 사실이고
 * <b>운영자에게만 다른 사실</b>이므로, 갈라야 할 곳은 응답이 아니라 관측이다.
 * (응답 코드를 나눴다면 프론트의 분기와 한국어 문구까지 늘어나는데, 그렇게 늘린 것으로
 * 사용자가 할 수 있는 일은 하나도 없다.)
 *
 * <p><b>왜 Timer 인가 — 카운터 두 개가 아니라.</b> 위 두 503 의 결정적 차이는 <b>지연</b>이다
 * (수 ms 대 수 초). Timer 하나면 {@code count} 로 "몇 번" 을, {@code sum} 으로 "얼마나 오래" 를
 * 같은 태그 위에서 준다. 카운터로 했으면 "급속" 이라는 말이 근거 없는 주장으로 남는다.
 *
 * <p><b>히스토그램 버킷은 켜지 않는다.</b> 여기서 알고 싶은 것은 p99 가 아니라
 * "이 경로가 ms 단위인가 초 단위인가" 라, {@code sum/count} 로 충분하다.
 * 버킷을 켜면 {@code operation × outcome} 조합마다 시계열이 수십 개씩 는다.
 *
 * <p><b>내보내는 것</b> (Prometheus 이름 기준)
 * <ul>
 *   <li>{@code alldap_ai_call_seconds_count|sum{operation,outcome}} — 호출 결과별 횟수와 걸린 시간</li>
 *   <li>{@code alldap_ai_retry_total{operation}} — 재시도한 횟수(연결 실패에만 붙는다)</li>
 * </ul>
 * 서킷 상태 자체는 {@link AiServiceCircuitBreaker} 가 낸다.
 */
@Component
public class AiServiceMetrics {

    /** 호출 <시도>의 결과. {@code AiServiceClient.call()} 의 분기와 1:1 로 대응한다. */
    public enum Outcome {

        /** 정상 응답. */
        SUCCESS("success"),

        /** 🔴 서킷이 열려 있어 <b>Python 을 부르지도 않고</b> 즉시 거절했다. 급속 503 이 이것이다. */
        CIRCUIT_OPEN("circuit_open"),

        /** 연결 자체가 안 됐다(거부·연결 타임아웃). 재시도가 붙는 유일한 경로이고, 느린 503 이 이것이다. */
        CONNECT_FAILURE("connect_failure"),

        /** 연결은 됐는데 응답이 안 왔다(읽기 타임아웃). 504. */
        READ_TIMEOUT("read_timeout"),

        /** 응답을 받는 도중 끊겼다. Python 이 처리 중 죽은 경우. */
        CONNECTION_LOST("connection_lost"),

        /** Python 이 5xx 로 답했다 = 스스로 고장났다고 말한 것이다. */
        PYTHON_SERVER_ERROR("python_5xx"),

        /** Python 이 4xx 로 거절했다 = <b>우리가 잘못 호출했거나</b> 사용자 파일이 잘못된 것이다. */
        PYTHON_CLIENT_ERROR("python_4xx"),

        /** 답변이 잘렸다(재시도로 안 풀린다). Python 장애가 아니다. */
        ANSWER_INCOMPLETE("answer_incomplete"),

        /** 응답은 받았는데 DTO 로 못 읽었다 = 우리 코드가 낡았다. */
        DECODE_ERROR("decode_error");

        private final String tag;

        Outcome(String tag) {
            this.tag = tag;
        }

        public String tag() {
            return tag;
        }
    }

    static final String CALL_TIMER = "alldap.ai.call";
    static final String RETRY_COUNTER = "alldap.ai.retry";

    private final MeterRegistry registry;

    public AiServiceMetrics(MeterRegistry registry) {
        this.registry = registry;
    }

    /**
     * 호출 한 건이 끝났다.
     *
     * <p>미터를 미리 만들어두지 않고 매번 {@code Timer.builder(...).register(...)} 를 부른다.
     * Micrometer 의 register 는 <b>같은 이름·태그면 기존 미터를 돌려주는</b> 멱등 연산이라
     * 새로 만들지 않는다. 조합마다 필드를 두면 아홉 결과 × 아홉 종류를 손으로 나열해야 한다.
     *
     * @param elapsed 서킷 검사부터 실패 판정까지. 급속 거절이면 사실상 0 이고, 그게 이 값의 요점이다
     */
    public void recordCall(AiOperation operation, Outcome outcome, Duration elapsed) {
        Timer.builder(CALL_TIMER)
                .description("Python AI 서비스 호출 1건. outcome 이 실패 원인을 가른다.")
                .tag("operation", operation.tag())
                .tag("outcome", outcome.tag())
                .register(registry)
                .record(elapsed);
    }

    /**
     * 재시도를 한 번 했다.
     *
     * <p>호출 <b>건수</b>가 아니라 <b>재시도 횟수</b>를 센다. 두 값을 나누면
     * ({@code rate(alldap_ai_retry_total) / rate(alldap_ai_call_seconds_count)})
     * "요청 하나가 평균 몇 번 다시 시도되는가" 가 나온다. 이 값이 0 보다 커지는 순간이
     * <b>서킷이 열리기 전에 오는 첫 신호</b>다 — 아직 성공하고 있지만 이미 흔들리는 구간이다.
     */
    public void recordRetry(AiOperation operation) {
        Counter.builder(RETRY_COUNTER)
                .description("연결 실패로 Python 호출을 다시 시도한 횟수")
                .tag("operation", operation.tag())
                .register(registry)
                .increment();
    }
}
