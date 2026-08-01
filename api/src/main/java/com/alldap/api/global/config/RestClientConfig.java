package com.alldap.api.global.config;

import lombok.RequiredArgsConstructor;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.ClientHttpRequestFactory;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

import java.net.http.HttpClient;

/**
 * Python AI 서비스(:8001) 호출용 {@link RestClient} 설정.
 *
 * <p><b>왜 타임아웃이 이 파일에서 가장 중요한가.</b>
 * CLAUDE.md 에 적힌 이 아키텍처의 알려진 약점이 "Spring 이 Python 을 동기 호출하므로
 * Python 이 죽으면 채팅이 죽는다" 이다. 타임아웃이 없으면 Python 이 응답하지 않을 때
 * Spring 의 요청 스레드와 DB 커넥션이 무한정 묶여서, 결국 Spring 까지 같이 죽는다.
 * 장애를 Python 안에 가두려면 타임아웃이 반드시 있어야 한다.
 *
 * <p><b>연결 타임아웃과 읽기 타임아웃을 나눈 이유.</b>
 * <ul>
 *   <li><b>연결(connect) 3초</b> — 같은 내부망이라 TCP 연결은 밀리초 단위로 끝나야 정상이다.
 *       3초를 넘겼다는 건 "느린 것"이 아니라 "Python 이 떠 있지 않은 것"에 가깝다.
 *       빨리 실패시켜 사용자에게 상태를 알려주는 편이 낫다.</li>
 *   <li><b>읽기(read) 120초</b> — 여기는 반대로 길게 잡아야 한다.
 *       Python 이 하는 일이 외부 LLM API 호출(임베딩·답변 생성)이라 응답까지 수십 초가 걸릴 수 있다.
 *       흔한 기본값(5~10초)을 그대로 두면 <b>정상 동작 중인 요청</b>을 우리가 끊어버리게 되고,
 *       그러면 이미 과금된 LLM 호출을 버리는 셈이라 손해가 두 배다.
 *       (문서 업로드는 202 로 즉시 응답하고 백그라운드 처리라 오래 걸리지 않는다.
 *        긴 읽기 타임아웃이 실제로 필요한 쪽은 POST /internal/chat 이다.)</li>
 * </ul>
 *
 * <p><b>왜 JdkClientHttpRequestFactory 인가.</b>
 * JDK 11+ 에 내장된 {@code java.net.http.HttpClient} 를 쓰므로 별도 HTTP 클라이언트 의존성
 * (Apache HttpClient, OkHttp)을 추가하지 않아도 된다. 연결 타임아웃은 {@code HttpClient} 쪽에,
 * 읽기 타임아웃은 팩토리 쪽에 설정하는 구조라 두 값을 나눠 줄 수 있다.
 */
@Configuration
@RequiredArgsConstructor
public class RestClientConfig {

    private final AiServiceProperties aiServiceProperties;

    @Bean
    public RestClient aiServiceRestClient() {
        HttpClient httpClient = HttpClient.newBuilder()
                // ⚠️ HTTP/1.1 을 명시하는 이 한 줄이 없으면 <문서 업로드가 실패한다>. 종단 확인에서 잡았다.
                //
                // JDK HttpClient 의 기본값은 HTTP_2 다. 평문(http://) 상대에게는 HTTP/2 를 바로 쓸 수 없으므로
                // "HTTP/1.1 로 시작하되 h2c 로 올려달라"는 업그레이드 요청을 함께 보낸다.
                //   Connection: Upgrade, HTTP2-Settings
                //   Upgrade: h2c
                // 그런데 Python 쪽 uvicorn(h11)은 h2c 업그레이드를 지원하지 않는다.
                // 로그에 "Unsupported upgrade request" 를 남기고 HTTP/1.1 로 계속 처리하는데,
                // 이때 <chunked 본문이 FastAPI 까지 전달되지 않는다>.
                // 결과: multipart 본문 자체는 완벽한데 Python 은 "file 필드가 없다"며 422 를 낸다.
                //
                // 우리 상대는 내부망의 uvicorn 하나뿐이고 HTTP/2 로 얻을 이득(멀티플렉싱)도 없다.
                // 협상 자체를 하지 않는 편이 단순하고 안전하다.
                .version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(aiServiceProperties.connectTimeout())
                .build();

        JdkClientHttpRequestFactory requestFactory = new JdkClientHttpRequestFactory(httpClient);
        requestFactory.setReadTimeout(aiServiceProperties.readTimeout());

        return buildClient(requestFactory);
    }

    private RestClient buildClient(ClientHttpRequestFactory requestFactory) {
        return RestClient.builder()
                .baseUrl(aiServiceProperties.baseUrl())
                .requestFactory(requestFactory)
                .build();

        // TODO(W2): 재시도(retry). 다만 무조건 재시도하면 안 된다.
        //   - 연결 실패/5xx 처럼 "요청이 처리되지 않은 게 확실한" 경우만 재시도한다.
        //   - POST /internal/bots/{id}/documents 는 재시도하면 문서 행이 중복 생성되므로 제외한다.
        //   - POST /internal/chat 재시도는 LLM 비용이 두 배로 나가므로 신중히 결정할 것.
        // TODO(W2): 서킷브레이커(resilience4j). 연속 실패가 임계치를 넘으면 일정 시간 호출을 끊고
        //   AI_SERVICE_UNAVAILABLE 을 즉시 반환해, 죽은 Python 을 계속 두드리다 스레드가 마르는 걸 막는다.
        //   (PRD §10.3 "Spring→Python 호출에는 타임아웃과 재시도를 반드시 설정한다"의 나머지 절반)
    }
}
