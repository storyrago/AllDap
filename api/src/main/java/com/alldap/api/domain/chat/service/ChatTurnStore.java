package com.alldap.api.domain.chat.service;

import com.alldap.api.domain.bot.entity.Bot;
import com.alldap.api.domain.bot.repository.BotRepository;
import com.alldap.api.domain.chat.entity.Conversation;
import com.alldap.api.domain.chat.entity.Message;
import com.alldap.api.domain.chat.repository.ConversationRepository;
import com.alldap.api.domain.chat.repository.MessageRepository;
import com.alldap.api.domain.usage.repository.UsageEventRepository;
import com.alldap.api.global.exception.ApiException;
import com.alldap.api.global.exception.ErrorCode;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;


/**
 * 채팅 한 턴의 <b>DB 작업만</b> 담당한다. Python 호출은 여기 들어오지 않는다.
 *
 * <h2>왜 {@link ChatService} 와 <b>별도 빈</b>인가 (이 클래스의 존재 이유)</h2>
 * 채팅 한 턴은 이렇게 흐른다.
 * <pre>
 *   ① 질문 저장          (DB, 짧다)
 *   ② Python 호출        (수십 초 걸릴 수 있다)   ← 트랜잭션 밖이어야 한다
 *   ③ 답변 저장          (DB, 짧다)
 * </pre>
 * ②를 트랜잭션 안에 넣으면 그동안 DB 커넥션이 묶인다. 기본 풀 크기가 10 이므로
 * <b>동시 질문 10개면 그 뒤 모든 요청이(채팅과 무관한 요청까지) 커넥션을 못 얻어 멈춘다.</b>
 * Python 하나가 느려진 것이 서비스 전체 장애가 되는 경로다.
 *
 * <p>그래서 ①·③만 짧은 트랜잭션으로 끊어야 하는데, <b>같은 클래스 안에서는 그게 안 된다.</b>
 * 스프링의 {@code @Transactional} 은 프록시로 동작해서, 같은 객체의 메서드를 자기가 부르면
 * ({@code this.saveAnswer(...)}) 프록시를 거치지 않아 <b>트랜잭션이 아예 걸리지 않는다.</b>
 * 컴파일도 되고 테스트도 통과하는데 트랜잭션만 조용히 사라지는, 스프링 AOP 의 유명한 함정이다.
 * 빈을 나누면 호출이 프록시를 거치므로 구조적으로 그 사고가 불가능해진다.
 *
 * <p>대안으로 {@code TransactionTemplate} 을 주입해 람다로 감싸는 방법도 있다. 빈이 안 늘어나지만
 * 트랜잭션 경계가 서비스 코드 사이에 섞여 "어디부터 어디까지가 한 트랜잭션인지" 읽기 어려워진다.
 * 경계를 <b>메서드 단위</b>로 드러내는 쪽이 나중에 읽을 사람에게 친절하다고 판단했다.
 */
@Component
@RequiredArgsConstructor
public class ChatTurnStore {

    private final BotRepository botRepository;
    private final ConversationRepository conversationRepository;
    private final MessageRepository messageRepository;
    private final UsageEventRepository usageEventRepository;

    /**
     * ① 소유권 확인 → 대화 찾기/만들기 → 질문 저장.
     *
     * <p>반환 타입이 엔티티가 아니라 {@link Turn}(값 몇 개)인 것이 중요하다.
     * 트랜잭션이 끝나면 엔티티는 준영속 상태가 되고, {@code Bot} 의 LAZY 필드를 건드리면
     * {@code open-in-view=false} 라 {@code LazyInitializationException} 이 난다.
     * 트랜잭션 <b>밖에서 필요한 값만</b> 미리 꺼내 담아 나가면 그 사고가 원천적으로 없다.
     *
     * @param channel {@link Conversation#CHANNEL_TEST} 또는 {@link Conversation#CHANNEL_WIDGET}
     */
    @Transactional
    public Turn openTurn(Long userId, Long botId, String message, String sessionId, String channel) {
        Bot bot = botRepository.findByIdAndUserId(botId, userId)
                .orElseThrow(() -> new ApiException(ErrorCode.BOT_NOT_FOUND));
        return open(bot, message, sessionId, channel);
    }

    /**
     * 위젯용. <b>소유권 검사가 없다</b> — 위젯은 인증이 없어 "누구의 것인가" 를 물을 수 없기 때문이다.
     *
     * <p>대신 진입 조건이 다르다: 호출자({@code ChatService.chatAsWidget})가 publicKey 로
     * 봇을 이미 찾아왔고, rate limit 을 통과한 뒤에만 여기 도달한다.
     * <b>이 메서드를 관리자 경로에서 쓰면 소유권 검사가 통째로 빠지므로 절대 그러지 말 것.</b>
     */
    @Transactional
    public Turn openWidgetTurn(Long botId, String message, String sessionId) {
        Bot bot = botRepository.findById(botId)
                .orElseThrow(() -> new ApiException(ErrorCode.BOT_NOT_FOUND));
        return open(bot, message, sessionId, Conversation.CHANNEL_WIDGET);
    }

