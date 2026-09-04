package com.alldap.api.domain.document.service;

import com.alldap.api.domain.bot.repository.BotRepository;
import com.alldap.api.domain.document.dto.DocumentResponse;
import com.alldap.api.domain.document.entity.Document;
import com.alldap.api.domain.document.repository.DocumentRepository;
import com.alldap.api.global.client.AiServiceClient;
import com.alldap.api.global.client.dto.AiDocumentResponse;
import com.alldap.api.global.exception.ApiException;
import com.alldap.api.global.exception.ErrorCode;
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
        requireOwnedBot(userId, botId);

        // 빈 파일은 Python 까지 보내지 않는다. Python 도 400 으로 막지만,
        // 왕복 한 번과 documents 행 하나를 아끼는 쪽이 낫다.
        // (Python 은 INSERT 전에 검사하므로 행이 생기지는 않지만, 네트워크 왕복은 그대로 발생한다)
        if (file.isEmpty()) {
            throw new ApiException(ErrorCode.EMPTY_FILE);
        }

        AiDocumentResponse uploaded = aiServiceClient.uploadDocument(botId, file);
        log.info("[upload] 문서 업로드 접수 userId={} botId={} documentId={} status={}",
                userId, botId, uploaded.id(), uploaded.status());
        return DocumentResponse.from(uploaded);

        // 확장자 검증은 Spring 에 복제하지 않는다 — 단일 기준은 Python 의 detect_type() 이다.
        // 목록을 양쪽에 두면 반드시 어긋나고, 그때 "Spring 은 통과시켰는데 Python 이 거절"이 된다.
        // .hwp 의 특별 안내도 Python 이 이미 한국어 문구로 주고 있어,
        // AiServiceClient 가 그 문구를 그대로 사용자에게 전달한다.
    }

    /**
     * 봇의 문서 목록. 프론트가 업로드 후 상태({@code pending → processing → ready|failed})를 폴링하는 경로다.
     *
     * <h2>Python 호출이 아니라 DB 직접 조회를 택했다 (설계 결정)</h2>
     * 두 선택지가 있었다.
     * <ul>
     *   <li>(a) Python 의 {@code GET /internal/bots/{id}/documents} 호출</li>
     *   <li>(b) {@code documentRepository} 로 DB 직접 조회 ← <b>택함</b></li>
     * </ul>
     *
     * <p><b>(b)를 택한 이유 두 가지.</b>
     * <ol>
     *   <li><b>업로드 시각을 채울 수 있다.</b> Python 의 {@code DocumentOut} 에는 {@code created_at} 이 없다.
     *       (a)로 가면 목록에 날짜를 못 띄우고, 그걸 채우려면 결국 DB 를 또 읽어 합쳐야 한다 —
     *       호출을 두 번 하느니 처음부터 한 번이 낫다.</li>
     *   <li><b>Python 이 죽어도 목록은 보인다.</b> 이 화면은 <b>폴링</b> 대상이라 호출이 잦다.
     *       Python 이 내려갔을 때 목록까지 503 이 되면 사용자는 "내 문서가 사라졌나" 싶고,
     *       죽은 서비스를 초당 몇 번씩 두드리게 된다. 상태 값이 잠시 낡을 뿐 목록은 보이는 편이 낫다.</li>
     * </ol>
     *
     * <p><b>소유권 규칙을 어기는 것 아닌가?</b> 아니다. {@code documents} 는
     * "쓰기 = Python / <b>읽기 = Spring 도 허용</b>" 테이블이다(AGENTS.md 테이블 소유권).
     * 우리가 하는 건 SELECT 뿐이고, 상태를 바꾸는 UPDATE 는 여전히 Python 만 한다.
     *
     * <p>대가도 분명히 적어둔다: 상태 판단 기준이 두 곳(Python 의 UPDATE, Spring 의 SELECT)에 걸쳐 있어,
     * 나중에 Python 이 상태 값을 하나 추가하면 Spring 은 그 값을 <b>모른 채 문자열로 흘려보낸다.</b>
     * {@code Document.status} 를 enum 이 아니라 String 으로 둔 것이 이 상황에 대한 대비다.
     */
    @Transactional(readOnly = true)
    public List<DocumentResponse> findDocuments(UUID userId, UUID botId) {
        requireOwnedBot(userId, botId);
        return documentRepository.findAllByBotIdOrderByCreatedAtDesc(botId).stream()
                .map(DocumentResponse::from)
                .toList();
    }

    /**
     * 문서 삭제 → Python 에 위임. chunks 는 DB 의 CASCADE 로 함께 사라진다.
     *
     * <p>경로({@code DELETE /api/documents/{docId}})에 botId 가 없으므로
     * 문서 → 봇 → 소유자 순으로 거슬러 올라가 권한을 확인해야 한다.
     */
    public void delete(UUID userId, UUID documentId) {
        // 문서 → 봇 → 소유자를 한 번의 조인 쿼리로 확인한다.
        // 없는 문서와 남의 문서를 모두 404 로 답한다 — 403 으로 구분해주면
        // 무작위 id 를 던져 "그 문서가 존재하는지"를 알아낼 수 있다(봇과 같은 규칙).
        Document document = documentRepository.findByIdAndBotUserId(documentId, userId)
                .orElseThrow(() -> new ApiException(ErrorCode.DOCUMENT_NOT_FOUND));

        // ⚠️ documentRepository.delete() 를 부르면 안 된다. documents 의 쓰기 소유자는 Python 이다.
        // 실제 DELETE 는 Python 이 하고, chunks 는 DB 의 ON DELETE CASCADE 로 함께 사라진다.
        //
        // botId 를 함께 넘긴다 — Python 쪽 WHERE 가 두 값으로 좁혀지므로,
        // 여기 소유권 검사가 언젠가 빠지더라도 남의 봇 문서까지는 지워지지 않는다.
        //
        // ⚠️ document.getBot() 은 초기화 안 된 Hibernate 프록시다 — findByIdAndBotUserId 는
        // fetch join 도 @EntityGraph 도 없고, 이 메서드는 @Transactional 이 아니며 open-in-view 도 false 다.
        // getId() 만 예외적으로 안전하다 — Hibernate 가 식별자 getter 를 가로채 DB 접근 없이 FK 값을 돌려준다.
        // getName() 등 다른 필드를 부르면 여기서 LazyInitializationException 이 난다.
        aiServiceClient.deleteDocument(document.getBot().getId(), document.getId());
        log.info("[delete] 문서 삭제 userId={} documentId={}", userId, documentId);
    }

    /**
     * 이 봇이 요청자의 것인지 확인한다. <b>Python 을 부르기 전에 반드시 통과해야 하는 관문이다.</b>
     *
     * <p>Python 의 {@code /internal/*} 에는 인증이 없다. 여기서 막지 않으면
     * 남의 봇 id 하나만 알면 그 봇에 문서를 넣거나 목록을 훔쳐볼 수 있다.
     * 반환값을 쓰지 않고 존재 확인만 하는 이유는, 필요한 게 "내 봇이 맞다"는 사실 하나뿐이기 때문이다.
     */
    private void requireOwnedBot(UUID userId, UUID botId) {
        botRepository.findByIdAndUserId(botId, userId)
                .orElseThrow(() -> new ApiException(ErrorCode.BOT_NOT_FOUND));
    }
}
