package com.alldap.api.domain.billing.controller;

import com.alldap.api.domain.billing.dto.BillingMethodResponse;
import com.alldap.api.domain.billing.dto.RegisterBillingMethodRequest;
import com.alldap.api.domain.billing.service.BillingService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.DeleteMapping;
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

    /**
     * DELETE /api/billing/method — 등록된 카드 삭제. 성공하면 본문 없이 <b>204</b>.
     *
     * <p>토스 쪽 빌링키도 함께 폐기된다({@code BillingService.delete} 주석 참고).
     * 실패는 {@code GlobalExceptionHandler} 가 공통 포맷으로 바꿔 내려준다 —
     * 등록된 카드가 없으면 <b>404</b>, 토스가 죽었거나 응답이 없으면 <b>503</b>(이때 카드는 그대로 남는다).
     *
     * <p>경로에 식별자가 없다. 계정당 카드는 한 장이고 "누구의 것인가"는
     * {@code @AuthenticationPrincipal} 이 이미 정한다 — id 를 받으면 남의 id 를 적어 보낼 자리가 생긴다.
     *
     * <p>⚠️ 브리프 원안은 {@code @DeleteMapping("/api/billing/method")} 였지만, 이 컨트롤러는
     * 클래스에 {@code @RequestMapping("/api/billing/method")} 를 이미 붙여두고
     * {@code @GetMapping}·{@code @PostMapping} 을 경로 없이 쓰는 관례다. 같은 관례를 따른다
     * (경로를 또 넣으면 {@code /api/billing/method/api/billing/method} 가 된다).
     */
    @DeleteMapping
    public ResponseEntity<Void> deleteBillingMethod(@AuthenticationPrincipal UUID userId) {
        billingService.delete(userId);
        return ResponseEntity.noContent().build();
    }
}
