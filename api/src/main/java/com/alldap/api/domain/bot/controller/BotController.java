package com.alldap.api.domain.bot.controller;

import com.alldap.api.domain.bot.dto.BotResponse;
import com.alldap.api.domain.bot.dto.CreateBotRequest;
import com.alldap.api.domain.bot.dto.UpdateBotRequest;
import com.alldap.api.domain.bot.service.BotService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.UUID;

/**
 * 봇 관리 API (PRD §10.1). 인증 필요.
 *
 * <p>컨트롤러는 얇게 유지한다 — 리포지토리를 직접 참조하지 않고 서비스에만 의존한다.
 *
 * <p>TODO(W2): 로그인한 사용자 id 를 어떻게 받을지 확정할 것.
 *   JWT 필터가 SecurityContext 에 principal 을 넣은 뒤
 *   {@code @AuthenticationPrincipal} 또는 커스텀 {@code @CurrentUser} 애너테이션으로 주입받는다.
 *   지금은 그 타입이 아직 없어서 파라미터를 비워두었다. 서비스 메서드는 이미 userId 를 받는 시그니처다.
 */
@RestController
@RequestMapping("/api/bots")
@RequiredArgsConstructor
public class BotController {

    private final BotService botService;

    /** GET /api/bots — 내 봇 목록 */
    @GetMapping
    public ResponseEntity<List<BotResponse>> getMyBots() {
        // TODO(W2): 인증 사용자 id 를 받아 botService.findMyBots(userId) 호출
        throw new UnsupportedOperationException("BotController.getMyBots 미구현 (W2)");
    }

    /** POST /api/bots — 봇 생성 */
    @PostMapping
    public ResponseEntity<BotResponse> createBot(@Valid @RequestBody CreateBotRequest request) {
        // TODO(W2): botService.createBot(userId, request) 호출 후 201 Created 반환
        throw new UnsupportedOperationException("BotController.createBot 미구현 (W2)");
    }

    /** GET /api/bots/{botId} — 봇 상세 */
    @GetMapping("/{botId}")
    public ResponseEntity<BotResponse> getBot(@PathVariable UUID botId) {
        // TODO(W2): botService.findMyBot(userId, botId) 호출
        throw new UnsupportedOperationException("BotController.getBot 미구현 (W2)");
    }

    /** PATCH /api/bots/{botId} — 봇 설정 부분 수정 */
    @PatchMapping("/{botId}")
    public ResponseEntity<BotResponse> updateBot(@PathVariable UUID botId,
                                                 @Valid @RequestBody UpdateBotRequest request) {
        // TODO(W2): botService.updateBot(userId, botId, request) 호출
        throw new UnsupportedOperationException("BotController.updateBot 미구현 (W2)");
    }

    /** DELETE /api/bots/{botId} — 봇 삭제 (문서·청크·대화 로그가 CASCADE 로 함께 삭제된다) */
    @DeleteMapping("/{botId}")
    public ResponseEntity<Void> deleteBot(@PathVariable UUID botId) {
        // TODO(W2): botService.deleteBot(userId, botId) 호출 후 204 No Content
        //   삭제는 되돌릴 수 없으므로 프론트에서 확인 절차를 둘 것.
        throw new UnsupportedOperationException("BotController.deleteBot 미구현 (W2)");
    }
}
