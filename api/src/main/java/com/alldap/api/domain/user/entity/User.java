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
        return user;
    }

    // TODO(W2): 비밀번호 변경·이름 변경이 필요해지면 changePassword(String newHash) 처럼
    //   의도가 드러나는 도메인 메서드로 추가할 것. @Setter 는 쓰지 않는다.
}
