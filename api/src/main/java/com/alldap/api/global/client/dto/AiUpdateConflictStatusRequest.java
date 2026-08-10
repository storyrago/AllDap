package com.alldap.api.global.client.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Python 의 {@code ConflictStatusRequest}. 필드가 하나뿐이라 변환은 없지만,
 * 요청 본문도 <b>DTO 로 명시</b>한다 — Map 으로 보내면 Python 스키마가 바뀔 때
 * 컴파일이 아니라 런타임 422 로 드러난다.
 *
 * @param status open | ignored | resolved
 */
public record AiUpdateConflictStatusRequest(
        @JsonProperty("status") String status
) {
}
