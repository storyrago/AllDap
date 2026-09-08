package com.alldap.api.domain.billing.controller;

import com.alldap.api.domain.billing.dto.BillingMethodsResponse;
import com.alldap.api.domain.billing.dto.RegisterBillingMethodRequest;
import com.alldap.api.domain.billing.service.BillingService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.UUID;

/**
 * 결제 수단 API. 인증 필요. V7(2026-09-08) 부터 <b>여러 장</b> — 경로가 {@code /method} 에서
 * {@code /methods} 로 바뀌었고, 삭제·기본 지정은 카드 {@code id} 를 경로에 받는다.
 *
 * <p>🔴 <b>{@code userId} 를 경로·쿼리·본문으로 받지 않는다.</b> {@code @AuthenticationPrincipal}
 * 로만 받는다 — 파라미터로 받으면 남의 id 를 적어 보내는 것만으로 남의 카드를 보거나 붙일 수 있다.
 * 카드 {@code id} 는 받지만, 그 id 가 <b>이 사용자의 것인지</b>는 서비스가 쿼리로 못박는다
 * ({@code findByIdAndUserId}). 남의 id 를 적어 보내면 <b>404</b> 다 — 403 은 "그 카드가 존재한다" 를
 * 알려주는 셈이라 봇과 같은 기준을 쓴다.
 *
 * <p>{@code SecurityConfig} 를 고칠 필요가 없다 — {@code /api/**} 는 {@code anyRequest().authenticated()} 다.
 */
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/billing/methods")
public class BillingController {

    private final BillingService billingService;

    /** GET /api/billing/methods — 카드가 없으면 {@code methods: []}, customerKey 는 항상 온다 */
    @GetMapping
    public ResponseEntity<BillingMethodsResponse> list(@AuthenticationPrincipal UUID userId) {
        return ResponseEntity.ok(billingService.find(userId));
    }

    /**
     * POST /api/billing/methods — 토스 {@code authKey} 를 빌링키로 바꿔 저장하고 <b>목록 전체</b>를 돌려준다.
     *
     * <p>201 + Location 이 아니라 200 + 목록인 이유: 프론트가 등록 직후 카드 목록을 그대로 그려야 하고,
     * 화면에 보이는 카드의 출처를 "이 응답 하나" 로 고정하면 "등록 직후만 다르게 보이는" 버그가 생길 자리가 없다.
     * 5장이 넘으면 <b>409</b>(토스를 부르기 전에 막는다).
     */
    @PostMapping
    public ResponseEntity<BillingMethodsResponse> register(
            @AuthenticationPrincipal UUID userId,
            @Valid @RequestBody RegisterBillingMethodRequest request) {
        return ResponseEntity.ok(billingService.register(userId, request));
    }

    /**
     * DELETE /api/billing/methods/{id} — 카드 한 장 삭제. 성공하면 본문 없이 <b>204</b>.
     *
     * <p>토스 쪽 빌링키도 함께 폐기된다({@code BillingService.delete}). 실패는 {@code GlobalExceptionHandler}
     * 가 공통 포맷으로 — 없거나 남의 것이면 <b>404</b>, 기본 카드인데 다른 카드가 남아 있으면 <b>409</b>,
     * 토스가 죽었거나 응답이 없으면 <b>503</b>(이때 카드는 그대로 남는다).
     */
    @DeleteMapping("/{id}")
    public ResponseEntity<Void> delete(@AuthenticationPrincipal UUID userId, @PathVariable UUID id) {
        billingService.delete(userId, id);
        return ResponseEntity.noContent().build();
    }

    /**
     * PUT /api/billing/methods/{id}/default — 그 카드를 기본(청구에 쓸 카드)으로. <b>목록 전체</b>를 돌려준다.
     *
     * <p>PUT 인 이유: 같은 요청을 몇 번 보내도 결과가 같다(멱등). "기본으로" 버튼 연타가 안전하다는 뜻이다.
     * 이미 기본이면 아무것도 바꾸지 않고 200 이다 — 오류가 아니다.
     */
    @PutMapping("/{id}/default")
    public ResponseEntity<BillingMethodsResponse> setDefault(
            @AuthenticationPrincipal UUID userId, @PathVariable UUID id) {
        return ResponseEntity.ok(billingService.setDefault(userId, id));
    }
}
