package com.alldap.api.domain.chat.controller;

import com.alldap.api.domain.chat.dto.ChatRequest;
import com.alldap.api.domain.chat.dto.ChatResponse;
import com.alldap.api.domain.chat.dto.FeedbackRequest;
import com.alldap.api.domain.chat.service.ChatService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

import java.util.UUID;

/**
 * 채팅·피드백 API (PRD §10.1). 인증 필요.
 *
 * <p>위젯용 공개 채팅({@code POST /api/w/{publicKey}/chat})은
 * 인증 규칙이 완전히 다르므로 {@code WidgetController} 에 따로 둔다.
 */
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
    @PostMapping("/api/bots/{botId}/chat")
    public ResponseEntity<ChatResponse> chat(@PathVariable UUID botId,
                                             @Valid @RequestBody ChatRequest request) {
        // TODO(W2): chatService.chatAsOwner(userId, botId, request) 호출
        throw new UnsupportedOperationException("ChatController.chat 미구현 (W2)");
    }

    /** POST /api/messages/{msgId}/feedback — 답변에 👍/👎 */
    @PostMapping("/api/messages/{msgId}/feedback")
    public ResponseEntity<Void> feedback(@PathVariable UUID msgId,
                                         @Valid @RequestBody FeedbackRequest request) {
        // TODO(W2): chatService.applyFeedback(userId, msgId, request.feedback()) 호출 후 204
        throw new UnsupportedOperationException("ChatController.feedback 미구현 (W2)");
    }
}
