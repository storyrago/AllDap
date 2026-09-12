package com.alldap.api.domain.widget.controller;

import com.alldap.api.domain.bot.entity.Bot;
import com.alldap.api.domain.bot.service.BotService;
import com.alldap.api.domain.chat.dto.ChatRequest;
import com.alldap.api.domain.chat.dto.ChatResponse;
import com.alldap.api.domain.chat.service.ChatService;
import com.alldap.api.domain.widget.dto.WidgetConfigResponse;
import com.alldap.api.global.config.WidgetProperties;
import com.alldap.api.global.exception.ApiException;
import com.alldap.api.global.exception.ErrorCode;
import com.alldap.api.global.ratelimit.RateLimiter;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import io.swagger.v3.oas.annotations.security.SecurityRequirements;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.Duration;

/**
 * 위젯 공개 API (PRD §10.1). <b>인증 없음.</b> SecurityConfig 에서 {@code /api/w/**} 를 열어두었다.
 *
 * <p><b>여기가 이 서비스에서 유일하게 인증 없이 열려 있는 문이다.</b> 보호 장치는 이렇게 놓였다.
 * <ol>
 *   <li><b>publicKey</b> — 존재하는 봇인지 확인. 16바이트 난수라 추측이 사실상 불가능하다.</li>
 *   <li><b>Origin 검증</b> — <b>설정 조회에만</b> 건다. 아래 "왜 채팅에는 못 거는가" 참고.</li>
 *   <li><b>rate limit</b> — IP + publicKey 기준. LLM 호출은 건당 비용이라
 *       제한이 없으면 요금 폭탄이 곧 서비스 거부 공격이 된다.</li>
 * </ol>
 *
 * <h2>왜 Origin 검증을 채팅에는 못 거는가 (설계상의 구멍 — 숨기지 않는다)</h2>
 * 위젯 구조는 <b>로더 스크립트 → iframe({@code /w/{publicKey}}, Next.js)</b> 이고,
 * 채팅 전송은 iframe 안에서 나간다. 그러면 브라우저가 붙이는 {@code Origin} 은
 * 고객 사이트가 아니라 <b>우리 Next.js 도메인</b>이다. iframe 은 cross-origin 이라
 * 부모 주소를 알 수도 없다. 즉 <b>봇의 허용 도메인과 대조할 값 자체가 오지 않는다.</b>
 *
 * <p>그래서 이렇게 나눴다.
 * <ul>
 *   <li><b>설정 조회</b>({@code GET /config}) — 로더가 고객 페이지에서 직접 부르므로
 *       브라우저가 <b>진짜 Origin</b> 을 붙여준다. 여기서 대조한다.
 *       <b>여기서 막히면 위젯 UI 가 아예 뜨지 않으므로</b>, 정상 브라우저 경로에서는
 *       이 단계가 "남의 봇을 자기 사이트에 붙이는 것" 에 대한 실질적 억제력이 된다.</li>
 *   <li><b>채팅</b> — publicKey + rate limit 으로 보호한다.</li>
 * </ul>
 *
 * <p>더 강하게 하려면 <b>채팅도 로더가 호출</b>하고 iframe 과는 postMessage 로 주고받는 구조로
 * 바꿔야 한다(그러면 브라우저가 진짜 Origin 을 붙인다). 위젯 스크립트를 고쳐야 하는
 * 아키텍처 변경이라 별도 결정으로 남긴다.
 * TODO(W2 이후): 위 구조 변경 여부를 결정하고 decisions.md 에 남길 것.
 *
 * <p>※ Origin 은 브라우저가 붙이는 값이라 curl 같은 도구로는 얼마든지 위조할 수 있다.
 *    즉 Origin 검증은 "브라우저를 통한 무단 사용" 만 막고, <b>결정적 방어는 rate limit</b> 이다.
 */
@Slf4j
@RestController
@RequestMapping("/api/w/{publicKey}")
@RequiredArgsConstructor
public class WidgetController {

    private final BotService botService;
    private final ChatService chatService;
    private final RateLimiter rateLimiter;
    private final WidgetProperties widgetProperties;

    /**
     * GET /api/w/{publicKey}/config — 위젯 초기 설정(봇 이름·인사말).
     *
     * <p>내부 설정이 새어나가지 않도록 응답은 반드시 {@link WidgetConfigResponse} 로 만든다.
     */
    // 위젯은 고객 사이트에 심겨 <방문자>가 쓴다. JWT 가 없다.
    // 보호는 publicKey + Origin 검증 + rate limit 이다(이 클래스 주석 참고).
    @SecurityRequirements
    @GetMapping("/config")
    public ResponseEntity<WidgetConfigResponse> getConfig(
            @PathVariable String publicKey,
            @RequestHeader(value = HttpHeaders.ORIGIN, required = false) String origin,
            HttpServletRequest servletRequest) {

        // rateLimiter.check 보다 먼저: publicKey 형식 자체를 검증해 키 공간을 제한한다.
        // (아래 requirePlausiblePublicKey 주석 참고)
        requirePlausiblePublicKey(publicKey);

        // 비용은 없지만 무제한이면 publicKey 를 무작위로 넣어 <존재하는 봇>을 훑을 수 있다.
        rateLimiter.check("widget-config", clientKey(servletRequest, publicKey),
                widgetProperties.configPerMinute(), Duration.ofMinutes(1));

        Bot bot = botService.findByPublicKey(publicKey);
        requireAllowedOrigin(bot, origin);

        return ResponseEntity.ok(WidgetConfigResponse.from(bot));
    }