    /**
     * 대화를 찾거나 만들고 질문을 저장한다.
     *
     * <p>{@code private} 이라 프록시를 거치지 않지만 문제없다 — 호출자가 이미 트랜잭션 안이다.
     * (트랜잭션이 필요한 쪽은 {@code public} 진입점이고, 여기는 그 안에서 도는 코드다)
     */
    private Turn open(Bot bot, String message, String sessionId, String channel) {
        Conversation conversation = conversationRepository
                .findFirstByBotIdAndSessionIdAndChannelOrderByCreatedAtDesc(bot.getId(), sessionId, channel)
                .orElseGet(() -> conversationRepository.save(Conversation.create(bot, sessionId, channel)));

        messageRepository.save(Message.createUserMessage(conversation, message));

        return new Turn(conversation.getId(), bot.getFallbackMessage());
    }

    /**
     * ③ 답변 저장. 새로 만들어진 messages 행의 id 를 돌려준다
     * (프론트가 👍/👎 를 부르려면 이 값이 필요하다).
     *
     * <p>{@code getReferenceById} 를 쓰는 이유: INSERT 에 필요한 것은 {@code conversation_id}
     * 하나뿐이라 대화 행을 실제로 읽어올 이유가 없다. 프록시만 있으면 FK 가 채워지므로
     * SELECT 한 번을 아낀다. (문서 삭제에서 {@code findById} 를 쓴 것과 반대인데,
     * 거기서는 "존재하지 않으면 사용자에게 안내"가 필요했고 여기는 방금 ①에서 만든 행이라 존재가 보장된다)
     */
    @Transactional
    public Long saveAnswer(Long conversationId, String content, String sourcesJson,
                           boolean isFallback, Integer latencyMs) {
        Conversation conversation = conversationRepository.getReferenceById(conversationId);
        Message answer = messageRepository.save(
                Message.createAssistantMessage(conversation, content, sourcesJson, isFallback, latencyMs));

        // 🔴 과금 계량. <같은 트랜잭션>이라 "답변은 남았는데 계량이 안 된" 상태가 생길 수 없다.
        //    무엇이 과금 대상인지는 전부 이 쿼리 안에 있다(위젯만 · fallback 제외).
        //    여기에 if 를 두지 않는 이유는 정책이 두 곳으로 나뉘는 것을 막기 위해서다.
        //
        //    ⚠️ occurred_at 은 여기(채팅)와 평가 실행 메꾸기(UsageEventRepository.backfillEvalRuns)가
        //    서로 다른 시계로 찍힌다 — 여기는 Postgres now(), 메꾸기는 Spring(JVM) 시계로 찍힌
        //    eval_runs.created_at 을 그대로 쓴다. 월 경계 몇백 ms 안에서 두 시계가 어긋나면
        //    답변 행과 그 원장 행이 서로 다른 달로 갈릴 수 있지만, 굳이 맞추지 않는다 —
        //    맞추려면 이 INSERT 가 애플리케이션 시계에 의존하게 되어 <플러시 순서>에 따라
        //    값이 달라질 위험이 생긴다. 몇백 ms 오차보다 그게 더 나쁘다.
        usageEventRepository.recordChatAnswer(answer.getId(), conversationId, isFallback);

        return answer.getId();
    }

    /**
     * 피드백 기록. 값 규칙은 {@link Message#applyFeedback} 이 강제한다.
     *
     * <p>조회를 소유자로 좁혀 남의 메시지에 손댈 수 없게 한다.
     * 없는 메시지와 남의 메시지를 모두 404 로 답하는 것도 봇·문서와 같은 규칙이다.
     */
    @Transactional
    public void applyFeedback(Long userId, Long messageId, Short feedback) {
        Message message = messageRepository.findByIdAndConversationBotUserId(messageId, userId)
                .orElseThrow(() -> new ApiException(ErrorCode.MESSAGE_NOT_FOUND));
        // 변경 감지(dirty checking)로 UPDATE 가 나간다. save() 를 부를 필요가 없다.
        message.applyFeedback(feedback);
    }

    /**
     * 트랜잭션 밖으로 들고 나갈 값들.
     *
     * @param conversationId  답변을 붙일 대화
     * @param fallbackMessage 이 봇의 거절 문구. Python 은 이 값을 모르므로 Spring 이 치환에 쓴다
     */
    public record Turn(Long conversationId, String fallbackMessage) {
    }
}
