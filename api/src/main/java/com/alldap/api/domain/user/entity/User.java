package com.alldap.api.domain.user.entity;

import com.alldap.api.global.common.BaseEntity;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.security.SecureRandom;
import java.util.HexFormat;
import java.util.UUID;

/**
 * 서비스 가입자. {@code users} 테이블.
 *
 * <p>쓰기 소유자는 Spring 이다. Python 은 조회만 한다.
 *
 * <p>스키마 대조 (db/migration):
 * <pre>
 * id            UUID PRIMARY KEY DEFAULT gen_random_uuid()
 * email         VARCHAR(255) UNIQUE NOT NULL
 * password_hash VARCHAR(255) NOT NULL
 * name          VARCHAR(50)              ← nullable
 * billing_customer_key VARCHAR(50) UNIQUE NOT NULL   ← V6. Spring 이 생성해 넣는다
 * created_at    TIMESTAMPTZ NOT NULL     ← BaseEntity
 * </pre>
 * updated_at 컬럼은 없다. BaseEntity 주석 참고.
 */
@Getter
@Entity
@Table(name = "users")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class User extends BaseEntity {

    /**
     * 토스에 보내는 우리 쪽 고객 식별자의 접두사.
     *
     * <p><b>왜 {@code users.id}(UUID)를 그대로 쓰지 않는가.</b> 토스의 형식 요구는 만족하지만,
     * 그러면 <b>내부 기본키가 외부 업체에 그대로 나간다</b> — 토스 대시보드·로그·CS 이력에 우리 PK 가 찍힌다.
     * {@code Bot.publicKey}('pk_...')가 정확히 같은 이유로 존재한다(봇 UUID 를 고객 사이트 HTML 에
     * 노출하지 않으려고 만든 별도 공개키). 결제도 같은 규칙을 따른다.
     *
     * <p><b>왜 카드가 아니라 사용자에 붙는가.</b> customerKey 는 카드보다 오래 산다 —
     * 카드를 빼도 남아야 재등록 시 토스 쪽 고객 이력이 이어진다.
     * 반대로 billingKey 는 카드와 함께 죽으므로 별도 테이블({@code billing_methods})에 있다.
     */
    public static final String BILLING_CUSTOMER_KEY_PREFIX = "bcus_";

    /**
     * 128비트 난수 → 소문자 hex 32자. 접두사 포함 37자로 {@code VARCHAR(50)} 에 들어간다.
     *
     * <p>{@code Bot.generatePublicKey()} 는 URL-safe Base64 를 쓰는데 여기서는 hex 다.
     * 이유 둘: ① 토스의 허용 문자 제약(영문·숫자·{@code - _ = . @})에 hex 는 고민 없이 들어간다.
     * ② {@code V6__billing_method.sql} 이 기존 계정을 메꿀 때
     * {@code replace(gen_random_uuid()::text,'-','')} 로 <b>같은 모양</b>을 만든다 —
     * 생성 경로가 둘인데 결과 형식이 다르면 나중에 "이건 어느 쪽이 만든 키지"를 따지게 된다.
     */
    private static final int BILLING_CUSTOMER_KEY_RANDOM_BYTES = 16;
    private static final SecureRandom RANDOM = new SecureRandom();

    /**
     * {@code GenerationType.UUID} 는 Hibernate 가 INSERT 전에 Java 에서 UUID 를 만든다.
     * DB 의 {@code DEFAULT gen_random_uuid()} 와 충돌하지 않으며(값을 넘기면 기본값은 무시된다),
     * INSERT 후 id 를 다시 읽어오는 왕복이 없어서 유리하다.
     */
    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    @Column(name = "id", nullable = false, updatable = false)
    private UUID id;

    @Column(name = "email", length = 255, nullable = false, unique = true)
    private String email;

    /** BCrypt 해시. 평문 비밀번호는 어떤 경우에도 여기 들어오면 안 된다. */
    @Column(name = "password_hash", length = 255, nullable = false)
    private String passwordHash;

    @Column(name = "name", length = 50)
    private String name;

    /**
     * 토스에 보내는 고객 식별자. 계정이 사는 동안 바뀌지 않는다 —
     * 카드를 지웠다 다시 넣어도 <b>같은 값이어야</b> 토스 쪽 고객 이력이 이어진다.
     * 그래서 바꾸는 도메인 메서드를 두지 않았다(setter 도 없다).
     *
     * <p>⚠️ 이 필드를 지우면 {@code ddl-auto=validate} 는 <b>통과한다</b>(매핑되지 않은 컬럼은
     * 검사 대상이 아니다). 대신 가입 INSERT 에 컬럼이 빠져 NOT NULL 위반으로 500 이 난다 —
     * 기동이 아니라 <b>첫 가입에서</b> 드러나는 종류의 고장이다.
     */
    @Column(name = "billing_customer_key", length = 50, nullable = false, unique = true)
    private String billingCustomerKey;

    /**
     * 정적 팩토리. {@code @Builder} 대신 이걸 쓰는 이유:
     * 빌더는 "이메일 없이 사용자 만들기" 같은 불완전한 객체 생성을 컴파일 단계에서 막지 못한다.
     * 정적 팩토리는 필수값을 파라미터로 강제하고, 이름으로 생성 의도를 드러낸다.
     *
     * @param passwordHash 반드시 해시된 값. 해싱은 서비스 계층(PasswordEncoder)의 책임이다.
     */
    public static User create(String email, String passwordHash, String name) {
        User user = new User();
        user.email = email;
        user.passwordHash = passwordHash;
        user.name = name;
        // 생성 책임을 여기(도메인) 안에 둔다. Bot.create() 가 publicKey 를 만드는 것과 같은 이유 —
        // 생성 위치가 밖에 있으면 "키를 안 넣고 만든 행"이 생길 여지가 남는다.
        // 컬럼이 NOT NULL 이라 그런 행은 DB 가 거절하지만, 거절은 <가입 실패>로 사용자에게 간다.
        // 불변식은 그것을 지켜야 하는 객체 안에서 지키는 게 맞다.
        user.billingCustomerKey = generateBillingCustomerKey();
        return user;
    }

    private static String generateBillingCustomerKey() {
        byte[] bytes = new byte[BILLING_CUSTOMER_KEY_RANDOM_BYTES];
        RANDOM.nextBytes(bytes);
        return BILLING_CUSTOMER_KEY_PREFIX + HexFormat.of().formatHex(bytes);
    }

    // TODO(W2): 비밀번호 변경·이름 변경이 필요해지면 changePassword(String newHash) 처럼
    //   의도가 드러나는 도메인 메서드로 추가할 것. @Setter 는 쓰지 않는다.
}
