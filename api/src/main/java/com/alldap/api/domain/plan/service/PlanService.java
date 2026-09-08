package com.alldap.api.domain.plan.service;

import com.alldap.api.domain.billing.repository.BillingMethodRepository;
import com.alldap.api.domain.plan.Plan;
import com.alldap.api.domain.plan.dto.PlanResponse;
import com.alldap.api.domain.user.entity.User;
import com.alldap.api.domain.user.repository.UserRepository;
import com.alldap.api.global.exception.ApiException;
import com.alldap.api.global.exception.ErrorCode;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.UUID;

/**
 * 계정의 요금제 조회·변경. 요금제 연동 4조각 중 <b>2번</b>이다.
 *
 * <p>🔴 <b>여기서 돈이 나가지 않는다.</b> 이 서비스가 하는 일은 {@code users.plan} 한 칸을
 * 읽고 쓰는 것이 전부다. 청구는 4번 조각이고 아직 없다 — 화면도 그렇게 안내한다.
 * 그래서 이 클래스에는 토스 호출이 없고, {@code BillingService} 와 달리
 * {@code @Transactional} 을 붙여도 안전하다(외부 호출이 트랜잭션 안에 들어갈 일이 없다).
 *
 * <h2>지키는 불변식 하나: 유료 요금제에는 카드가 있어야 한다</h2>
 * 두 방향 모두에서 막는다.
 * <ul>
 *   <li><b>여기</b>({@link #changePlan}) — 카드가 0장이면 유료로 못 바꾼다</li>
 *   <li>{@code BillingService.delete} — 유료 상태에서 <b>마지막</b> 카드는 못 지운다</li>
 * </ul>
 * 🔴 <b>한쪽만 막으면 그 규칙은 없는 것과 같다.</b> 유료로 바꿀 때만 검사하면, 바꾼 뒤 카드를
 * 지워서 "카드 없는 유료 계정" 을 만들 수 있다. 이 저장소가 반복해 낸 부류의 실수를
 * (한 사실을 두 자리에서 다르게 다루는 것) 여기서 되풀이하지 않으려고 양쪽에 둔다.
 *
 * <p>⚠️ <b>지금은 이 규칙에 실질적 효력이 없다</b> — 청구가 없으니 "카드 없는 유료 계정" 이
 * 당장 사고를 내지는 않는다. 그럼에도 지금 넣는 이유는 4번 조각이 이 불변식 위에 얹히기 때문이다.
 * 나중에 넣으면 <b>이미 규칙을 어긴 계정들</b>을 먼저 정리해야 한다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class PlanService {

    private final UserRepository userRepository;
    private final BillingMethodRepository billingMethodRepository;

    @Transactional(readOnly = true)
    public PlanResponse find(UUID userId) {
        return new PlanResponse(user(userId).getPlan());
    }

    /**
     * 요금제 변경. 같은 요금제로 다시 바꿔도 200 이다 — PUT 이라 멱등해야 하고,
     * 사용자가 "Pro" 를 두 번 눌렀다고 오류를 보여줄 이유가 없다.
     */
    @Transactional
    public PlanResponse changePlan(UUID userId, Plan plan) {
        User user = user(userId);

        // 🔴 카드 검사는 <바꾸기 전에>. 순서를 바꾸면 "요금제는 유료가 됐는데 카드가 없다" 는
        //    상태가 잠깐이라도 커밋될 수 있다(예외가 나도 롤백되지만, 검사를 뒤에 두는 코드는
        //    다음 사람이 트랜잭션을 떼는 순간 조용히 깨진다).
        if (plan.isPaid() && billingMethodRepository.countByUserId(userId) == 0) {
            throw new ApiException(ErrorCode.PLAN_REQUIRES_BILLING_METHOD);
        }

        user.changePlan(plan);
        log.info("[요금제] 변경 userId={} plan={}", userId, plan.code());
        return new PlanResponse(plan);
    }

    private User user(UUID userId) {
        // 토큰은 유효한데 그 사이 계정이 지워진 경우를 여기서 거른다 —
        // BillingService.billingCustomerKey 와 같은 이유다.
        return userRepository.findById(userId)
                .orElseThrow(() -> new ApiException(ErrorCode.INVALID_TOKEN));
    }
}
