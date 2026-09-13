package com.alldap.api.domain.document.controller;

import com.alldap.api.domain.document.dto.DocumentResponse;
import com.alldap.api.domain.document.service.DocumentService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestPart;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;

import java.util.List;

/**
 * 문서 API (PRD §10.1). 인증 필요.
 *
 * <p>경로가 두 갈래({@code /api/bots/{botId}/documents} 와 {@code /api/documents/{docId}})라
 * 클래스 레벨 {@code @RequestMapping} 을 두지 않고 메서드마다 전체 경로를 적는다.
 */
@Tag(name = "문서", description = "봇의 지식 원본. 업로드는 비동기로 처리된다.")
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
    @Operation(summary = "문서 업로드 (비동기 처리)")
    @PostMapping("/api/bots/{botId}/documents")
    public ResponseEntity<DocumentResponse> uploadDocument(@AuthenticationPrincipal Long userId,
                                                           @PathVariable Long botId,
                                                           @RequestPart("file") MultipartFile file) {
        DocumentResponse document = documentService.upload(userId, botId, file);
        // 201 Created 가 아니라 202 Accepted 인 이유: 문서 행은 생겼지만 <처리는 아직 안 끝났다>.
        // 201 로 답하면 프론트가 "다 됐다"고 읽고 상태 폴링을 하지 않는다.
        return ResponseEntity.accepted().body(document);
    }

    /** GET /api/bots/{botId}/documents — 문서 목록 (프론트가 상태 폴링에 사용) */
    @Operation(summary = "문서 목록 조회")
    @GetMapping("/api/bots/{botId}/documents")
    public ResponseEntity<List<DocumentResponse>> getDocuments(@AuthenticationPrincipal Long userId,
                                                               @PathVariable Long botId) {
        return ResponseEntity.ok(documentService.findDocuments(userId, botId));
    }

    /** DELETE /api/documents/{docId} — 문서 삭제 (청크도 CASCADE 로 함께 삭제된다) */
    @Operation(summary = "문서 삭제")
    @DeleteMapping("/api/documents/{docId}")
    public ResponseEntity<Void> deleteDocument(@AuthenticationPrincipal Long userId,
                                               @PathVariable Long docId) {
        documentService.delete(userId, docId);
        return ResponseEntity.noContent().build();
    }
}