    /**
     * POST /api/w/{publicKey}/chat — 위젯 채팅.
     *
     * <p>Origin 을 받아 넘기지만 <b>차단에 쓰지는 않는다</b>(위 클래스 주석의 구조적 이유).
     * 진단용으로 기록한다.
     */
    // 위젯 채팅. 인증 없이 열린 유일한 문이고 실질 방어선은 rate limit 이다.
    @SecurityRequirements
    @PostMapping("/chat")
    public ResponseEntity<ChatResponse> chat(
            @PathVariable String publicKey,
            @RequestHeader(value = HttpHeaders.ORIGIN, required = false) String origin,
            @Valid @RequestBody ChatRequest request,
            HttpServletRequest servletRequest) {

        // rateLimiter.check 보다 먼저: publicKey 형식 자체를 검증해 키 공간을 제한한다.
        requirePlausiblePublicKey(publicKey);

        // 여기가 실질적 방어선이다. 채팅 한 번은 외부 LLM 호출 = 실제 돈이다.
        rateLimiter.check("widget-chat", clientKey(servletRequest, publicKey),
                widgetProperties.chatPerMinute(), Duration.ofMinutes(1));

        return ResponseEntity.ok(chatService.chatAsWidget(publicKey, origin, request));
    }

    /**
     * publicKey 의 <b>형식만</b> 본다 — 존재 여부는 여전히 {@code findByPublicKey} 의 몫이고,
     * 그 호출은 rate limit <b>뒤에</b> 남아 있어야 한다(조회 자체도 제한받아야 하므로).
     *
     * <p>🔴 이 검사를 rate limit <b>앞에</b> 두는 이유: {@code publicKey} 는 검증 없이 그대로
     * rate limit 키({@code clientKey})에 들어간다. 매 요청 다른 무작위 문자열을 publicKey 자리에
     * 넣으면 요청마다 새 카운터 버킷이 생겨 <b>절대 429 에 걸리지 않고</b>,
     * {@code RateLimiter.counters} 가 무한히 자란다. 10만 개를 넘기면
     * {@code RateLimiter} 가 <b>전체 카운터를 통째로 비우는데</b>, 그 순간 다른 모든 봇·방문자의
     * 카운터도 같이 사라진다 — 공격 경제성은 나쁘지만({@code Bot.generatePublicKey} 형식을
     * 맞추지 않고 100,000 건을 보내야 한다) 형식만 확인하면 그 통로 자체를 막을 수 있다.
     *
     * <p>형식은 {@code Bot.generatePublicKey()} 가 실제로 만드는 값과 맞춘다 —
     * {@code "pk_"} 접두사 + Base64 URL-safe(패딩 없음) 22자 = 총 25자. 넉넉히 32자까지 허용해
     * 포맷이 조금 바뀌어도(컬럼 길이 VARCHAR(32)) 깨지지 않게 한다.
     *
     * <p>존재 여부를 드러내지 않도록 형식이 틀렸을 때도 {@link ErrorCode#BOT_NOT_FOUND} 를
     * 던진다 — 실제로 없는 publicKey 를 조회했을 때({@code findByPublicKey}) 나는 것과 같은 코드다.
     */
    private void requirePlausiblePublicKey(String publicKey) {
        if (publicKey == null || publicKey.length() > 32 || !publicKey.startsWith("pk_")) {
            throw new ApiException(ErrorCode.BOT_NOT_FOUND);
        }
    }

    /**
     * 봇이 허용한 도메인에서 온 요청인지 확인한다.
     *
     * <p><b>Origin 헤더가 없으면 통과시킨다.</b> 브라우저는 cross-origin 요청에 반드시 Origin 을 붙이지만
     * 같은 출처의 요청이나 curl 에는 없을 수 있다. 없는 요청을 막아봐야
     * <b>브라우저가 아닌 호출자는 어차피 아무 값이나 넣을 수 있어</b> 얻는 게 없고,
     * 개발 중 로컬 확인만 불편해진다. 이 경로의 진짜 방어는 rate limit 이다.
     *
     * <p>안내 문구를 두 갈래로 나눈다 — "아직 하나도 설정 안 함" 과 "설정했는데 이 주소가 없음" 은
     * 관리자가 해야 할 행동이 다르기 때문이다.
     */
    private void requireAllowedOrigin(Bot bot, String origin) {
        if (origin == null || origin.isBlank() || bot.isOriginAllowed(origin)) {
            return;
        }

        log.warn("[widget] 허용되지 않은 Origin — publicKey={} origin={}", bot.getPublicKey(), origin);

        if (bot.hasNoAllowedOrigins()) {
            throw new ApiException(ErrorCode.ORIGIN_NOT_ALLOWED,
                    "이 봇에는 아직 허용 도메인이 설정되지 않았습니다. "
                            + "봇 설정에서 위젯을 설치할 주소(예: https://example.com)를 추가해주세요.");
        }
        throw new ApiException(ErrorCode.ORIGIN_NOT_ALLOWED);
    }

