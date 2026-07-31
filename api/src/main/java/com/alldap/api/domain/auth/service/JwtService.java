package com.alldap.api.domain.auth.service;

import com.alldap.api.global.config.JwtProperties;
import com.alldap.api.global.exception.ApiException;
import com.alldap.api.global.exception.ErrorCode;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.JwtParser;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Date;
import java.util.UUID;

/**
 * JWT 발급·검증.
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
public class JwtService {

    private final JwtProperties jwtProperties;

    /**
     * 서명 키. 요청마다 새로 만들지 않고 필드에 캐시한다.
     *
     * <p>이유 두 가지.
     * <ol>
     *   <li><b>비용.</b> {@code Keys.hmacShaKeyFor()} 는 바이트 배열 복사 + 키 길이 검증을 매번 수행한다.
     *       키는 애플리케이션 수명 동안 변하지 않으므로 요청마다 반복할 이유가 없다.</li>
     *   <li><b>fail-fast.</b> HS256 은 최소 256비트(32바이트) 키를 요구하고,
     *       모자라면 {@code WeakKeyException} 이 난다. 이걸 생성자에서 터뜨리면
     *       <b>기동 단계에서</b> 죽는다. 요청 시점에 만들면 첫 로그인 요청에서야 500 으로 드러난다.
     *       설정 실수는 시끄럽게, 그리고 일찍 죽는 편이 안전하다(application-prod.yaml 의 fail-closed 원칙과 같은 결).</li>
     * </ol>
     * {@code SecretKey} 는 불변이라 여러 스레드가 공유해도 안전하다.
     */
    private final SecretKey secretKey;

    /**
     * 파서도 캐시한다. jjwt 의 {@code JwtParserBuilder.build()} 는
     * "불변이며 스레드 안전한" 파서를 돌려주도록 문서화돼 있고,
     * build() 내부에서 JSON Deserializer 를 ServiceLoader 로 찾는 작업이 있어 매번 만들면 낭비다.
     */
    private final JwtParser jwtParser;

    /**
     * Lombok {@code @RequiredArgsConstructor} 를 쓰지 않고 생성자를 직접 쓴 이유:
     * {@code secretKey}/{@code jwtParser} 는 주입받는 값이 아니라 <b>주입값에서 파생되는 값</b>이다.
     * Lombok 이 만드는 생성자는 final 필드를 전부 파라미터로 받아버리므로 이 구분을 표현할 수 없다.
     */
    public JwtService(JwtProperties jwtProperties) {
        this.jwtProperties = jwtProperties;
        this.secretKey = Keys.hmacShaKeyFor(jwtProperties.secret().getBytes(StandardCharsets.UTF_8));
        this.jwtParser = Jwts.parser().verifyWith(this.secretKey).build();
    }

    /**
     * 액세스 토큰 발급.
     *
     * <p>클레임은 {@code sub}(사용자 id) · {@code iat} · {@code exp} 셋뿐이다.
     * <b>이메일·이름을 넣지 않는다</b> — JWT 페이로드는 서명만 될 뿐 암호화되지 않아
     * 누구나 Base64 디코드로 읽을 수 있다. 토큰이 로그·브라우저 저장소·프록시 로그를 타고
     * 돌아다니는 것을 감안하면 개인정보를 실어 보낼 이유가 없다.
     * 사용자 정보가 필요하면 {@code sub} 로 DB 를 조회하면 된다.
     */
    public String issueAccessToken(UUID userId) {
        Instant now = Instant.now();
        Instant expiresAt = now.plus(jwtProperties.accessTokenTtl());

        return Jwts.builder()
                .subject(userId.toString())          // 봇/문서 소유권 검사에 쓸 식별자
                .issuedAt(Date.from(now))
                .expiration(Date.from(expiresAt))
                .signWith(secretKey)                 // 알고리즘은 키 길이로 자동 결정된다(HS256/384/512)
                .compact();
    }

    /**
     * 토큰 검증 후 사용자 id 추출.
     *
     * <p>서명 불일치·만료·형식 오류를 <b>전부</b> {@link ApiException}({@link ErrorCode#INVALID_TOKEN})
     * 하나로 바꿔 던진다. 라이브러리 예외를 그대로 흘려보내면
     * {@code GlobalExceptionHandler} 의 마지막 핸들러에 걸려 500 이 나가는데,
     * "토큰이 잘못됐다"는 <b>클라이언트 잘못</b>이라 401 이 맞다.
     *
     * <p>실패 사유(만료인지 위조인지)를 응답으로 구분해주지 않는 것도 의도다.
     * 공격자에게 "서명은 맞는데 만료됐다" 같은 힌트를 줄 이유가 없고,
     * 프론트가 할 일은 어느 쪽이든 "토큰 버리고 다시 로그인"으로 동일하다.
     */
    public UUID parseUserId(String token) {
        try {
            Claims claims = jwtParser.parseSignedClaims(token).getPayload();
            String subject = claims.getSubject();

            if (subject == null) {
                // 서명은 우리 키로 검증됐지만 sub 가 없는 토큰. 정상 경로로는 나올 수 없다.
                // 아래 catch 가 함께 잡도록 IllegalArgumentException 으로 던진다.
                throw new IllegalArgumentException("sub 클레임이 없는 토큰");
            }
            // sub 가 UUID 형식이 아니면 여기서 IllegalArgumentException 이 난다.
            return UUID.fromString(subject);

        } catch (JwtException | IllegalArgumentException e) {
            // ⚠️ 토큰 문자열 자체를 로그에 남기지 않는다. 로그를 볼 수 있는 사람이
            //    그 토큰으로 그대로 로그인할 수 있게 되어 로그가 곧 인증정보가 된다.
            //    예외 메시지에도 토큰 조각이 섞여 나올 수 있으므로 예외 '종류'만 남긴다.
            log.debug("[JWT] 토큰 검증 실패 reason={}", e.getClass().getSimpleName());
            throw new ApiException(ErrorCode.INVALID_TOKEN);
        }
    }
}
