package com.alldap.api.domain.bot.entity;

import com.alldap.api.domain.user.entity.User;
import com.alldap.api.global.common.BaseEntity;
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

import java.security.SecureRandom;
import java.util.Base64;
import java.util.UUID;

/**
 * 챗봇. {@code bots} 테이블. 쓰기 소유자는 Spring, Python 은 조회만 한다.
 *
 * <p>스키마 대조 (db/migration):
 * <pre>
 * id               UUID PRIMARY KEY
 * user_id          UUID REFERENCES users(id) ON DELETE CASCADE   ← nullable (로컬 시드 봇은 user_id 가 없다)
 * name             VARCHAR(100) NOT NULL
 * public_key       VARCHAR(32)  UNIQUE NOT NULL                  ← Spring 이 생성해 넣는다
 * system_prompt    TEXT                                          ← nullable
 * welcome_message  TEXT NOT NULL DEFAULT '무엇을 도와드릴까요?'
 * fallback_message TEXT NOT NULL DEFAULT '문서에서 답을 찾지 못했어요...'
 * allowed_origins  TEXT[]                                        ← Postgres 배열
 * created_at       TIMESTAMPTZ NOT NULL                          ← BaseEntity
 * </pre>
 */
@Getter
@Entity
@Table(name = "bots")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class Bot extends BaseEntity {

    /**
     * DB 의 DEFAULT 와 같은 값을 Java 에도 둔다.
     *
     * <p>왜 필요한가: Hibernate 는 INSERT 문에 모든 컬럼을 명시하므로,
     * 필드가 null 이면 DB 기본값이 아니라 명시적 NULL 이 들어가 NOT NULL 제약에 걸린다.
     * 즉 "DB 에 DEFAULT 가 있으니 안 넣어도 된다"는 통하지 않는다.
     */
    public static final String DEFAULT_WELCOME_MESSAGE = "무엇을 도와드릴까요?";
    public static final String DEFAULT_FALLBACK_MESSAGE = "문서에서 답을 찾지 못했어요. 담당자에게 문의해주세요.";

    private static final String PUBLIC_KEY_PREFIX = "pk_";
    /** 16바이트 랜덤 → Base64(URL-safe, 패딩 없음) 22자. 접두사 포함 25자로 VARCHAR(32)에 들어간다. */
    private static final int PUBLIC_KEY_RANDOM_BYTES = 16;
    private static final SecureRandom RANDOM = new SecureRandom();

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    @Column(name = "id", nullable = false, updatable = false)
    private UUID id;

    /**
     * 소유자. 스키마상 nullable 이라 {@code optional = true} 로 둔다.
     * (db/migration 의 로컬 시드 봇 'pk_local_dev' 에는 user_id 가 없다.
     *  여기서 nullable=false 로 잡으면 그 행을 읽을 때 터진다.)
     *
     * <p>LAZY 인 이유: 봇 목록·위젯 설정 조회에서 소유자 정보는 대부분 필요 없다.
     * {@code open-in-view=false} 이므로 트랜잭션 밖에서 이 필드를 건드리면
     * LazyInitializationException 이 난다 — 필요하면 fetch join 으로 가져올 것.
     */
    @ManyToOne(fetch = FetchType.LAZY, optional = true)
    @JoinColumn(name = "user_id")
    private User user;

    @Column(name = "name", length = 100, nullable = false)
    private String name;

    /**
     * 위젯 공개 주소 {@code /w/{publicKey}} 에 쓰이는 키.
     *
     * <p>봇 id(UUID)를 쓰지 않고 별도 키를 두는 이유: 공개 키는 고객 사이트의 HTML 에 그대로 노출된다.
     * 내부 식별자와 분리해 두면 나중에 키만 재발급해 유출에 대응할 수 있다.
     */
    @Column(name = "public_key", length = 32, nullable = false, unique = true)
    private String publicKey;

    /**
     * ⚠️ 저장은 되지만 <b>현재 답변에 반영되지 않는다.</b>
     * Python 의 {@code POST /internal/chat} 이 system_prompt 를 받지 않기 때문이다
     * (AiChatRequest 주석 참고). "이미 동작한다"고 말하거나 문서에 쓰지 말 것.
     */
    @Column(name = "system_prompt")
    private String systemPrompt;

    @Column(name = "welcome_message", nullable = false)
    private String welcomeMessage;

    /**
     * 근거를 못 찾았을 때 보여줄 문구.
     * Python 은 {@code is_fallback=true} 만 돌려주고 이 문구를 모르므로,
     * Spring 이 응답의 answer 를 이 값으로 치환한다. (ChatService 참고)
     */
    @Column(name = "fallback_message", nullable = false)
    private String fallbackMessage;

    /**
     * 위젯 임베드를 허용할 도메인 목록. Postgres {@code TEXT[]} 배열 컬럼이다.
     *
     * <p>{@code @JdbcTypeCode(SqlTypes.ARRAY)} 로 Java 배열 ↔ Postgres 배열을 직접 매핑한다.
     * {@code @ElementCollection} 을 쓰면 별도 조인 테이블이 필요한데 스키마에는 그런 테이블이 없다.
     *
     * <p>TODO(W2): 첫 기동 시 {@code ddl-auto=validate} 가 이 컬럼을 통과하는지 반드시 확인할 것.
     *   Hibernate 가 기대하는 배열 타입 표기와 Postgres 의 {@code _text} 표기가 어긋나면
     *   기동 단계에서 SchemaManagementException 이 난다. 그 경우 {@code columnDefinition}
     *   지정 또는 커스텀 UserType 으로 대응한다.
     */
    @JdbcTypeCode(SqlTypes.ARRAY)
    @Column(name = "allowed_origins")
    private String[] allowedOrigins;

    /**
     * 봇 생성. publicKey 생성 책임을 여기(도메인) 안에 둔다.
     *
     * <p>서비스 계층에 두지 않는 이유: publicKey 없는 Bot 은 존재할 수 없는데,
     * 생성 위치가 밖에 있으면 "키를 안 넣고 만든 봇"이 생길 여지가 남는다.
     * 불변식은 그것을 지켜야 하는 객체 안에서 지키는 게 맞다.
     */
    public static Bot create(User owner, String name) {
        Bot bot = new Bot();
        bot.user = owner;
        bot.name = name;
        bot.publicKey = generatePublicKey();
        bot.welcomeMessage = DEFAULT_WELCOME_MESSAGE;
        bot.fallbackMessage = DEFAULT_FALLBACK_MESSAGE;
        bot.allowedOrigins = new String[0];
        return bot;
    }

    private static String generatePublicKey() {
        byte[] bytes = new byte[PUBLIC_KEY_RANDOM_BYTES];
        RANDOM.nextBytes(bytes);
        // URL-safe 인코딩: 위젯 주소 /w/{publicKey} 의 경로에 그대로 들어가므로
        // '+' '/' 가 나오면 안 된다. 패딩('=')도 뺀다.
        return PUBLIC_KEY_PREFIX + Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    // TODO(W2): 봇 설정 수정 도메인 메서드를 추가할 것.
    //   PATCH /api/bots/{botId} 는 부분 수정이므로 "보낸 필드만 바꾸기"를 어떻게 표현할지가 핵심이다.
    //   updateSettings(...) 하나로 묶을지, rename()/changeWelcomeMessage() 처럼 쪼갤지 결정한다.
    //   어느 쪽이든 @Setter 는 쓰지 않는다 — 변경 의도가 메서드 이름에 드러나야 한다.

    // TODO(W2): allowed_origins 검증(위젯 Origin 체크)은 도메인 메서드
    //   isOriginAllowed(String origin) 으로 두는 게 맞다. 규칙(와일드카드 허용 여부, 빈 배열의 의미)을
    //   먼저 정할 것 — 빈 배열을 "전부 허용"으로 두면 보안 구멍이 된다.
}
