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
 * <p>✅ <b>봇 설정 화면을 만들어 보니 이 구분은 필요 없었다</b>(옛 TODO 를 지운 자리다).
 *   그 화면({@code web/app/(dashboard)/bot/[botId]/settings/page.tsx})은 systemPrompt 를
 *   <b>항상 문자열로</b> 보낸다: 초기값이 {@code ""} 이고, 불러온 값도 {@code ?? ""} 로
 *   받아 넣는다. 즉 "지우기" 는 null 이 아니라 <b>빈 문자열</b>로 표현되고,
 *   null 은 애초에 전송되지 않는다. 검토 대상이던 {@code JsonNullable}(jackson-databind-nullable)
 *   도입도, PATCH 를 PUT(전체 교체)로 바꾸는 것도 하지 않았다.
 *   그래서 null = "안 보냄" 이라는 해석은 그대로 유효하다.
 *   <b>다시 {@code JsonNullable} 을 검토하고 싶어지면 이 문단을 먼저 읽을 것.</b>
 *   필요해지는 시점은 화면이 null 을 보내기 시작할 때다.
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
