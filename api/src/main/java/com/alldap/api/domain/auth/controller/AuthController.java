package com.alldap.api.domain.auth.controller;

import com.alldap.api.domain.auth.dto.AuthResponse;
import com.alldap.api.domain.auth.dto.LoginRequest;
import com.alldap.api.domain.auth.dto.SignupRequest;
import com.alldap.api.domain.auth.service.AuthService;
import com.alldap.api.global.config.WidgetProperties;
import com.alldap.api.global.ratelimit.RateLimiter;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import io.swagger.v3.oas.annotations.security.SecurityRequirements;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.Duration;

/**
 * 인증 API (PRD §10.1). SecurityConfig 에서 공개 경로로 열려 있다.
 */
@RestController
@RequestMapping("/api/auth")
@RequiredArgsConstructor
public class AuthController {

    private final AuthService authService;
    private final RateLimiter rateLimiter;
    private final WidgetProperties widgetProperties;

    /**
     * POST /api/auth/signup — 가입. 성공하면 바로 토큰까지 준다(가입 후 재로그인을 시키지 않는다).
     *
     * <p>201 Created 를 쓰되 {@code Location} 헤더는 붙이지 않는다.
     * Location 은 "만들어진 리소스를 여기서 조회하라"는 뜻인데,
     * 우리 API 에는 사용자 단건 조회 경로가 없다(PRD §10.1). 없는 주소를 가리킬 수는 없다.
     */
    // 전역 JWT 요구를 해제한다. 이 애노테이션의 <유무>가 공통 401 을 붙일지 판정하는 신호이기도 하다
    // (OpenApiConfig 참고). 보안 표기와 401 표기가 자동으로 맞는다.
    @SecurityRequirements
    @PostMapping("/signup")
    public ResponseEntity<AuthResponse> signup(@Valid @RequestBody SignupRequest request) {
        AuthResponse response = authService.signup(request);
        return ResponseEntity.status(HttpStatus.CREATED).body(response);
    }

    /**
     * POST /api/auth/login — 로그인.
     *
     * <p>200 OK 다. 로그인은 서버에 새 리소스를 만드는 행위가 아니라
     * 이미 있는 계정을 확인하고 토큰을 발급받는 행위이기 때문이다.
     *
     * <p><b>요청 수를 제한한다.</b> 이 경로는 {@code permitAll} 이고 실패 카운트도 지연도 없어,
     * 유일한 방어가 BCrypt 비용(약 100ms/회)뿐이었다. 병렬 커넥션이면 분당 수천 회 추측이 가능하고,
     * {@code PasswordEncoder.matches} 가 요청당 CPU 를 태우므로 그 자체가 저비용 DoS 이기도 하다.
     *
     * <p><b>여기서 세는 키는 IP 다.</b> 이메일로 잡으면 남의 계정을 골라 잠글 수 있다(계정 잠금 공격).
     * ⚠️ 이 IP 가 믿을 수 있으려면 프록시가 X-Forwarded-For 를 덮어써야 한다 — Caddyfile 참고.
     *
     * <p><b>이 겹만으로는 부족하다.</b> 요청 수 제한은 속도만 늦출 뿐이라, 한 IP 가 한도만큼
     * <b>영원히</b> 추측을 이어갈 수 있다. 연속 <b>실패</b>를 세어 끊는 두 번째 겹은
     * {@code AuthService.login} 에 있다(거기서 IP 가 필요해 아래처럼 넘겨준다).
     */
    // 전역 JWT 요구를 해제한다. 로그인 자체가 토큰을 <발급받는> 요청이다.
    // ⚠️ 이 경로의 401(INVALID_CREDENTIALS)은 "토큰이 없어서" 가 아니라 "비밀번호가 틀려서" 다.
    //    별개 사실이므로 공통 401 이 아니라 엔드포인트별 @ApiResponse 로 단다(PR 2).
    @SecurityRequirements
    @PostMapping("/login")
    public ResponseEntity<AuthResponse> login(@Valid @RequestBody LoginRequest request,
                                              HttpServletRequest servletRequest) {
        String clientIp = servletRequest.getRemoteAddr();
        rateLimiter.check("login", clientIp, widgetProperties.loginPerMinute(), Duration.ofMinutes(1));
        AuthResponse response = authService.login(request, clientIp);
        return ResponseEntity.ok(response);
    }

    // TODO(W2): GET /api/auth/me 가 필요한지 결정할 것.
    //   프론트가 새로고침 후 토큰만으로 사용자 정보를 복원하려면 필요하다.
    //   PRD §10.1 표에는 없는 경로이므로 추가하려면 PRD 도 함께 갱신한다.
}
