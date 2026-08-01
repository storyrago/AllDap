package com.alldap.api.domain.chat.service;

import com.alldap.api.domain.bot.entity.Bot;
import com.alldap.api.domain.bot.service.BotService;
import com.alldap.api.domain.chat.dto.ChatRequest;
import com.alldap.api.domain.chat.dto.ChatResponse;
import com.alldap.api.domain.chat.dto.SourceResponse;
import com.alldap.api.domain.chat.entity.Conversation;
import com.alldap.api.global.client.AiServiceClient;
import com.alldap.api.global.client.dto.AiChatRequest;
import com.alldap.api.global.client.dto.AiChatResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import tools.jackson.databind.ObjectMapper;

import java.util.List;
import java.util.UUID;

/**
 * 채팅 서비스. 이 프로젝트에서 가장 중요한 흐름이다.
 *
 * <p><b>흐름 (PRD 요청 흐름 ②):</b>
 * <pre>
 * 1. 봇 확인 (관리자 채팅이면 소유권)
 * 2. conversations 조회 또는 생성 → user 메시지 저장     ┐ 짧은 트랜잭션
 * 3. Python 호출 (POST /internal/chat)                  ← 트랜잭션 &lt;밖&gt;. 수십 초 걸릴 수 있다
 * 4. is_fallback == true 면 answer 를 봇의 fallback_message 로 치환
 * 5. assistant 메시지 저장                              ┘ 짧은 트랜잭션
 * 6. messageId 를 포함한 응답 반환 (피드백 API 를 부르려면 필요하다)
 * </pre>
 *
 * <p><b>이 클래스에 {@code @Transactional} 이 없는 것이 설계다.</b>
 * 2·5번의 트랜잭션은 {@link ChatTurnStore} 가 갖고 있고, 3번은 그 밖에서 일어난다.
 * 왜 별도 빈으로 나눴는지는 그 클래스 주석에 적어두었다(스프링 AOP self-invocation 함정).
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ChatService {

    private final AiServiceClient aiServiceClient;
    private final ChatTurnStore turnStore;

    /** 위젯 경로 전용. publicKey 로 봇을 찾는 데만 쓴다(관리자 경로는 소유권 조회를 따로 한다). */
    private final BotService botService;

    /** {@code messages.sources}(JSONB)에 넣을 JSON 을 만드는 데만 쓴다. */
    private final ObjectMapper objectMapper;

    /**
     * 관리자 테스트 채팅. {@code channel = "test"} 로 기록한다.
     *
     * <p>테스트 대화를 따로 표시하는 이유: 품질 지표(응답률·미답변 목록)를 낼 때
     * 관리자가 직접 돌려본 대화가 섞이면 실사용 수치가 왜곡된다.
     */
    public ChatResponse chatAsOwner(UUID userId, UUID botId, ChatRequest request) {
        ChatTurnStore.Turn turn = turnStore.openTurn(
                userId, botId, request.message(), request.sessionId(), Conversation.CHANNEL_TEST);

        // ⚠️ 여기가 트랜잭션 밖이다. 아래 호출이 실패하면 위에서 저장한 질문만 남는다 — 의도한 동작이다.
        //
        // 질문을 지우지 않는 이유: ① 지우려면 보상 트랜잭션이 필요한데 그 코드가 또 실패할 수 있고
        // ② "질문은 왔는데 답이 없다"는 기록이 장애 추적에 실제로 쓸모가 있다.
        // 단, 이건 fallback(근거를 못 찾아 거절)과 <완전히 다른 상태>다. fallback 은 답변 행이 남지만
        // 이쪽은 답변 행 자체가 없다. W3 에서 미답변을 집계할 때 둘을 섞지 말 것.
        AiChatResponse ai = aiServiceClient.chat(
                new AiChatRequest(botId, request.message(), request.sessionId()));

        String answer = resolveAnswer(turn.fallbackMessage(), ai);
        List<SourceResponse> sources = toSources(ai);

        UUID messageId = turnStore.saveAnswer(
                turn.conversationId(), answer, toSourcesJson(sources), ai.isFallback(), ai.latencyMs());

        log.info("[chat] botId={} conversationId={} messageId={} isFallback={} sources={} latencyMs={}",
                botId, turn.conversationId(), messageId, ai.isFallback(), sources.size(), ai.latencyMs());

        return new ChatResponse(answer, sources, ai.isFallback(), ai.latencyMs(), messageId);
    }

    /**
     * 위젯 채팅(공개). {@code channel = "widget"} 으로 기록한다.
     *
     * <p>관리자 채팅과 <b>본문 흐름은 같고 진입 조건만 다르다.</b> 인증이 없으므로
     * 소유권 대신 publicKey 존재 확인 + rate limit 을 통과해야 한다(컨트롤러가 담당).
     *
     * <p><b>{@code origin} 을 받지만 여기서 차단하지 않는다 — 알고 그렇게 뒀다.</b>
     * 이 요청은 iframe({@code /w/{publicKey}}) 안에서 나가므로 헤더의 Origin 은
     * 고객 사이트가 아니라 <b>우리 Next.js</b>다. 즉 봇의 허용 도메인과 대조할 값 자체가 오지 않는다.
     * Origin 대조는 <b>설정 조회</b>({@code GET /config})에서 한다 — 그건 로더가 고객 페이지에서
     * 직접 부르므로 브라우저가 진짜 Origin 을 붙여준다. 설정 조회가 막히면 위젯 UI 가 아예 뜨지 않으므로
     * 정상 브라우저 경로에서는 그 단계가 실질적 억제력이 된다.
     * 여기서는 진단용으로 기록만 하고, 실질 방어는 rate limit 이 맡는다(WidgetController 주석).
     */
    public ChatResponse chatAsWidget(String publicKey, String origin, ChatRequest request) {
        Bot bot = botService.findByPublicKey(publicKey);
        log.debug("[widget-chat] publicKey={} origin={}", publicKey, origin);

        ChatTurnStore.Turn turn = turnStore.openWidgetTurn(
                bot.getId(), request.message(), request.sessionId());

        AiChatResponse ai = aiServiceClient.chat(
                new AiChatRequest(bot.getId(), request.message(), request.sessionId()));

        String answer = resolveAnswer(turn.fallbackMessage(), ai);
        List<SourceResponse> sources = toSources(ai);

        UUID messageId = turnStore.saveAnswer(
                turn.conversationId(), answer, toSourcesJson(sources), ai.isFallback(), ai.latencyMs());

        log.info("[widget-chat] botId={} conversationId={} isFallback={} latencyMs={}",
                bot.getId(), turn.conversationId(), ai.isFallback(), ai.latencyMs());

        return new ChatResponse(answer, sources, ai.isFallback(), ai.latencyMs(), messageId);
    }

    /** 피드백 기록 (👍/👎). 값 규칙과 소유권 확인은 {@link ChatTurnStore} 와 엔티티가 맡는다. */
    public void applyFeedback(UUID userId, UUID messageId, Short feedback) {
        turnStore.applyFeedback(userId, messageId, feedback);
    }

    /**
     * Python 응답을 봇 설정에 맞춰 후처리한다.
     *
     * <p><b>현재 봇별 설정을 반영할 수 있는 유일한 지점이다.</b>
     * Python 의 {@code POST /internal/chat} 은 {@code fallback_message} 를 받지 않아
     * 자기 기본 문구로 거절한다. Spring 이 {@code is_fallback == true} 를 보고 봇의 문구로 바꾼다.
     *
     * <p>⚠️ {@code system_prompt} 는 이 방식으로도 반영할 수 없다. 그건 <b>생성 과정</b>에 들어가야 하는데
     * Python 요청 스키마에 자리가 없다. 봇 설정 화면에서 저장은 되지만 답변에는 아무 영향이 없다 —
     * "이미 동작한다"고 말하거나 문서에 쓰지 말 것(AiChatRequest 주석).
     */
    private String resolveAnswer(String fallbackMessage, AiChatResponse ai) {
        if (!ai.isFallback()) {
            return ai.answer();
        }
        // Python 원본 거절 문구는 로그에만 남긴다. messages.content 에는
        // <사용자가 실제로 본 문장>이 들어가야 로그를 보고 상황을 재현할 수 있다.
        log.debug("[chat] fallback 치환 — python=\"{}\" → bot=\"{}\"", ai.answer(), fallbackMessage);
        return fallbackMessage;
    }

    /** Python 의 snake_case source 를 우리 camelCase DTO 로 바꾼다. null 이면 빈 목록. */
    private List<SourceResponse> toSources(AiChatResponse ai) {
        if (ai.sources() == null) {
            return List.of();
        }
        return ai.sources().stream().map(SourceResponse::from).toList();
    }

    /**
     * {@code messages.sources}(JSONB)에 저장할 JSON. 근거가 없으면 null 을 저장한다.
     *
     * <p><b>Python 응답이 아니라 우리 DTO({@link SourceResponse})를 직렬화하는 이유.</b>
     * 저장 형식이 우리 공개 API 형식과 같아지므로, 나중에 로그 화면에서 읽을 때
     * <b>파싱해서 그대로 내려주면 된다</b>(snake_case ↔ camelCase 변환을 두 번 하지 않는다).
     * Python 이 Source 스키마를 바꿔도 과거 로그는 우리 형식으로 남아 계속 읽힌다.
     */
    private String toSourcesJson(List<SourceResponse> sources) {
        if (sources.isEmpty()) {
            return null;
        }
        return objectMapper.writeValueAsString(sources);
    }
}
