package com.alldap.api.domain.bot.dto;

import com.alldap.api.domain.bot.entity.Bot;
import com.alldap.api.domain.bot.repository.BotRepository.BotMetrics;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.Arrays;
import java.util.List;

/**
 * 봇 <b>목록</b> 응답 (PRD §8 봇 카드). 프론트의 {@code BotSummary}({@code web/lib/types.ts})와 맞춘다.
 *
 * <p><b>왜 {@link BotResponse} 에 필드를 더하지 않고 별도 record 인가.</b>
 * 상세 조회({@code GET /api/bots/{botId}})는 이 집계를 내려줄 이유가 없다.
 * 한 DTO 를 공유하면 상세 응답에서 세 값이 전부 null 이 되고, 그러면
 * <b>"집계가 0 이다"와 "이 응답은 집계를 담지 않는다"가 같은 모양</b>이 된다.
 * 이 저장소가 반복해서 낸 버그가 정확히 그 부류다(서로 다른 사실을 같은 값으로 뭉개기).
 * 필드 여덟 개를 한 번 더 적는 대가로 그 혼동을 없앤다.
 */
public record BotSummaryResponse(
        Long id,
        String name,
        String publicKey,
        String systemPrompt,
        String welcomeMessage,
        String fallbackMessage,
        List<String> allowedOrigins,
        Instant createdAt,
        /** 이 봇에 올라간 문서 수. 처리 중·실패 문서도 포함한다(문서 관리 화면의 목록 길이와 일치한다). */
        long documentCount,
        /** 최근 7일(168시간) 안에 시작된 대화 수. 위젯·관리자 테스트 채팅을 모두 센다. */
        long weeklyConversationCount,
        /**
         * 가장 최근 <b>완료된</b> 평가 실행의 <b>전체 충실성</b>. 평가를 한 번도 완주하지 못했으면 null.
         *
         * <p><b>{@code avgFaithfulness} 를 그대로 쓰지 않는 이유가 이 필드의 존재 이유다.</b>
         * 평균은 채점된 질문만 분모로 삼는데, 어려운 질문일수록 fallback 되어 채점에서 빠진다.
         * 그래서 <b>답을 덜 할수록 점수가 올라간다</b>(생존 편향). 실제로 이 저장소가 그 함정에
         * 한 번 속아 W4 비교표를 다시 만들었다({@code EvalRunResponse.overallFaithfulness} 주석).
         * 카드에 평균을 띄우면 같은 함정을 화면으로 옮기는 것이라,
         * 품질 대시보드가 쓰는 것과 <b>같은 지표</b>({@code avg × scored / total})를 쓴다.
         *
         * <p>계산할 수 없는 실행(running·failed·옛 실행이라 분모 미기록)은 아예 고르지 않고
         * 그 이전의 계산 가능한 실행을 찾는다. 0 으로 채우지 않는다. "모른다"와 "0점"은 다르다.
         */
        BigDecimal latestOverallFaithfulness
) {

    public static BotSummaryResponse of(Bot bot, BotMetrics metrics) {
        return new BotSummaryResponse(
                bot.getId(),
                bot.getName(),
                bot.getPublicKey(),
                bot.getSystemPrompt(),
                bot.getWelcomeMessage(),
                bot.getFallbackMessage(),
                // BotResponse.from 과 같은 이유로 null 을 빈 배열로 바꾼다(프론트가 배열을 전제로 한다).
                bot.getAllowedOrigins() == null ? List.of() : Arrays.asList(bot.getAllowedOrigins()),
                bot.getCreatedAt(),
                // 방금 만들어져 문서·대화·평가가 하나도 없는 봇은 집계 결과에 값이 없을 수 있다.
                // 그건 "0 건"이 맞다. 스칼라 서브쿼리라 count 는 항상 오지만, 방어적으로 둔다.
                metrics == null ? 0 : metrics.getDocumentCount(),
                metrics == null ? 0 : metrics.getWeeklyConversationCount(),
                metrics == null ? null : metrics.getLatestOverallFaithfulness()
        );
    }
}
