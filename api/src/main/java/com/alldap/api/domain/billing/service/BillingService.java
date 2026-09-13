package com.alldap.api.domain.billing.service;

import com.alldap.api.domain.billing.client.TossBilling;
import com.alldap.api.domain.billing.client.TossClient;
import com.alldap.api.domain.billing.dto.BillingMethodsResponse;
import com.alldap.api.domain.billing.dto.RegisterBillingMethodRequest;
import com.alldap.api.domain.billing.entity.BillingMethod;
import com.alldap.api.domain.billing.repository.BillingMethodRepository;
import com.alldap.api.domain.plan.Plan;
import com.alldap.api.domain.user.entity.User;
import com.alldap.api.domain.user.repository.UserRepository;
import com.alldap.api.global.crypto.BillingCrypto;
import com.alldap.api.global.exception.ApiException;
import com.alldap.api.global.exception.ErrorCode;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.ZoneId;
import java.util.List;

/**
 * 결제 수단 목록·추가·삭제·기본 지정. <b>계정 단위</b>다 — 봇이 아니라 봇의 주인이 카드를 등록한다.
 * V7(2026-09-08) 부터 <b>계정당 여러 장</b>이고, 그중 <b>기본 카드</b>(청구에 쓸 카드)가 하나다.
 *
 * <p>🔴 <b>토스를 부르는 메서드({@code register}·{@code delete})에는 {@code @Transactional} 을 붙이지 않는다.</b>
 * "DB 읽기(짧음) → 토스 호출(최대 10초) → DB 쓰기(짧음)" 모양인데, 가운데 외부 호출을 트랜잭션에 넣으면
 * 커넥션 풀(기본 10)이 마르고 결제와 무관한 요청까지 전부 멈춘다 — 채팅에서 이미 겪은 모양이다
 * ({@code ChatService}/{@code ChatTurnStore}). 유일한 예외는 {@link #setDefault} — 토스 호출이 없는
 * 유일한 쓰기라 붙여도 된다(붙여야 한다).
 *
 * <p><b>불변식: 카드가 하나라도 있으면 기본 카드가 정확히 하나다.</b> 앱 코드가 지키는 방법은 셋이다 —
 * 첫 카드는 자동 기본({@code register}), 기본 카드는 다른 카드가 남아 있으면 삭제 거부({@code delete}),
 * 기본 지정은 "이전 해제 → 새로 설정" 을 한 트랜잭션에({@code setDefault}). 그리고 <b>마지막 방어선은 DB</b> —
 * V7 의 부분 유니크 인덱스가 "기본 2장" 을 거부한다. 앱 검사는 흔한 경우에 친절한 안내를 주기 위한 것이다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class BillingService {

    /**
     * 계정당 카드 상한. 🔴 <b>근거 없는 숫자다</b> — "무한정 쌓이지 않게" 가 목적이고 5 는 그냥 넉넉한 값이다.
     * 상한이 있어야 하는 진짜 이유는 <b>고아 빌링키</b>다: 등록만 하고 안 지우는 카드가 무한히 쌓이면
     * 토스 쪽에도 그만큼 빌링키가 남는데, 조회 API 가 없어 우리 행을 잃으면 영영 못 지운다.
     */
    static final int MAX_METHODS = 5;

    /**
     * 등록일을 보여줄 시간대. {@code UsageService.BILLING_ZONE} 과 같은 값이다.
     * 공유 상수로 빼지 않은 이유: 쓰는 곳이 두 군데뿐이고, 세 번째가 생기면 그때 뺀다.
     */
    private static final ZoneId BILLING_ZONE = ZoneId.of("Asia/Seoul");

    private final BillingMethodRepository billingMethodRepository;
    private final UserRepository userRepository;
    private final TossClient tossClient;
    private final BillingCrypto billingCrypto;

    /** 카드가 없어도 {@code customerKey} 는 내려간다 — 결제창을 열려면 그게 먼저 필요하다. */
    public BillingMethodsResponse find(Long userId) {
        return new BillingMethodsResponse(billingCustomerKey(userId), cards(userId));
    }

    public BillingMethodsResponse register(Long userId, RegisterBillingMethodRequest request) {
        String customerKey = billingCustomerKey(userId);

        // 🔴 ① 쿼리로 돌아온 customerKey 를 신뢰하지 않는다. 대조만 하고, 토스에는 DB 의 값을 넘긴다.
        //    신뢰하면 남의 customerKey 를 적어 보내는 것만으로 카드가 남에게 붙는다.
        //    userId 를 @AuthenticationPrincipal 로만 받는 규칙과 정확히 같은 이유 —
        //    "출처가 우리가 서명한 토큰인 값만 신뢰한다".
        if (!customerKey.equals(request.customerKey())) {
            log.warn("[결제] customerKey 불일치. userId={}", userId);
            throw new ApiException(ErrorCode.INVALID_INPUT,
                    "카드 등록 정보가 현재 로그인한 계정과 맞지 않습니다. "
                            + "다른 계정으로 결제창을 열었을 수 있습니다. 페이지를 새로고침한 뒤 다시 등록해주세요.");
        }

        // ② 상한 검사는 토스를 부르기 <전에>. 부르고 나서 막으면 이미 발급된 빌링키가
        //    회수 불가능한 고아로 남는다(토스에 조회 API 가 없다). V6 의 "이미 있으면 409" 가 있던 자리다.
        long existing = billingMethodRepository.countByUserId(userId);
        if (existing >= MAX_METHODS) {
            throw new ApiException(ErrorCode.BILLING_METHOD_LIMIT_EXCEEDED);
        }

        // ③ 발급. 실패는 TossClient 안에서 전부 ApiException 으로 바뀌어 나온다.
        TossBilling billing = tossClient.issueBillingKey(request.authKey(), customerKey);

        // ④ 즉시 암호화해 저장한다. 평문 billingKey 는 이 줄 이후로 아무 데도 남지 않는다.
        //    첫 카드는 자동으로 기본이다 — "카드는 있는데 기본이 없는" 상태를 만들지 않기 위해서다.
        //    두 번째부터는 사용자가 지정할 때만 기본이 된다(방금 넣은 카드가 말없이 청구 카드가 되면 놀란다).
        try {
            billingMethodRepository.save(BillingMethod.create(
                    userId, billingCrypto.encrypt(billing.billingKey()),
                    billing.issuerCode(), billing.cardNumberMasked(), existing == 0));
        } catch (DataIntegrityViolationException e) {
            // 부분 유니크 인덱스 충돌 = 동시에 들어온 <첫 등록 둘> 이 둘 다 "기본" 으로 저장하려 했다.
            // ⚠️ 이 경우 방금 발급받은 빌링키는 저장되지 못하고 고아가 된다. 막을 방법이 없어
            //    (조회 API 가 없다) 로그로만 남긴다. 사용자가 등록 버튼을 두 번 눌러야 나는 상황이고,
            //    다시 시도하면 existing == 1 이라 기본이 아닌 카드로 정상 저장된다.
            log.error("[결제] 저장 중 기본 카드 충돌. 방금 발급한 빌링키가 고아로 남는다. userId={}", userId, e);
            throw new ApiException(ErrorCode.BILLING_METHOD_CONFLICT);
        }

        log.info("[결제] 카드 등록 userId={} issuerCode={} default={}", userId, billing.issuerCode(), existing == 0);
        return new BillingMethodsResponse(customerKey, cards(userId));
    }

    /**
     * 카드 삭제. <b>토스 먼저, 우리 나중.</b> {@code @Transactional} 없음. (둘 다 V6 때의 설계 그대로다 —
     * 이유는 이 클래스 javadoc 과 {@code docs/superpowers/specs/2026-09-06-billing-method-design.md})
     *
     * <h2>🔴 유료 요금제의 <b>마지막</b> 카드는 지우지 않는다 (409)</h2>
     * 지우면 "카드 없는 유료 계정" 이 된다. 같은 불변식을 {@code PlanService.changePlan} 이
     * 반대 방향에서도 막는다(카드 0장이면 유료로 못 바꾼다) — <b>한쪽만 막으면 규칙이 없는 것과
     * 같기 때문</b>이다(유료로 바꾼 뒤 카드를 지우면 그만이다).
     * ⚠️ 지금은 청구가 없어 이 상태가 당장 사고를 내지는 않는다. 그럼에도 지금 막는 이유는
     * 4번 조각(청구)이 이 불변식 위에 얹히기 때문이다 — 나중에 넣으면 이미 어긴 계정부터 정리해야 한다.
     *
     * <h2>🔴 기본 카드는 다른 카드가 남아 있으면 지우지 않는다 (409)</h2>
     * 지우면 "카드는 있는데 기본이 없는" 상태가 된다. 대안이었던 <b>자동 승계</b>(가장 최근 카드를 기본으로)는
     * 토스 호출 <b>뒤에</b> DB 쓰기가 두 번(삭제 + 승계)이 되어 그 둘을 묶을 트랜잭션이 필요해진다 —
     * 그런데 이 메서드는 토스 호출 때문에 트랜잭션을 일부러 안 쓴다. 거부는 {@code if} 한 줄이고,
     * 사용자에게 "다른 카드를 기본으로 지정한 뒤 삭제하라" 고 명시적으로 말한다.
     * 마지막 한 장은 기본이어도 지운다 — 남는 카드가 없으니 불변식이 깨지지 않는다.
     *
     * <h2>순서를 뒤집으면 안 되는 이유 (V6 그대로)</h2>
     * 우리 행을 먼저 지우고 토스 호출이 실패하면 그 빌링키는 <b>영영 폐기할 수 없는 고아</b>가 된다 —
     * 토스에 빌링키 조회 API 가 없어 우리 DB 가 유일한 사본이다. 반대 순서의 최악은
     * "행이 남아 사용자가 버튼을 다시 누른다" 뿐이다. 자기 치유는 토스가 404 를 줄 때만 성립한다
     * ({@link TossClient#deleteBillingKey}).
     */
    public void delete(Long userId, Long methodId) {
        // 소유권은 쿼리에 못박혀 있다 — 남의 카드는 "없는 카드" 와 같은 404 다.
        BillingMethod method = billingMethodRepository.findByIdAndUserId(methodId, userId)
                .orElseThrow(() -> new ApiException(ErrorCode.BILLING_METHOD_NOT_FOUND));

        // 두 검사 모두 토스를 부르기 <전에> 끝난다. 부른 뒤 거부하면 토스 쪽 빌링키만 폐기되고
        // 우리 행은 남는 최악의 불일치가 난다.
        long owned = billingMethodRepository.countByUserId(userId);

        if (owned == 1 && planOf(userId).isPaid()) {
            throw new ApiException(ErrorCode.BILLING_METHOD_REQUIRED_BY_PLAN);
        }
        if (method.isDefault() && owned > 1) {
            throw new ApiException(ErrorCode.BILLING_DEFAULT_METHOD_IN_USE);
        }

        // 복호화는 토스를 부르기 <전에> 한다. 여기서 실패하면(암호화 키 분실·행 손상) 토스도 안 부르고
        // 행도 안 지운다. 사용자에게는 500 이 나가지만, "지울 수 없는 키를 모르는 채 행만 지우는" 것보다 낫다.
        tossClient.deleteBillingKey(billingCrypto.decrypt(method.getBillingKeyEnc()));

        billingMethodRepository.delete(method);

        // 🔴 빌링키도 customerKey 도 로그에 남기지 않는다. 우리 DB 가 유일한 사본이라는 말은
        //    <로그로 새면 그것도 사본이 된다>는 뜻이다. userId 와 카드 id 면 추적에 충분하다.
        log.info("[결제] 결제 수단 삭제 userId={} methodId={}", userId, methodId);
    }

    /**
     * 기본 카드 변경. 이 클래스에서 <b>유일하게 {@code @Transactional}</b> 인 메서드다 — 토스를 부르지 않고
     * DB 쓰기가 둘(이전 해제 · 새로 설정)이라, 둘 사이에서 죽으면 "기본 카드 0장" 이 남는다.
     *
     * <p><b>두 문장인 이유.</b> 한 문장 {@code SET is_default = (id = :id) WHERE user_id = :userId} 가 더 짧지만,
     * 부분 유니크 인덱스는 <b>행 단위로 즉시</b> 검사되므로 새 기본 행이 이전 기본 행보다 먼저 처리되면
     * 그 순간 "기본 2장" 이 되어 터진다. 순서는 물리 저장 순서라 우리가 정할 수 없다.
     * 해제(JPQL) → 설정(더티체킹, 커밋 시 UPDATE) 으로 나누면 순서가 확정된다.
     *
     * <p><b>이미 기본이면 아무것도 안 한다.</b> 성능이 아니라 <b>정확성</b> 때문이다 — {@code clearDefault} 는
     * JPQL 이라 영속성 컨텍스트를 우회한다. 이미 로드된 {@code method} 의 {@code isDefault} 는 {@code true}
     * 로 남아 있고, {@code markDefault()} 는 값을 바꾸지 않으니 더티체킹이 UPDATE 를 안 만든다.
     * 결과: DB 에서는 해제됐는데 되돌리는 UPDATE 가 안 나가 <b>기본 카드가 0장</b>이 된다. 그래서 먼저 돌려보낸다.
     */
    @Transactional
    public BillingMethodsResponse setDefault(Long userId, Long methodId) {
        BillingMethod method = billingMethodRepository.findByIdAndUserId(methodId, userId)
                .orElseThrow(() -> new ApiException(ErrorCode.BILLING_METHOD_NOT_FOUND));

        if (!method.isDefault()) {
            billingMethodRepository.clearDefault(userId);
            method.markDefault();
            log.info("[결제] 기본 카드 변경 userId={} methodId={}", userId, methodId);
        }
        return new BillingMethodsResponse(billingCustomerKey(userId), cards(userId));
    }

    private List<BillingMethodsResponse.Card> cards(Long userId) {
        return billingMethodRepository.findByUserIdOrderByCreatedAtAsc(userId).stream()
                .map(this::toCard)
                .toList();
    }

    private BillingMethodsResponse.Card toCard(BillingMethod method) {
        return new BillingMethodsResponse.Card(
                method.getId(),
                method.getIssuerCode(),
                CardIssuer.nameOf(method.getIssuerCode()),
                method.getCardNumberMasked(),
                // UsageService 가 기간 경계를 KST 로 내려주는 것과 같은 방식이다.
                method.getCreatedAt().atZone(BILLING_ZONE).toOffsetDateTime(),
                method.isDefault());
    }

    /**
     * 이 계정의 요금제. 카드 삭제를 막을지 판단하는 데만 쓴다.
     * ⚠️ 계정이 그 사이 지워졌다면 {@code INVALID_TOKEN} 이 아니라 <b>무료로 본다</b> —
     * 여기서 예외를 던지면 "카드를 지우려 했더니 토큰이 이상하다" 는 엉뚱한 안내가 나가고,
     * 어차피 바로 아래에서 토스 호출과 행 삭제가 이어져 계정 유무는 그 경로가 판단한다.
     */
    private Plan planOf(Long userId) {
        return userRepository.findById(userId).map(User::getPlan).orElse(Plan.FREE);
    }

    private String billingCustomerKey(Long userId) {
        // 토큰은 유효한데 그 사이 계정이 지워진 경우를 여기서 거른다 —
        // BotService.createBot 이 getReferenceById 대신 findById 를 쓰는 것과 같은 이유다.
        return userRepository.findById(userId)
                .orElseThrow(() -> new ApiException(ErrorCode.INVALID_TOKEN))
                .getBillingCustomerKey();
    }
}
