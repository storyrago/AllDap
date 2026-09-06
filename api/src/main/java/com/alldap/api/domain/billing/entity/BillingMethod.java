package com.alldap.api.domain.billing.entity;

import com.alldap.api.domain.billing.service.CardIssuer;
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
 * 계정에 등록된 결제 수단(토스 빌링키) 한 장. <b>계정당 최대 1장</b>이다.
 *
 * <p>스키마 대조 ({@code V6__billing_method.sql}):
 * <pre>
 * id                 UUID PRIMARY KEY
 * user_id            UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE
 * billing_key_enc    VARCHAR(512) NOT NULL   ← Base64(IV ‖ 암호문 ‖ GCM 태그)
 * issuer_code        VARCHAR(4)   NOT NULL
 * card_number_masked VARCHAR(20)  NOT NULL
 * created_at         TIMESTAMPTZ  NOT NULL   ← BaseEntity
 * </pre>
 * updated_at 컬럼은 없다. 카드는 고치는 게 아니라 지우고 다시 등록하는 것이다.
 *
 * <p><b>왜 {@code @ManyToOne User} 가 아니라 {@code UUID userId} 인가.</b>
 * {@code UsageEvent} 와 같은 이유다 — 여기서 사용자를 타고 갈 일이 없고,
 * {@code open-in-view=false} 라 LAZY 프록시를 트랜잭션 밖으로 들고 나가면 터진다.
 *
 * <p>🔴 <b>이 엔티티에 빌링키 평문이 들어오는 일은 없다.</b> 필드 이름이 {@code billingKeyEnc} 인 것이
 * 그 약속이다. 복호화는 {@code BillingCrypto} 만 하고, 그 결과는 토스로 나갈 때만 존재한다.
 *
 * <p><b>setter 도 도메인 메서드도 두지 않는다.</b> 카드 정보를 바꾸는 연산이 없기 때문이다
 * (교체 = 삭제 후 재등록). 상태 전이가 없으면 만들지 않는다.
 */
@Getter
@Entity
@Table(name = "billing_methods")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class BillingMethod extends BaseEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    @Column(name = "id", nullable = false, updatable = false)
    private UUID id;

    @Column(name = "user_id", nullable = false, updatable = false, unique = true)
    private UUID userId;

    /** Base64(IV 12B ‖ 암호문 ‖ GCM 인증태그 16B). 평문이 아니다. */
    @Column(name = "billing_key_enc", length = 512, nullable = false, updatable = false)
    private String billingKeyEnc;

    /** 토스 카드 발급사 코드("61"). 이름은 {@link CardIssuer} 가 붙인다. */
    @Column(name = "issuer_code", length = 4, nullable = false, updatable = false)
    private String issuerCode;

    /** 토스가 마스킹해서 준 번호("43301234****123*"). 전체 번호는 우리 서버에 닿지 않는다. */
    @Column(name = "card_number_masked", length = 20, nullable = false, updatable = false)
    private String cardNumberMasked;

    public static BillingMethod create(UUID userId, String billingKeyEnc,
                                       String issuerCode, String cardNumberMasked) {
        BillingMethod method = new BillingMethod();
        method.userId = userId;
        method.billingKeyEnc = billingKeyEnc;
        method.issuerCode = issuerCode;
        method.cardNumberMasked = cardNumberMasked;
        return method;
    }
}
