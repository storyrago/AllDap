package com.alldap.api.domain.auth.dto;

/**
 * 가입·로그인 응답. 프론트의 {@code AuthResponse}({@code web/lib/types.ts})와 맞춘다.
 *
 * <pre>
 * { "token": "...", "user": { ... } }
 * </pre>
 *
 * <p>토큰을 쿠키가 아니라 응답 본문으로 주는 이유:
 * 위젯이 고객 사이트의 iframe 안에서 동작해 서드파티 쿠키 차단의 영향을 받기 때문이다.
 * 관리자 화면과 위젯이 같은 인증 방식을 쓰도록 {@code Authorization: Bearer} 헤더로 통일한다.
 *
 * <p>TODO(W2): 리프레시 토큰 도입 여부를 결정할 것.
 *   지금은 액세스 토큰 하나(TTL 24h)뿐이라, 토큰이 유출되면 만료까지 회수할 방법이 없다.
 */
public record AuthResponse(
        String token,
        UserResponse user
) {
}
