package com.alldap.api.domain.auth.controller;

import com.alldap.api.domain.auth.dto.AuthResponse;
import com.alldap.api.domain.auth.dto.LoginRequest;
import com.alldap.api.domain.auth.dto.SignupRequest;
import com.alldap.api.domain.auth.service.AuthService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 인증 API (PRD §10.1). SecurityConfig 에서 공개 경로로 열려 있다.
 */
@RestController
@RequestMapping("/api/auth")
@RequiredArgsConstructor
public class AuthController {

    private final AuthService authService;

    /** POST /api/auth/signup — 가입. 성공하면 바로 토큰까지 준다(가입 후 재로그인을 시키지 않는다). */
    @PostMapping("/signup")
    public ResponseEntity<AuthResponse> signup(@Valid @RequestBody SignupRequest request) {
        // TODO(W2): authService.signup(request) 호출 후 201 Created 반환
        throw new UnsupportedOperationException("AuthController.signup 미구현 (W2)");
    }

    /** POST /api/auth/login — 로그인 */
    @PostMapping("/login")
    public ResponseEntity<AuthResponse> login(@Valid @RequestBody LoginRequest request) {
        // TODO(W2): authService.login(request) 호출 후 200 OK 반환
        throw new UnsupportedOperationException("AuthController.login 미구현 (W2)");
    }

    // TODO(W2): GET /api/auth/me 가 필요한지 결정할 것.
    //   프론트가 새로고침 후 토큰만으로 사용자 정보를 복원하려면 필요하다.
    //   PRD §10.1 표에는 없는 경로이므로 추가하려면 PRD 도 함께 갱신한다.
}
