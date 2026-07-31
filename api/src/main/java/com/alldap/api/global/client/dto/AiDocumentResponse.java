package com.alldap.api.global.client.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.UUID;

/**
 * Python 의 {@code DocumentOut} (ai-service/app/schemas.py).
 *
 * <pre>
 * { id, filename, file_type, status, error_message, char_count, chunk_count }
 * status ∈ pending | processing | ready | failed
 * </pre>
 *
 * <p><b>여기가 snake_case ↔ camelCase 변환의 경계다.</b>
 * Jackson 의 전역 네이밍 전략을 SNAKE_CASE 로 바꾸면 우리 공개 API 응답까지 snake_case 가 되어
 * 프론트({@code web/lib/types.ts})가 전부 깨진다.
 * 그래서 전역 설정을 건드리지 않고 이 경계 DTO 에만 {@code @JsonProperty} 를 붙인다.
 *
 * <p>Python 은 {@code created_at} 을 돌려주지 않는다. 문서 목록에 생성 시각이 필요하면
 * Spring 이 documents 테이블에서 직접 읽어 채워야 한다(TODO 는 DocumentService 참고).
 */
public record AiDocumentResponse(
        @JsonProperty("id") UUID id,
        @JsonProperty("filename") String filename,
        @JsonProperty("file_type") String fileType,
        @JsonProperty("status") String status,
        @JsonProperty("error_message") String errorMessage,
        @JsonProperty("char_count") Integer charCount,
        @JsonProperty("chunk_count") Integer chunkCount
) {
}
