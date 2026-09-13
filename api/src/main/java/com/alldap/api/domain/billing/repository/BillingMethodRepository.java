package com.alldap.api.domain.billing.repository;

import com.alldap.api.domain.billing.entity.BillingMethod;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;
import java.util.Optional;

public interface BillingMethodRepository extends JpaRepository<BillingMethod, Long> {

    /** 등록 순서대로. 화면이 "먼저 등록한 카드가 위" 로 그리고, 순서가 요청마다 바뀌지 않아야 한다. */
    List<BillingMethod> findByUserIdOrderByCreatedAtAsc(Long userId);

    /**
     * 🔴 소유권을 <b>검사하지 않고 쿼리에 못박는다</b> — {@code BotRepository.findByIdAndUserId} 와 같은 방식.
     * {@code findById} 뒤에 {@code if (남의 것) throw} 를 두면 검사를 빠뜨려도 컴파일이 통과한다.
     * 남의 카드는 "없는 카드" 와 같은 결과(404)다. 403 은 그 id 가 존재한다는 것을 알려준다.
     */
    Optional<BillingMethod> findByIdAndUserId(Long id, Long userId);

    long countByUserId(Long userId);

    /**
     * 같은 계정의 기본 카드를 <b>해제</b>한다. 새 기본을 설정하기 <b>전에</b> 불러야 한다 —
     * 순서를 바꾸면 부분 유니크 인덱스(기본 카드 최대 1장)가 새 기본의 UPDATE 를 거부한다.
     *
     * <p>파생 쿼리 이름 대신 JPQL 인 이유: "찾아서 하나씩 false 로" 는 SELECT + UPDATE 두 번이고
     * 그 사이가 벌어진다. 한 문장이면 벌어질 틈이 없다.
     * ⚠️ JPQL 은 영속성 컨텍스트를 <b>우회</b>한다 — 이미 로드된 엔티티의 {@code isDefault} 는 낡은 값이 된다.
     * {@code BillingService.setDefault} 가 그 함정을 피하는 방법을 적어뒀다.
     */
    @Modifying
    @Query("UPDATE BillingMethod m SET m.isDefault = false WHERE m.userId = :userId AND m.isDefault = true")
    int clearDefault(@Param("userId") Long userId);
}
