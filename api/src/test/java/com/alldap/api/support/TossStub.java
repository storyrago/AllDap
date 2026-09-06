package com.alldap.api.support;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Queue;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * 토스페이먼츠 자리에 세우는 <b>가짜 HTTP 서버</b>. {@link AiServiceStub} 과 같은 패턴이다.
 *
 * <h2>왜 진짜 HTTP 서버를 세우는가 (Mockito 대신)</h2>
 * 이 슬라이스에서 검증하려는 것 대부분이 <b>HTTP 경계에서만 드러난다.</b>
 * <ul>
 *   <li>{@code Authorization} 이 {@code base64(secretKey + ":")} 인가 — <b>바이트를 봐야</b> 안다.
 *       콜론이 빠져도 자바 코드는 멀쩡히 컴파일되고, 실패는 토스에서만 드러난다</li>
 *   <li>재시도가 <b>같은 {@code Idempotency-Key}</b> 를 쓰는가 — 실제로 나간 두 요청을 비교해야 안다.
 *       {@code TossClient} 를 Mockito 로 흉내내면 "우리가 상상한 호출" 만 검증하게 된다</li>
 *   <li>연결이 끊겼을 때 어떤 예외가 오는가 — 진짜로 끊어야 재현된다.
 *       이 저장소는 <b>통합 테스트 71건이 전부 초록불인 상태에서</b> HTTP/2 업그레이드 버그를 놓쳤다</li>
 * </ul>
 *
 * <h2>왜 WireMock 이 아니라 JDK 내장 서버인가</h2>
 * {@code com.sun.net.httpserver.HttpServer} 는 JDK 에 들어 있어 <b>의존성이 0개</b>다.
 * 필요한 기능이 "정해둔 응답 돌려주기 + 받은 요청 기록하기" 둘뿐이라
 * 라이브러리를 하나 더 들이는 값을 하지 못한다.
 *
 * <h2>⚠️ {@code setExecutor} 를 빠뜨리면 테스트가 서로를 오염시킨다</h2>
 * {@link AiServiceStub} 클래스 주석에 겪은 사고가 적혀 있다. 여기도 같은 이유로 스레드 풀을 준다
 * (지금은 느린 응답 기능이 없어 증상이 덜하지만, 나중에 누가 추가하는 순간 같은 함정에 빠진다).
 *
 * <h2>포트를 0으로 여는 이유</h2>
 * OS 가 비어 있는 포트를 고르게 한다. 실제 포트는 {@link #baseUrl()} 로 알아내
 * {@code app.toss.base-url} 에 주입한다({@link TestcontainersConfiguration} 참고).
 *
 * <h2>왜 {@link AiServiceStub} 과 합치지 않았는가</h2>
 * 중복된 ~140줄은 <b>{@code HttpServer} 배관</b>이고 외부 계약과 무관하다. 계약 차이는 세 군데뿐이다 —
 * 빈 큐 응답 본문({@code {"detail"}} vs {@code {"code","message"}}) · {@code hasHeader(boolean)} vs
 * {@code header(String)} · {@code enqueueSlow} 부재.
 * <p>그럼에도 합치지 않는 이유는 <b>공통화하면 {@link AiServiceStub} 을 쓰는 기존 131건의 지지대를
 * 건드리기 때문</b>이다. 얻는 것은 거의 안 바뀌는 테스트 지원 코드 140줄이고, 잃는 것은 초록불
 * 스위트에 대한 리스크다.
 * <p>{@code enqueueSlow} 부재는 <b>의도된 갈라짐</b>이다 — {@code AiServiceClient} 는 연결 실패(503)와
 * 읽기 타임아웃(504)을 가르지만 {@code TossClient} 는 둘을 한 블록으로 받아 같은 503 을 준다.
 * 느린 응답 재현이 없어도 커버리지 구멍이 아니다.
 */
public class TossStub implements AutoCloseable {

    private final HttpServer server;
    private final ExecutorService executor = Executors.newCachedThreadPool();

    /** 테스트가 미리 넣어두는 응답 대기열. 요청 처리 스레드와 테스트 스레드가 다르므로 Concurrent 계열이다. */
    private final Queue<Canned> canned = new ConcurrentLinkedQueue<>();

    /** 스텁이 실제로 받은 요청들. "무엇이 나갔는지" 를 확인하는 데 쓴다. */
    private final List<Recorded> received = Collections.synchronizedList(new ArrayList<>());

    private record Canned(int status, String body, boolean abort) {
    }

    /**
     * @param headers 요청 헤더. 이름은 <b>소문자로 정규화</b>해 담는다(HTTP 헤더는 대소문자를 구분하지 않는다).
     */
    public record Recorded(String method, String path, String body, Map<String, String> headers) {

        /** 없으면 null. {@code Idempotency-Key} → {@code "idempotency-key"} 로 찾는다. */
        public String header(String name) {
            return headers.get(name.toLowerCase(Locale.ROOT));
        }
    }

    public TossStub() {
        try {
            server = HttpServer.create(new InetSocketAddress(0), 0);
        } catch (IOException e) {
            throw new IllegalStateException("가짜 토스 서버를 띄우지 못했습니다.", e);
        }
        server.createContext("/", this::handle);
        server.setExecutor(executor);
        server.start();
    }

    public String baseUrl() {
        return "http://localhost:" + server.getAddress().getPort();
    }

    /**
     * 스프링이 {@code AutoCloseable} 빈의 {@code close()} 를 소멸 콜백으로 잡아준다.
     * 디스패처 스레드와 풀이 데몬이 아니라, 정리하지 않으면 JVM 이 종료되지 않을 수 있다.
     */
    @Override
    public void close() {
        server.stop(0);
        executor.shutdownNow();
    }

    // ── 테스트가 쓰는 조작 API ────────────────────────────────────────────

    /** 다음 요청에 이 응답을 돌려준다. */
    public void enqueue(int status, String body) {
        canned.add(new Canned(status, body, false));
    }

    /**
     * 다음 요청에 <b>응답하지 않고 연결을 끊는다.</b> "토스와의 통신이 끊겼다" 를 재현한다.
     * 클라이언트가 받는 결과는 연결 거부·읽기 타임아웃과 같은 "응답을 못 받은 I/O 실패" 라
     * {@code TossClient} 의 같은 재시도 분기를 탄다.
     */
    public void enqueueAbort() {
        canned.add(new Canned(0, null, true));
    }

    public List<Recorded> received() {
        return List.copyOf(received);
    }

    /** 테스트 사이의 격리. 대기열과 기록을 함께 비운다. */
    public void reset() {
        canned.clear();
        received.clear();
    }

    // ── 요청 처리 ────────────────────────────────────────────────────────

    private void handle(HttpExchange exchange) throws IOException {
        byte[] requestBody = exchange.getRequestBody().readAllBytes();

        Map<String, String> headers = new HashMap<>();
        exchange.getRequestHeaders().forEach((name, values) ->
                headers.put(name.toLowerCase(Locale.ROOT), String.join(",", values)));

        received.add(new Recorded(
                exchange.getRequestMethod(),
                exchange.getRequestURI().getPath(),
                new String(requestBody, StandardCharsets.UTF_8),
                headers));

        Canned response = canned.poll();
        if (response == null) {
            // 준비 안 된 요청을 조용히 성공시키지 않는다. 500 으로 답해야
            // "테스트가 예상 못 한 호출이 나갔다" 는 사실이 드러난다.
            respond(exchange, 500, "{\"code\":\"STUB_NOT_READY\",\"message\":\"스텁에 준비된 응답이 없습니다\"}");
            return;
        }

        if (response.abort()) {
            exchange.close();   // 응답 헤더도 안 보내고 끊는다 → 클라이언트는 I/O 실패로 본다
            return;
        }

        respond(exchange, response.status(), response.body());
    }

    private void respond(HttpExchange exchange, int status, String body) throws IOException {
        byte[] bytes = body == null ? new byte[0] : body.getBytes(StandardCharsets.UTF_8);

        // 토스의 한국어 에러 문구가 오가므로 charset 을 명시한다. 빠뜨리면 클라이언트가
        // 기본 charset 으로 디코딩해 문구가 깨지고, "코드는 멀쩡한데 테스트만 실패" 한다.
        exchange.getResponseHeaders().add("Content-Type", "application/json; charset=utf-8");
        exchange.sendResponseHeaders(status, status == 204 || bytes.length == 0 ? -1 : bytes.length);

        if (bytes.length > 0 && status != 204) {
            try (OutputStream out = exchange.getResponseBody()) {
                out.write(bytes);
            }
        }
        exchange.close();
    }
}
