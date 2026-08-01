package com.alldap.api.support;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Queue;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Python AI 서비스(:8001) 자리에 세우는 <b>가짜 HTTP 서버</b>.
 *
 * <h2>⚠️ {@code setExecutor} 를 빠뜨리면 테스트가 서로를 오염시킨다 (실제로 겪은 함정)</h2>
 * {@code HttpServer.create()} 만 하고 executor 를 지정하지 않으면 JDK 는 기본 구현
 * ({@code task.run()} — 새 스레드를 만들지 않는다)을 쓴다. 그러면 <b>모든 요청이
 * 디스패처 스레드 하나에서 순차 처리</b>되므로, {@link #enqueueSlow} 의 {@code Thread.sleep} 이
 * 그 요청 하나가 아니라 <b>서버 전체를 멈춘다.</b>
 *
 * <p>결과가 고약하다. "느린 Python → 504" 테스트가 끝난 뒤에도 스텁은 몇 초 더 마비 상태라,
 * 바로 다음 테스트의 요청이 잠든 서버에 막혀 <b>엉뚱한 504</b> 를 받는다.
 * {@link #reset()} 은 큐와 기록만 비울 뿐 잠들어 있는 핸들러는 되돌리지 못한다.
 * 게다가 이 실패는 JUnit 의 메서드 실행 순서에 따라 나타났다 사라져서,
 * <b>테스트를 하나 추가하거나 이름만 바꿔도 갑자기 깨진다.</b>
 * (운영 코드는 멀쩡한데 테스트만 깨지는, 원인 추적이 가장 어려운 종류다)
 *
 * <p>그래서 아래 생성자에서 스레드 풀을 명시적으로 준다.
 *
 * <h2>왜 진짜 HTTP 서버를 세우는가 (모킹 대신)</h2>
 * 이 슬라이스에서 검증하려는 것 대부분이 <b>HTTP 경계에서만 드러난다.</b>
 * <ul>
 *   <li>multipart 본문에 <b>파일명이 실려 나가는가</b> — 안 실리면 Python 이 확장자를 못 읽어
 *       멀쩡한 PDF 도 거절한다. 이건 바이트를 봐야 알 수 있다</li>
 *   <li>Python 이 죽었을 때 <b>503</b> 이 나오는가 — {@code AiServiceClient} 를 Mockito 로 흉내내면
 *       "우리가 상상한 예외"를 검증할 뿐, 실제로 어떤 예외가 오는지는 영원히 모른다</li>
 *   <li>읽기 타임아웃이 <b>504</b> 로 번역되는가 — 진짜로 늦게 응답해야 재현된다</li>
 * </ul>
 *
 * <h2>왜 WireMock 이 아니라 JDK 내장 서버인가</h2>
 * {@code com.sun.net.httpserver.HttpServer} 는 JDK 에 들어 있어 <b>의존성이 0개</b>다.
 * 필요한 기능이 "정해둔 응답 돌려주기 + 받은 요청 기록하기" 둘뿐이라
 * 라이브러리를 하나 더 들이는 값을 하지 못한다.
 *
 * <h2>포트를 0으로 여는 이유</h2>
 * 0은 "OS 가 비어 있는 포트를 골라달라"는 뜻이다. 8001 로 고정하면
 * 개발 중 진짜 Python 이 떠 있을 때 충돌해 "내 코드는 안 건드렸는데 테스트가 깨진다".
 * 실제 포트는 {@link #baseUrl()} 로 알아내 {@code app.ai-service.base-url} 에 주입한다
 * ({@link TestcontainersConfiguration} 참고).
 */
public class AiServiceStub implements AutoCloseable {

    private final HttpServer server;

    /**
     * 요청마다 스레드를 주는 풀. 이유는 클래스 주석의 "setExecutor 함정" 참고.
     *
     * <p>{@code newCachedThreadPool} 인 이유: 테스트가 동시에 던지는 요청이 많아야 몇 개라
     * 고정 크기를 정할 근거가 없다. 놀고 있는 스레드는 60초 뒤 알아서 회수된다.
     */
    private final ExecutorService executor = Executors.newCachedThreadPool();

    /**
     * 테스트가 미리 넣어두는 응답 대기열. 요청이 오면 앞에서 하나씩 꺼내 쓴다.
     *
     * <p>{@code Concurrent} 계열인 이유: 요청을 처리하는 스레드(HttpServer 의 워커)와
     * 응답을 넣는 스레드(테스트)가 서로 다르다. 평범한 {@code LinkedList} 를 쓰면
     * 눈에 안 보이는 경합이 생겨 가끔 실패하는 테스트가 된다.
     */
    private final Queue<Canned> canned = new ConcurrentLinkedQueue<>();

    /** 스텁이 실제로 받은 요청들. 테스트가 "무엇이 나갔는지" 확인하는 데 쓴다. */
    private final List<Recorded> received = Collections.synchronizedList(new ArrayList<>());

    /** 준비해 둔 응답 하나. {@code delay} 는 타임아웃 재현용, {@code abort} 는 "처리 중 죽음" 재현용. */
    private record Canned(int status, String body, Duration delay, boolean abort) {
    }

    /**
     * 스텁이 받은 요청 하나.
     *
     * @param method HTTP 메서드
     * @param path   경로 (쿼리 제외)
     * @param body   본문 — multipart 원본 바이트를 문자열로 본다.
     *               바이너리가 섞여 있어도 파일명·필드명 같은 <b>ASCII 헤더 부분은 그대로 읽힌다.</b>
     */
    public record Recorded(String method, String path, String body) {
    }

    public AiServiceStub() {
        try {
            server = HttpServer.create(new InetSocketAddress(0), 0);
        } catch (IOException e) {
            throw new IllegalStateException("가짜 AI 서비스를 띄우지 못했습니다.", e);
        }
        server.createContext("/", this::handle);
        server.setExecutor(executor);   // ← 이 한 줄이 빠지면 클래스 주석의 오염 사고가 난다
        server.start();
    }

    public String baseUrl() {
        return "http://localhost:" + server.getAddress().getPort();
    }

    /**
     * 스프링 컨텍스트가 닫힐 때 자동으로 호출된다
     * (스프링은 {@code AutoCloseable} 빈의 {@code close()} 를 소멸 콜백으로 잡아준다).
     *
     * <p>{@code HttpServer} 의 디스패처 스레드와 우리 스레드 풀은 <b>데몬 스레드가 아니라서</b>,
     * 정리하지 않으면 테스트가 다 끝나도 JVM 이 종료되지 않을 수 있다.
     */
    @Override
    public void close() {
        server.stop(0);
        executor.shutdownNow();
    }

    // ── 테스트가 쓰는 조작 API ────────────────────────────────────────────

    /** 다음 요청에 이 응답을 돌려준다. */
    public void enqueue(int status, String body) {
        canned.add(new Canned(status, body, Duration.ZERO, false));
    }

    /** 다음 요청에 {@code delay} 만큼 늦게 응답한다. 읽기 타임아웃을 재현할 때 쓴다. */
    public void enqueueSlow(Duration delay, int status, String body) {
        canned.add(new Canned(status, body, delay, false));
    }

    /**
     * 다음 요청에 <b>응답하지 않고 연결을 끊는다.</b> "Python 이 처리 중 죽었다"를 재현한다.
     *
     * <p>연결 자체가 거부되는 상황(프로세스가 아예 없음)과 완전히 같지는 않지만,
     * 클라이언트가 받는 결과는 똑같이 "응답을 못 받은 I/O 실패"라 같은 분기를 탄다.
     */
    public void enqueueAbort() {
        canned.add(new Canned(0, null, Duration.ZERO, true));
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
        received.add(new Recorded(
                exchange.getRequestMethod(),
                exchange.getRequestURI().getPath(),
                new String(requestBody, StandardCharsets.UTF_8)));

        Canned response = canned.poll();
        if (response == null) {
            // 준비 안 된 요청이 오면 조용히 성공시키지 않는다.
            // 500 으로 답해야 "테스트가 예상 못 한 호출이 나갔다"는 사실이 드러난다.
            respond(exchange, 500, "{\"detail\":\"스텁에 준비된 응답이 없습니다\"}");
            return;
        }

        if (response.abort()) {
            exchange.close();   // 응답 헤더도 안 보내고 끊는다 → 클라이언트는 I/O 실패로 본다
            return;
        }

        if (!response.delay().isZero()) {
            try {
                Thread.sleep(response.delay());
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();   // 인터럽트 상태를 삼키지 않는다
                return;
            }
        }

        respond(exchange, response.status(), response.body());
    }

    private void respond(HttpExchange exchange, int status, String body) throws IOException {
        byte[] bytes = body == null ? new byte[0] : body.getBytes(StandardCharsets.UTF_8);

        // 한국어 에러 메시지가 오가므로 charset 을 명시한다. 빠뜨리면 클라이언트가
        // 기본 charset 으로 디코딩해 문구가 깨지고, "코드는 멀쩡한데 테스트만 실패"한다.
        exchange.getResponseHeaders().add("Content-Type", "application/json; charset=utf-8");

        // 204 는 본문을 가질 수 없다. 길이를 -1 로 주면 "본문 없음"이라는 뜻이다.
        exchange.sendResponseHeaders(status, status == 204 || bytes.length == 0 ? -1 : bytes.length);

        if (bytes.length > 0 && status != 204) {
            try (OutputStream out = exchange.getResponseBody()) {
                out.write(bytes);
            }
        }
        exchange.close();
    }
}
