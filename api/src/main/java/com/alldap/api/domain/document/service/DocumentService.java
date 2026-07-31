package com.alldap.api.domain.document.service;

import com.alldap.api.domain.bot.repository.BotRepository;
import com.alldap.api.domain.document.dto.DocumentResponse;
import com.alldap.api.domain.document.repository.DocumentRepository;
import com.alldap.api.global.client.AiServiceClient;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;
import java.util.UUID;

/**
 * 문서 서비스.
 *
 * <p><b>Spring 의 역할은 "문지기"다.</b> 실제 문서 처리는 전부 Python 이 한다.
 * Spring 이 하는 일은 (1) 요청자가 이 봇의 주인이 맞는지 확인하고
 * (2) Python 으로 넘기고 (3) 결과를 camelCase 로 바꿔 내려주는 것뿐이다.
 * Python 의 {@code /internal/*} 에는 인증이 없으므로, 여기서 권한을 확인하지 않으면
 * 아무나 남의 봇에 문서를 넣거나 지울 수 있다.
 *
 * <p>클래스에 {@code @Transactional} 을 걸지 않은 이유:
 * 이 서비스의 주 작업은 DB 트랜잭션이 아니라 <b>외부 HTTP 호출</b>이다.
 * 수십 초 걸릴 수 있는 호출을 트랜잭션 안에 넣으면 그동안 DB 커넥션이 묶여 풀이 마른다.
 * 조회 메서드에만 개별적으로 {@code @Transactional(readOnly = true)} 를 붙인다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class DocumentService {

    private final AiServiceClient aiServiceClient;
    private final BotRepository botRepository;
    private final DocumentRepository documentRepository;

    /**
     * 문서 업로드 → Python 에 위임.
     *
     * <p>Python 은 documents 행만 만들고 202(pending)로 즉시 응답한다.
     * 파싱·청킹·임베딩은 백그라운드에서 돌아가므로, 프론트는 목록을 폴링해 상태를 따라가야 한다.
     * (임베딩이 수십 초 걸릴 수 있어 업로드 응답과 처리를 분리한 것 — PRD 요청 흐름 ①)
     */
    public DocumentResponse upload(UUID userId, UUID botId, MultipartFile file) {
        // TODO(W2): 구현.
        //   1) botRepository.findByIdAndUserId(botId, userId) 로 소유권 확인. 없으면 BOT_NOT_FOUND.
        //   2) 빈 파일이면 EMPTY_FILE 로 미리 거절(Python 까지 보낼 필요 없다).
        //   3) aiServiceClient.uploadDocument(botId, file) 호출
        //   4) DocumentResponse.from(ai) 로 변환해 반환
        //   ※ 확장자 검증은 Python 의 detect_type() 이 단일 기준이다. Spring 에 목록을 복제하면
        //     둘이 어긋났을 때 "Spring 은 통과시켰는데 Python 이 거절"하는 상태가 된다.
        //     다만 .hwp 는 사용자 안내가 특별하므로(LEGACY_HWP_NOT_SUPPORTED) 예외로 둘지 검토할 것.
        throw new UnsupportedOperationException("DocumentService.upload 미구현 (W2)");
    }

    /**
     * 봇의 문서 목록.
     *
     * <p>TODO(W2): 두 경로 중 하나를 고를 것.
     *   (a) Python 의 {@code GET /internal/bots/{id}/documents} 를 호출 — 상태 판단 기준이 한 곳에 모인다.
     *   (b) documentRepository 로 DB 를 직접 조회 — created_at 을 채울 수 있고 Python 이 죽어도 목록은 보인다.
     *   documents 는 "Spring 도 읽기 허용" 테이블이므로 (b)도 소유권 위반이 아니다.
     *   목록에 업로드 시각이 필요하다면 (b) 가 유력하다.
     */
    @Transactional(readOnly = true)
    public List<DocumentResponse> findDocuments(UUID userId, UUID botId) {
        throw new UnsupportedOperationException("DocumentService.findDocuments 미구현 (W2)");
    }

    /**
     * 문서 삭제 → Python 에 위임. chunks 는 DB 의 CASCADE 로 함께 사라진다.
     *
     * <p>경로({@code DELETE /api/documents/{docId}})에 botId 가 없으므로
     * 문서 → 봇 → 소유자 순으로 거슬러 올라가 권한을 확인해야 한다.
     */
    public void delete(UUID userId, UUID documentId) {
        // TODO(W2): 구현.
        //   1) documentRepository.findById(documentId) → 없으면 DOCUMENT_NOT_FOUND
        //   2) 그 문서의 bot 소유자가 userId 인지 확인 → 아니면 DOCUMENT_NOT_FOUND(403 이 아니라 404)
        //   3) aiServiceClient.deleteDocument(documentId)
        //   ※ Spring 이 documentRepository.delete() 를 호출하면 안 된다. 쓰기 소유자는 Python 이다.
        throw new UnsupportedOperationException("DocumentService.delete 미구현 (W2)");
    }
}
