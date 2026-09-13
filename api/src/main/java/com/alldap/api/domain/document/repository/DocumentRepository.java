package com.alldap.api.domain.document.repository;

import com.alldap.api.domain.document.entity.Document;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

/**
 * documents 조회 전용 리포지토리.
 *
 * <p>{@link JpaRepository} 를 상속하면 {@code save} / {@code delete} 도 딸려 오지만
 * <b>쓰기 메서드를 호출하지 말 것.</b> 이 테이블의 쓰기 소유자는 Python 이다
 * (이유는 {@link Document} 클래스 주석 참고).
 *
 * <p>TODO(W2): 실수 방지가 필요하다고 판단되면 {@code Repository<Document, Long>} 를 직접 상속해
 *   필요한 조회 메서드만 노출하는 방식으로 좁힐 것. 지금은 주석으로만 규율한다.
 */
public interface DocumentRepository extends JpaRepository<Document, Long> {

    /** 봇의 문서 목록. bot_id 로 스코프를 좁히는 게 핵심이다. */
    List<Document> findAllByBotIdOrderByCreatedAtDesc(Long botId);

    /**
     * 문서 하나를 소유 봇과 함께 확인. {@code DELETE /api/documents/{docId}} 처럼
     * 경로에 botId 가 없는 API 에서 소유권을 검사하는 데 쓴다.
     */
    Optional<Document> findByIdAndBotId(Long id, Long botId);

    /**
     * 문서 → 봇 → 소유자까지 <b>한 번의 쿼리로</b> 거슬러 올라가 확인한다.
     * {@code DELETE /api/documents/{docId}} 는 경로에 botId 가 없어서 이게 필요하다.
     *
     * <p>메서드 이름의 {@code BotUser} 는 Spring Data 가 {@code document.bot.user.id} 로 해석해
     * {@code JOIN bots ON ... JOIN users ON ...} 을 만들어준다.
     *
     * <p><b>왜 findById 로 가져와 자바에서 비교하지 않는가.</b> 두 가지다.
     * ① {@code BotService.findOwnedBot} 과 같은 이유 — 조회 자체를 소유자로 좁히면
     *    검사를 빠뜨린 조회를 쓰는 코드를 아예 작성할 수 없다(AGENTS.md 봇 소유권 규칙).
     * ② {@code Document.bot} 이 LAZY 이고 {@code open-in-view=false} 라,
     *    자바에서 {@code document.getBot().getUser()} 를 타고 가려면 트랜잭션 안이어야 하고
     *    프록시 초기화 쿼리가 두 번 더 나간다. 조인 한 번이 더 싸고 더 안전하다.
     */
    Optional<Document> findByIdAndBotUserId(Long id, Long userId);
}
