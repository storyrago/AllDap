package com.alldap.api.domain.chat.controller;

import com.alldap.api.domain.chat.dto.ChatRequest;
import com.alldap.api.domain.chat.dto.ChatResponse;
import com.alldap.api.domain.chat.dto.FeedbackRequest;
import com.alldap.api.domain.chat.service.ChatService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;


/**
 * 채팅·피드백 API (PRD §10.1). 인증 필요.
 *
 * <p>위젯용 공개 채팅({@code POST /api/w/{publicKey}/chat})은
 * 인증 규칙이 완전히 다르므로 {@code WidgetController} 에 따로 둔다.
 */
@Tag(name = "채팅", description = "관리자 테스트 채팅과 답변 피드백.")
@RestController
@RequiredArgsConstructor
public class ChatController {

    private final ChatService chatService;

    /**
     * POST /api/bots/{botId}/chat — 관리자 테스트 채팅.
     *
     * <p>이 호출은 Python 을 거치므로 수십 초 걸릴 수 있다.
     * 프론트에서 로딩 상태와 타임아웃 안내를 반드시 붙일 것.
     */
    @Operation(summary = "관리자 테스트 채팅")
    @PostMapping("/api/bots/{botId}/chat")
    public ResponseEntity<ChatResponse> chat(@AuthenticationPrincipal Long userId,
                                             @PathVariable Long botId,
                                             @Valid @RequestBody ChatRequest request) {
        return ResponseEntity.ok(chatService.chatAsOwner(userId, botId, request));
    }

    /** POST /api/messages/{msgId}/feedback — 답변에 👍/👎 */
    @Operation(summary = "답변 피드백 등록")
    @PostMapping("/api/messages/{msgId}/feedback")
    public ResponseEntity<Void> feedback(@AuthenticationPrincipal Long userId,
                                         @PathVariable Long msgId,
                                         @Valid @RequestBody FeedbackRequest request) {
        chatService.applyFeedback(userId, msgId, request.feedback());
        // 204. 피드백은 서버에 새 리소스를 만드는 게 아니라 기존 메시지의 값을 바꾸는 것이고,
        // 프론트가 돌려받아 쓸 값도 없다(버튼 상태는 프론트가 이미 안다).
        return ResponseEntity.noContent().build();
    }
}
