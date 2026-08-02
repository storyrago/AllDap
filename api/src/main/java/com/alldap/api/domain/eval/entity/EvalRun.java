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
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import java.math.BigDecimal;
import java.util.UUID;

/**
 * 평가 실행 1회. {@code eval_runs} 테이블. <b>쓰기 소유자는 Python</b>, Spring 은 조회만 한다.
 *
 * <p>스키마 대조 (db/migration):
 * <pre>
 * id               UUID PRIMARY KEY
 * bot_id           UUID NOT NULL REFERENCES bots(id) ON DELETE CASCADE
 * config           JSONB                          -- {top_k, hybrid, reranker, model}
 * avg_faithfulness NUMERIC(4,3)                   -- → BigDecimal
 * avg_relevancy    NUMERIC(4,3)                   -- → BigDecimal
 * answered_rate    NUMERIC(4,3)                   -- → BigDecimal
 * status           VARCHAR(20) NOT NULL DEFAULT 'running'
 * created_at       TIMESTAMPTZ NOT NULL           ← BaseEntity
 * </pre>
 *
 * <p><b>왜 double 이 아니라 BigDecimal 인가.</b> 컬럼이 {@code NUMERIC(4,3)} 이다.
 * {@code double} 로 매핑하면 {@code ddl-auto=validate} 에서 타입이 어긋날 뿐 아니라,
 * W4 의 "리랭커 도입으로 충실성 0.71 → 0.86" 같은 비교표에서 부동소수점 오차가 그대로 드러난다.
 * 소수 셋째 자리까지가 의미 있는 값이므로 정확한 십진 표현이 필요하다.
 */
@Getter
@Entity
@Table(name = "eval_runs")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class EvalRun extends BaseEntity {

    public static final String STATUS_RUNNING = "running";
    public static final String STATUS_COMPLETED = "completed";
    public static final String STATUS_FAILED = "failed";

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    @Column(name = "id", nullable = false, updatable = false)
    private UUID id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "bot_id", nullable = false)
    private Bot bot;

    /**
     * 실행 시점의 검색 설정 스냅샷. {@code {top_k, max_distance, hybrid, reranker, model}}
     *
     * <p>이 값이 있어야 W4 의 before/after 비교가 성립한다.
     * "무엇을 바꿨더니 점수가 올랐는가"를 말할 수 없으면 개선 수치가 근거를 잃는다.
     * 타입은 Message.sources 와 같은 이유로 원시 JSON 문자열이다.
     */
    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "config")
    private String config;

    /** 충실성 평균: 답이 근거 문서와 일치하는가 (0~1) */
    @Column(name = "avg_faithfulness", precision = 4, scale = 3)
    private BigDecimal avgFaithfulness;

    /** 관련성 평균: 질문에 맞는 답인가 (0~1) */
    @Column(name = "avg_relevancy", precision = 4, scale = 3)
    private BigDecimal avgRelevancy;

    /** 응답률: fallback 하지 않고 답한 비율 (0~1) */
    @Column(name = "answered_rate", precision = 4, scale = 3)
    private BigDecimal answeredRate;

    /**
     * 이 실행의 대상 질문 수. <b>{@code avg_*} 를 해석하려면 반드시 필요한 분모다.</b>
     *
     * <p>옛 실행(V3 이전)은 null 이다. 그때 몇 문항이었는지 알 수 없어 채워 넣지 않았다 —
     * 추측해서 넣으면 없는 사실을 지어내는 것이다.
     */
    @Column(name = "question_count")
    private Integer questionCount;

    /**
     * 실제로 채점된 질문 수. {@code avgFaithfulness}/{@code avgRelevancy} 의 진짜 분모다.
     * {@code questionCount} 보다 작으면 fallback·처리실패로 빠진 것이 있다는 뜻이다.
     */
    @Column(name = "scored_count")
    private Integer scoredCount;

    /** running | completed | failed. Python 이 갱신한다. */
    @Column(name = "status", length = 20, nullable = false)
    private String status;
}
