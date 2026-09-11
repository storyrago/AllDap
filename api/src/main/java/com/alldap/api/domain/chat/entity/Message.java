package com.alldap.api.domain.chat.entity;

import com.alldap.api.global.common.BaseEntity;
import com.alldap.api.global.exception.ApiException;
import com.alldap.api.global.exception.ErrorCode;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import java.util.UUID;

/**
 * 대화 메시지 한 건. {@code messages} 테이블. 쓰기 소유자는 Spring 이다.
 *
 * <p>스키마 대조 (db/migration):
 * <pre>
 * id              UUID PRIMARY KEY
 * conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE
 * role            VARCHAR(10) NOT NULL          -- user/assistant
 * content         TEXT NOT NULL
 * sources         JSONB                         -- nullable, assistant 메시지에만
 * is_fallback     BOOLEAN NOT NULL DEFAULT false
 * feedback        SMALLINT                      -- null / 1 / -1  → Java 타입은 Short
 * latency_ms      INT                           -- nullable
 * created_at      TIMESTAMPTZ NOT NULL          ← BaseEntity
 * </pre>
 */
@Getter
@Entity
@Table(name = "messages")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class Message extends BaseEntity {

    public static final String ROLE_USER = "user";
    public static final String ROLE_ASSISTANT = "assistant";

    /** 도움이 됨 (👍) */
    public static final short FEEDBACK_UP = 1;
    /** 도움이 안 됨 (👎) */
    public static final short FEEDBACK_DOWN = -1;

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    @Column(name = "id", nullable = false, updatable = false)
    private UUID id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "conversation_id", nullable = false)
    private Conversation conversation;

    /** user | assistant */
    @Column(name = "role", length = 10, nullable = false)
    private String role;

    /**
     * 메시지 본문.
     *
     * <p>assistant 메시지이고 {@code isFallback} 이 true 이면,
     * 여기 저장되는 값은 Python 의 원본 거절 문구가 아니라 <b>봇의 fallback_message 로 치환된 문구</b>다.
     * 사용자가 실제로 본 문장을 그대로 남겨야 로그를 보고 상황을 재현할 수 있기 때문이다.
     */
    @Column(name = "content", nullable = false)
    private String content;

    /**
     * 답변의 근거 청크 목록. Postgres {@code JSONB} 컬럼이다.
     *
     * <p><b>왜 별도 테이블이 아니라 JSONB 인가.</b> sources 는 "그 시점에 무엇을 근거로 답했는가"를
     * 박제해두는 스냅샷이다. 청크가 나중에 재임베딩되거나 문서가 지워져도
     * 당시 기록은 그대로 남아야 로그·품질 분석이 의미를 갖는다.
     * chunks 테이블로 조인하면 그 시점을 재현할 수 없다(게다가 chunks 는 Python 소유다).
     *
     * <p>타입이 {@code String} 인 이유: Spring 은 이 JSON 의 내용을 해석할 필요가 거의 없고
     * 응답으로 내려줄 때만 파싱하면 된다. 객체로 매핑하면 Python 이 Source 스키마를 바꿀 때마다
     * 과거 로그를 못 읽는 문제가 생긴다.
     *
     * <p>✅ 응답 DTO 변환은 <b>이미 이렇게 하고 있다</b>(옛 TODO 를 지운 자리다).
     *   {@code ConversationLogService} 가 {@code ObjectMapper} 로 파싱해
     *   {@code MessageResponse.sources} 에 담고, <b>파싱에 실패해도 예외를 던지지 않는다</b>:
     *   {@code catch (RuntimeException)} 에서 로그만 남기고 그 메시지를 근거 없이 내려보낸다.
     *   과거 로그 한 건의 JSON 이 깨졌다고 대화 전체가 500 이 되면 안 되기 때문이다.
     */
    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "sources")
    private String sources;

    /**
     * 근거를 찾지 못해 답변을 거절했는가.
     *
     * <p>이 프로젝트의 핵심 지표다. 품질 대시보드의 "미답변 목록"과 응답률(answered_rate)이
     * 전부 이 컬럼에서 나온다. 편의를 이유로 기록을 생략하지 말 것.
     */
    @Column(name = "is_fallback", nullable = false)
    private boolean isFallback;

    /**
     * null / 1(👍) / -1(👎).
     *
     * <p>컬럼이 {@code SMALLINT} 이므로 Java 타입은 {@code Short} 다.
     * {@code Integer} 로 두면 {@code ddl-auto=validate} 에서 타입이 어긋난다.
     * 또 "피드백 없음"을 표현해야 하므로 primitive({@code short})가 아니라 래퍼 타입이어야 한다.
     */
    @Column(name = "feedback")
    private Short feedback;

    /** Python 내부에서 잰 시간. Spring→Python 왕복 시간은 포함되지 않는다. */
    @Column(name = "latency_ms")
    private Integer latencyMs;

    /** 사용자 질문 메시지. */
    public static Message createUserMessage(Conversation conversation, String content) {
        Message message = new Message();
        message.conversation = conversation;
        message.role = ROLE_USER;
        message.content = content;
        message.isFallback = false;
        return message;
    }

    /**
     * 답변 메시지.
     *
     * @param content   사용자가 실제로 보게 될 문장 (fallback 이면 봇의 fallback_message)
     * @param sourcesJson 근거 청크 JSON 문자열. 근거가 없으면 null.
     */
    public static Message createAssistantMessage(Conversation conversation,
                                                 String content,
                                                 String sourcesJson,
                                                 boolean isFallback,
                                                 Integer latencyMs) {
        Message message = new Message();
        message.conversation = conversation;
        message.role = ROLE_ASSISTANT;
        message.content = content;
        message.sources = sourcesJson;
        message.isFallback = isFallback;
        message.latencyMs = latencyMs;
        return message;
    }

    /**
     * 피드백 기록. 상태 변경을 의도가 드러나는 도메인 메서드로 노출한다(@Setter 금지).
     *
     * <p><b>값 규칙을 컨트롤러가 아니라 여기서 강제하는 이유.</b>
     * 피드백을 남기는 경로가 앞으로 최소 둘이 된다 — 관리자 대시보드와 위젯 엔드유저.
     * 검증을 컨트롤러에 두면 경로를 하나 추가할 때마다 같은 검증을 복사해야 하고,
     * 한 번 빠뜨리면 DB 에 0 이나 5 같은 값이 들어간다. 엔티티에 두면 <b>어느 경로로 와도</b> 지켜진다.
     *
     * <p>{@code FeedbackRequest} 의 {@code @Min(-1) @Max(1)} 만으로는 <b>0 이 통과한다.</b>
     * 여기가 그 구멍을 막는 자리다.
     */
    public void applyFeedback(Short feedback) {
        if (feedback == null || (feedback != FEEDBACK_UP && feedback != FEEDBACK_DOWN)) {
            throw new ApiException(ErrorCode.INVALID_INPUT,
                    "피드백 값은 도움됨(1) 또는 도움안됨(-1) 만 보낼 수 있습니다.");
        }
        // 질문에 "도움이 됐다"를 매기는 건 의미가 없다. 품질 지표는 <답변>에 대한 평가로만 집계된다.
        if (!ROLE_ASSISTANT.equals(role)) {
            throw new ApiException(ErrorCode.INVALID_INPUT,
                    "답변에만 피드백을 남길 수 있습니다. 질문이 아니라 답변 메시지를 선택해주세요.");
        }
        this.feedback = feedback;
    }
}
