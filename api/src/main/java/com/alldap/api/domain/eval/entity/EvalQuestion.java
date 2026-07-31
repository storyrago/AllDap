package com.alldap.api.domain.eval.entity;

import com.alldap.api.domain.bot.entity.Bot;
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

import java.util.UUID;

/**
 * 평가용 테스트 질문. {@code eval_questions} 테이블.
 *
 * <p><b>쓰기 소유자는 Python 이다</b>(질문 자동 생성이 W3 의 핵심 기능). Spring 은 조회만 한다.
 * 따라서 상태 변경 메서드도, 정적 팩토리도 두지 않는다.
 * TODO(W3): 관리자가 질문을 직접 추가/비활성화하는 기능이 필요해지면,
 *   Spring 이 직접 쓸지 Python 에 위임할지 먼저 결정할 것. 소유권을 흐리면 안 된다.
 *
 * <p>스키마 대조 (db/migration):
 * <pre>
 * id              UUID PRIMARY KEY
 * bot_id          UUID NOT NULL REFERENCES bots(id) ON DELETE CASCADE
 * question        TEXT NOT NULL
 * ground_truth    TEXT NOT NULL
 * source_chunk_id UUID REFERENCES chunks(id) ON DELETE SET NULL   ← nullable
 * is_active       BOOLEAN NOT NULL DEFAULT true
 * created_at      TIMESTAMPTZ NOT NULL                            ← BaseEntity
 * </pre>
 */
@Getter
@Entity
@Table(name = "eval_questions")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class EvalQuestion extends BaseEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    @Column(name = "id", nullable = false, updatable = false)
    private UUID id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "bot_id", nullable = false)
    private Bot bot;

    @Column(name = "question", nullable = false)
    private String question;

    /** 문서 청크에서 뽑아낸 기대 답변. 채점(LLM-as-judge)의 기준이 된다. */
    @Column(name = "ground_truth", nullable = false)
    private String groundTruth;

    /**
     * 이 질문이 어느 청크에서 생성됐는지.
     *
     * <p><b>{@code @ManyToOne Chunk} 가 아니라 원시 UUID 로 둔 이유:</b>
     * chunks 엔티티가 존재하지 않기 때문이다.
     * {@code chunks.embedding} 이 pgvector 의 {@code VECTOR(1536)} 타입이라 JPA 로 매핑할 수 없고,
     * 소유권상으로도 chunks 는 Python 전담이라 Spring 이 건드리지 않는다
     * (자세한 설명은 {@code Document} 엔티티 클래스 주석 참고).
     * 여기서는 FK 값 자체만 들고 있다가 필요하면 Python 에 물어보는 방식이 맞다.
     */
    @Column(name = "source_chunk_id")
    private UUID sourceChunkId;

    /** false 면 평가 실행에서 제외된다(관리자가 끌 수 있음). */
    @Column(name = "is_active", nullable = false)
    private boolean isActive;
}
