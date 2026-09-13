package com.alldap.api.domain.document.dto;

import com.alldap.api.domain.document.entity.Document;
import com.alldap.api.global.client.dto.AiDocumentResponse;

import java.time.Instant;

/**
 * 문서 응답. 프론트의 {@code DocumentItem}({@code web/lib/types.ts})과 필드명을 맞춘다.
 *
 * <p><b>여기가 snake_case → camelCase 변환이 실제로 일어나는 지점이다.</b>
 * Python 의 {@code file_type / error_message / char_count / chunk_count} 를
 * {@code fileType / errorMessage / charCount / chunkCount} 로 바꿔서 내려보낸다.
 * Python 응답을 그대로 흘려보내면 프론트 타입이 전부 거짓이 된다(PRD §10.3).
 */
public record DocumentResponse(
        Long id,
        String filename,
        String fileType,
        String status,
        String errorMessage,
        Integer charCount,
        Integer chunkCount,
        Instant createdAt
) {

    /**
     * Python 응답에서 변환.
     *
     * <p>Python 의 {@code DocumentOut} 에는 {@code created_at} 이 없다.
     * TODO(W2): 목록 화면에 업로드 시각이 필요하면 documents 테이블에서 읽어 채울 것.
     *   그 전까지는 null 로 내려간다(프론트 타입에서도 optional 이다).
     */
    public static DocumentResponse from(AiDocumentResponse ai) {
        return new DocumentResponse(
                ai.id(),
                ai.filename(),
                ai.fileType(),
                ai.status(),
                ai.errorMessage(),
                ai.charCount(),
                ai.chunkCount(),
                null
        );
    }

    /** DB 조회 결과에서 변환. 이쪽은 createdAt 을 채울 수 있다. */
    public static DocumentResponse from(Document document) {
        return new DocumentResponse(
                document.getId(),
                document.getFilename(),
                document.getFileType(),
                document.getStatus(),
                document.getErrorMessage(),
                document.getCharCount(),
                document.getChunkCount(),
                document.getCreatedAt()
        );
    }
}
