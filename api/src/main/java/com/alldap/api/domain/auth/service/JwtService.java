package com.alldap.api.domain.auth.service;

import com.alldap.api.global.config.JwtProperties;
import com.alldap.api.global.exception.ApiException;
import com.alldap.api.global.exception.ErrorCode;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jws;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.JwtParser;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import io.jsonwebtoken.security.MacAlgorithm;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Service;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Arrays;
import java.util.Date;
import java.util.Locale;
import java.util.Set;

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

    /**
     * 서명 알고리즘을 <b>상수로 고정</b>한다. 발급도 검증도 반드시 이 알고리즘이어야 한다.
     *
     * <p><b>왜 고정하나.</b> 원래 코드는 {@code signWith(key)} 로 알고리즘을 jjwt 에 맡겼는데,
     * 그러면 두 가지가 조용히 어긋난다.
     * <ol>
     *   <li><b>발급 쪽:</b> jjwt 는 <b>키 길이</b>로 알고리즘을 고른다. 시크릿을 32바이트로 바꾸면
     *       어느 날 HS512 였던 서명이 HS256 으로 바뀐다 — 코드는 한 줄도 안 고쳤는데.</li>
     *   <li><b>검증 쪽(더 중요):</b> 파서는 <b>토큰 헤더에 적힌</b> 알고리즘을 그대로 믿는다.
     *       그래서 우리가 HS512 로 발급했더라도 같은 키로 HS384 서명한 토큰이 통과한다.
     *       (실제로 확인했다) "누가 알고리즘을 정하는가"가 서버가 아니라 <b>토큰</b>이 되는 셈이라,
     *       알고리즘 혼동(algorithm confusion) 류 공격의 출발점이 된다.</li>
     * </ol>
     *
     * <p>HS256 을 고른 이유: HS256 은 최소 32바이트 키를 요구하고 HS512 는 64바이트를 요구한다.
     * 상한이 아니라 <b>하한</b>이므로 긴 키를 써도 그대로 동작한다.
     * 즉 HS256 으로 고정해두면 운영자가 32바이트짜리 시크릿을 넣어도 기동이 막히지 않는다.
     * (HMAC 은 256비트만으로도 충분히 안전하다. 여기서 512 로 올려 얻는 실질 이득은 없다)
     *
     * <p>⚠️ 이 변경으로 <b>기존에 발급된 토큰(HS512)은 무효</b>가 된다. 다시 로그인하면 된다.
     */
    private static final MacAlgorithm SIGNATURE_ALGORITHM = Jwts.SIG.HS256;

    /**
     * {@code application.yaml} 에 박혀 있는(= 저장소에 공개된) 로컬 개발용 기본 시크릿.
     *
     * <p>여기에 값을 <b>복사해두는 것 자체가 목적</b>이다. "이 값은 이미 공개됐으니 운영에서 쓰면 안 된다"는
     * 블랙리스트이기 때문이다. 두 곳에 같은 문자열이 있는 건 중복이 맞고, 실제로 약한 고리다 —
     * yaml 의 기본값만 바꾸면 이 가드는 아무 말 없이 무력해진다.
     * 그래서 {@code application.yaml} 쪽에도 "이 값을 바꾸면 여기도 함께 바꾸라"는 주석을 남겨뒀다.
     */
    private static final String KNOWN_LOCAL_DEFAULT_SECRET =
            "alldap-local-dev-only-secret-key-do-not-use-in-production-0123456789";

    /**
     * "여긴 개발 환경이다"로 인정할 프로파일 이름들.
     *
     * <p><b>판정 기준을 이렇게 잡은 근거.</b> 반대로(= 운영 프로파일 목록을 나열해서) 판단하면
     * {@code staging}·{@code prod2} 같은 이름이 새로 생길 때마다 가드가 조용히 뚫린다.
     * 안전한 쪽은 <b>허용 목록</b>이다 — 모르는 이름은 전부 "운영일 수도 있다"로 본다.
     */
    private static final Set<String> DEVELOPMENT_PROFILES = Set.of("local", "dev", "development", "test");

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
    public JwtService(JwtProperties jwtProperties, Environment environment) {
        assertSecretIsSafeFor(environment, jwtProperties.secret());

        this.jwtProperties = jwtProperties;
        this.secretKey = Keys.hmacShaKeyFor(jwtProperties.secret().getBytes(StandardCharsets.UTF_8));
        this.jwtParser = Jwts.parser().verifyWith(this.secretKey).build();
    }

    /**
     * 저장소에 공개된 기본 시크릿으로 <b>운영에 뜨는 것</b>을 막는다(fail-fast).
     *
     * <p><b>왜 필요한가.</b> 이 시크릿 하나만 알면 누구나 아무 {@code sub}(사용자 id)나 넣어
     * 유효한 토큰을 만들 수 있다. 즉 전 계정 사칭이다. 그런데 그 값이 지금 저장소에 그대로 들어 있다.
     * {@code prod} 프로파일을 켜면 {@code application-prod.yaml} 이 {@code JWT_SECRET} 환경변수를
     * 강제하지만, <b>프로파일을 깜빡하고 배포하면</b> 아무 경고 없이 그 공개된 키로 기동해버린다.
     *
     * <p><b>기동 시점에 죽이는 이유.</b> 이런 실수는 "조용히 잘 도는 것"이 최악이다.
     * 첫 요청에서 500 이 나는 것도 아니고, 아무 일 없이 몇 달 돌다가 사고로 드러난다.
     * 그래서 요청 처리 중이 아니라 <b>빈 생성 시점</b>에 검사한다 —
     * 여기서 예외가 나면 스프링 컨텍스트 초기화가 실패해 톰캣이 요청을 받기 전에 죽는다.
     *
     * <p><b>프로파일이 하나도 활성화되지 않은 경우를 '개발'로 보는 이유(트레이드오프).</b>
     * 로컬 실행({@code ./gradlew bootRun})·IDE 실행·통합 테스트가 전부 프로파일 없이 돈다.
     * 이걸 막으면 README 의 실행 절차부터 전부 깨진다.
     * 대신 <b>잔여 위험</b>이 남는다 — 프로파일을 지정하지 않고 배포하면 이 가드도 통과한다.
     * 근본 해결은 {@code application.yaml} 에서 기본값 자체를 없애고 로컬에서도 {@code JWT_SECRET} 을
     * 주입하게 만드는 것이다. TODO(배포 준비 단계): 그때 이 예외 조건도 함께 조인다.
     */
    private void assertSecretIsSafeFor(Environment environment, String secret) {
        // ⚠️ 기본값 비교보다 먼저 해야 하는 검사.
        // @ConfigurationProperties 는 해석 못 한 ${JWT_SECRET} 를 예외 없이 리터럴 문자열로 바인딩한다
        // (@Value 와 다르다 — CorsProperties.UNRESOLVED_PLACEHOLDER 주석에 자세히 적어뒀다).
        // 그대로 두면 13자짜리 "${JWT_SECRET}" 가 서명 키가 되고, jjwt 가 던지는 영어 WeakKeyException 만
        // 보게 된다. 무엇을 어떻게 고쳐야 하는지 한국어로 알려주려면 여기서 먼저 잡아야 한다.
        if (secret == null || secret.isBlank() || secret.startsWith("${")) {
            throw new IllegalStateException(
                    "JWT 서명 키(app.jwt.secret)가 설정되지 않았습니다. JWT_SECRET 환경변수를 설정해주세요. "
                            + "HS256 서명에는 32바이트(영문 32자) 이상이 필요하며, 아무도 추측할 수 없는 무작위 값이어야 합니다. "
                            + "예: openssl rand -base64 48");
        }

        if (!KNOWN_LOCAL_DEFAULT_SECRET.equals(secret)) {
            return;   // 직접 설정한 시크릿 — 검사할 것이 없다.
        }

        String[] activeProfiles = environment.getActiveProfiles();
        boolean development = activeProfiles.length == 0
                || Arrays.stream(activeProfiles)
                .anyMatch(profile -> DEVELOPMENT_PROFILES.contains(profile.toLowerCase(Locale.ROOT)));

        if (development) {
            log.warn("[JWT] 저장소에 공개된 로컬 기본 시크릿으로 기동한다. 배포 환경에서는 반드시 JWT_SECRET 환경변수를 설정할 것.");
            return;
        }

        throw new IllegalStateException("""
                JWT 서명 키(app.jwt.secret)가 저장소에 공개된 로컬 기본값 그대로입니다. \
                이 값을 아는 사람은 누구나 토큰을 위조해 아무 계정이나 사칭할 수 있으므로 기동을 중단합니다.
                → 배포 환경이라면: JWT_SECRET 환경변수에 32바이트(영문·숫자 32자) 이상의 임의 문자열을 설정한 뒤 다시 실행하세요. \
                (예: openssl rand -base64 48)
                → 로컬 개발이라면: SPRING_PROFILES_ACTIVE=local 로 실행하거나 프로파일 없이 실행하세요.
                현재 활성 프로파일: %s""".formatted(Arrays.toString(activeProfiles)));
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
    public String issueAccessToken(Long userId) {
        Instant now = Instant.now();
        Instant expiresAt = now.plus(jwtProperties.accessTokenTtl());

        return Jwts.builder()
                .subject(userId.toString())          // 봇/문서 소유권 검사에 쓸 식별자
                .issuedAt(Date.from(now))
                .expiration(Date.from(expiresAt))
                // 알고리즘을 키 길이에 맡기지 않고 명시한다. 근거는 SIGNATURE_ALGORITHM 주석 참고.
                .signWith(secretKey, SIGNATURE_ALGORITHM)
                .compact();
    }

    /**
     * 토큰 검증 후 사용자 id 추출.
     *
     * <p>검사 항목은 네 가지다: 서명, 서명 <b>알고리즘</b>, {@code exp}(만료) <b>존재 여부와 만료 시각</b>,
     * {@code sub} 형식. 뒤의 두 가지는 라이브러리가 대신 해주지 않아 직접 확인한다.
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
    public Long parseUserId(String token) {
        try {
            Jws<Claims> jws = jwtParser.parseSignedClaims(token);

            // ① 서명 알고리즘이 우리가 발급할 때 쓴 것과 같은가.
            //    파서는 "토큰 헤더에 적힌" 알고리즘으로 검증하므로, 이 확인을 빼면
            //    같은 키로 다른 HMAC 알고리즘(HS384 등)을 써서 만든 토큰도 통과한다.
            String algorithm = jws.getHeader().getAlgorithm();
            if (!SIGNATURE_ALGORITHM.getId().equals(algorithm)) {
                throw new IllegalArgumentException("서명 알고리즘 불일치: " + algorithm);
            }

            Claims claims = jws.getPayload();

            // ② 만료 시각이 반드시 있어야 한다.
            //    JWT 규격에서 exp 는 '선택' 클레임이라, 없으면 파서는 "만료 검사할 것이 없다"며 통과시킨다.
            //    즉 exp 없는 토큰 = 영원히 유효한 토큰이 된다. 우리는 항상 exp 를 넣어 발급하므로
            //    (issueAccessToken 참고) exp 가 없는 토큰은 우리가 만든 것이 아니다 — 거절한다.
            //    JWT 는 서버에서 강제 무효화할 수 없어 만료가 사실상 유일한 안전장치다.
            if (claims.getExpiration() == null) {
                throw new IllegalArgumentException("exp 클레임이 없는 토큰");
            }

            String subject = claims.getSubject();

            if (subject == null) {
                // 서명은 우리 키로 검증됐지만 sub 가 없는 토큰. 정상 경로로는 나올 수 없다.
                // 아래 catch 가 함께 잡도록 IllegalArgumentException 으로 던진다.
                throw new IllegalArgumentException("sub 클레임이 없는 토큰");
            }
            // sub 가 숫자가 아니면 여기서 NumberFormatException(IllegalArgumentException 의 하위)이 난다.
            // 아래 catch 가 그대로 잡는다.
            return Long.parseLong(subject);

        } catch (JwtException | IllegalArgumentException e) {
            // ⚠️ 토큰 문자열 자체를 로그에 남기지 않는다. 로그를 볼 수 있는 사람이
            //    그 토큰으로 그대로 로그인할 수 있게 되어 로그가 곧 인증정보가 된다.
            //    예외 메시지에도 토큰 조각이 섞여 나올 수 있으므로 예외 '종류'만 남긴다.
            log.debug("[JWT] 토큰 검증 실패 reason={}", e.getClass().getSimpleName());
            throw new ApiException(ErrorCode.INVALID_TOKEN);
        }
    }
}
