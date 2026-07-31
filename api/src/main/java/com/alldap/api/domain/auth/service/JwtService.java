package com.alldap.api.domain.auth.service;

import com.alldap.api.global.config.JwtProperties;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.UUID;

/**
 * JWT 발급·검증. 자리만 잡아둔 상태다.
 *
 * <p><b>왜 JWT 인가.</b> 세션 방식은 서버가 세션 저장소를 들고 있어야 하는데,
 * 이 프로젝트는 배포 대상이 이미 3개(Spring·Python·Next.js)라 운영할 것을 더 늘리고 싶지 않다.
 * JWT 는 토큰 자체에 사용자 식별자가 들어 있어 별도 저장소가 필요 없다.
 * 대신 <b>만료 전 강제 로그아웃이 불가능</b>하다는 단점이 있다 — 이 트레이드오프는 알고 택한 것이다.
 *
 * <p>라이브러리는 jjwt 0.12.6 을 쓴다(build.gradle 에 이미 있음).
 * jjwt 0.12 부터 API 가 {@code Jwts.builder().subject(...).signWith(key)} 형태로 바뀌었다 —
 * 0.11 예제(setSubject, signWith(key, alg))를 그대로 복사하면 컴파일되지 않는다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class JwtService {

    private final JwtProperties jwtProperties;

    /**
     * 액세스 토큰 발급.
     *
     * <p>TODO(W2): 구현.
     * <pre>
     * SecretKey key = Keys.hmacShaKeyFor(jwtProperties.secret().getBytes(StandardCharsets.UTF_8));
     * Instant now = Instant.now();
     * return Jwts.builder()
     *         .subject(userId.toString())        // 봇/문서 소유권 검사에 쓸 식별자
     *         .issuedAt(Date.from(now))
     *         .expiration(Date.from(now.plus(jwtProperties.accessTokenTtl())))
     *         .signWith(key)
     *         .compact();
     * </pre>
     * 클레임에 이메일·이름을 넣지 말 것 — JWT 페이로드는 서명만 될 뿐 암호화되지 않아
     * 누구나 Base64 디코드로 읽을 수 있다.
     */
    public String issueAccessToken(UUID userId) {
        throw new UnsupportedOperationException("JwtService.issueAccessToken 미구현 (W2)");
    }

    /**
     * 토큰 검증 후 사용자 id 추출.
     *
     * <p>TODO(W2): 구현. 서명 불일치·만료·형식 오류를 모두 잡아
     * {@code ApiException(ErrorCode.INVALID_TOKEN)} 으로 바꿔 던질 것.
     * 예외를 그대로 흘려보내면 GlobalExceptionHandler 가 500 으로 처리해버린다.
     */
    public UUID parseUserId(String token) {
        throw new UnsupportedOperationException("JwtService.parseUserId 미구현 (W2)");
    }

    // TODO(W2): JwtAuthenticationFilter (OncePerRequestFilter) 를 만들어
    //   Authorization: Bearer 헤더를 읽고 SecurityContext 에 인증 객체를 넣을 것.
    //   그런 다음 SecurityConfig 의 addFilterBefore TODO 를 해제한다.
}
