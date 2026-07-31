package com.alldap.api.domain.auth.dto;

import com.alldap.api.global.validation.ByteLength;
import jakarta.validation.constraints.NotBlank;

/**
 * {@code POST /api/auth/login} 요청 본문.
 *
 * <p>여기서는 이메일 형식·비밀번호 길이를 검증하지 않는다.
 * 로그인 실패 사유를 세분화하면 "이 이메일은 가입돼 있다" 같은 정보가 새어나간다.
 * 실패는 전부 INVALID_CREDENTIALS 하나로 답한다.
 *
 * <p><b>비밀번호 길이만은 검증한다 — BCrypt 가 72바이트에서 조용히 잘라내기 때문이다.</b>
 * 이건 열거 방지의 예외가 아니라 <b>정확성 문제</b>다.
 * BCrypt 는 72바이트를 넘는 입력의 뒷부분을 그냥 버린다. 그래서 검증이 없으면
 * 비밀번호가 정확히 72바이트인 계정에 <b>73바이트·75바이트 비밀번호로도 로그인이 성공한다</b>
 * (앞 72바이트만 같으면 통과). 실제로 리뷰에서 세 가지 다른 비밀번호가 같은 계정에
 * 전부 200 으로 로그인되는 것이 실기동으로 확인됐다.
 *
 * <p><b>이 검증은 열거를 유발하지 않는다.</b> 400 이 나가는 조건이 "입력한 비밀번호의 바이트 길이"
 * 하나뿐이고 <b>계정 존재 여부와 무관</b>하기 때문이다. 공격자가 400 을 받아도
 * 알 수 있는 것은 "내가 보낸 값이 규격 밖"이라는 사실뿐이다.
 * 반면 이메일 형식 검증은 넣지 않는다 — 그건 실패 사유를 세분화해 열거로 이어질 수 있다.
 */
public record LoginRequest(
        @NotBlank(message = "이메일을 입력해주세요.")
        String email,

        @NotBlank(message = "비밀번호를 입력해주세요.")
        @ByteLength(max = 72, message = "비밀번호가 너무 깁니다. 글자 수가 아니라 UTF-8 바이트 수(72바이트) 기준이라 한글은 24자까지 입력할 수 있습니다.")
        String password
) {
}