    /**
     * 제한을 셀 단위. <b>IP 와 publicKey 를 함께</b> 쓴다.
     *
     * <p>IP 만 쓰면 한 회사에서 여러 봇을 쓸 때 서로의 한도를 잡아먹고,
     * publicKey 만 쓰면 한 명이 그 봇 전체를 마비시킬 수 있다.
     *
     * <p>🔴 <b>{@code X-Forwarded-For} 를 직접 읽지 않는다.</b> 예전에는 이 메서드가 그 헤더의
     * 맨 앞 항목을 원 클라이언트로 삼았는데, <b>그 값은 클라이언트가 위조할 수 있다.</b>
     * 파싱 규칙을 여기와 프레임워크 두 곳에 두면 어긋나기도 한다. 그래서 프레임워크 한 곳에
     * 맡기고({@code server.forward-headers-strategy: framework}) 여기서는
     * {@code getRemoteAddr()} 만 부른다.
     *
     * <p>⚠️ <b>다만 이 변경만으로 prod 동작이 바뀌지는 않았다.</b> 실측·소스 확인한 사실:
     * <ul>
     *   <li>[실측] caddy 2.11.4 컨테이너로 재현한 결과, 신뢰하지 않는 상대가 보낸
     *       {@code X-Forwarded-*} 는 잇는(append) 게 아니라 <b>버려졌다</b>.
     *       (더 이른 버전부터인지는 실측하지 않았다 — 아래 참고)</li>
     *   <li>[소스 확인] {@code framework} 전략의 {@code ForwardedHeaderExtractingRequest} 는
     *       {@code ForwardedHeaderRemovingRequest} 를 상속해({@code ForwardedHeaderFilter.java:247})
     *       {@code X-Forwarded-*} 를 감춘다. 즉 prod 에서는 옛 코드도 이미
     *       {@code getRemoteAddr()} 로 떨어졌다.</li>
     * </ul>
     * 진짜 구멍은 <b>{@code Forwarded}(RFC 7239)</b> 쪽이었다. caddy 는 이 헤더를
     * 건드리지 않고 그대로 넘기는데, Spring 의 {@code ForwardedHeaderUtils} 는
     * {@code X-Forwarded-For} 보다 <b>먼저</b> 이걸 읽는다 → 클라이언트가 매 요청
     * {@code Forwarded: for=...} 를 바꾸면 rate limit 키가 달라져 한도가 무제한이 된다.
     * {@code Caddyfile} 의 {@code header_up -Forwarded} 가 그 통로를 막는다.
     * ({@code header_up X-Forwarded-For {remote_host}} 는 caddy 기본값에 기대지 않겠다는
     * 명시이고, {@code trusted_proxies} 를 설정하는 순간부터 실제로 필요해진다)
     *
     * <p>⚠️ <b>실패 방향이 안전한 쪽으로 바뀐다.</b> 프록시 설정({@code forward-headers-strategy})이
     * 빠진 채 배포되면, <b>프록시(caddy) 자체가 없는 경우에만</b> 예전 코드가 "제한 없음"(위조 자유)이었다.
     * caddy 는 있는데 이 설정만 빠졌다면 옛 코드도 caddy 가 써준 실제 접속 IP 를 읽고 있었으니
     * 그 경우는 "제한 없음"이 아니었다. 이 조합이 빠지면 이제는 모든 요청이 프록시 IP 하나로 묶여
     * <b>과하게 엄격해진다.</b> 보안 장치는 이 방향으로 실패해야 한다.
     */
    private String clientKey(HttpServletRequest request, String publicKey) {
        return request.getRemoteAddr() + "|" + publicKey;
    }

    // TODO(W2 이후): 위젯 사용자가 👍/👎 를 누를 수 있어야 하는지 결정할 것.
    //   PRD §10.1 의 피드백 API 는 인증 경로(/api/messages/{msgId}/feedback)에 있는데,
    //   실제로 피드백을 남길 사람은 대부분 위젯 엔드유저다. 공개 경로가 필요하다면
    //   "자기가 방금 받은 메시지에만" 달 수 있도록 제한하는 방법을 함께 정해야 한다.
}
