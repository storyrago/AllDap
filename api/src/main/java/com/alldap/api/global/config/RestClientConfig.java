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

    /**
     * 헬스체크 전용 클라이언트. 위 {@link #aiServiceRestClient()} 와 <b>타임아웃만</b> 다르다.
     *
     * <p><b>왜 따로 두는가.</b> 읽기 120초는 LLM 을 기다리는 채팅을 위한 값이다. 헬스체크가 그 값을
     * 물려받으면, Python 이 연결은 받되 응답을 안 하는(멈춘) 상태에서 {@code /actuator/health} 한 번이
     * 2분을 매달린다. 헬스체크는 "지금 대답할 수 있는가" 를 묻는 것이라 대답이 늦은 것 자체가 답이다.
     * 연결·읽기 모두 {@code health-timeout}(기본 2초) 하나로 묶는다.
     *
     * <p>Python 의 {@code /health} 는 {@code SELECT 1} 한 번이라 밀리초 단위로 끝난다. 2초는 여유다.
     * (근거가 얕은 값이다. 실측이 아니라 판단이다)
     */
    @Bean
    public RestClient aiServiceHealthRestClient() {
        HttpClient httpClient = HttpClient.newBuilder()
                // HTTP/1.1 고정 이유는 위 aiServiceRestClient 의 주석과 같다(uvicorn 이 h2c 업그레이드를 모른다).
                .version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(aiServiceProperties.healthTimeout())
                .build();

        JdkClientHttpRequestFactory requestFactory = new JdkClientHttpRequestFactory(httpClient);
        requestFactory.setReadTimeout(aiServiceProperties.healthTimeout());

        return buildClient(requestFactory);
    }

    private RestClient buildClient(ClientHttpRequestFactory requestFactory) {
        return RestClient.builder()
                .baseUrl(aiServiceProperties.baseUrl())
                .requestFactory(requestFactory)
                .build();

        // ✅ 재시도·서킷브레이커는 2026-08-17 에 붙였다. 둘 다 AiServiceClient.call() 안에 있다.
        //
        // ⚠️ 여기 있던 TODO 의 분류가 <틀렸었다>. "연결 실패/5xx 처럼 요청이 처리되지 않은 게
        //    확실한 경우만 재시도" 라고 적혀 있었는데, **5xx 는 Python 이 응답했다는 뜻 =
        //    요청이 도달했다는 뜻**이다. 도달한 요청은 이미 문서 행을 만들었거나 LLM 을
        //    호출했을 수 있다. 재시도가 안전한 것은 <연결 자체가 안 된 경우>뿐이다.
        //
        //    그리고 그렇게 좁히면 "업로드는 제외" 라던 예외도 필요 없어진다 —
        //    요청이 안 갔으니 중복될 행이 없다. 그래서 호출부마다 켜고 끄지 않고
        //    call() 안에서 일괄 처리한다. 자세한 근거는 AiServiceClient.attemptWithRetry 주석.
    }
}
