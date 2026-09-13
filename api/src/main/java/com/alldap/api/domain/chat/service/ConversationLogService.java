package com.alldap.api.domain.chat.service;

import com.alldap.api.domain.bot.repository.BotRepository;
import com.alldap.api.domain.chat.dto.ConversationSummaryResponse;
import com.alldap.api.domain.chat.dto.MessageResponse;
import com.alldap.api.domain.chat.dto.SourceResponse;
import com.alldap.api.domain.chat.entity.Conversation;
import com.alldap.api.domain.chat.entity.Message;
import com.alldap.api.domain.chat.repository.ConversationRepository;
import com.alldap.api.domain.chat.repository.MessageRepository;
import com.alldap.api.global.common.PageResponse;
import com.alldap.api.global.exception.ApiException;
import com.alldap.api.global.exception.ErrorCode;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;

import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneId;
import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;

/**
 * 대화 로그 조회 서비스.
 *
 * <p>{@link ChatService} 와 분리한 이유: 채팅은 외부 호출이 섞인 쓰기 흐름이고,
 * 로그는 순수한 읽기 흐름이라 트랜잭션 성격이 정반대다.
 * 한 클래스에 두면 {@code @Transactional} 설정이 서로 발목을 잡는다.
 *
 * <p><b>W3(품질 대시보드)의 미답변 목록이 결국 여기서 나온다.</b>
 * 그래서 {@code hasFallback} 을 목록 단계에서 집계해 두는 것이 이 슬라이스의 실질적 목적이다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class ConversationLogService {

    /**
     * 로그 화면의 날짜 필터가 기준으로 삼는 시간대.
     *
     * <p><b>왜 명시해야 하나.</b> {@code created_at} 은 {@code TIMESTAMPTZ}(절대 시각)인데
     * 사용자가 보내는 {@code from=2026-08-01} 은 <b>달력 날짜</b>다. 둘을 잇는 데는 시간대가 필요하고,
     * 서버 기본 시간대에 맡기면 배포 환경(대개 UTC)과 사용자가 보는 날짜가 9시간 어긋나
     * "어제 대화가 오늘 목록에 나온다". 이 제품의 사용자는 한국 기업이므로 KST 로 못박는다.
     *
     * <p>TODO(W3 이후): 해외 고객이 생기면 봇별 시간대 설정이 필요해진다. 지금은 필요 없다.
     */
    private static final ZoneId LOG_ZONE = ZoneId.of("Asia/Seoul");

    private final BotRepository botRepository;
    private final ConversationRepository conversationRepository;
    private final MessageRepository messageRepository;
    private final ObjectMapper objectMapper;

    /**
     * 대화 로그 목록. {@code GET /api/bots/{botId}/logs}
     *
     * <p><b>쿼리가 정확히 2번 나간다 (페이지에 몇 건이 있든).</b>
     * ① 조건에 맞는 대화 페이지 ② 그 대화들의 집계를 한 번에.
     * 대화마다 메시지를 조회하면 N+1 이 되어 목록이 커질수록 급격히 느려진다.
     *
     * @param from 포함. null 이면 제한 없음
     * @param to   <b>이 날짜까지 포함</b>한다. 사용자가 기대하는 "8/1 ~ 8/3" 은 3일치이므로
     *             내부적으로는 8/4 00:00 <b>미만</b>으로 바꿔 비교한다
     */
    public PageResponse<ConversationSummaryResponse> findLogs(Long userId, Long botId,
                                                              boolean onlyFallback, boolean onlyThumbsDown,
                                                              LocalDate from, LocalDate to,
                                                              Pageable pageable) {
        requireOwnedBot(userId, botId);

        Page<Conversation> conversations = conversationRepository.findLogs(
                botId, onlyFallback, onlyThumbsDown, startOfDay(from), startOfNextDay(to), pageable);

        Map<Long, MessageRepository.ConversationAggregate> aggregates = loadAggregates(conversations);

        return PageResponse.of(conversations, conversation -> toSummary(conversation, aggregates));
    }

    /**
     * 대화 한 건의 메시지 전체. {@code GET /api/bots/{botId}/logs/{conversationId}}
     *
     * <p>경로에 {@code botId} 를 둔 이유: 소유권 확인을 <b>봇 단위로 한 번에</b> 끝낼 수 있고,
     * 목록 → 상세로 이어지는 화면 흐름과 주소가 일치한다.
     * PRD §10.1 표에는 이 경로가 없다 — 이 슬라이스에서 정한 것이므로 PRD 도 함께 갱신할 것.
     */
    public List<MessageResponse> findMessages(Long userId, Long botId, Long conversationId) {
        requireOwnedBot(userId, botId);

        // 대화가 <이 봇의 것인지>까지 확인한다. 봇 소유권만 보고 통과시키면
        // 남의 봇 대화 id 를 내 botId 와 조합해 훔쳐볼 수 있다.
        Conversation conversation = conversationRepository.findById(conversationId)
                .filter(it -> it.getBot().getId().equals(botId))
                .orElseThrow(() -> new ApiException(ErrorCode.RESOURCE_NOT_FOUND,
                        "대화를 찾을 수 없습니다. 목록을 새로고침한 뒤 다시 시도해주세요."));

        return messageRepository.findAllByConversationIdOrderByCreatedAtAsc(conversation.getId()).stream()
                .map(this::toMessageResponse)
                .toList();
    }

    // ── 내부 ─────────────────────────────────────────────────────────────

    /** 페이지가 비어 있으면 쿼리를 아예 보내지 않는다 ({@code IN ()} 은 문법 오류다). */
    private Map<Long, MessageRepository.ConversationAggregate> loadAggregates(Page<Conversation> conversations) {
        if (conversations.isEmpty()) {
            return Map.of();
        }
        List<Long> ids = conversations.getContent().stream().map(Conversation::getId).toList();
        return messageRepository.aggregateByConversationIds(ids).stream()
                .collect(Collectors.toMap(
                        MessageRepository.ConversationAggregate::getConversationId, Function.identity()));
    }

    private ConversationSummaryResponse toSummary(Conversation conversation,
                                                  Map<Long, MessageRepository.ConversationAggregate> aggregates) {
        // 메시지가 한 건도 없는 대화는 GROUP BY 결과에 아예 나오지 않는다.
        // 그런 대화가 생길 수 있으므로(대화만 만들어지고 메시지 저장이 실패하는 경로) null 로 터지지 않게 한다.
        MessageRepository.ConversationAggregate aggregate = aggregates.get(conversation.getId());

        return new ConversationSummaryResponse(
                conversation.getId(),
                conversation.getSessionId(),
                conversation.getChannel(),
                conversation.getCreatedAt(),
                aggregate == null ? 0 : aggregate.getMessageCount(),
                aggregate != null && aggregate.getHasFallback(),
                aggregate == null ? null : aggregate.getFirstUserMessage());
    }

    private MessageResponse toMessageResponse(Message message) {
        return new MessageResponse(
                message.getId(),
                message.getRole(),
                message.getContent(),
                parseSources(message),
                message.isFallback(),
                message.getFeedback(),
                message.getLatencyMs(),
                message.getCreatedAt());
    }

    /**
     * {@code messages.sources}(JSONB 문자열) → DTO 목록.
     *
     * <p><b>파싱 실패를 예외로 만들지 않는다.</b> 이 값은 과거에 저장된 데이터라
     * 우리가 지금 고칠 수 없다. 한 건이 깨졌다고 대화 전체 조회가 500 이 되면
     * 사용자는 <b>멀쩡한 나머지 메시지까지 못 본다.</b> 로그만 남기고 null 로 넘어간다.
     *
     * <p>{@code TypeReference} 를 쓰는 이유: 자바 제네릭은 실행 시점에 타입이 지워져서
     * {@code List<SourceResponse>.class} 같은 표현이 불가능하다. 익명 하위 클래스를 만들어
     * 제네릭 정보를 클래스 파일에 남기는 것이 Jackson 의 관용구다.
     */
    private List<SourceResponse> parseSources(Message message) {
        String json = message.getSources();
        if (json == null || json.isBlank()) {
            return null;   // 프론트 타입이 Source[] | null 이라 "근거 없음"을 null 로 내려준다
        }
        try {
            return objectMapper.readValue(json, new TypeReference<List<SourceResponse>>() {
            });
        } catch (RuntimeException e) {
            log.warn("[logs] sources JSON 파싱 실패 — messageId={} 는 근거 없이 내려보낸다.", message.getId(), e);
            return null;
        }
    }

    /**
     * "기간 제한 없음" 을 나타내는 경계값.
     *
     * <p>null 을 그대로 쿼리에 넘기면 Postgres 가
     * {@code could not determine data type of parameter} 로 거절한다 —
     * 파라미터가 {@code IS NULL} 비교에만 쓰이면 타입을 추론할 근거가 없기 때문이다.
     * 그래서 리포지토리에는 <b>항상 값이 있는</b> 비교만 남기고, "제한 없음" 을 여기서 넓은 범위로 바꾼다.
     * (대화가 1970년 이전이거나 9999년 이후일 일은 없다)
     */
    private static final Instant NO_LOWER_BOUND = Instant.EPOCH;
    private static final Instant NO_UPPER_BOUND = Instant.parse("9999-12-31T00:00:00Z");

    private Instant startOfDay(LocalDate date) {
        return date == null ? NO_LOWER_BOUND : date.atStartOfDay(LOG_ZONE).toInstant();
    }

    /** {@code to} 는 "그 날짜까지 포함" 이므로 다음 날 00:00 미만으로 비교한다. */
    private Instant startOfNextDay(LocalDate date) {
        return date == null ? NO_UPPER_BOUND : date.plusDays(1).atStartOfDay(LOG_ZONE).toInstant();
    }

    private void requireOwnedBot(Long userId, Long botId) {
        botRepository.findByIdAndUserId(botId, userId)
                .orElseThrow(() -> new ApiException(ErrorCode.BOT_NOT_FOUND));
    }
}
