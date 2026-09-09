package com.alldap.api.global.ratelimit;

import com.alldap.api.global.exception.ApiException;
import com.alldap.api.global.exception.ErrorCode;
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
     */
    private static final int MAX_KEYS = 100_000;

    private final Map<String, AtomicInteger> counters = new ConcurrentHashMap<>();

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
        return counter != null && counter.get() >= limit;
    }

    /** 한도 검사 없이 1 올리기만 한다. 판정은 {@link #isBlocked} 가 따로 한다. */
    public void record(String bucket, String client, Duration window) {
        increment(key(bucket, client, window));
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
            log.warn("[rate-limit] 키가 {}개를 넘어 카운터를 비운다.", MAX_KEYS);
            counters.clear();
        }

        // computeIfAbsent + incrementAndGet 조합이라 같은 키에 동시 요청이 와도 수를 잃지 않는다.
        return counters.computeIfAbsent(key, ignored -> new AtomicInteger()).incrementAndGet();
    }

    /** 테스트 격리용. 운영 코드에서 부르지 말 것. */
    public void reset() {
        counters.clear();
    }
}
