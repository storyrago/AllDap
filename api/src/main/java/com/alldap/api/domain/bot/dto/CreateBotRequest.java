package com.alldap.api.domain.bot.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

/**
 * {@code POST /api/bots} 요청 본문.
 *
 * <p>이름만 받는 이유: 나머지 설정(인사말·거절 문구·허용 도메인)은 기본값으로 만들고
 * 봇 설정 화면에서 수정하게 한다. 생성 단계를 가볍게 두는 편이 이탈이 적다.
 */
public record CreateBotRequest(
        @NotBlank(message = "봇 이름을 입력해주세요.")
        @Size(max = 100, message = "봇 이름은 100자까지 입력할 수 있습니다.")
        String name
) {
}
