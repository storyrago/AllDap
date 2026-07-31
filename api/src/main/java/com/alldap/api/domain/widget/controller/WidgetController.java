package com.alldap.api.domain.widget.controller;

import com.alldap.api.domain.bot.service.BotService;
import com.alldap.api.domain.chat.dto.ChatRequest;
import com.alldap.api.domain.chat.dto.ChatResponse;
import com.alldap.api.domain.chat.service.ChatService;
import com.alldap.api.domain.widget.dto.WidgetConfigResponse;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 위젯 공개 API (PRD §10.1). <b>인증 없음.</b> SecurityConfig 에서 {@code /api/w/**} 를 열어두었다.
 *
 * <p><b>여기가 이 서비스에서 유일하게 인증 없이 열려 있는 문이다.</b> 보호 장치는 세 겹으로 설계한다.
 * <ol>
 *   <li><b>publicKey</b> — 존재하는 봇인지 확인. 추측이 어렵도록 랜덤 문자열로 만든다(Bot.create).</li>
 *   <li><b>Origin 검증</b> — 요청 헤더의 Origin 이 봇의 {@code allowed_origins} 에 있는지 확인.
 *       publicKey 는 고객 사이트 HTML 에 그대로 노출되므로 누구나 복사해 갈 수 있다.
 *       Origin 검증이 없으면 남의 봇을 자기 사이트에 붙여 LLM 비용을 떠넘길 수 있다.</li>
 *   <li><b>rate limit</b> — 같은 IP·같은 봇의 요청 빈도 제한. LLM 호출은 건당 비용이 들기 때문에
 *       제한이 없으면 요금 폭탄이 곧 서비스 거부 공격이 된다.</li>
 * </ol>
 *
 * <p>※ Origin 헤더는 브라우저가 붙이는 값이라 curl 같은 도구로는 얼마든지 위조할 수 있다.
 *    즉 Origin 검증은 "실수로 잘못 붙는 것"과 "브라우저를 통한 무단 사용"을 막을 뿐,
 *    결정적 방어는 rate limit 쪽이다. 이 한계를 알고 쓸 것.
 */
@RestController
@RequestMapping("/api/w/{publicKey}")
@RequiredArgsConstructor
public class WidgetController {

    private final BotService botService;
    private final ChatService chatService;

    /**
     * GET /api/w/{publicKey}/config — 위젯 초기 설정(봇 이름·인사말).
     *
     * <p>내부 설정이 새어나가지 않도록 응답은 반드시 {@link WidgetConfigResponse} 로 만든다.
     */
    @GetMapping("/config")
    public ResponseEntity<WidgetConfigResponse> getConfig(@PathVariable String publicKey) {
        // TODO(W2): botService.findByPublicKey(publicKey) → WidgetConfigResponse.from(bot)
        // TODO(W2): rate limit 적용. 설정 조회도 무제한이면 봇 존재 여부를 대량 스캔당할 수 있다.
        throw new UnsupportedOperationException("WidgetController.getConfig 미구현 (W2)");
    }

    /**
     * POST /api/w/{publicKey}/chat — 위젯 채팅.
     *
     * <p>Origin 을 헤더에서 직접 받는 이유: 봇마다 허용 도메인이 달라
     * 전역 CORS 설정만으로는 검사할 수 없고, 서비스 계층에서 봇 설정과 대조해야 하기 때문이다.
     * {@code required = false} 인 이유는 Origin 헤더가 항상 오지는 않기 때문이며,
     * 없을 때 통과시킬지 거절할지는 서비스에서 정책으로 정한다.
     */
    @PostMapping("/chat")
    public ResponseEntity<ChatResponse> chat(@PathVariable String publicKey,
                                             @RequestHeader(value = HttpHeaders.ORIGIN, required = false) String origin,
                                             @Valid @RequestBody ChatRequest request) {
        // TODO(W2): chatService.chatAsWidget(publicKey, origin, request) 호출
        // TODO(W2): rate limit 적용 (IP + publicKey 기준).
        //   1인 개발이므로 Redis 를 새로 띄우기보다 인메모리 버킷(Bucket4j 등)으로 시작하고,
        //   인스턴스가 늘어나면 그때 공유 저장소로 옮긴다. 이 트레이드오프를 decisions.md 에 남길 것.
        throw new UnsupportedOperationException("WidgetController.chat 미구현 (W2)");
    }

    // TODO(W2): 위젯 사용자가 👍/👎 를 누를 수 있어야 하는지 결정할 것.
    //   PRD §10.1 의 피드백 API 는 인증 경로(/api/messages/{msgId}/feedback)에 있는데,
    //   실제로 피드백을 남길 사람은 대부분 위젯 엔드유저다. 공개 경로가 필요하다면
    //   "자기가 방금 받은 메시지에만" 달 수 있도록 제한하는 방법을 함께 정해야 한다.
}
