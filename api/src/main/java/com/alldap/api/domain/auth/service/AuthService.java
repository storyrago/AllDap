package com.alldap.api.domain.auth.service;

import com.alldap.api.domain.auth.dto.AuthResponse;
import com.alldap.api.domain.auth.dto.LoginRequest;
import com.alldap.api.domain.auth.dto.SignupRequest;
import com.alldap.api.domain.auth.dto.UserResponse;
import com.alldap.api.domain.user.entity.User;
import com.alldap.api.domain.user.repository.UserRepository;
import com.alldap.api.global.config.WidgetProperties;
import com.alldap.api.global.exception.ApiException;
import com.alldap.api.global.exception.ErrorCode;
import com.alldap.api.global.ratelimit.RateLimiter;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Duration;
import java.util.Locale;
import java.util.Optional;
import java.util.UUID;

/**
 * 가입·로그인 서비스.
 */
@Slf4j
@Service
@Transactional(readOnly = true)
public class AuthService {

    /**
     * 실패 누적을 세는 통. {@code "login"}(요청 수 제한)과 <b>다른 이름이어야 한다.</b>
     * 같은 통을 쓰면 요청 수와 실패 수가 한 카운터에 섞여 둘 다 뜻을 잃는다.
     */
    private static final String FAILURE_BUCKET = "login-failure";

    /**
     * 실패 누적이 유지되는 기간. 지나면 카운터가 저절로 사라진다(고정 윈도우).
     *
     * <p><b>영구 잠금이 아니라 시간이 지나면 풀리는 이유.</b> 영구 잠금은 관리자가 풀어줘야 하는데,
     * 우리에게는 그 화면도 메일 발송 수단도 없다. 그러면 <b>공격자가 남의 계정을 잠그는 것</b>이
     * 곧 완전한 서비스 거부가 된다. 시간이 지나면 풀리는 차단은 그 최악을 15분으로 묶는다.
     *
     * <p>⚠️ {@code ErrorCode.TOO_MANY_LOGIN_FAILURES} 문구가 "15분" 을 글자로 담고 있다.
     * 이 값을 바꾸면 그 문구도 함께 바꿀 것.
     */
    private static final Duration FAILURE_WINDOW = Duration.ofMinutes(15);

    private final UserRepository userRepository;
    private final PasswordEncoder passwordEncoder;
    private final JwtService jwtService;
    private final RateLimiter rateLimiter;
    private final WidgetProperties widgetProperties;

    /**
     * 존재하지 않는 이메일로 로그인 시도가 왔을 때 대조할 <b>더미 해시</b>. (타이밍 공격 방어)
     *
     * <p><b>문제.</b> "사용자가 없으면 곧바로 실패"로 짜면 응답 시간이 갈린다.
     * BCrypt 대조는 의도적으로 느려서(수십~수백 ms) 이 차이가 네트워크 너머에서도 측정된다.
     * 즉 응답 <b>내용</b>은 INVALID_CREDENTIALS 하나로 통일해도,
     * 응답 <b>속도</b>가 "이 이메일은 가입돼 있다"를 알려주게 된다.
     * 이러면 로그인 폼이 회원 이메일 목록을 캐내는 도구가 된다.
     *
     * <p><b>해결.</b> 사용자를 못 찾아도 이 더미 해시를 상대로 {@code matches()} 를 한 번 돌려
     * 두 경로가 같은 양의 일을 하게 만든다.
     *
     * <p>평문을 하드코딩하지 않고 기동할 때마다 임의의 문자열(UUID)로 만드는 이유:
     * 이 해시에 대응하는 평문을 <b>아무도 모르게</b> 하기 위해서다.
     * 고정 문자열을 소스에 박아두면 "이 값으로 로그인되나?" 하는 의심을 사기도 하고,
     * 실수로 어딘가에서 재사용될 여지도 남는다.
     * 또 {@code passwordEncoder} 로 직접 만들었으므로 실제 저장 해시와 work factor 가 자동으로 같아진다.
     */
    private final String dummyPasswordHash;

