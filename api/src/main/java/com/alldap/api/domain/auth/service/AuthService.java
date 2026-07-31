package com.alldap.api.domain.auth.service;

import com.alldap.api.domain.auth.dto.AuthResponse;
import com.alldap.api.domain.auth.dto.LoginRequest;
import com.alldap.api.domain.auth.dto.SignupRequest;
import com.alldap.api.domain.user.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 가입·로그인 서비스.
 */
@Slf4j
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class AuthService {

    private final UserRepository userRepository;
    private final PasswordEncoder passwordEncoder;
    private final JwtService jwtService;

    @Transactional
    public AuthResponse signup(SignupRequest request) {
        // TODO(W2): 구현.
        //   1) userRepository.existsByEmail → 있으면 ApiException(EMAIL_ALREADY_EXISTS)
        //   2) passwordEncoder.encode(request.password()) 로 해시
        //   3) User.create(...) 저장
        //   4) jwtService.issueAccessToken(user.getId()) 로 토큰 발급 후 AuthResponse 반환
        //   ※ 동시 가입 경합은 existsByEmail 로 막히지 않는다.
        //     DataIntegrityViolationException 도 EMAIL_ALREADY_EXISTS 로 변환할 것.
        throw new UnsupportedOperationException("AuthService.signup 미구현 (W2)");
    }

    public AuthResponse login(LoginRequest request) {
        // TODO(W2): 구현.
        //   findByEmail → passwordEncoder.matches(평문, 저장된해시) 비교.
        //   ⚠️ "없는 이메일"과 "틀린 비밀번호"를 구분해서 응답하지 말 것.
        //      둘 다 INVALID_CREDENTIALS 로 답해야 가입 여부가 새어나가지 않는다.
        //   TODO(W2): 로그인 실패 횟수 제한(brute-force 방어)도 검토할 것.
        throw new UnsupportedOperationException("AuthService.login 미구현 (W2)");
    }
}
