package com.alldap.api.domain.chat.controller;

import com.alldap.api.domain.chat.dto.ConversationSummaryResponse;
import com.alldap.api.domain.chat.dto.MessageResponse;
import com.alldap.api.domain.chat.service.ConversationLogService;
import com.alldap.api.global.common.PageResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.data.web.PageableDefault;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;

import java.time.LocalDate;
import java.util.List;
import java.util.UUID;

/**
 * 대화 로그 API (PRD §10.1 {@code GET /api/bots/{botId}/logs}). 인증 필요.
 */
@Tag(name = "대화 로그", description = "위젯·관리자 채팅에서 오간 대화 기록.")
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
     * <p><b>{@code @PageableDefault} 로 정렬 기본값을 여기서 정하는 이유.</b>
     * 정렬을 지정하지 않으면 DB 가 돌려주는 순서는 <b>보장되지 않는다.</b>
     * 그러면 2페이지에 1페이지 항목이 다시 나오거나 일부가 영영 안 보이는 일이 생긴다.
     * 리포지토리 쿼리에 {@code ORDER BY} 를 넣지 않은 것도 이 때문이다 —
     * 거기 넣으면 {@code Pageable} 의 정렬과 겹쳐 {@code ORDER BY} 가 두 번 붙는다.
     *
     * <p>필터 파라미터는 프론트 {@code LogsQuery} 타입과 이름을 맞췄다.
     * {@code from}·{@code to} 는 {@code YYYY-MM-DD} 이며 <b>둘 다 그 날짜를 포함</b>한다
     * (시간대 처리는 서비스가 한다 — KST 기준).
     */
    @Operation(summary = "대화 목록 조회")
    @GetMapping
    public ResponseEntity<PageResponse<ConversationSummaryResponse>> getLogs(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID botId,
            @RequestParam(defaultValue = "false") boolean onlyFallback,
            @RequestParam(defaultValue = "false") boolean onlyThumbsDown,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate from,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate to,
            @PageableDefault(size = 20, sort = "createdAt", direction = Sort.Direction.DESC) Pageable pageable) {

        return ResponseEntity.ok(conversationLogService.findLogs(
                userId, botId, onlyFallback, onlyThumbsDown, from, to, pageable));
    }

    /**
     * GET /api/bots/{botId}/logs/{conversationId} — 대화 한 건의 메시지 전체.
     *
     * <p>PRD §10.1 표에는 없던 경로다. 목록만으로는 "이 세션에서 무슨 대화가 오갔는지" 를 볼 수 없어
     * 이 슬라이스에서 추가했다. 경로에 {@code botId} 를 유지하는 이유는 서비스 주석 참고.
     *
     * <p>페이지네이션을 두지 않았다: 한 세션의 메시지는 대화 특성상 수십 건을 넘기 어렵다.
     * 넘기 시작하면 그때 붙인다.
     */
    @Operation(summary = "대화 상세(메시지 목록) 조회")
    @GetMapping("/{conversationId}")
    public ResponseEntity<List<MessageResponse>> getMessages(@AuthenticationPrincipal UUID userId,
                                                             @PathVariable UUID botId,
                                                             @PathVariable UUID conversationId) {
        return ResponseEntity.ok(conversationLogService.findMessages(userId, botId, conversationId));
    }
}