    /**
     * Lombok {@code @RequiredArgsConstructor} 대신 생성자를 직접 쓴 이유:
     * {@link #dummyPasswordHash} 는 주입값이 아니라 주입받은 {@code passwordEncoder} 로
     * 만들어내는 파생값이라 자동 생성 생성자로는 표현할 수 없다.
     * (BCrypt 한 번 분량의 비용이 기동 시 한 번 발생한다. 요청 처리 중이 아니라 기동 중이므로 문제되지 않는다.)
     */
    public AuthService(UserRepository userRepository, PasswordEncoder passwordEncoder, JwtService jwtService,
                       RateLimiter rateLimiter, WidgetProperties widgetProperties) {
        this.userRepository = userRepository;
        this.passwordEncoder = passwordEncoder;
        this.jwtService = jwtService;
        this.rateLimiter = rateLimiter;
        this.widgetProperties = widgetProperties;
        this.dummyPasswordHash = passwordEncoder.encode(UUID.randomUUID().toString());
    }

    /**
     * 가입. 성공하면 토큰까지 함께 돌려준다(가입 직후 재로그인을 시키지 않는다).
     *
     * <h2>가입은 사용자 열거(enumeration)를 막지 않는다 — 알고 택한 것이다</h2>
     * 로그인은 더미 해시까지 써서 "이 이메일이 가입돼 있는지"를 감추는데,
     * 가입은 409 {@link ErrorCode#EMAIL_ALREADY_EXISTS} 로 그 사실을 그대로 알려준다.
     * <b>이 비대칭은 빠뜨린 게 아니라 저울질한 결과다.</b>
     *
     * <p>중복을 알려주지 않으려면 "가입 요청을 받았습니다"라고만 답하고 실제 안내는 메일로 보내야 한다
     * (이메일 인증 방식). 그런데 지금은 메일 발송 수단이 없고, 그렇다고 무작정 성공처럼 답하면
     * 사용자는 <b>왜 로그인이 안 되는지 영영 알 수 없다.</b> 그 UX 손해가
     * "가입 폼으로 이메일 가입 여부를 알아낼 수 있다"는 보안 이득보다 크다고 판단했다.
     *
     * <p>다만 로그인과 달리 가입은 <b>계정을 만드는</b> 행위라 스팸·자동 가입 자체를 막을 필요가 있다.
     * TODO(W2 이후): 가입에도 IP 단위 rate limit 을 걸 것. 장치는 이미 있다:
     * {@code AuthController.login} 이 {@code RateLimiter} 를 쓰는 방식을 그대로 따르면 된다.
     * (실패 횟수 제한은 로그인에만 뜻이 있다. 가입에는 "틀린 비밀번호" 라는 개념이 없다)
     */
    @Transactional
    public AuthResponse signup(SignupRequest request) {
        String email = normalizeEmail(request.email());

        // 1차 방어: 흔한 경우를 미리 걸러 사용자에게 정확한 안내(409)를 준다.
        if (userRepository.existsByEmail(email)) {
            throw new ApiException(ErrorCode.EMAIL_ALREADY_EXISTS);
        }

        // encode() 는 비밀번호가 UTF-8 72바이트를 넘으면 IllegalArgumentException 을 던진다(BCrypt 자체의 한계).
        // 그 검사는 여기가 아니라 SignupRequest 의 @ByteLength(max = 72) 가 이미 통과시킨 뒤다 —
        // 입력 검증은 컨트롤러 진입 시점에 한 곳에서 끝내고, 서비스는 "규격을 통과한 값"만 다룬다.
        User user = User.create(email, passwordEncoder.encode(request.password()), normalizeName(request.name()));

        try {
            // saveAndFlush 로 INSERT 를 '지금' 보낸다.
            // 그냥 save() 만 하면 Hibernate 가 INSERT 를 트랜잭션 커밋 시점까지 미룰 수 있는데,
            // 커밋은 이 메서드가 끝난 뒤(@Transactional 프록시)에 일어나므로
            // 아래 catch 문이 제약 위반을 잡지 못하고 500 이 나가버린다.
            userRepository.saveAndFlush(user);

        } catch (DataIntegrityViolationException e) {
            // 2차(최종) 방어: 같은 이메일로 동시에 두 요청이 들어오면 위의 existsByEmail 은 둘 다 통과한다.
            // 진짜 방어선은 DB 의 email UNIQUE 제약이고, 그 위반이 여기로 올라온다.
            // 사용자 입장에서는 1차에서 걸린 것과 똑같은 상황이므로 같은 코드로 답한다.
            log.warn("[signup] 이메일 UNIQUE 제약 위반 — 동시 가입 경합으로 보인다. email={}", maskEmail(email));
            throw new ApiException(ErrorCode.EMAIL_ALREADY_EXISTS);
        }

        // 이메일·이름은 남기지 않는다. userId 만으로 추적이 가능하고, 로그는 평문 개인정보의 흔한 유출 경로다.
        log.info("[signup] 신규 가입 userId={}", user.getId());
        return toAuthResponse(user);
    }

