package com.alldap.api.global.client;

import com.alldap.api.global.client.dto.AiChatRequest;
import com.alldap.api.global.client.dto.AiChatResponse;
import com.alldap.api.global.client.dto.AiDocumentResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;
import java.util.UUID;

/**
 * Python AI 서비스(:8001) 호출 담당.
 *
 * <p><b>이 클래스가 존재하는 이유.</b> Python 컨트랙트를 아는 코드를 여기 한 곳에 가둔다.
 * 서비스 계층은 {@code snake_case} 도 HTTP 도 모른 채 도메인 언어로만 대화한다.
 * 나중에 Python 컨트랙트가 바뀌어도 고칠 곳이 이 파일과 {@code client/dto} 뿐이다.
 *
 * <p><b>실제 컨트랙트</b> (ai-service/app/main.py 를 읽어 확인한 것):
 * <pre>
 * GET    /health                             -> {"status":"ok"}
 * POST   /internal/bots/{bot_id}/documents   multipart 필드명 "file" -> 202 + DocumentOut
 * GET    /internal/bots/{bot_id}/documents   -> DocumentOut[]
 * DELETE /internal/documents/{doc_id}        -> 204 (본문 없음)
 * POST   /internal/chat                      {bot_id, message, session_id} -> ChatResponse
 * </pre>
 *
 * <p><b>주의:</b> {@code /internal/*} 에는 인증이 없다. Spring 이 앞단에서 막아준다는 전제다.
 * 이 서비스를 외부에 노출하면 누구나 남의 봇 문서를 조회할 수 있다.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class AiServiceClient {

    /** RestClientConfig 의 {@code aiServiceRestClient} 빈. baseUrl 과 타임아웃이 이미 박혀 있다. */
    private final RestClient aiServiceRestClient;

    /**
     * 문서 업로드. Python 은 documents 행만 만들고 202 로 즉시 응답한 뒤
     * 파싱·청킹·임베딩은 백그라운드로 처리한다. 따라서 반환되는 status 는 보통 {@code pending} 이다.
     *
     * <p>multipart 필드명은 반드시 {@code "file"} 이어야 한다 (FastAPI 의 {@code File(...)} 파라미터명).
     *
     * @param botId 문서를 붙일 봇. 호출 전에 <b>반드시 소유권을 검증</b>해야 한다
     *              (Python 에는 인증이 없어 여기서 막지 않으면 남의 봇에 문서를 넣을 수 있다).
     */
    public AiDocumentResponse uploadDocument(UUID botId, MultipartFile file) {
        // TODO(W2): 구현.
        //   1) MultipartFile 을 ByteArrayResource 로 감싸고 getFilename() 을 오버라이드해
        //      원본 파일명을 유지한다. 파일명이 없으면 Python 의 detect_type() 이 확장자를 못 읽는다.
        //   2) MultiValueMap<String, Object> 에 "file" 키로 담아 MULTIPART_FORM_DATA 로 POST.
        //   3) 4xx/5xx 를 ApiException(AI_SERVICE_*) 으로 변환한다.
        //      특히 Python 의 400(형식)·413(크기)은 사용자 입력 문제이므로
        //      502 가 아니라 UNSUPPORTED_FILE_TYPE / FILE_TOO_LARGE 로 바꿔 내려야 한다.
        throw new UnsupportedOperationException("AiServiceClient.uploadDocument 미구현 (W2)");
    }

    /**
     * 봇의 문서 목록 조회.
     *
     * <p>documents 테이블은 Python 이 쓰기 소유자다. Spring 이 DB 를 직접 읽어도 되지만,
     * 상태 판단 기준을 한 곳에 두려고 Python 을 거친다.
     * TODO(W2): 목록 화면에 created_at 이 필요하면 Python 응답에는 없으므로
     *   Spring 이 documents 테이블에서 읽어 합쳐야 한다. 그 경우 이 메서드 대신
     *   DocumentRepository 조회로 갈지 결정할 것.
     */
    public List<AiDocumentResponse> listDocuments(UUID botId) {
        // TODO(W2): 구현. GET /internal/bots/{botId}/documents
        throw new UnsupportedOperationException("AiServiceClient.listDocuments 미구현 (W2)");
    }

    /**
     * 문서 삭제. chunks 는 DB 의 ON DELETE CASCADE 로 함께 지워진다.
     *
     * <p>Spring 이 documents 를 직접 DELETE 하지 않는 이유: 쓰기 소유자가 Python 이기 때문이다.
     * 양쪽이 같은 테이블에 쓰기 시작하면 누가 무엇을 바꿨는지 추적이 불가능해진다.
     */
    public void deleteDocument(UUID documentId) {
        // TODO(W2): 구현. DELETE /internal/documents/{documentId} -> 204
        throw new UnsupportedOperationException("AiServiceClient.deleteDocument 미구현 (W2)");
    }

    /**
     * 질문 → 답변. 이 프로젝트에서 유일하게 오래 걸리는(수십 초) 동기 호출이다.
     *
     * <p>응답의 {@code isFallback} 이 true 면 근거를 못 찾은 것이다.
     * 봇별 문구 치환은 여기가 아니라 ChatService 에서 한다(클라이언트는 Python 응답을 그대로 전달).
     */
    public AiChatResponse chat(AiChatRequest request) {
        // TODO(W2): 구현. POST /internal/chat
        //   ResourceAccessException(타임아웃) -> AI_SERVICE_TIMEOUT
        //   연결 거부/5xx                     -> AI_SERVICE_UNAVAILABLE
        //   그 외 4xx                         -> AI_SERVICE_ERROR
        throw new UnsupportedOperationException("AiServiceClient.chat 미구현 (W2)");
    }

    /**
     * Python 서비스 헬스체크.
     *
     * <p>TODO(W2): Spring 의 {@code /actuator/health} 에 커스텀 HealthIndicator 로 물릴 것.
     *   Python 이 죽으면 채팅이 죽으므로, Spring 만 살아있고 health 가 UP 이면 거짓 신호가 된다.
     */
    public boolean isHealthy() {
        // TODO(W2): 구현. GET /health -> {"status":"ok"}
        throw new UnsupportedOperationException("AiServiceClient.isHealthy 미구현 (W2)");
    }

    // TODO(W3): /internal/eval/* 호출 메서드.
    //   Python 에 아직 해당 엔드포인트가 없다. W3 에서 Python 을 먼저 만든 뒤 여기에 추가한다.
    //   지금 시그니처를 미리 만들어두면 존재하지 않는 컨트랙트를 코드로 굳히게 되므로 두지 않는다.
}
