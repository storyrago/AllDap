package com.alldap.api.global.ratelimit;

import com.alldap.api.global.exception.ApiException;
import com.alldap.api.global.exception.ErrorCode;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.MeterRegistry;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * 아주 단순한 <b>인메모리 고정 윈도우</b> 요청 제한기.
 *
 * <h2>왜 필요한가</h2>
 * 위젯 API 는 이 서비스에서 유일하게 인증 없이 열려 있는 문이다. 그런데 채팅 한 번은
 * <b>외부 LLM 호출 = 실제 돈</b>이다. 제한이 없으면 요금 폭탄이 곧 서비스 거부 공격이 된다.
 * Origin 검증은 브라우저 밖에서는 위조할 수 있으므로, <b>결정적 방어는 여기다.</b>
 *
 * <h2>왜 라이브러리(Bucket4j·Resilience4j)를 안 썼나</h2>
 * 필요한 기능이 "같은 키로 1분에 N번" 하나뿐이다. 그 한 줄짜리 규칙 때문에 의존성을 들이면
 * 나중에 버전 관리·설정 학습 비용이 붙는다. 아래 구현은 40줄이고 읽으면 바로 이해된다.
 * 토큰 버킷의 부드러운 유량 제어가 실제로 필요해지면 그때 바꾼다.
 *
 * <h2>⚠️ 알고 택한 한계 — 인스턴스가 늘면 무력해진다</h2>
 * 카운터가 <b>이 프로세스의 메모리</b>에 있다. 서버를 2대로 늘리면 각자 세므로 실질 한도가 2배가 되고,
 * 재시작하면 카운터가 초기화된다. 제대로 하려면 Redis 같은 공유 저장소가 필요한데,
 * 그건 <b>운영해야 할 것이 하나 더 늘어난다</b>는 뜻이다(PRD §11.2 원칙).
 * 1인 개발·단일 인스턴스인 지금은 이 트레이드오프가 맞다.
 * <b>수평 확장을 시작하는 시점이 교체 시점이다.</b>
 *
 * <h2>고정 윈도우의 경계 문제도 알고 넘어간다</h2>
 * 윈도우가 딱 끊기므로 12:00:59 에 N번, 12:01:00 에 N번을 몰아 2초 안에 2N번이 통과할 수 있다.
 * 슬라이딩 윈도우로 막을 수 있지만 코드가 몇 배 복잡해진다.
 * 우리 목적은 "정밀한 유량 제어" 가 아니라 "무한 호출 차단" 이라 이 정도로 충분하다.
 *
 * <h2>관측 (Micrometer)</h2>
 * 거절이 일어난 것을 <b>밖에서 볼 수 있어야</b> 한다. HTTP 상태만 보면 알 수 없기 때문이다:
 * {@link ErrorCode#RATE_LIMIT_EXCEEDED} 와 {@link ErrorCode#TOO_MANY_LOGIN_FAILURES} 가
 * <b>둘 다 429</b> 라, 429 곡선만으로는 위젯 채팅 거절인지 로그인 브루트포스 차단인지 구별되지 않는다.
 *
 * <ul>
 *   <li>{@code alldap.ratelimit.rejected} (counter, 태그 {@code bucket} {@code mode}) 거절 횟수</li>
 *   <li>{@code alldap.ratelimit.recorded} (counter, 태그 {@code bucket}) {@link #record} 로 쌓은 횟수</li>
 *   <li>{@code alldap.ratelimit.keys} (gauge) 지금 들고 있는 키 수</li>
 *   <li>{@code alldap.ratelimit.keys.cleared} (counter) {@link #MAX_KEYS} 초과로 통째로 비운 횟수</li>
 * </ul>
 *
 * <p>🔴 <b>{@code mode} 태그를 둔 이유: 거절 둘의 의미가 다르다.</b> 뭉개면 안 된다.
 * <ul>
 *   <li>{@code mode="check"} ({@link #check}) 세고 나서 판정한다. 막힌 요청도 카운터를 올리므로
 *       <b>두드릴수록 차단이 연장된다.</b></li>
 *   <li>{@code mode="blocked"} ({@link #isBlocked}) 쌓인 것을 보기만 하고 판정한다. 카운터를 올리지 않아
 *       <b>막힌 뒤에 더 두드려도 차단이 연장되지 않는다.</b></li>
 * </ul>
 * 같은 이름 한 값으로 합치면 "이 트래픽이 차단 기간을 늘리고 있는가" 를 지표에서 되물을 수 없게 된다.
 * 이 저장소가 반복해서 낸 버그가 정확히 그 부류다(AGENTS.md "낸 버그 7건").
 *
 * <p>⚠️ 키(IP·publicKey·이메일)는 <b>태그에 넣지 않는다.</b> 시계열이 무한히 늘어나 Prometheus 가
 * 죽고, 무엇보다 <b>개인정보를 지표로 내보내는 것</b>이 된다. 버킷 이름은 넷뿐이라 안전하다.
 */
@Slf4j
@Component
public class RateLimiter {

    /**
     * 키가 무한히 쌓이는 것을 막는 상한. 넘으면 통째로 비운다.
     *
     * <p>정교한 만료(TTL) 대신 이렇게 한 이유: 지난 윈도우의 키는 어차피 쓸모가 없고,
     * 비워봐야 최악의 경우 그 순간의 카운터가 초기화될 뿐이라 손해가 작다.
     * 반대로 정리를 안 하면 IP 마다 키가 쌓여 <b>메모리 누수</b>가 된다.
     *
     * <h2>🔴 그런데 비우는 범위가 <b>버킷을 안 가린다</b> (알고 남긴 것)</h2>
     * {@code counters.clear()} 는 맵 전체를 지운다. 즉 <b>위젯 키를 10만 개 흘리면
     * 15분짜리 {@code login-failure} 카운터까지 함께 날아간다.</b> 공격자가 매 요청 다른
     * publicKey 를 넣어 키를 부풀리면, 그것만으로 로그인 실패 누적 차단이 초기화된다.
     *
     * <p>⚠️ {@code WidgetController.requirePlausiblePublicKey} 가 이 통로를 막아준다고 <b>믿지 말 것</b>.
     * 그 검사는 {@code "pk_"} 접두사와 길이 32자 이하만 본다. {@code pk_1}, {@code pk_2} ...
     * 처럼 형식을 맞춘 서로 다른 값은 여전히 무한히 만들 수 있으므로, 10만 건을 보내는 난이도가
     * 거의 그대로다. 그 주석이 "형식만 확인하면 그 통로 자체를 막을 수 있다" 고 적은 것은 과장이다
     * (좁히기는 하지만 닫지는 못한다).
     *
     * <p>이번 슬라이스에서 <b>고치지 않았다.</b> 이 작업의 범위는 동작을 바꾸지 않고
     * <b>보이게 만드는 것</b>이다. 대신 {@code alldap.ratelimit.keys.cleared} 로
     * <b>언제 일어났는지를 부하 곡선과 같은 시간축에서</b> 볼 수 있게 했다.
     * 고칠 때의 방향은 버킷별로 맵을 나누거나(폭발 반경을 버킷 안으로 가둔다) 오래된 윈도우 키만
     * 골라 지우는 것이다. 둘 다 동작 변경이라 별도 슬라이스다.
     */
    private static final int MAX_KEYS = 100_000;

    private final Map<String, AtomicInteger> counters = new ConcurrentHashMap<>();

    private final MeterRegistry meterRegistry;

    /** {@link #MAX_KEYS} 초과로 통째로 비운 횟수. 위 주석의 "폭발 반경" 사건이 실제로 났는지를 센다. */
    private final Counter keysClearedCounter;

    public RateLimiter(MeterRegistry meterRegistry) {
        this.meterRegistry = meterRegistry;

        // 게이지는 <값을 밀어넣는> 것이 아니라 스크레이프 때 맵을 들여다본다.
        // counters 는 이 싱글턴이 계속 들고 있으므로 Micrometer 의 약한 참조가 끊길 일이 없다.
        Gauge.builder("alldap.ratelimit.keys", counters, Map::size)
                .description("제한기가 지금 들고 있는 카운터 키 수. MAX_KEYS 에 가까워지면 clear 가 임박한 것이다.")
                .register(meterRegistry);

        this.keysClearedCounter = Counter.builder("alldap.ratelimit.keys.cleared")
                .description("MAX_KEYS 초과로 카운터 맵을 통째로 비운 횟수. 버킷을 가리지 않으므로 태그가 없다.")
                .register(meterRegistry);
    }

    /**
     * 한도를 넘으면 {@link ErrorCode#RATE_LIMIT_EXCEEDED}(429)를 던진다.
     *
     * @param bucket 제한을 따로 세고 싶은 단위. 예: {@code "widget-chat"}
     * @param client 누구를 셀 것인가. 예: {@code "1.2.3.4|pk_abc"}
     * @param limit  윈도우당 허용 횟수
     * @param window 윈도우 길이
     */
    public void check(String bucket, String client, int limit, Duration window) {
        int used = increment(key(bucket, client, window));

        if (used > limit) {
            log.warn("[rate-limit] 한도 초과 bucket={} client={} used={}/{}", bucket, client, used, limit);
            // mode="check": 이 거절은 카운터를 <올린 뒤> 난 것이다 = 두드릴수록 차단이 연장된다.
            countRejection(bucket, "check");
            throw new ApiException(ErrorCode.RATE_LIMIT_EXCEEDED);
        }
    }

    /**
     * 이미 쌓인 횟수가 한도 <b>이상</b>인가. 보기만 하고 세지 않는다.
     *
     * <p>{@link #check} 와 나눠둔 이유: 로그인 실패 제한처럼 <b>세는 시점과 막는 시점이 다른</b>
     * 용도가 있다. 실패는 비밀번호를 대조한 <b>뒤에</b>야 알 수 있는데, 막는 것은 대조하기
     * <b>전에</b> 해야 한다. 대조 뒤에 막으면 공격자가 맞는 비밀번호를 찾아낸 그 요청은 그냥 통과한다.
     *
     * <p>세지 않으므로 <b>막힌 뒤에 더 두드려도 차단 기간이 늘어나지 않는다.</b>
     * 늘어나게 하면 공격자가 계속 두드리는 것만으로 차단을 무한정 연장할 수 있다.
     */
    public boolean isBlocked(String bucket, String client, int limit, Duration window) {
        AtomicInteger counter = counters.get(key(bucket, client, window));
        boolean blocked = counter != null && counter.get() >= limit;

        if (blocked) {
            // mode="blocked": 카운터를 올리지 않은 거절이다 = 이 요청은 차단 기간을 늘리지 않았다.
            //
            // ⚠️ 여기서 세는 것은 "거절했다" 가 아니라 정확히는 "막으라고 답했다" 다. 호출자가 그 답을
            //    무시하고 통과시키면 지표가 거짓이 된다. 지금은 호출자가 AuthService.login 하나뿐이고
            //    true 를 받는 즉시 TOO_MANY_LOGIN_FAILURES 를 던지므로 둘이 같다.
            //    호출자가 늘어나면 이 가정을 다시 확인할 것.
            countRejection(bucket, "blocked");
        }

        return blocked;
    }

    /**
     * 한도 검사 없이 1 올리기만 한다. 판정은 {@link #isBlocked} 가 따로 한다.
     *
     * <p>이것도 따로 센다({@code alldap.ratelimit.recorded}). 쌓는 것과 거절하는 것은 <b>다른 사실</b>이라,
     * 이 값이 없으면 {@code login-failure} 버킷의 거절 곡선에 분모가 없다. 실패가 쌓이다가 차단이
     * 시작되는 모습을 보려면 둘이 같은 시간축에 있어야 한다.
     */
    public void record(String bucket, String client, Duration window) {
        increment(key(bucket, client, window));

        Counter.builder("alldap.ratelimit.recorded")
                .description("record() 로 쌓은 횟수. 거절이 아니라 누적이다.")
                .tag("bucket", bucket)
                .register(meterRegistry)
                .increment();
    }

    /** 이 키의 누적을 지운다. 로그인에 성공했을 때처럼 "쌓인 실패가 무효가 되는" 경우에 쓴다. */
    public void forget(String bucket, String client, Duration window) {
        counters.remove(key(bucket, client, window));
    }

    /**
     * 윈도우 번호를 키에 섞는다. 윈도우가 넘어가면 키가 통째로 달라지므로
     * 만료 처리를 따로 하지 않아도 지난 카운터가 자연히 버려진다.
     */
    private String key(String bucket, String client, Duration window) {
        long windowIndex = System.currentTimeMillis() / window.toMillis();
        return bucket + "|" + client + "|" + windowIndex;
    }

    private int increment(String key) {
        if (counters.size() > MAX_KEYS) {
            // 🔴 버킷을 가리지 않고 전부 지운다. 폭발 반경은 MAX_KEYS 주석에 적어뒀다.
            log.warn("[rate-limit] 키가 {}개를 넘어 카운터를 비운다. (버킷 구분 없이 전부)", MAX_KEYS);
            counters.clear();
            keysClearedCounter.increment();
        }

        // computeIfAbsent + incrementAndGet 조합이라 같은 키에 동시 요청이 와도 수를 잃지 않는다.
        return counters.computeIfAbsent(key, ignored -> new AtomicInteger()).incrementAndGet();
    }

    /**
     * 거절을 센다. 키(IP·publicKey·이메일)는 <b>태그에 넣지 않는다</b>(카디널리티 폭발 + 개인정보).
     *
     * @param mode {@code "check"} 또는 {@code "blocked"}. 차이는 클래스 주석 "관측" 절 참고.
     */
    private void countRejection(String bucket, String mode) {
        Counter.builder("alldap.ratelimit.rejected")
                .description("요청 제한기가 거절한 횟수. mode 로 차단 연장 여부가 갈린다.")
                .tag("bucket", bucket)
                .tag("mode", mode)
                .register(meterRegistry)
                .increment();
    }

    /**
     * 테스트 격리용. 운영 코드에서 부르지 말 것.
     *
     * <p>지표는 되돌리지 않는다. Micrometer 카운터는 단조 증가여야 하고(Prometheus 가 감소를
     * 재시작으로 해석한다), 무엇보다 {@code keys.cleared} 와 구별이 안 되게 된다.
     */
    public void reset() {
        counters.clear();
    }
}