    /**
     * 로그인.
     *
     * <p>실패 응답은 사유와 무관하게 {@link ErrorCode#INVALID_CREDENTIALS} 하나다.
     * "없는 이메일"과 "틀린 비밀번호"를 구분해주면 로그인 폼으로 가입 여부를 조회할 수 있게 된다.
     *
     * <h2>무차별 대입(brute-force) 방어: 두 겹이고, 세는 것이 다르다</h2>
     * <ol>
     *   <li><b>요청 수 / IP</b> ({@code AuthController}, PR #44). 한 IP 가 여러 계정을 훑는 것을 막는다.
     *       다만 이것만으로는 <b>한도만큼 영원히</b> 추측을 이어갈 수 있다.
     *       분당 10회면 하루 14,400회고, 흔한 비밀번호 목록에는 그 정도면 충분하다.</li>
     *   <li><b>실패 수 / (IP + 이메일)</b> ← 여기. 같은 계정을 겨냥한 연속 실패가 쌓이면 끊는다.</li>
     * </ol>
     *
     * <h2>왜 키가 IP <b>와</b> 이메일인가</h2>
     * 어느 한쪽만으로는 둘 중 하나가 반드시 깨진다.
     * <ul>
     *   <li><b>IP 만</b> 세면 회사·학교처럼 NAT 뒤에 있는 정상 사용자들이 서로에게 말려든다.
     *       옆자리 동료가 비밀번호를 틀린 탓에 내가 로그인을 못 한다.</li>
     *   <li><b>이메일만</b> 세면 공격자가 남의 이메일로 일부러 실패를 쌓아 그 계정을 잠글 수 있다.
     *       <b>계정 잠금이 곧 서비스 거부</b>가 된다. 우리에게는 잠금을 풀어줄 화면도 메일 발송 수단도 없다.</li>
     * </ul>
     * 둘을 함께 쓰면 차단 범위가 "이 IP 에서 이 계정을 노리는 시도" 하나로 좁아진다.
     * 공격자는 자기 자신만 막히고, 피해자는 자기 IP 에서 평소처럼 로그인할 수 있다.
     *
     * <p>🔴 <b>대가는 분산 공격이다.</b> 서로 다른 IP 수천 개(봇넷)로 한 계정을 노리면
     * 각 IP 의 카운터가 따로 놀아 이 겹은 막지 못한다. 그걸 막으려면 이메일 단위로 세야 하는데,
     * 그건 위에 적은 계정 잠금 서비스 거부를 <b>스스로 만들어 주는</b> 일이다.
     * 분산 공격을 실제로 겪으면 답은 계정 잠금이 아니라 다른 축(캡차, 2단계 인증)이다.
     *
     * <h2>왜 지연이 아니라 차단인가</h2>
     * 실패할 때마다 응답을 늦추는(sleep) 방식은 <b>우리 스레드를 붙잡는다.</b>
     * 톰캣 스레드 풀이 한정돼 있으므로, 공격자가 일부러 실패를 쌓아 스레드를 점유하면
     * 방어 장치가 그 자체로 서비스 거부 수단이 된다. 게다가 BCrypt 가 이미 회당 약 100ms 를 쓴다.
     * 시간이 지나면 풀리는 차단은 스레드를 잡지 않고, 막힌 요청은 BCrypt 대조조차 하지 않아 <b>더 싸다.</b>
     *
     * @param clientIp 요청자 IP. 컨트롤러가 넘긴다.
     *                 ⚠️ 이 값이 믿을 만하려면 앞단 프록시(Caddy)가 헤더를 정리해야 한다. Caddyfile 참고.
     */
    public AuthResponse login(LoginRequest request, String clientIp) {
        String email = normalizeEmail(request.email());
        String failureKey = clientIp + "|" + email;

        // 🔴 대조 <전에> 막는다. 대조 뒤에 막으면 공격자가 맞는 비밀번호를 찾아낸 바로 그 요청은
        //    이미 통과한 뒤라, 방어가 아무것도 막지 못한 것이 된다.
        if (rateLimiter.isBlocked(FAILURE_BUCKET, failureKey,
                widgetProperties.loginFailureLimit(), FAILURE_WINDOW)) {
            log.warn("[login] 실패 누적으로 차단 email={}", maskEmail(email));
            throw new ApiException(ErrorCode.TOO_MANY_LOGIN_FAILURES);
        }

        Optional<User> found = userRepository.findByEmail(email);

        // 사용자가 없어도 matches() 를 건너뛰지 않는다 — 근거는 dummyPasswordHash 주석 참고.
        // (Optional.map(...).orElse(...) 는 "있으면 이걸로, 없으면 저걸로"를 분기문 없이 쓰는 관용구다)
        String passwordHash = found.map(User::getPasswordHash).orElse(dummyPasswordHash);
        boolean passwordMatched = passwordEncoder.matches(request.password(), passwordHash);

        if (found.isEmpty() || !passwordMatched) {
            // 🔴 가입 여부와 무관하게 <똑같이> 센다. 존재하는 계정에서만 세면 차단 시점이 갈려
            //    "몇 번 만에 429 가 나오는가" 가 가입 여부를 알려주게 된다. 응답 본문만 통일해서는 부족하다.
            rateLimiter.record(FAILURE_BUCKET, failureKey, FAILURE_WINDOW);
            log.warn("[login] 로그인 실패 email={}", maskEmail(email));
            throw new ApiException(ErrorCode.INVALID_CREDENTIALS);
        }

        // 성공하면 누적을 지운다. 안 지우면 비밀번호를 몇 번 헷갈렸다가 제대로 로그인한 사용자가,
        // 15분 안에 한 번만 더 틀려도 차단된다. 실패가 <연속>일 때만 의심스러운 것이다.
        rateLimiter.forget(FAILURE_BUCKET, failureKey, FAILURE_WINDOW);

        return toAuthResponse(found.get());
    }

