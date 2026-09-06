package com.alldap.api.global.config;

import lombok.RequiredArgsConstructor;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpHeaders;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

import java.net.http.HttpClient;
import java.nio.charset.StandardCharsets;
import java.util.Base64;

/**
 * 토스페이먼츠 호출용 {@link RestClient}.
 *
 * <p>🔴 <b>{@code aiServiceRestClient} 와 빈을 공유하지 않는다.</b> 공유하면 두 상대가
 * 커넥션 풀과 타임아웃을 나눠 쓰게 되어 <b>토스 장애가 채팅을 끊고, 그 반대도 된다.</b>
 * 이 프로젝트가 이미 문서화한 약점("Python 이 죽으면 채팅이 죽는다")을 결제까지 번지게 하는 셈이다.
 *
 * <p><b>타임아웃을 AI 서비스와 다르게 잡은 이유.</b>
 * <ul>
 *   <li><b>연결 3초</b> — AI 와 같다. 다만 이유는 다르다. 저쪽은 내부망이라 3초면 "안 떠 있다"는 뜻이고,
 *       이쪽은 공인망이라 3초가 그냥 넉넉한 값이다.</li>
 *   <li><b>읽기 10초</b> — AI 는 120초다. 그쪽은 LLM 이 수십 초 걸리는 게 <b>정상</b>이지만,
 *       빌링키 발급은 카드사 인증 결과를 확인만 하는 호출이라 정상값이 1~3초다.
 *       120초를 그대로 쓰면 카드 등록 화면 앞의 사용자를 2분 동안 세워둔다.</li>
 * </ul>
 *
 * <p>⚠️ <b>10초의 대가를 적어둔다.</b> 읽기 타임아웃이 나도 토스는 이미 빌링키를 발급했을 수 있고,
 * 토스에는 <b>빌링키 조회 API 가 없어</b> 그 키는 영원히 회수할 수 없다.
 * 그래서 {@code TossClient} 가 <b>같은 멱등키로</b> 한 번 더 시도한다 — 값을 짧게 잡을 수 있는 것은
 * 그 재시도가 있기 때문이다. 둘은 한 세트다. 한쪽만 바꾸지 말 것.
 *
 * <p><b>HTTP/1.1 을 고정하는 이유</b>는 {@code RestClientConfig} 와 같다. 토스는 HTTPS 라
 * h2c 업그레이드 문제가 없지만, 통합 테스트의 {@code TossStub}(JDK {@code HttpServer}) 은 평문이라
 * 같은 함정에 걸린다. <b>테스트와 운영이 같은 프로토콜을 타야</b> 테스트가 의미를 갖는다.
 */
@Configuration
@RequiredArgsConstructor
public class TossClientConfig {

    private final TossProperties tossProperties;

    @Bean
    public RestClient tossRestClient() {
        HttpClient httpClient = HttpClient.newBuilder()
                .version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(tossProperties.connectTimeout())
                .build();

        JdkClientHttpRequestFactory requestFactory = new JdkClientHttpRequestFactory(httpClient);
        requestFactory.setReadTimeout(tossProperties.readTimeout());

        return RestClient.builder()
                .baseUrl(tossProperties.baseUrl())
                // 인증 헤더를 여기 한 번만 박는다. 호출 지점마다 붙이면 언젠가 한 곳이 빠지고,
                // 그 한 곳은 401 로만 드러난다.
                .defaultHeader(HttpHeaders.AUTHORIZATION, basicAuth(tossProperties.secretKey()))
                .requestFactory(requestFactory)
                .build();
    }

    /**
     * 토스의 Basic 인증: {@code base64(secretKey + ":")}.
     *
     * <p>🔴 <b>콜론이 핵심이다.</b> 토스는 시크릿 키를 <b>아이디</b> 자리에 쓰고 비밀번호는 비운다.
     * 콜론을 빼고 인코딩하면 {@code INCORRECT_BASIC_AUTH_FORMAT} 으로 전부 거절당한다.
     *
     * <p>⚠️ <b>UTF-8 BOM 함정.</b> 시크릿 키를 파일에서 읽어오거나 웹에서 복사해 붙이면
     * 앞에 눈에 안 보이는 BOM({@code U+FEFF})이나 공백이 딸려올 수 있다. 그러면 base64 결과가
     * 달라져 <b>키는 맞는데 401 이 나는</b> 가장 헷갈리는 실패가 된다. 그래서 {@code strip()} 한다
     * (BOM 은 자바의 {@code String.strip()} 이 공백으로 취급해 제거한다 — {@code trim()} 은 못 한다).
     */
    private String basicAuth(String secretKey) {
        String raw = (secretKey == null ? "" : secretKey.strip()) + ":";
        return "Basic " + Base64.getEncoder().encodeToString(raw.getBytes(StandardCharsets.UTF_8));
    }
}
