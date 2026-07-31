package com.alldap.api.domain.bot.repository;

import com.alldap.api.domain.bot.entity.Bot;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface BotRepository extends JpaRepository<Bot, UUID> {

    /** 위젯 공개 API 진입점. publicKey 하나로 봇을 찾는다. */
    Optional<Bot> findByPublicKey(String publicKey);

    /** 대시보드 봇 목록. */
    List<Bot> findAllByUserIdOrderByCreatedAtDesc(UUID userId);

    /**
     * 소유권까지 함께 검사하는 조회.
     *
     * <p>{@code findById} 로 가져와 나중에 소유자를 비교하는 방식은
     * 검사를 빠뜨리기 쉽다. 조회 자체를 소유자로 좁히면 봇 간 데이터 유출
     * (CLAUDE.md "bot_id 스코프 격리")을 구조적으로 막을 수 있다.
     */
    Optional<Bot> findByIdAndUserId(UUID id, UUID userId);
}
