package com.alldap.api.domain.usage.controller;

import com.alldap.api.domain.usage.dto.UsageResponse;
import com.alldap.api.domain.usage.service.UsageService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.UUID;

/**
 * 사용량 API. 인증 필요.
 *
 * <p>🔴 <b>{@code userId} 를 쿼리 파라미터로 받지 않는다.</b> {@code @AuthenticationPrincipal} 로만
 * 받는다 — 파라미터로 받으면 남의 id 를 적어 보내는 것만으로 남의 청구 내역을 볼 수 있다.
 * 봇 소유권 검사가 필요 없는 이유도 같다: 조회 자체가 <b>토큰의 주인</b>으로 좁혀져 있다.
 *
 * <p>{@code SecurityConfig} 를 고칠 필요가 없다 — 공개 경로는 {@code /api/auth/signup} ·
 * {@code /api/auth/login} · {@code /api/w/**} · {@code /actuator/health} · {@code /widget/**}
 * 뿐이고, 나머지 {@code /api/**}(이 컨트롤러 포함)는 {@code anyRequest().authenticated()} 로
 * 이미 인증을 요구한다.
 */
@RestController
@RequiredArgsConstructor
public class UsageController {

    private final UsageService usageService;

    /** GET /api/usage?month=YYYY-MM — 생략하면 이번 달(한국 시간 기준) */
    @GetMapping("/api/usage")
    public ResponseEntity<UsageResponse> getUsage(@AuthenticationPrincipal UUID userId,
                                                  @RequestParam(required = false) String month) {
        return ResponseEntity.ok(usageService.findUsage(userId, month));
    }
}
