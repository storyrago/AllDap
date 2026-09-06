package com.alldap.api.domain.billing.controller;

import com.alldap.api.domain.billing.dto.BillingMethodResponse;
import com.alldap.api.domain.billing.dto.RegisterBillingMethodRequest;
import com.alldap.api.domain.billing.service.BillingService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.UUID;

/**
 * 결제 수단 API. 인증 필요.
 *
 * <p>🔴 <b>{@code userId} 를 경로·쿼리·본문으로 받지 않는다.</b> {@code @AuthenticationPrincipal}
 * 로만 받는다 — 파라미터로 받으면 남의 id 를 적어 보내는 것만으로 남의 카드를 보거나 붙일 수 있다.
 * 봇 소유권 검사가 없는 이유도 같다: 이 리소스는 <b>토큰의 주인</b> 자체로 좁혀져 있다.
 *
 * <p>{@code SecurityConfig} 를 고칠 필요가 없다 — 공개 경로는
 * {@code /api/auth/signup}·{@code /api/auth/login}·{@code /api/w/**}·{@code /actuator/health}·
 * {@code /widget/**} 뿐이고, 나머지 {@code /api/**} 는 {@code anyRequest().authenticated()} 로
 * 이미 인증을 요구한다.
 *
 * <p>DELETE 는 Task 3 에서 붙인다.
 */
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/billing/method")
public class BillingController {

    private final BillingService billingService;

    /** GET /api/billing/method — 카드가 없으면 {@code method: null}, customerKey 는 항상 온다 */
    @GetMapping
    public ResponseEntity<BillingMethodResponse> get(@AuthenticationPrincipal UUID userId) {
        return ResponseEntity.ok(billingService.find(userId));
    }

    /**
     * POST /api/billing/method — 토스 {@code authKey} 를 빌링키로 바꿔 저장한다.
     *
     * <p>201 이 아니라 200 인 이유: 프론트가 등록 직후 카드 정보를 그대로 화면에 그려야 해서
     * 본문이 필요하고, 이 리소스는 계정당 하나뿐이라 클라이언트가 따라갈 새 주소가 없다
     * (Location 헤더로 가리킬 것이 {@code GET} 과 같은 주소다).
     */
    @PostMapping
    public ResponseEntity<BillingMethodResponse> register(
            @AuthenticationPrincipal UUID userId,
            @Valid @RequestBody RegisterBillingMethodRequest request) {
        return ResponseEntity.ok(billingService.register(userId, request));
    }
}
