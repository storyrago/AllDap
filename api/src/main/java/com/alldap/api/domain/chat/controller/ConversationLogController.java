package com.alldap.api.domain.chat.controller;

import com.alldap.api.domain.chat.dto.ConversationSummaryResponse;
import com.alldap.api.domain.chat.service.ConversationLogService;
import com.alldap.api.global.common.PageResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Pageable;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.UUID;

/**
 * 대화 로그 API (PRD §10.1 {@code GET /api/bots/{botId}/logs}). 인증 필요.
 */
@RestController
@RequestMapping("/api/bots/{botId}/logs")
@RequiredArgsConstructor
public class ConversationLogController {

    private final ConversationLogService conversationLogService;

    /**
     * GET /api/bots/{botId}/logs — 대화 로그 목록.
     *
     * <p>응답은 {@link PageResponse} 로 감싼다. Spring Data 의 {@code Page} 를 그대로 내리면
     * 프론트의 {@code Paged<T>} 와 필드명이 어긋난다(PageResponse 주석 참고).
     *
     * <p>TODO(W2): 필터 파라미터(onlyFallback / onlyThumbsDown / from / to)를 추가할 것.
     *   프론트 {@code LogsQuery} 타입에 이미 정의돼 있다.
     */
    @GetMapping
    public ResponseEntity<PageResponse<ConversationSummaryResponse>> getLogs(@PathVariable UUID botId,
                                                                            Pageable pageable) {
        // TODO(W2): conversationLogService.findLogs(userId, botId, pageable) 호출
        throw new UnsupportedOperationException("ConversationLogController.getLogs 미구현 (W2)");
    }
}
