package com.alldap.api.domain.eval.entity;

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

import java.math.BigDecimal;
import java.util.UUID;

/**
 * 질문 하나에 대한 채점 결과. {@code eval_results} 테이블.
 * <b>쓰기 소유자는 Python</b>, Spring 은 조회만 한다.
 *
 * <p>스키마 대조 (db/migration):
 * <pre>
 * id               UUID PRIMARY KEY
 * run_id           UUID NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE
 * question_id      UUID NOT NULL REFERENCES eval_questions(id) ON DELETE CASCADE
 * generated_answer TEXT             -- nullable
 * retrieved_chunks JSONB            -- nullable
 * faithfulness     NUMERIC(4,3)     -- → BigDecimal
 * relevancy        NUMERIC(4,3)     -- → BigDecimal
 * created_at       TIMESTAMPTZ NOT NULL   ← BaseEntity
 * </pre>
 */
@Getter
@Entity
@Table(name = "eval_results")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class EvalResult extends BaseEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    @Column(name = "id", nullable = false, updatable = false)
    private UUID id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "run_id", nullable = false)
    private EvalRun run;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "question_id", nullable = false)
    private EvalQuestion question;

    @Column(name = "generated_answer")
    private String generatedAnswer;

    /**
     * 이 답변이 실제로 참고한 청크들(스냅샷). {@code messages.sources} 와 같은 구조·같은 이유로 JSONB 다.
     * chunks 테이블로 조인하지 않는다 — 그 시점을 재현할 수 없고, chunks 는 Python 소유다.
     */
    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "retrieved_chunks")
    private String retrievedChunks;

    /** 충실성: 답이 근거 문서와 일치하는가 (0~1) */
    @Column(name = "faithfulness", precision = 4, scale = 3)
    private BigDecimal faithfulness;

    /** 관련성: 질문에 맞는 답인가 (0~1) */
    @Column(name = "relevancy", precision = 4, scale = 3)
    private BigDecimal relevancy;
}
