package com.alldap.api.domain.document.controller;

import com.alldap.api.domain.document.dto.DocumentResponse;
import com.alldap.api.domain.document.service.DocumentService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestPart;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;
import java.util.UUID;

/**
 * 문서 API (PRD §10.1). 인증 필요.
 *
 * <p>경로가 두 갈래({@code /api/bots/{botId}/documents} 와 {@code /api/documents/{docId}})라
 * 클래스 레벨 {@code @RequestMapping} 을 두지 않고 메서드마다 전체 경로를 적는다.
 */
@RestController
@RequiredArgsConstructor
public class DocumentController {

    private final DocumentService documentService;

    /**
     * POST /api/bots/{botId}/documents — 문서 업로드 (multipart).
     *
     * <p>{@code @RequestPart} 의 이름을 {@code "file"} 로 둔 이유:
     * Python 의 {@code File(...)} 파라미터명이 {@code file} 이라 그대로 흘려보내기 좋고,
     * 프론트도 이 이름 하나만 기억하면 된다.
     *
     * <p>응답은 {@code 202 Accepted} 가 의미상 맞다 — 요청을 접수했을 뿐 처리는 아직 끝나지 않았다.
     */
    @PostMapping("/api/bots/{botId}/documents")
    public ResponseEntity<DocumentResponse> uploadDocument(@PathVariable UUID botId,
                                                           @RequestPart("file") MultipartFile file) {
        // TODO(W2): documentService.upload(userId, botId, file) 호출 후 202 Accepted 반환
        throw new UnsupportedOperationException("DocumentController.uploadDocument 미구현 (W2)");
    }

    /** GET /api/bots/{botId}/documents — 문서 목록 (프론트가 상태 폴링에 사용) */
    @GetMapping("/api/bots/{botId}/documents")
    public ResponseEntity<List<DocumentResponse>> getDocuments(@PathVariable UUID botId) {
        // TODO(W2): documentService.findDocuments(userId, botId) 호출
        throw new UnsupportedOperationException("DocumentController.getDocuments 미구현 (W2)");
    }

    /** DELETE /api/documents/{docId} — 문서 삭제 (청크도 CASCADE 로 함께 삭제된다) */
    @DeleteMapping("/api/documents/{docId}")
    public ResponseEntity<Void> deleteDocument(@PathVariable UUID docId) {
        // TODO(W2): documentService.delete(userId, docId) 호출 후 204 No Content
        throw new UnsupportedOperationException("DocumentController.deleteDocument 미구현 (W2)");
    }
}
