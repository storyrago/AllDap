package com.alldap.api.domain.widget.dto;

import com.alldap.api.domain.bot.entity.Bot;

/**
 * {@code GET /api/w/{publicKey}/config} 응답. 프론트의 {@code WidgetConfig} 와 맞춘다.
 *
 * <p><b>이 DTO 의 존재 이유는 "무엇을 안 내보내는가" 다.</b>
 * 이 응답은 인증 없이 아무나 볼 수 있고 고객 사이트의 브라우저에 그대로 노출된다.
 * 따라서 {@code systemPrompt}(내부 지시문), {@code fallbackMessage}, {@code allowedOrigins},
 * 소유자 정보, 봇 id 는 <b>절대 포함하면 안 된다.</b>
 * BotResponse 를 재사용하고 싶어지더라도 그렇게 하지 말 것 —
 * 나중에 BotResponse 에 필드가 하나 추가되는 순간 조용히 유출된다.
 *
 * <p>{@code fallbackMessage} 를 빼는 이유가 헷갈릴 수 있는데,
 * 이 문구는 fallback 이 실제로 일어났을 때 채팅 응답의 {@code answer} 로 치환돼서 나간다.
 * 위젯이 미리 알고 있을 필요가 없다.
 */
public record WidgetConfigResponse(
        String botName,
        /** 대화 시작 시 위젯이 먼저 띄우는 인사말 */
        String welcomeMessage,
        /**
         * ⚠️ PRD 와 DB 의 불일치: PRD F-04 는 "브랜드 색상 1종 커스텀"을 요구하는데
         * bots 테이블에는 색상 컬럼이 없다.
         * TODO(W2): Flyway 마이그레이션으로 theme_color 컬럼을 추가하거나 MVP 에서 뺄 것.
         *   지금은 항상 null 로 나간다(프론트에서도 optional 이다).
         */
        String themeColor
) {

    public static WidgetConfigResponse from(Bot bot) {
        return new WidgetConfigResponse(bot.getName(), bot.getWelcomeMessage(), null);
    }
}
