package com.alldap.api.domain.auth.service;

import com.alldap.api.domain.auth.dto.AuthResponse;
import com.alldap.api.domain.auth.dto.LoginRequest;
import com.alldap.api.domain.auth.dto.SignupRequest;
import com.alldap.api.domain.auth.dto.UserResponse;
import com.alldap.api.domain.user.entity.User;
import com.alldap.api.domain.user.repository.UserRepository;
import com.alldap.api.global.exception.ApiException;
import com.alldap.api.global.exception.ErrorCode;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

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

    private final UserRepository userRepository;
    private final PasswordEncoder passwordEncoder;
    private final JwtService jwtService;

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
     * <p>평문을 하드코딩하지 않고 기동할 때마다 임의의 UUID 로 만드는 이유:
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
    public AuthService(UserRepository userRepository, PasswordEncoder passwordEncoder, JwtService jwtService) {
        this.userRepository = userRepository;
        this.passwordEncoder = passwordEncoder;
        this.jwtService = jwtService;
        this.dummyPasswordHash = passwordEncoder.encode(UUID.randomUUID().toString());
    }

    /**
     * 가입. 성공하면 토큰까지 함께 돌려준다(가입 직후 재로그인을 시키지 않는다).
     */
    @Transactional
    public AuthResponse signup(SignupRequest request) {
        String email = normalizeEmail(request.email());

        // 1차 방어: 흔한 경우를 미리 걸러 사용자에게 정확한 안내(409)를 준다.
        if (userRepository.existsByEmail(email)) {
            throw new ApiException(ErrorCode.EMAIL_ALREADY_EXISTS);
        }

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
     */
    public AuthResponse login(LoginRequest request) {
        String email = normalizeEmail(request.email());
        Optional<User> found = userRepository.findByEmail(email);

        // 사용자가 없어도 matches() 를 건너뛰지 않는다 — 근거는 dummyPasswordHash 주석 참고.
        // (Optional.map(...).orElse(...) 는 "있으면 이걸로, 없으면 저걸로"를 분기문 없이 쓰는 관용구다)
        String passwordHash = found.map(User::getPasswordHash).orElse(dummyPasswordHash);
        boolean passwordMatched = passwordEncoder.matches(request.password(), passwordHash);

        if (found.isEmpty() || !passwordMatched) {
            log.warn("[login] 로그인 실패 email={}", maskEmail(email));
            throw new ApiException(ErrorCode.INVALID_CREDENTIALS);
        }

        return toAuthResponse(found.get());

        // TODO(W2 이후): 로그인 실패 횟수 제한(brute-force 방어).
        //   JWT 라 서버에 상태가 없으므로 실패 카운터를 어디에 둘지부터 정해야 한다
        //   (DB 컬럼 추가 = 마이그레이션 필요 / Redis 도입 = 운영 대상 증가).
        //   지금 결정하지 않고 남겨둔다.
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
