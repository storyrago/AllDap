package com.alldap.api.global.client.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.time.Instant;
import java.util.UUID;

/**
 * Python 의 {@code ConflictOut} (ai-service/app/schemas.py).
 *
 * <pre>
 * { id, topic, a_says, b_says, a_filename, b_filename, a_content, b_content,
 *   distance, status, created_at }
 * status ∈ open | ignored | resolved | clear   (목록으로 오는 것은 보통 open)
 * </pre>
 *
 * <p><b>왜 청크 원문(a_content/b_content)까지 받나:</b> 관리자가 판정을 <b>검증</b>할 수 있어야 한다.
 * 요약({@code topic}/{@code a_says}/{@code b_says})만 보여주면 "정말 그렇게 쓰여 있나"를 확인할
 * 방법이 없고, 확인할 수 없는 지적은 무시당한다.
 *
 * <p>{@code distance} 가 {@link Double}(래퍼)인 이유: null 이 올 수 있다.
 * 판정 근거가 아니라 <b>임계값 튜닝용 기록</b>이라 없어도 화면은 성립한다.
 */
public record AiConflictResponse(
        @JsonProperty("id") UUID id,
        @JsonProperty("topic") String topic,
        @JsonProperty("a_says") String aSays,
        @JsonProperty("b_says") String bSays,
        @JsonProperty("a_filename") String aFilename,
        @JsonProperty("b_filename") String bFilename,
        @JsonProperty("a_content") String aContent,
        @JsonProperty("b_content") String bContent,
        @JsonProperty("distance") Double distance,
        @JsonProperty("status") String status,
        @JsonProperty("created_at") Instant createdAt
) {
}
