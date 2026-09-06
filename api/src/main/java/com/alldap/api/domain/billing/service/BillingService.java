package com.alldap.api.domain.billing.service;

import com.alldap.api.domain.billing.client.TossBilling;
import com.alldap.api.domain.billing.client.TossClient;
import com.alldap.api.domain.billing.dto.BillingMethodResponse;
import com.alldap.api.domain.billing.dto.RegisterBillingMethodRequest;
import com.alldap.api.domain.billing.entity.BillingMethod;
import com.alldap.api.domain.billing.repository.BillingMethodRepository;
import com.alldap.api.domain.user.repository.UserRepository;
import com.alldap.api.global.crypto.BillingCrypto;
import com.alldap.api.global.exception.ApiException;
import com.alldap.api.global.exception.ErrorCode;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;

import java.time.ZoneId;
import java.util.UUID;

/**
 * 결제 수단 등록·조회. <b>계정 단위</b>다 — 봇이 아니라 봇의 주인이 카드를 등록한다.
 *
 * <p>🔴 <b>{@code @Transactional} 을 붙이지 않는 것이 의도다.</b>
 * {@code register} 는 "DB 읽기(짧음) → 토스 호출(최대 10초) → DB 쓰기(짧음)" 모양인데,
 * 이 저장소는 정확히 같은 모양을 채팅에서 이미 겪었다 —
 * <b>가운데 외부 호출을 트랜잭션에 넣으면 커넥션 풀(기본 10)이 마르고,
 * 결제와 무관한 요청까지 전부 멈춘다.</b> 토스 하나가 느려진 것이 서비스 전체 장애가 된다.
 * ({@code ChatService}/{@code ChatTurnStore} 가 그래서 나뉘어 있다)
 *
 * <p>트랜잭션이 없어 생기는 구멍은 하나뿐이다 — 아래 "이미 있는지" 검사와 INSERT 사이에
 * 같은 사용자의 요청이 둘 동시에 들어오는 경우. 그건 <b>DB 의 {@code UNIQUE(user_id)}</b> 가 막고,
 * 그때 나오는 {@link DataIntegrityViolationException} 을 409 로 바꾼다.
 * 애플리케이션 검사는 "흔한 경우에 친절한 안내를 주기 위한 것" 이고 <b>마지막 방어선은 DB</b> 다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class BillingService {

    /**
     * 등록일을 보여줄 시간대. {@code UsageService.BILLING_ZONE} 과 같은 값이다.
     *
     * <p>상수를 공유 클래스로 빼지 않은 이유: 쓰는 곳이 두 군데뿐이고,
     * 그걸 위해 파일을 하나 더 만들면 "어디서 가져오는가" 를 찾는 비용이 중복보다 크다.
     * 세 번째 사용처가 생기면 그때 뺀다.
     */
    private static final ZoneId BILLING_ZONE = ZoneId.of("Asia/Seoul");

    private final BillingMethodRepository billingMethodRepository;
    private final UserRepository userRepository;
    private final TossClient tossClient;
    private final BillingCrypto billingCrypto;

    /** 카드가 없어도 {@code customerKey} 는 내려간다 — 결제창을 열려면 그게 먼저 필요하다. */
    public BillingMethodResponse find(UUID userId) {
        String customerKey = billingCustomerKey(userId);
        return new BillingMethodResponse(customerKey,
                billingMethodRepository.findByUserId(userId).map(this::toCard).orElse(null));
    }

    public BillingMethodResponse register(UUID userId, RegisterBillingMethodRequest request) {
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

        // ② 토스를 부르기 <전에> 중복을 막는다. 부르고 나서 막으면 이미 발급된 빌링키가
        //    회수 불가능한 고아로 남는다(토스에 조회 API 가 없다).
        if (billingMethodRepository.findByUserId(userId).isPresent()) {
            throw new ApiException(ErrorCode.BILLING_METHOD_ALREADY_EXISTS);
        }

        // ③ 발급. 실패는 TossClient 안에서 전부 ApiException 으로 바뀌어 나온다.
        TossBilling billing = tossClient.issueBillingKey(request.authKey(), customerKey);

        // ④ 즉시 암호화해 저장한다. 평문 billingKey 는 이 줄 이후로 아무 데도 남지 않는다.
        BillingMethod saved;
        try {
            saved = billingMethodRepository.save(BillingMethod.create(
                    userId, billingCrypto.encrypt(billing.billingKey()),
                    billing.issuerCode(), billing.cardNumberMasked()));
        } catch (DataIntegrityViolationException e) {
            // UNIQUE(user_id) 충돌 = 그 사이 다른 요청이 먼저 등록했다.
            // ⚠️ 이 경우 방금 발급받은 빌링키는 저장되지 못하고 고아가 된다. 막을 방법이 없어
            //    (조회 API 가 없다) 로그로만 남긴다. 사용자가 등록 버튼을 두 번 눌러야 나는 상황이다.
            log.error("[결제] 저장 중 중복 충돌. 방금 발급한 빌링키가 고아로 남는다. userId={}", userId, e);
            throw new ApiException(ErrorCode.BILLING_METHOD_ALREADY_EXISTS);
        }

        log.info("[결제] 카드 등록 userId={} issuerCode={}", userId, billing.issuerCode());
        return new BillingMethodResponse(customerKey, toCard(saved));
    }

    private BillingMethodResponse.Card toCard(BillingMethod method) {
        return new BillingMethodResponse.Card(
                CardIssuer.nameOf(method.getIssuerCode()),
                method.getCardNumberMasked(),
                // UsageService 가 기간 경계를 KST 로 내려주는 것과 같은 방식이다.
                method.getCreatedAt().atZone(BILLING_ZONE).toOffsetDateTime());
    }

    private String billingCustomerKey(UUID userId) {
        // 토큰은 유효한데 그 사이 계정이 지워진 경우를 여기서 거른다 —
        // BotService.createBot 이 getReferenceById 대신 findById 를 쓰는 것과 같은 이유다.
        return userRepository.findById(userId)
                .orElseThrow(() -> new ApiException(ErrorCode.INVALID_TOKEN))
                .getBillingCustomerKey();
    }

    /**
     * 결제 수단 삭제. <b>토스 먼저, 우리 나중.</b>
     *
     * <h2>🔴 순서를 뒤집으면 안 되는 이유</h2>
     * 우리 행을 먼저 지우고 토스 호출이 실패하면, 그 빌링키는 <b>영영 폐기할 수 없는 고아</b>가 된다.
     * 토스에는 <b>빌링키를 조회하는 API 가 없다</b>(문서 원문: "발급된 빌링키를 조회하는 API는
     * 제공되지 않습니다"). 우리 DB 가 그 키의 유일한 사본이므로, 지우는 순간 우리도 토스도
     * 아무도 그 키를 모른다.
     * <p>반대 순서의 최악은 "행이 남아 사용자가 버튼을 다시 누른다" 뿐이다. 비대칭이 크다.
     *
     * <h2>{@code @Transactional} 을 붙이지 않는다</h2>
     * 붙이면 토스 호출이 끝날 때까지 DB 커넥션 하나가 묶인다 — 기본 풀이 10 이라
     * 결제 화면 몇 개가 <b>채팅까지 멈춘다.</b> {@code ChatTurnStore} 가 별도 빈까지 만들어 푼 문제가 이것이다.
     *
     * <p><b>다만 여기는 그런 분리가 필요 없다.</b> 채팅은 긴 호출 <b>양옆에</b> DB 작업이 있어
     * "각각 짧은 트랜잭션 두 개"가 필요했고, 같은 클래스 안에서 자기 메서드를 부르면 프록시를 안 거쳐
     * 트랜잭션이 조용히 사라지므로 빈을 나눠야 했다. 삭제는 <b>조회 1번 · 삭제 1번</b>이고
     * 둘이 같은 트랜잭션일 이유가 없다. 스프링 데이터 JPA 의 리포지토리 메서드는 각자 자기 트랜잭션을
     * 열고 닫으므로, <b>아무것도 안 붙이는 것이 곧 "짧은 트랜잭션 두 개"</b>다.
     * {@code DocumentService.delete}(조회 → 외부 호출)와 같은 모양이다.
     *
     * <p>대가는 원자성이다. 토스가 200 을 준 뒤 우리 DELETE 전에 프로세스가 죽으면
     * <b>죽은 키를 가진 행</b>이 남는다. 이 상태가 스스로 낫는지는 <b>토스가 무슨 코드를 주느냐에
     * 달려 있다</b>. 사용자가 다시 삭제를 누르면 토스는 이미 없는 빌링키를 보고 <b>404</b> 를 줄
     * 것이고, {@code TossClient} 는 <b>404 만</b> "이미 없다"로 보고 행을 지운다 — 그러면 자기 치유가
     * 성립한다. <b>404 가 아닌 다른 코드(401·429 등)가 오면 성립하지 않는다</b> — {@code TossClient}
     * 는 그런 코드를 "모른다"로 보고 행을 그대로 남긴다({@link TossClient#deleteBillingKey} 의 javadoc
     * 참고). 이건 완화되지 않은 <b>알려진 한계</b>다({@code docs/decisions.md} 와 설계 문서에 적어뒀다).
     */
    public void delete(UUID userId) {
        // 없는 것과 남의 것을 구분할 필요가 없다 — 조회 자체가 토큰 주인으로 좁혀져 있어
        // "남의 결제 수단" 이라는 경우가 애초에 이 쿼리에 걸리지 않는다.
        BillingMethod method = billingMethodRepository.findByUserId(userId)
                .orElseThrow(() -> new ApiException(ErrorCode.BILLING_METHOD_NOT_FOUND));

        // 복호화는 토스를 부르기 <전에> 한다. 여기서 실패하면(암호화 키 분실·행 손상) 토스도 안 부르고
        // 행도 안 지운다. 사용자에게는 500 이 나가지만, "지울 수 없는 키를 모르는 채 행만 지우는" 것보다 낫다.
        tossClient.deleteBillingKey(billingCrypto.decrypt(method.getBillingKeyEnc()));

        billingMethodRepository.delete(method);

        // 🔴 빌링키도 customerKey 도 로그에 남기지 않는다. 우리 DB 가 유일한 사본이라는 말은
        //    <로그로 새면 그것도 사본이 된다>는 뜻이다. userId 하나면 추적에 충분하다.
        log.info("[결제] 결제 수단 삭제 userId={}", userId);
    }
}
