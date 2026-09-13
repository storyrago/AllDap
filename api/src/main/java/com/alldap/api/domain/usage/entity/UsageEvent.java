package com.alldap.api.domain.usage.entity;

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

import java.time.Instant;

/**
 * 과금 대상 사건 한 건. <b>append-only 다 — 만들고 나면 고치지도 지우지도 않는다.</b>
 *
 * <p><b>왜 연관관계(@ManyToOne)를 하나도 두지 않는가.</b>
 * {@code user_id} 는 FK 지만 {@code User} 로 매핑하지 않고 {@code Long} 그대로 둔다.
 * 이 엔티티에서 사용자나 봇을 타고 갈 일이 없고, LAZY 프록시를 트랜잭션 밖으로 들고 나가
 * 터지는 사고({@code open-in-view=false})를 애초에 만들지 않기 위해서다.
 * {@code bot_id} 는 아예 FK 가 아니다 — 봇이 지워져도 이 행은 남아야 한다.
 *
 * <p><b>이 엔티티는 거의 읽히지 않는다.</b> 쓰기는 네이티브 INSERT 로 하고 집계는 count 로 한다.
 * 그래도 두는 이유는 {@code ddl-auto=validate} 다 — 마이그레이션과 코드가 어긋나면
 * <b>기동 단계에서 바로 실패해</b> 조용한 드리프트를 막아준다.
 */
@Getter
@Entity
@Table(name = "usage_events")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class UsageEvent extends BaseEntity {

    /** 위젯에서 실제로 만들어진 답변. fallback 은 제외된다 */
    public static final String KIND_CHAT_ANSWER = "chat_answer";
    /** 완료된 품질 평가 실행. partial·failed 는 제외된다 */
    public static final String KIND_EVAL_RUN = "eval_run";

    /** DB 가 번호를 매긴다(IDENTITY). 그 이유와 대가(배치 INSERT 가 꺼지는 것)는 {@link com.alldap.api.domain.user.entity.User} 의 id 주석 참고. */
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "id", nullable = false, updatable = false)
    private Long id;

    @Column(name = "user_id", nullable = false, updatable = false)
    private Long userId;

    /** 표시용. 봇이 지워지면 가리키는 대상이 없어진다 — 의도한 것이다 */
    @Column(name = "bot_id", updatable = false)
    private Long botId;

    @Column(name = "kind", length = 20, nullable = false, updatable = false)
    private String kind;

    @Column(name = "source_ref", nullable = false, updatable = false)
    private Long sourceRef;

    @Column(name = "occurred_at", nullable = false, updatable = false)
    private Instant occurredAt;
}
