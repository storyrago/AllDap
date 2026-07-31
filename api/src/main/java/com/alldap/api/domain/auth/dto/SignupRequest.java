package com.alldap.api.domain.auth.dto;

import com.alldap.api.global.validation.ByteLength;
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

        // 두 제약이 <b>서로 다른 단위</b>를 재고 있다. 둘 다 필요하다.
        //   @Size       : 문자 수. 사람이 이해하는 "몇 글자냐"에 대한 규칙.
        //   @ByteLength : UTF-8 바이트 수. BCrypt 가 72바이트까지만 처리한다는 라이브러리 제약.
        // BCryptPasswordEncoder.encode() 는 72바이트를 넘으면 IllegalArgumentException 을 던진다.
        // 이 검증이 없으면 한글 25자(75바이트)가 @Size(max=64)를 통과한 뒤 인코딩 단계에서 터져 500 이 난다.
        // (실제로 그렇게 났다. 이 애너테이션이 그 500 을 400 + 안내 메시지로 바꾸는 역할이다)
        @NotBlank(message = "비밀번호를 입력해주세요.")
        @Size(min = 8, max = 64, message = "비밀번호는 8자 이상 64자 이하로 입력해주세요.")
        @ByteLength(max = 72, message = "비밀번호가 너무 깁니다. "
                + "글자 수가 아니라 UTF-8 바이트 수(72바이트) 기준이라, 한글은 한 글자가 3바이트로 계산돼 24자까지만 됩니다. "
                + "영문·숫자를 섞거나 길이를 줄여주세요.")
        String password,

        @Size(max = 50, message = "이름은 50자까지 입력할 수 있습니다.")
        String name
) {
}