    private AuthResponse toAuthResponse(User user) {
        return new AuthResponse(jwtService.issueAccessToken(user.getId()), UserResponse.from(user));
    }

    /**
     * 이메일을 소문자로 통일해 저장·조회한다.
     *
     * <p>DB 의 UNIQUE 제약은 대소문자를 구분하므로, 정규화하지 않으면
     * {@code A@x.com} 과 {@code a@x.com} 이 서로 다른 계정이 된다.
     * 사용자는 같은 주소라고 생각하는데 로그인이 안 되는 상황이 생긴다.
     * <b>가입과 로그인 양쪽에서 똑같이 적용해야</b> 의미가 있다.
     */
    private String normalizeEmail(String email) {
        return email == null ? null : email.trim().toLowerCase(Locale.ROOT);
    }

    /** 이름은 선택 입력이다. 공백만 넣은 경우는 "입력 안 함"과 같이 취급해 null 로 저장한다. */
    private String normalizeName(String name) {
        if (name == null) {
            return null;
        }
        String trimmed = name.trim();
        return trimmed.isEmpty() ? null : trimmed;
    }

    /**
     * 로그용 이메일 마스킹. {@code hong@example.com} → {@code ho***@example.com}
     *
     * <p>전체를 찍으면 로그 파일이 개인정보 저장소가 된다.
     * 그렇다고 아무것도 안 남기면 "누가 계속 로그인에 실패하는지" 추적이 불가능해
     * 최소한의 식별만 남긴다.
     */
    private String maskEmail(String email) {
        if (email == null || email.isBlank()) {
            return "(없음)";
        }
        int atIndex = email.indexOf('@');
        if (atIndex <= 0) {
            return "***";
        }
        String localPart = email.substring(0, atIndex);
        String visible = localPart.length() <= 2 ? localPart.substring(0, 1) : localPart.substring(0, 2);
        return visible + "***" + email.substring(atIndex);
    }
}
