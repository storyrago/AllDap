package com.alldap.api.domain.billing.repository;

import com.alldap.api.domain.billing.entity.BillingMethod;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;
import java.util.UUID;

/**
 * <p>🔴 <b>조회 메서드가 {@code findByUserId} 하나뿐인 것이 격리 설계다.</b>
 * {@code findById(cardId)} 로 카드를 찾는 길을 열어두면 "그 다음 소유권을 확인" 하는 코드를
 * 언젠가 빠뜨리게 된다. 이 저장소는 봇에서 같은 규칙을 쓴다 —
 * <b>소유권을 "검사" 하지 않고 조회 쿼리에 못박는다</b>({@code findByIdAndUserId}).
 * 여기서는 계정당 1장이라 {@code userId} 하나로 충분하다.
 */
public interface BillingMethodRepository extends JpaRepository<BillingMethod, UUID> {

    Optional<BillingMethod> findByUserId(UUID userId);
}
