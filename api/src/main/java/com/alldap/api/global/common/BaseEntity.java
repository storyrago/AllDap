package com.alldap.api.global.common;

import jakarta.persistence.Column;
import jakarta.persistence.EntityListeners;
import jakarta.persistence.MappedSuperclass;
import lombok.Getter;
import org.springframework.data.annotation.CreatedDate;
import org.springframework.data.jpa.domain.support.AuditingEntityListener;

import java.time.Instant;

/**
 * 모든 엔티티가 공유하는 생성 시각 필드.
 *
 * <p><b>⚠️ updatedAt 을 추가하지 말 것.</b>
 * db/migration 의 스키마에는 {@code updated_at} 컬럼이 단 한 곳도 없다(전부 {@code created_at} 뿐).
 * {@code spring.jpa.hibernate.ddl-auto=validate} 이므로 없는 컬럼을 매핑하면
 * 애플리케이션이 기동 단계에서 바로 실패한다.
 * 수정 시각이 필요해지면 먼저 Flyway 마이그레이션으로 컬럼을 추가하고 나서 여기에 넣을 것.
 *
 * <p>타입을 {@code Instant} 로 둔 이유: 컬럼이 {@code TIMESTAMPTZ}(시간대 포함)라
 * "특정 시점"을 그대로 담는 {@code Instant} 가 의미상 맞다.
 * {@code LocalDateTime} 은 시간대 정보가 없어 서버 타임존이 바뀌면 값이 달라진다.
 */
@Getter
@MappedSuperclass
@EntityListeners(AuditingEntityListener.class)
public abstract class BaseEntity {

    /**
     * DB 컬럼 기본값은 {@code now()} 이고, Spring 이 INSERT 하는 경우에는
     * {@code @CreatedDate}(JpaConfig 의 @EnableJpaAuditing)가 값을 채운다.
     *
     * <p>documents / eval_* 처럼 Python 이 INSERT 하는 테이블에서는
     * 이 필드가 "읽기 전용 매핑" 역할만 한다.
     */
    @CreatedDate
    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;
}
