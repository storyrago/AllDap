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
import java.util.List;
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
     * 봇별 답변 지침. <b>실제 답변에 반영된다</b> (2026-08-13, PRD F-06 충족).
     *
     * <p>다만 <b>Spring 이 전달하지 않는다.</b> Python 이 이 컬럼을 직접 읽어 간다
     * ({@code ai-service/app/generator.py} 의 {@code fetch_bot_prompt}).
     * 이유는 AiChatRequest 주석에 적어뒀다. 요약하면 평가({@code evalrun})가 Spring 을
     * 거치지 않기 때문이고, 그래서 Spring 쪽에는 이 값을 쓰는 코드가 한 줄도 없다.
     *
     * <p>⚠️ 그래서 <b>Spring 코드만 읽어서는 "반영되지 않는다"고 오해하기 쉽다.</b>
     * 실제로 2026-09 까지 이 저장소의 주석 6곳이 그렇게 적혀 있었다.
     *
     * <p>🔴 결합은 <b>대체가 아니라 덧붙임</b>이다. 기본 규칙을 앞에 두고 "충돌하면 위가 우선"을
     * 명시한다. 대체하면 {@code NO_ANSWER} 규칙이 사라져 환각 억제가 설정 하나로 뚫린다.
     * 그마저도 <b>방어이지 보장이 아니다</b>: 지침으로 지침을 막는 것이라
     * 실제로 뚫리는 경우가 실측돼 있다({@code ai-service/app/bot_prompt_check.py}).
     * 봇 지침을 바꾼 뒤에는 그걸 돌려 깨지는지 볼 것.
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
     * <p>✅ <b>{@code ddl-auto=validate} 통과는 확인됐다</b>(옛 TODO 를 지운 자리다).
     *   걱정했던 것은 Hibernate 가 기대하는 배열 타입 표기와 Postgres 의 {@code _text} 표기가
     *   어긋나 기동 단계에서 SchemaManagementException 이 나는 경우였는데, 그런 일은 없었다.
     *   {@code columnDefinition} 지정도 커스텀 UserType 도 필요하지 않았다.
     *
     *   <p><b>근거는 1회성 기동 로그가 아니다.</b> 통합 테스트가 Testcontainers 로 매번
     *   진짜 Postgres 를 띄우고 Flyway 를 적용한 뒤 {@code validate} 로 기동하므로,
     *   이 매핑은 <b>테스트를 돌릴 때마다 다시 검증된다.</b> 스키마나 이 필드를 건드려 어긋나면
     *   전체 통합 테스트가 기동 단계에서 한꺼번에 실패하는 형태로 드러난다.
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

    /**
     * 봇 설정 부분 수정. <b>null 인 인자는 "안 보냄"이므로 기존 값을 유지한다.</b>
     *
     * <p>메서드를 하나로 묶은 이유: 호출 지점이 {@code PATCH /api/bots/{botId}} 하나뿐이라
     * rename()/changeWelcomeMessage() 로 쪼개도 서비스에서 다시 5번 if 로 조립하게 된다.
     * 필드마다 다른 규칙(검증·이벤트 발행)이 생기면 그때 쪼갠다.
     *
     * <p>{@code @Setter} 를 쓰지 않는 이유는 여전히 유효하다 — setter 는 아무 데서나
     * 아무 필드나 바꿀 수 있게 열어주지만, 이 메서드는 "설정 화면에서 고칠 수 있는 것"만 받는다.
     * publicKey·user 는 인자에 없으므로 <b>바꾸는 코드를 쓸 수가 없다.</b>
     */
    public void updateSettings(String name, String systemPrompt, String welcomeMessage,
                               String fallbackMessage, List<String> allowedOrigins) {
        if (name != null) {
            this.name = name;
        }
        if (systemPrompt != null) {
            this.systemPrompt = systemPrompt;
        }
        if (welcomeMessage != null) {
            this.welcomeMessage = welcomeMessage;
        }
        if (fallbackMessage != null) {
            this.fallbackMessage = fallbackMessage;
        }
        if (allowedOrigins != null) {
            // List<String> → String[]. 변환을 여기 한 곳에 두면 서비스가 배열 타입을 몰라도 된다.
            this.allowedOrigins = allowedOrigins.toArray(String[]::new);
        }
    }

    /**
     * 이 Origin 에서 위젯을 쓰도록 허용했는가.
     *
     * <h2>빈 목록은 "전부 허용" 이 아니라 "전부 차단" 이다 (가장 중요한 규칙)</h2>
     * 봇을 만들면 {@code allowedOrigins} 는 빈 배열이다. 이걸 "아직 설정 안 했으니 다 열어두자" 로
     * 해석하면 <b>모든 신규 봇이 무방비 상태로 태어난다.</b> publicKey 는 고객 사이트 HTML 에
     * 그대로 노출되므로 누구나 복사해 자기 사이트에 붙일 수 있고, 그러면 LLM 비용이 봇 주인에게 청구된다.
     * 보안 기본값은 <b>닫힘</b>이어야 한다 — 열려면 주인이 의도를 갖고 도메인을 적어야 한다.
     *
     * <p>대신 UX 로 보완한다: 차단됐을 때 {@link com.alldap.api.global.exception.ErrorCode#ORIGIN_NOT_ALLOWED}
     * 가 "봇 설정의 허용 도메인에 현재 주소를 추가해주세요" 라고 무엇을 하면 되는지 알려준다.
     *
     * <h2>정확히 일치만 허용한다</h2>
     * 와일드카드({@code *.example.com})는 지원하지 않는다. 부분 일치·접미사 비교는
     * {@code evil-example.com} 이 {@code example.com} 으로 통과하는 고전적인 실수를 부른다.
     * 필요해지면 그때 <b>파싱된 호스트 단위</b>로 규칙을 만든다. 지금은 필요 없다.
     *
     * <p>Origin 은 스킴+호스트+포트다({@code https://example.com:8443}). 경로는 들어 있지 않다.
     * 대소문자는 스킴·호스트만 무시하면 되지만, 실무에서 오는 값이 이미 소문자로 정규화돼 있어
     * 여기서는 {@code trim} 뒤 대소문자 무시 비교로 충분하다.
     */
    public boolean isOriginAllowed(String origin) {
        if (origin == null || origin.isBlank() || allowedOrigins == null) {
            return false;
        }
        String normalized = origin.trim();
        for (String allowed : allowedOrigins) {
            if (allowed != null && allowed.trim().equalsIgnoreCase(normalized)) {
                return true;
            }
        }
        return false;
    }

    /** 허용 도메인을 하나도 설정하지 않은 상태. 안내 문구를 다르게 주려고 구분한다. */
    public boolean hasNoAllowedOrigins() {
        return allowedOrigins == null || allowedOrigins.length == 0;
    }
}
