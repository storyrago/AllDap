package com.alldap.api.domain.bot.dto;

import jakarta.validation.constraints.Size;

import java.util.List;

/**
 * {@code PATCH /api/bots/{botId}} 요청 본문. <b>보낸 필드만 수정된다.</b>
 *
 * <p>그래서 모든 필드가 nullable 이고 {@code @NotBlank} 를 붙이지 않는다.
 * "보내지 않음(null)"과 "빈 값으로 지움"을 구분해야 하는데,
 * record + null 조합만으로는 systemPrompt 를 "null 로 지우기"와 "안 보냄"을 구분할 수 없다.
 *
 * <p>TODO(W2): 이 구분이 실제로 필요한지 봇 설정 화면을 만들며 판단할 것.
 *   필요하면 {@code JsonNullable}(jackson-databind-nullable) 도입이나
 *   PATCH 대신 PUT(전체 교체)로 바꾸는 방안을 검토한다. 지금은 null = "안 보냄" 으로 본다.
 */
public record UpdateBotRequest(
        @Size(max = 100, message = "봇 이름은 100자까지 입력할 수 있습니다.")
        String name,

        /**
         * 봇별 답변 지침. 실제 답변에 반영된다(Python 이 이 컬럼을 직접 읽는다).
         * 바꾼 뒤에는 환각 억제가 깨지지 않는지 재볼 것. 근거는 Bot 엔티티 주석.
         */
        String systemPrompt,

        String welcomeMessage,

        String fallbackMessage,

        /** 위젯 임베드를 허용할 도메인 목록. 예: ["https://example.com"] */
        List<String> allowedOrigins
) {
}
