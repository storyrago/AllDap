package com.alldap.api.domain.plan.controller;

import com.alldap.api.domain.plan.dto.ChangePlanRequest;
import com.alldap.api.domain.plan.dto.PlanResponse;
import com.alldap.api.domain.plan.service.PlanService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.UUID;

/**
 * 요금제 API. 인증 필요.
 *
 * <p>🔴 <b>{@code userId} 를 경로·쿼리·본문으로 받지 않는다.</b> {@code @AuthenticationPrincipal}
 * 로만 받는다 — 받으면 남의 id 를 적어 보내는 것만으로 남의 요금제를 바꿀 수 있다.
 * 요금제는 <b>계정</b>에 붙으므로 봇 소유권 검사 같은 것이 필요 없다 — 토큰의 주인 자체가 대상이다.
 *
 * <p>{@code SecurityConfig} 를 고칠 필요가 없다 — {@code /api/**} 는 이미 인증을 요구한다.
 */
@Tag(name = "요금제", description = "무료·Pro 선택. 무엇을 골랐는지만 기억하고 청구는 하지 않는다.")
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/plan")
public class PlanController {

    private final PlanService planService;

    /** GET /api/plan — 지금 요금제. 새 계정은 {@code free} 다(V8 의 DEFAULT). */
    @Operation(summary = "현재 요금제 조회")
    @GetMapping
    public ResponseEntity<PlanResponse> get(@AuthenticationPrincipal UUID userId) {
        return ResponseEntity.ok(planService.find(userId));
    }

    /**
     * PUT /api/plan — 요금제 변경. 바뀐 요금제를 돌려준다.
     *
     * <p>PUT 인 이유: 같은 값을 몇 번 보내도 결과가 같다(멱등). 버튼 연타가 안전하다는 뜻이고,
     * 실제로 같은 요금제를 다시 보내면 아무것도 바꾸지 않고 200 이다 — 오류가 아니다.
     *
     * <p>실패는 {@code GlobalExceptionHandler} 가 공통 포맷으로 — 카드가 없는데 유료로 바꾸려 하면
     * <b>409</b>({@code PLAN_REQUIRES_BILLING_METHOD}), 모르는 요금제 문자열이면 <b>400</b>.
     *
     * <p>🔴 <b>이 호출로 돈이 나가지 않는다.</b> 청구는 4번 조각이고 아직 없다.
     */
    @Operation(summary = "요금제 변경")
    @PutMapping
    public ResponseEntity<PlanResponse> change(@AuthenticationPrincipal UUID userId,
                                               @Valid @RequestBody ChangePlanRequest request) {
        return ResponseEntity.ok(planService.changePlan(userId, request.plan()));
    }
}
