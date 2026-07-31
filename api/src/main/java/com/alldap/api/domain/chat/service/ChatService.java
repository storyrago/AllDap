package com.alldap.api.domain.chat.service;

import com.alldap.api.domain.bot.entity.Bot;
import com.alldap.api.domain.bot.repository.BotRepository;
import com.alldap.api.domain.chat.dto.ChatRequest;
import com.alldap.api.domain.chat.dto.ChatResponse;
import com.alldap.api.domain.chat.repository.ConversationRepository;
import com.alldap.api.domain.chat.repository.MessageRepository;
import com.alldap.api.global.client.AiServiceClient;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.UUID;

/**
 * 채팅 서비스. 이 프로젝트에서 가장 중요한 흐름이다.
 *
 * <p><b>흐름 (PRD 요청 흐름 ②):</b>
 * <pre>
 * 1. 봇 확인 (관리자 채팅이면 소유권, 위젯이면 publicKey + Origin)
 * 2. conversations 조회 또는 생성 → user 메시지 저장
 * 3. Python 호출 (POST /internal/chat)   ← 수십 초 걸릴 수 있는 구간
 * 4. is_fallback == true 면 answer 를 봇의 fallback_message 로 치환
 * 5. assistant 메시지 저장 (sources JSONB + is_fallback + latency_ms)
 * 6. messageId 를 포함한 응답 반환 (피드백 API 를 부르려면 필요하다)
 * </pre>
 *
 * <p><b>트랜잭션 경계가 이 클래스의 핵심 설계 포인트다.</b>
 * 3번(Python 호출)을 하나의 트랜잭션 안에 넣으면 수십 초 동안 DB 커넥션이 묶여
 * 동시 사용자가 조금만 늘어도 커넥션 풀이 마른다. 그래서 클래스에 {@code @Transactional} 을 걸지 않고,
 * <b>DB 작업 구간(2번, 5번)만 짧은 트랜잭션으로 끊는다.</b>
 *
 * <p>TODO(W2): 위 구조를 구현할 때 "저장 전용" 메서드를 별도 빈으로 분리할지 결정할 것.
 *   같은 클래스 안에서 {@code @Transactional} 메서드를 self-invocation 하면
 *   프록시를 거치지 않아 트랜잭션이 걸리지 않는다(Spring AOP 의 유명한 함정).
 *
 * <p>TODO(W2): 3번이 실패했을 때 2번에서 저장한 user 메시지를 어떻게 할지 정할 것.
 *   남겨두면 "질문만 있고 답이 없는" 로그가 생기는데, 오히려 장애 추적에 유용할 수 있다.
 *   지우려면 보상 트랜잭션이 필요하다. 남기는 쪽을 기본으로 검토한다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ChatService {

    private final AiServiceClient aiServiceClient;
    private final BotRepository botRepository;
    private final ConversationRepository conversationRepository;
    private final MessageRepository messageRepository;

    /**
     * 관리자 테스트 채팅. {@code channel = "test"} 로 기록한다.
     *
     * <p>테스트 대화를 따로 표시하는 이유: 품질 지표(응답률·미답변 목록)를 낼 때
     * 관리자가 직접 돌려본 대화가 섞이면 실사용 수치가 왜곡된다.
     */
    public ChatResponse chatAsOwner(UUID userId, UUID botId, ChatRequest request) {
        // TODO(W2): 구현. 위 클래스 주석의 1~6단계.
        throw new UnsupportedOperationException("ChatService.chatAsOwner 미구현 (W2)");
    }

    /**
     * 위젯 채팅(공개). {@code channel = "widget"} 으로 기록한다.
     *
     * <p>인증이 없으므로 보호 장치가 세 겹이다: publicKey 존재 확인 + Origin 검증 + rate limit.
     */
    public ChatResponse chatAsWidget(String publicKey, String origin, ChatRequest request) {
        // TODO(W2): 구현. 1단계에서 Origin 검증(bot.allowedOrigins)과 rate limit 을 추가로 통과시킬 것.
        throw new UnsupportedOperationException("ChatService.chatAsWidget 미구현 (W2)");
    }

    /**
     * 피드백 기록 (👍/👎).
     *
     * <p>경로에 botId 가 없으므로 message → conversation → bot → 소유자 순으로
     * 거슬러 올라가 권한을 확인해야 한다.
     */
    public void applyFeedback(UUID userId, UUID messageId, Short feedback) {
        // TODO(W2): 구현. Message.applyFeedback() 을 호출한다(엔티티가 값 규칙을 강제).
        //   TODO(W2): 위젯 엔드유저도 피드백을 남길 수 있어야 하는지 결정할 것.
        //     PRD §10.1 의 피드백 API 는 인증 경로에 있는데, 실제로 👍/👎 를 누르는 사람은
        //     대부분 위젯 사용자다. 그렇다면 공개 경로가 따로 필요하고 남용 방지도 필요해진다.
        throw new UnsupportedOperationException("ChatService.applyFeedback 미구현 (W2)");
    }

    /**
     * Python 응답을 봇 설정에 맞춰 후처리한다.
     *
     * <p>현재 봇별 설정을 반영할 수 있는 <b>유일한</b> 지점이다.
     * {@code is_fallback == true} 이면 Python 이 만든 거절 문구 대신 봇의 {@code fallback_message} 를 쓴다.
     * ({@code system_prompt} 는 Python 컨트랙트를 고치기 전까지 반영할 방법이 없다)
     *
     * <p>TODO(W2): 구현. Python 원본 문구도 로그에 남길지 결정할 것 —
     *   messages.content 에는 사용자가 실제로 본 문장(치환된 문구)이 들어가야 한다.
     */
    private String resolveAnswer(Bot bot, String pythonAnswer, boolean isFallback) {
        throw new UnsupportedOperationException("ChatService.resolveAnswer 미구현 (W2)");
    }
}
