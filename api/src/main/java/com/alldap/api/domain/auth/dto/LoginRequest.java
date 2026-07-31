package com.alldap.api.domain.auth.dto;

import jakarta.validation.constraints.NotBlank;

/**
 * {@code POST /api/auth/login} 요청 본문.
 *
 * <p>여기서는 이메일 형식·비밀번호 길이를 검증하지 않는다.
 * 로그인 실패 사유를 세분화하면 "이 이메일은 가입돼 있다" 같은 정보가 새어나간다.
 * 실패는 전부 INVALID_CREDENTIALS 하나로 답한다.
 */
public record LoginRequest(
        @NotBlank(message = "이메일을 입력해주세요.")
        String email,

        @NotBlank(message = "비밀번호를 입력해주세요.")
        String password
) {
}
