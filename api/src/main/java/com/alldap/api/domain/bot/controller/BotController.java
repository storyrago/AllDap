package com.alldap.api.domain.bot.controller;

import com.alldap.api.domain.bot.dto.BotResponse;
import com.alldap.api.domain.bot.dto.BotSummaryResponse;
import com.alldap.api.domain.bot.dto.CreateBotRequest;
import com.alldap.api.domain.bot.dto.UpdateBotRequest;
import com.alldap.api.domain.bot.service.BotService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.net.URI;
import java.util.List;
import java.util.UUID;

/**
 * 봇 관리 API (PRD §10.1). 인증 필요.
 *
 * <p>컨트롤러는 얇게 유지한다 — 리포지토리를 직접 참조하지 않고 서비스에만 의존한다.
 *
 * <h2>로그인한 사용자를 {@code @AuthenticationPrincipal UUID userId} 로 받는 이유</h2>
 * {@link com.alldap.api.domain.auth.filter.JwtAuthenticationFilter} 가 SecurityContext 의
 * principal 에 사용자 id(UUID) 자체를 넣는다. 이 애너테이션은 그 principal 을 꺼내
 * 파라미터 타입으로 캐스팅해줄 뿐이라 중간 타입이 필요 없다.
 *
 * <p>대신 <b>클라이언트가 보낸 값에서는 절대 userId 를 받지 않는다.</b>
 * 쿼리 파라미터나 본문으로 받으면 남의 id 를 적어 보내는 것만으로 소유권 검사가 무너진다.
 * 출처가 "우리가 서명한 토큰"인 값만 신뢰한다.
 *
 * <p>여기서 userId 가 null 이 되는 경우는 없다 — SecurityConfig 가 {@code /api/bots/**} 를
 * {@code authenticated()} 로 잠가둬서, 인증 없는 요청은 컨트롤러에 도달하기 전에 401 로 끊긴다.
 */
@RestController
@RequestMapping("/api/bots")
@RequiredArgsConstructor
public class BotController {

    private final BotService botService;

    /**
     * GET /api/bots (내 봇 목록).
     *
     * <p>상세 조회와 달리 {@link BotSummaryResponse} 다. 카드에 얹을 집계(문서 수·주간 대화 수·
     * 최근 평가 점수)가 붙는다. 두 응답의 타입을 나눈 이유는 그 DTO 주석 참고.
     */
    @GetMapping
    public ResponseEntity<List<BotSummaryResponse>> getMyBots(@AuthenticationPrincipal UUID userId) {
        return ResponseEntity.ok(botService.findMyBots(userId));
    }

    /**
     * POST /api/bots — 봇 생성.
     *
     * <p>{@code Location} 헤더를 붙인다. 여기는 AuthController 와 달리 만들어진 리소스를
     * 조회할 경로({@code GET /api/bots/{botId}})가 실제로 존재하기 때문이다.
     */
    @PostMapping
    public ResponseEntity<BotResponse> createBot(@AuthenticationPrincipal UUID userId,
                                                 @Valid @RequestBody CreateBotRequest request) {
        BotResponse bot = botService.createBot(userId, request);
        return ResponseEntity.created(URI.create("/api/bots/" + bot.id())).body(bot);
    }

    /** GET /api/bots/{botId} — 봇 상세 */
    @GetMapping("/{botId}")
    public ResponseEntity<BotResponse> getBot(@AuthenticationPrincipal UUID userId,
                                              @PathVariable UUID botId) {
        return ResponseEntity.ok(botService.findMyBot(userId, botId));
    }

    /** PATCH /api/bots/{botId} — 봇 설정 부분 수정 */
    @PatchMapping("/{botId}")
    public ResponseEntity<BotResponse> updateBot(@AuthenticationPrincipal UUID userId,
                                                 @PathVariable UUID botId,
                                                 @Valid @RequestBody UpdateBotRequest request) {
        return ResponseEntity.ok(botService.updateBot(userId, botId, request));
    }

    /**
     * DELETE /api/bots/{botId} — 봇 삭제 (문서·청크·대화 로그가 CASCADE 로 함께 삭제된다).
     *
     * <p>204 No Content 다. 지워진 리소스를 본문에 담아 돌려줄 이유가 없다.
     * 삭제는 되돌릴 수 없으므로 프론트에서 확인 절차를 둘 것.
     */
    @DeleteMapping("/{botId}")
    public ResponseEntity<Void> deleteBot(@AuthenticationPrincipal UUID userId,
                                          @PathVariable UUID botId) {
        botService.deleteBot(userId, botId);
        return ResponseEntity.noContent().build();
    }
}
