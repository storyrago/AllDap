package com.alldap.api.domain.document.repository;

import com.alldap.api.domain.document.entity.Document;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

/**
 * documents 조회 전용 리포지토리.
 *
 * <p>{@link JpaRepository} 를 상속하면 {@code save} / {@code delete} 도 딸려 오지만
 * <b>쓰기 메서드를 호출하지 말 것.</b> 이 테이블의 쓰기 소유자는 Python 이다
 * (이유는 {@link Document} 클래스 주석 참고).
 *
 * <p>TODO(W2): 실수 방지가 필요하다고 판단되면 {@code Repository<Document, UUID>} 를 직접 상속해
 *   필요한 조회 메서드만 노출하는 방식으로 좁힐 것. 지금은 주석으로만 규율한다.
 */
public interface DocumentRepository extends JpaRepository<Document, UUID> {

    /** 봇의 문서 목록. bot_id 로 스코프를 좁히는 게 핵심이다. */
    List<Document> findAllByBotIdOrderByCreatedAtDesc(UUID botId);

    /**
     * 문서 하나를 소유 봇과 함께 확인. {@code DELETE /api/documents/{docId}} 처럼
     * 경로에 botId 가 없는 API 에서 소유권을 검사하는 데 쓴다.
     */
    Optional<Document> findByIdAndBotId(UUID id, UUID botId);
}
