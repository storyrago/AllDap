package com.alldap.api.domain.bot.dto;

import com.alldap.api.domain.bot.entity.Bot;

import java.time.Instant;
import java.util.Arrays;
import java.util.List;
import java.util.UUID;

/**
 * 봇 응답. 프론트의 {@code Bot}({@code web/lib/types.ts})과 필드명을 맞춘다.
 *
 * <p>엔티티를 그대로 반환하지 않는 이유:
 * ① 지연 로딩 프록시가 직렬화되며 예상치 못한 쿼리·예외가 나고
 * ② 스키마에 컬럼을 추가하는 순간 API 응답이 조용히 바뀌며
 * ③ 내부에만 있어야 할 값(예: 소유자 정보)이 새어나갈 수 있다.
 */
public record BotResponse(
        UUID id,
        String name,
        String publicKey,
        String systemPrompt,
        String welcomeMessage,
        String fallbackMessage,
        List<String> allowedOrigins,
        Instant createdAt
) {

    public static BotResponse from(Bot bot) {
        return new BotResponse(
                bot.getId(),
                bot.getName(),
                bot.getPublicKey(),
                bot.getSystemPrompt(),
                bot.getWelcomeMessage(),
                bot.getFallbackMessage(),
                // TEXT[] 는 null 로 올 수 있다(스키마상 NOT NULL 이 아니다).
                // 프론트는 배열을 전제로 하므로 null 대신 빈 배열로 내려 화면에서 분기를 줄인다.
                bot.getAllowedOrigins() == null ? List.of() : Arrays.asList(bot.getAllowedOrigins()),
                bot.getCreatedAt()
        );
    }

    // TODO(W2): PRD §8 의 봇 카드는 문서 수·주간 대화 수·최근 평가 점수까지 요구한다
    //   (프론트 타입 BotSummary). 목록 응답을 이 DTO 로 할지 별도 집계 DTO 를 둘지 결정할 것.
    //   집계를 봇 개수만큼 반복 조회하면 N+1 이 되므로 한 번의 group by 쿼리로 가져와야 한다.
}
