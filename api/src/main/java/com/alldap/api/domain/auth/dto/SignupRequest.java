package com.alldap.api.domain.auth.dto;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

/**
 * {@code POST /api/auth/signup} 요청 본문.
 *
 * <p>검증 메시지를 한국어로 적는 이유: GlobalExceptionHandler 가 이 문구를 모아
 * 그대로 사용자에게 내려보내기 때문이다(CLAUDE.md 작업 규칙 4).
 */
public record SignupRequest(
        @NotBlank(message = "이메일을 입력해주세요.")
        @Email(message = "이메일 형식이 올바르지 않습니다. 예: name@example.com")
        @Size(max = 255, message = "이메일은 255자까지 입력할 수 있습니다.")
        String email,

        @NotBlank(message = "비밀번호를 입력해주세요.")
        @Size(min = 8, max = 64, message = "비밀번호는 8자 이상 64자 이하로 입력해주세요.")
        String password,

        @Size(max = 50, message = "이름은 50자까지 입력할 수 있습니다.")
        String name
) {
}
