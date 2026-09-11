package com.alldap.api.domain.billing;

import com.alldap.api.domain.auth.dto.SignupRequest;
import com.alldap.api.domain.user.repository.UserRepository;
import com.alldap.api.support.IntegrationTest;
import com.alldap.api.support.TossStub;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.client.EntityExchangeResult;
import org.springframework.test.web.servlet.client.RestTestClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 결제 수단 통합 테스트 — 목록·추가·삭제·기본 지정. V7(2026-09-08) 부터 <b>계정당 여러 장</b>이다.
 *
 * <p><b>여기서 지키려는 주장은 여섯 개다.</b> 나머지는 배관이다.
 * <ul>
 *   <li>DB 에 <b>평문 빌링키가 없다</b> — 이 조각의 존재 이유</li>
 *   <li>어떤 응답 본문에도 <b>빌링키가 없다</b> — DTO 에 필드를 두지 않은 것의 실증</li>
 *   <li>쿼리로 온 {@code customerKey} 를 <b>신뢰하지 않는다</b> — 신뢰하면 남의 계정에 카드가 붙는다</li>
 *   <li>연결이 끊기면 <b>같은 멱등키로</b> 재시도한다 — 다른 키로 재시도하면 회수 불가능한 고아가 하나 더 는다</li>
 *   <li><b>카드가 있으면 기본 카드가 정확히 하나</b>다 — 첫 등록·기본 변경·삭제 어느 경로로도 깨지지 않는다</li>
 *   <li><b>남의 카드 id 로는 아무것도 못 한다</b> — 404 이고, 토스에 요청이 <b>가지 않는다</b></li>
 * </ul>
 *
 * <p>진짜 톰캣 + 진짜 PostgreSQL + {@link TossStub}(진짜 HTTP) 위에서 돈다.
 * Mockito 로 {@code TossClient} 를 흉내내면 "우리가 상상한 예외" 만 검증하게 된다 —
 * 이 저장소는 <b>통합 테스트 71건이 전부 초록불인 상태에서</b> HTTP/2 업그레이드 버그와
 * iframe Origin 버그를 놓친 적이 있다. HTTP 경계는 HTTP 로만 검증된다.
 */
@IntegrationTest
@DisplayName("결제 수단 통합 테스트")
class BillingIntegrationTest {

    private static final String PASSWORD = "correct-password-1234";
    private static final String METHODS = "/api/billing/methods";

    /** 토스가 돌려주는 빌링키. 이 문자열이 DB·응답 어디에도 <그대로> 나오면 안 된다. */
    private static final String 빌링키 = "iQ4y9sTrKp2mBillingKeySecret0001";

    /**
     * 토스 발급 성공 응답. <b>일부러 우리 DTO 에 없는 필드를 잔뜩 넣었다</b> —
     * {@code mId}·{@code method}·{@code authenticatedAt}·{@code card.cardType} 등.
     * 토스 문서가 "하위호환을 위해 모르는 필드는 무시하라" 고 권고하므로, 그게 실제로
     * 되는지를 테스트가 못박는다. (Jackson 3 은 FAIL_ON_UNKNOWN_PROPERTIES 가 기본 off 다)
     *
     * <p>⚠️ {@code cardCompany}·{@code cardNumber} 는 <b>일부러 넣지 않았다.</b>
     * 2024-06-01 버전부터 응답에서 제거된 필드라, 그걸 읽는 코드는 운영에서 NPE 가 난다.
     */
    private static final String 발급성공 = """
            {"mId":"tosspayments","customerKey":"%s","authenticatedAt":"2026-09-06T14:03:11+09:00",
             "method":"카드","billingKey":"%s",
             "card":{"issuerCode":"61","acquirerCode":"61","number":"43301234****123*",
                     "cardType":"신용","ownerType":"개인"}}""";

    /** 카드를 여러 장 등록하는 검사용 — 발급사·번호를 바꿔 <어느 카드인지> 응답에서 구별할 수 있게. */
    private static final String 발급성공_카드 = """
            {"billingKey":"%s","card":{"issuerCode":"%s","number":"%s"}}""";

    /** 토스 v1 에러 본문. {@code {"code","message","data"}} 모양이다. */
    private static final String 발급거절 = """
            {"code":"INVALID_CARD_EXPIRATION",
             "message":"카드 유효기간이 올바르지 않습니다.","data":null}""";

    // ── 삭제 검사 전용 ──────────────────────────────────────────────────

    /**
     * 삭제 검사 전용 발급 응답. <b>빌링키에 {@code /} 와 {@code +} 가 든 것이 의도</b>다 —
     * 토스의 빌링키는 base64 라 실제로 이 문자들이 온다(문서 예시를 그대로 옮겼다).
     * 평범한 영숫자 키로만 검사하면 경로를 만드는 코드가 이 문자들에서 터져도 드러나지 않는다.
     */
    private static final String 빌링키_BASE64 = "IuLQlvcbmS/5jVDkbnRnAmCn88YZLfnGpVBGpLJ+abU=";

    private static final String 발급응답_BASE64키 = """
            {"billingKey":"IuLQlvcbmS/5jVDkbnRnAmCn88YZLfnGpVBGpLJ+abU=",
             "card":{"issuerCode":"61","number":"43301234****123*"}}""";

    /** 토스의 오류 본문 모양은 {@code {code, message}} 두 필드다. */
    private static final String 토스_4xx =
            """
            {"code":"NOT_FOUND_BILLING_KEY","message":"존재하지 않는 빌링키 입니다."}""";

    private static final String 토스_5xx =
            """
            {"code":"FAILED_INTERNAL_SYSTEM_PROCESSING","message":"내부 시스템 처리 작업이 실패했습니다."}""";

    @LocalServerPort
    private int port;

    @Autowired
    private UserRepository userRepository;

    @Autowired
    private TossStub tossStub;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    private RestTestClient client;
    private String ownerToken;
    private UUID userId;
    private String customerKey;

    @BeforeEach
    void setUp() {
        client = RestTestClient.bindToServer().baseUrl("http://localhost:" + port).build();

        // billing_methods 는 ON DELETE CASCADE 라 이 한 줄로 함께 지워진다.
        userRepository.deleteAll();

        // ⚠️ 스텁 정리를 빠뜨리면 "실행 순서에 따라 나타났다 사라지는" 실패가 난다.
        //    이 저장소가 AiServiceStub 에서 이미 두 번 겪은 부류다.
        tossStub.reset();

        ownerToken = signup("owner@example.com");
        userId = userRepository.findByEmail("owner@example.com").orElseThrow().getId();
        customerKey = customerKeyOf(userId);
    }

    // ── 등록 ─────────────────────────────────────────────────────────────

    @Test
    @DisplayName("[결제] 카드를 등록하면 카드사 이름·마스킹 번호·등록일이 목록으로 돌아온다")
    void 카드_등록_성공() {
        tossStub.enqueue(200, 발급성공.formatted(customerKey, 빌링키));

        Response 응답 = post(ownerToken, customerKey, "auth-key-1");

        assertThat(응답.status()).isEqualTo(200);
        JsonNode json = 응답.json();
        assertThat(json.path("customerKey").asString()).isEqualTo(customerKey);
        JsonNode 카드 = json.path("methods").get(0);
        assertThat(카드.path("id").asString()).isNotBlank();
        // issuerCode "61" → "현대". 코드→이름 변환이 Spring 책임이라는 것을 여기서 못박는다.
        assertThat(카드.path("issuerName").asString()).isEqualTo("현대");
        // 코드도 <함께> 내려간다. 프론트가 카드 면 색을 고르는 키다(web/lib/cardBrand.ts) —
        // 이름을 키로 쓰면 문구를 다듬는 순간 색이 조용히 사라진다.
        assertThat(카드.path("issuerCode").asString()).isEqualTo("61");
        assertThat(카드.path("cardNumberMasked").asString()).isEqualTo("43301234****123*");
        // KST 오프셋으로 직렬화된다 — UsageResponse.periodStart 와 같은 규칙이다.
        assertThat(카드.path("registeredAt").asString()).endsWith("+09:00");
        // 🔴 필드 이름이 "isDefault" 다. record 접근자가 isDefault() 라 Jackson 빈 규칙으로는 "default" 가
        //    될 수 있어 @JsonProperty 로 못박았다 — 프론트 types.ts 가 isDefault 를 전제한다.
        assertThat(카드.has("isDefault")).isTrue();

        // 우리가 실제로 보낸 요청도 확인한다. 헤더는 소문자로 정규화돼 있다.
        List<TossStub.Recorded> 보낸것 = tossStub.received();
        assertThat(보낸것).hasSize(1);
        assertThat(보낸것.getFirst().path()).isEqualTo("/v1/billing/authorizations/issue");
        assertThat(보낸것.getFirst().body()).contains(customerKey).contains("auth-key-1");
        assertThat(보낸것.getFirst().header("idempotency-key")).isNotBlank();
        // Basic base64(secretKey + ":") — 콜론이 빠지면 토스가 INCORRECT_BASIC_AUTH_FORMAT 을 준다.
        String 인증 = 보낸것.getFirst().header("authorization");
        assertThat(인증).startsWith("Basic ");
        assertThat(new String(Base64.getDecoder().decode(인증.substring(6)), StandardCharsets.UTF_8))
                .endsWith(":");
    }

    @Test
    @DisplayName("[결제] DB 에 평문 빌링키가 저장되지 않는다 (이 조각의 존재 이유)")
    void 저장된_빌링키는_평문이_아니다() {
        tossStub.enqueue(200, 발급성공.formatted(customerKey, 빌링키));
        post(ownerToken, customerKey, "auth-key-1");

        String 저장값 = jdbcTemplate.queryForObject(
                "SELECT billing_key_enc FROM billing_methods WHERE user_id = ?", String.class, userId);

        assertThat(저장값).isNotBlank().doesNotContain(빌링키);
        // 🔴 Base64 를 한 번 풀어서도 확인한다. 인코딩만 해두고 "암호화했다" 고 부르는 사고를 막는다.
        assertThat(new String(Base64.getDecoder().decode(저장값), StandardCharsets.UTF_8))
                .doesNotContain(빌링키);
    }

    @Test
    @DisplayName("[결제] 어떤 응답 본문에도 빌링키가 실리지 않는다")
    void 응답에는_빌링키가_없다() {
        tossStub.enqueue(200, 발급성공.formatted(customerKey, 빌링키));

        assertThat(post(ownerToken, customerKey, "auth-key-1").body()).doesNotContain(빌링키);
        assertThat(get(ownerToken).body()).doesNotContain(빌링키);
    }

    @Test
    @DisplayName("[보안] 남의 customerKey 를 실어 보내면 400 이고 토스를 부르지 않는다")
    void 남의_customerKey_는_거부한다() {
        String 남의키 = customerKeyOf(userRepository.findByEmail(signupAndReturnEmail()).orElseThrow().getId());

        Response 응답 = post(ownerToken, 남의키, "auth-key-1");

        assertThat(응답.status()).isEqualTo(400);
        assertThat(응답.json().path("error").path("code").asString()).isEqualTo("INVALID_INPUT");
        // 🔴 "400 이 났다" 가 아니라 <요청이 토스까지 가지 않았다> 를 확인한다.
        //    소유권 판단이 외부 호출 <전에> 끝나야 한다는 이 저장소의 규칙 그대로다.
        assertThat(tossStub.received()).isEmpty();
    }

    @Test
    @DisplayName("[결제] 토스가 카드를 거절하면 400 이고 토스의 한국어 문구가 그대로 실린다")
    void 토스가_거절하면_400_에_토스_메시지가_실린다() {
        tossStub.enqueue(400, 발급거절);

        Response 응답 = post(ownerToken, customerKey, "auth-key-1");

        assertThat(응답.status()).isEqualTo(400);
        assertThat(응답.json().path("error").path("code").asString()).isEqualTo("BILLING_AUTH_FAILED");
        // 🔴 우리 기본 문구로 뭉개면 사용자가 <다음에 뭘 해야 하는지> 를 잃는다.
        //    문서 업로드에서 Python 의 ParseError 문구를 그대로 내려보내는 것과 같은 규칙이다.
        assertThat(응답.json().path("error").path("message").asString())
                .isEqualTo("카드 유효기간이 올바르지 않습니다.");
    }

    @Test
    @DisplayName("[결제] 토스가 5xx 면 503 이고 재시도하지 않는다")
    void 토스가_5xx_면_503() {
        tossStub.enqueue(500, "{\"code\":\"FAILED_INTERNAL_SYSTEM_PROCESSING\",\"message\":\"내부 오류\"}");

        Response 응답 = post(ownerToken, customerKey, "auth-key-1");

        assertThat(응답.status()).isEqualTo(503);
        assertThat(응답.json().path("error").path("code").asString())
                .isEqualTo("BILLING_PROVIDER_UNAVAILABLE");
        // 🔴 5xx 는 <토스가 응답했다> = 요청이 도달했다는 뜻이다. 발급이 됐을 수도 있으므로
        //    자동으로 다시 보내지 않는다. 재시도는 I/O 실패에만 한다(아래 테스트).
        assertThat(tossStub.received()).hasSize(1);
    }

    @Test
    @DisplayName("[결제] 토스가 발급에서 429(레이트리밋) 면 503 이다 — 카드 문제가 아니라 우리 잘못이다")
    void 발급에서_429_면_503() {
        tossStub.enqueue(429, "{\"code\":\"REJECT_CARD_PAYMENT\",\"message\":\"요청이 일시적으로 많습니다.\"}");

        Response 응답 = post(ownerToken, customerKey, "auth-key-1");

        // 🔴 고치기 전에는 401 만 따로 뗐고 429 는 <그 밖의 4xx> 로 떨어져 400 BILLING_AUTH_FAILED
        //    ("카드 정보를 확인해주세요")가 나갔다 — 사용자가 손쓸 수 없는 레이트리밋을 카드 탓으로 돌린 것이다.
        //    같은 429 가 삭제 경로(TossClient.deleteBillingKey)에서는 이미 503 이다. 발급도 같은 기준을 따른다.
        assertThat(응답.status()).isEqualTo(503);
        assertThat(응답.json().path("error").path("code").asString())
                .isEqualTo("BILLING_PROVIDER_UNAVAILABLE");
        assertThat(tossStub.received()).hasSize(1);
    }

    @Test
    @DisplayName("[결제] 연결이 끊기면 <같은 멱등키로> 한 번만 재시도한다")
    void 연결이_끊기면_같은_멱등키로_재시도한다() {
        tossStub.enqueueAbort();                                   // 1회차: 응답 없이 끊김
        tossStub.enqueue(200, 발급성공.formatted(customerKey, 빌링키)); // 2회차: 성공

        Response 응답 = post(ownerToken, customerKey, "auth-key-1");

        assertThat(응답.status()).isEqualTo(200);
        List<TossStub.Recorded> 보낸것 = tossStub.received();
        assertThat(보낸것).hasSize(2);
        // 🔴 이 한 줄이 이 기능의 전부다. 다른 키로 재시도하면 토스는 <두 번째 빌링키>를 발급하고,
        //    조회 API 가 없어서 그 고아를 영원히 회수할 수 없다.
        assertThat(보낸것.get(0).header("idempotency-key"))
                .isEqualTo(보낸것.get(1).header("idempotency-key"));
    }

    // ── 조회 ─────────────────────────────────────────────────────────────

    @Test
    @DisplayName("[결제] 카드가 없어도 customerKey 는 내려온다 (결제창을 열려면 필요하다)")
    void 카드가_없으면_methods_는_빈_목록이다() {
        Response 응답 = get(ownerToken);

        assertThat(응답.status()).isEqualTo(200);
        assertThat(응답.json().path("customerKey").asString()).isEqualTo(customerKey);
        // 필드가 <있고 빈 배열> 이어야 한다. null 이면 프론트가 .map 에서 터진다.
        assertThat(응답.json().path("methods").isArray()).isTrue();
        assertThat(응답.json().path("methods")).isEmpty();
    }

    @Test
    @DisplayName("[보안] 남의 결제 수단이 내 조회에 섞이지 않는다")
    void 남의_카드는_내_조회에_안_섞인다() {
        tossStub.enqueue(200, 발급성공.formatted(customerKey, 빌링키));
        post(ownerToken, customerKey, "auth-key-1");

        String 침입자 = signup("intruder@example.com");
        Response 응답 = get(침입자);

        assertThat(응답.status()).isEqualTo(200);
        assertThat(응답.json().path("methods")).isEmpty();
        // customerKey 도 자기 것이어야 한다 — 남의 것을 받으면 남의 계정에 카드를 붙일 수 있다.
        assertThat(응답.json().path("customerKey").asString()).isNotEqualTo(customerKey);
    }

    // ── 여러 장 · 기본 카드 (V7 의 핵심 주장) ─────────────────────────────

    @Test
    @DisplayName("[여러 장] 첫 카드는 자동으로 기본이고, 둘째부터는 기본이 아니다")
    void 첫_카드는_자동으로_기본이다() {
        String 첫째 = 등록한다("61", "43301234****123*");
        String 둘째 = 등록한다("41", "55201234****456*");

        JsonNode 목록 = get(ownerToken).json().path("methods");
        assertThat(목록).hasSize(2);
        // 등록 순서대로 온다 — 화면이 "먼저 등록한 카드가 위" 로 그린다.
        assertThat(목록.get(0).path("id").asString()).isEqualTo(첫째);
        assertThat(목록.get(0).path("isDefault").asBoolean()).isTrue();
        assertThat(목록.get(1).path("id").asString()).isEqualTo(둘째);
        assertThat(목록.get(1).path("issuerName").asString()).isEqualTo("신한");
        // 🔴 방금 넣은 카드가 말없이 청구 카드가 되면 사용자가 놀란다. 둘째는 지정할 때만 기본이 된다.
        assertThat(목록.get(1).path("isDefault").asBoolean()).isFalse();
        assertThat(기본_카드_수(userId)).isEqualTo(1);
    }

    @Test
    @DisplayName("[여러 장] 기본을 바꾸면 정확히 하나만 기본이다 — 이미 기본인 카드를 다시 지정해도 그대로다")
    void 기본_지정하면_정확히_하나만_기본이다() {
        String 첫째 = 등록한다("61", "43301234****123*");
        String 둘째 = 등록한다("41", "55201234****456*");

        Response 응답 = request(HttpMethod.PUT, METHODS + "/" + 둘째 + "/default", ownerToken, null);

        assertThat(응답.status()).isEqualTo(200);
        JsonNode 목록 = 응답.json().path("methods");
        assertThat(목록.get(0).path("id").asString()).isEqualTo(첫째);
        assertThat(목록.get(0).path("isDefault").asBoolean()).isFalse();
        assertThat(목록.get(1).path("isDefault").asBoolean()).isTrue();
        assertThat(기본_카드_수(userId)).isEqualTo(1);

        // 🔴 <이미 기본인 카드> 를 다시 지정한다. 여기가 함정이 있던 자리다 —
        //    clearDefault(JPQL) 가 영속성 컨텍스트를 우회하므로, "먼저 해제하고 다시 켠다" 를 순진하게 하면
        //    엔티티의 낡은 true 때문에 되돌리는 UPDATE 가 안 나가 <기본 카드가 0장> 이 된다.
        //    서비스는 이미 기본이면 아무것도 안 하는 것으로 피한다. 이 검사가 그걸 못박는다.
        Response 다시 = request(HttpMethod.PUT, METHODS + "/" + 둘째 + "/default", ownerToken, null);
        assertThat(다시.status()).isEqualTo(200);
        assertThat(다시.json().path("methods").get(1).path("isDefault").asBoolean()).isTrue();
        assertThat(기본_카드_수(userId)).isEqualTo(1);
        // 기본 지정은 토스를 부르지 않는다.
        assertThat(tossStub.received()).hasSize(2); // 발급 2회뿐
    }

    @Test
    @DisplayName("[여러 장] 기본 카드는 다른 카드가 남아 있으면 삭제 거부(409)이고 토스를 부르지 않는다")
    void 기본_카드는_다른_카드가_있으면_삭제_거부() {
        String 첫째 = 등록한다("61", "43301234****123*");
        등록한다("41", "55201234****456*");
        tossStub.reset();

        Response 응답 = 삭제(ownerToken, 첫째);

        assertThat(응답.status()).isEqualTo(409);
        assertThat(응답.json().path("error").path("code").asString())
                .isEqualTo("BILLING_DEFAULT_METHOD_IN_USE");
        // 🔴 거부는 토스 호출 <전에> 결정된다. 불렀다면 토스 쪽 빌링키만 폐기되고 우리 행은 남는
        //    최악의 불일치가 난다(그 행으로 다시 삭제하면 토스가 404 → 그때서야 지워지지만, 그 사이 청구는 실패한다).
        assertThat(tossStub.received()).isEmpty();
        assertThat(카드_행수(userId)).isEqualTo(2);
    }

    @Test
    @DisplayName("[요금제] 🔴 유료 요금제의 마지막 카드는 삭제 거부(409)이고 토스를 부르지 않는다")
    void 유료_요금제의_마지막_카드는_못_지운다() {
        String 유일 = 등록한다("61", "43301234****123*");
        assertThat(request(HttpMethod.PUT, "/api/plan", ownerToken, Map.of("plan", "pro")).status())
                .isEqualTo(200);
        tossStub.reset();

        Response 응답 = 삭제(ownerToken, 유일);

        assertThat(응답.status()).isEqualTo(409);
        assertThat(응답.json().path("error").path("code").asString())
                .isEqualTo("BILLING_METHOD_REQUIRED_BY_PLAN");
        // 🔴 이 검사가 <PlanService 의 반쪽>이다. 거기서는 "카드 0장이면 유료로 못 바꾼다" 를 막고,
        //    여기서는 "유료인데 마지막 카드를 지우는 것" 을 막는다. 한쪽만 두면 유료로 바꾼 뒤
        //    카드를 지워서 규칙을 우회할 수 있어 <규칙이 없는 것과 같아진다>.
        assertThat(tossStub.received()).isEmpty();
        assertThat(카드_행수(userId)).isEqualTo(1);
    }

    @Test
    @DisplayName("[요금제] 유료라도 카드가 두 장이면 기본이 아닌 쪽은 지워진다")
    void 유료라도_카드가_둘이면_지워진다() {
        등록한다("61", "43301234****123*");
        String 둘째 = 등록한다("41", "55201234****456*");
        assertThat(request(HttpMethod.PUT, "/api/plan", ownerToken, Map.of("plan", "pro")).status())
                .isEqualTo(200);
        tossStub.reset();
        tossStub.enqueue(200, "");

        assertThat(삭제(ownerToken, 둘째).status()).isEqualTo(204);
        // 유료 계정에 카드가 한 장 남았다 — 불변식이 지켜진 상태다.
        assertThat(카드_행수(userId)).isEqualTo(1);
    }

    @Test
    @DisplayName("[여러 장] 마지막 한 장은 기본이어도 삭제된다 — 남는 카드가 없으니 불변식이 깨지지 않는다")
    void 마지막_한_장은_기본이어도_삭제된다() {
        String 유일 = 등록한다("61", "43301234****123*");
        tossStub.reset();
        tossStub.enqueue(200, "");

        assertThat(삭제(ownerToken, 유일).status()).isEqualTo(204);
        assertThat(카드_행수(userId)).isZero();
    }

    @Test
    @DisplayName("[보안] 남의 카드 id 로는 삭제도 기본 지정도 404 이고, 토스에 요청이 가지 않는다")
    void 남의_카드는_404_이고_토스에_안_간다() {
        String 내카드 = 등록한다("61", "43301234****123*");
        String 침입자 = signup("intruder@example.com");
        tossStub.reset();

        Response 삭제시도 = 삭제(침입자, 내카드);
        Response 기본시도 = request(HttpMethod.PUT, METHODS + "/" + 내카드 + "/default", 침입자, null);

        // 🔴 403 이 아니라 404 — 403 은 "그 id 의 카드가 존재한다" 를 알려준다. 봇과 같은 기준이다.
        assertThat(삭제시도.status()).isEqualTo(404);
        assertThat(기본시도.status()).isEqualTo(404);
        assertThat(삭제시도.json().path("error").path("code").asString()).isEqualTo("BILLING_METHOD_NOT_FOUND");
        // "404 가 났다" 가 아니라 <토스까지 가지 않았다> 를 확인한다.
        assertThat(tossStub.received()).isEmpty();
        // 내 카드는 그대로, 여전히 기본이다.
        assertThat(카드_행수(userId)).isEqualTo(1);
        assertThat(기본_카드_수(userId)).isEqualTo(1);
    }

    @Test
    @DisplayName("[여러 장] 여섯 장째는 409 이고 토스를 부르지 않는다 — 발급 뒤에 막으면 고아가 남는다")
    void 여섯_장째는_409_이고_토스에_안_간다() {
        for (int i = 0; i < 5; i++) {
            등록한다("61", "4330123" + i + "****123*");
        }
        tossStub.reset();

        Response 응답 = post(ownerToken, customerKey, "auth-key-6");

        assertThat(응답.status()).isEqualTo(409);
        assertThat(응답.json().path("error").path("code").asString())
                .isEqualTo("BILLING_METHOD_LIMIT_EXCEEDED");
        assertThat(tossStub.received()).isEmpty();
        assertThat(카드_행수(userId)).isEqualTo(5);
    }

    // ── 삭제 (설계 §쓰기 경로 ②) ─────────────────────────────────────────

    @Test
    @DisplayName("[삭제] 우리가 저장한 그 빌링키로 토스에 폐기를 요청한다")
    void 삭제는_토스에_그_키를_보낸다() {
        String id = 등록한다();
        tossStub.reset();               // 발급 때의 기록을 지운다 — 아래 검증이 <삭제> 호출만 보게
        tossStub.enqueue(200, "");      // 토스 레퍼런스는 "비어있는 body 에 200" 이라고 한다

        Response 응답 = 삭제(ownerToken, id);

        assertThat(응답.status()).isEqualTo(204);

        var 삭제요청 = tossStub.received().getFirst();
        assertThat(삭제요청.method()).isEqualTo("DELETE");
        // 이 한 줄이 두 가지를 지킨다:
        //  ① 토스를 실제로 불렀다
        //  ② 저장된 암호문을 제대로 복호화했다 — DB 왕복을 거쳐 원래 키가 돌아왔다는 뜻이다
        assertThat(삭제요청.path()).isEqualTo("/v1/billing/" + 빌링키_BASE64);

        // ⚠️ 이 검사가 <못> 하는 것 두 가지를 적어둔다. 이 저장소는 "숫자가 나왔다"에서 멈춰서
        //    사고를 반복해 냈다(AGENTS.md 의 "낸 버그" 절).
        //    ① 인코딩: 스텁의 getPath() 가 퍼센트 인코딩을 풀어 돌려주므로, '/' 를 %2F 로 보냈든
        //       그대로 보냈든 같은 문자열이 된다. 토스가 %2F 를 어떻게 해석하는지는
        //       테스트 키 브라우저 종단에서만 알 수 있다(2026-09-07 에 확인했다).
        //    ② "먼저": 순서를 증명하는 것은 이 테스트가 아니라 아래 5xx 테스트다.
        //       우리가 먼저 지웠다면 5xx 일 때 행이 남아 있을 수 없다.
    }

    @Test
    @DisplayName("[삭제] 토스가 5xx 면 503 이고 <우리 행이 남는다> — 이 Task 의 핵심 주장")
    void 토스_5xx_면_우리_행이_남는다() {
        String id = 등록한다();
        tossStub.enqueue(500, 토스_5xx);

        Response 응답 = 삭제(ownerToken, id);

        assertThat(응답.status()).isEqualTo(503);
        assertThat(응답.json().path("error").path("code").asString())
                .isEqualTo("BILLING_PROVIDER_UNAVAILABLE");

        // 🔴 여기가 전부다. 행이 남아야 <다시 시도해 폐기할 수> 있다.
        //    먼저 지웠다면 토스에는 우리가 값을 모르는 빌링키가 영영 남는다 —
        //    토스에 <빌링키를 조회하는 API 가 없어서> 다시 알아낼 방법이 없다.
        assertThat(카드_행수(userId)).isEqualTo(1);

        // 화면에도 그대로 보여야 한다. 행만 남고 조회가 비면 사용자는 "지워졌다"고 믿고
        // 다시 시도하지 않는다 = 고아를 만드는 것과 결과가 같다.
        assertThat(get(ownerToken).json().path("methods")).hasSize(1);
    }

    @Test
    @DisplayName("[삭제] 연결이 끊기면 503 이고 <우리 행이 남는다>")
    void 삭제_중_연결이_끊기면_우리_행이_남는다() {
        String id = 등록한다();
        tossStub.enqueueAbort();   // 응답 없이 끊김 — TossClient 가 로그에 URL(빌링키 포함)을 남기면 안 되는 경로

        Response 응답 = 삭제(ownerToken, id);

        assertThat(응답.status()).isEqualTo(503);
        assertThat(응답.json().path("error").path("code").asString())
                .isEqualTo("BILLING_PROVIDER_UNAVAILABLE");

        // 5xx 테스트와 같은 방식으로 행 유지를 증명한다 — DB 행수와 GET 응답 둘 다 본다.
        assertThat(카드_행수(userId)).isEqualTo(1);
        assertThat(get(ownerToken).json().path("methods")).hasSize(1);
    }

    @Test
    @DisplayName("[삭제] 토스가 401 이면 503 이고 <우리 행이 남는다> — 401 은 '없다'가 아니라 '모른다'다")
    void 삭제_중_토스가_401_이면_우리_행이_남는다() {
        String id = 등록한다();
        tossStub.enqueue(401, "{\"code\":\"UNAUTHORIZED_KEY\",\"message\":\"인증되지 않은 요청입니다.\"}");

        Response 응답 = 삭제(ownerToken, id);

        assertThat(응답.status()).isEqualTo(503);
        assertThat(응답.json().path("error").path("code").asString())
                .isEqualTo("BILLING_PROVIDER_UNAVAILABLE");

        // 🔴 404 만 삼키고 그 밖의 4xx(401 포함)는 우리 행을 지우지 않는다는 것을 못박는다.
        //    시크릿 키가 잘못돼 토스가 빌링키를 쳐다보지도 않았는데 우리만 유일한 사본을 지우면 안 된다.
        assertThat(카드_행수(userId)).isEqualTo(1);
        assertThat(get(ownerToken).json().path("methods")).hasSize(1);
    }

    @Test
    @DisplayName("[삭제] 토스가 404 면 우리 행은 지운다 (토스 쪽엔 이미 없다는 뜻) — 바로 위 401 테스트와 짝이다")
    void 토스_404_면_우리_행을_지운다() {
        String id = 등록한다();
        tossStub.enqueue(404, 토스_4xx);

        Response 응답 = 삭제(ownerToken, id);

        assertThat(응답.status()).isEqualTo(204);
        assertThat(카드_행수(userId)).isZero();

        // 바로 위 401 테스트와 이 테스트가 함께 실제 기준을 증명한다 — 갈리는 것은
        // "4xx 냐 아니냐"가 아니라 <404 냐 아니냐>다. 401(위)은 행을 남기고, 404(여기)는 행을 지운다.
        // 반대로 잡으면(404 도 유지) 사용자가 카드를 <영영 못 지운다>.
        // 이건 해석이지 확인된 사실이 아니다 — 토스 문서에 이 API 의 에러 코드표가 없다.
    }

    @Test
    @DisplayName("[삭제] 🔴 암호문이 손상되면 500 BILLING_METHOD_UNREADABLE 이고, 토스를 부르지 않으며 행이 남는다")
    void 복호화_실패는_재시도_안내를_하지_않는다() {
        String id = 등록한다();
        // 2026-09-07 에 손으로 했던 것과 같은 조작이다: 암호문 한 글자를 바꾼다.
        // GCM 인증태그가 이걸 잡아낸다(CBC 였다면 복호화가 그냥 성공했을 것이다).
        암호문을_변조한다(id);
        tossStub.reset();

        Response 응답 = 삭제(ownerToken, id);

        // 🔴 INTERNAL_ERROR("잠시 후 다시 시도해주세요")가 아니다. 키 분실·손상·변조 중 하나라
        //    재시도로는 절대 안 풀린다.
        assertThat(응답.status()).isEqualTo(500);
        assertThat(응답.json().path("error").path("code").asString())
                .isEqualTo("BILLING_METHOD_UNREADABLE");
        assertThat(응답.json().path("error").path("message").asString())
                .doesNotContain("잠시 후");

        // "모르면 지우지 않는다": 복호화 전에 멈추므로 토스는 아예 부르지 않고 행도 남는다.
        // (지웠다면 토스에 우리가 값을 모르는 빌링키가 영영 남는다)
        assertThat(tossStub.received()).isEmpty();
        assertThat(카드_행수(userId)).isEqualTo(1);
    }

    @Test
    @DisplayName("[삭제] 없는 카드 id 면 404 이고 토스를 부르지 않는다")
    void 없는_카드를_지우면_404() {
        Response 응답 = 삭제(ownerToken, UUID.randomUUID().toString());

        assertThat(응답.status()).isEqualTo(404);
        assertThat(응답.json().path("error").path("code").asString())
                .isEqualTo("BILLING_METHOD_NOT_FOUND");

        // "요청이 토스까지 가지 않았다" 를 확인한다. "404 가 났다" 만 보면
        // <토스가 거절해서 404> 인 경우와 구별되지 않는다.
        assertThat(tossStub.received()).isEmpty();
    }

    @Test
    @DisplayName("[종단] 삭제 후 다시 등록된다. customerKey 는 그대로다")
    void 삭제하고_다시_등록된다() {
        String 처음_customerKey = get(ownerToken).json().path("customerKey").asString();

        String id = 등록한다();
        tossStub.enqueue(200, "");
        assertThat(삭제(ownerToken, id).status()).isEqualTo(204);

        // 다시 등록한다. 새 카드는 유일하므로 다시 기본이어야 한다.
        등록한다();

        JsonNode 조회 = get(ownerToken).json();
        assertThat(조회.path("methods")).hasSize(1);
        assertThat(조회.path("methods").get(0).path("cardNumberMasked").asString()).isEqualTo("43301234****123*");
        assertThat(조회.path("methods").get(0).path("isDefault").asBoolean()).isTrue();

        // 🔴 customerKey 는 카드보다 오래 산다. 카드를 뺐다 넣어도 같아야 토스 쪽 고객 이력이 이어진다.
        //    users(customerKey) 와 billing_methods(billingKey) 로 테이블을 나눈 이유가 이것이다.
        assertThat(조회.path("customerKey").asString()).isEqualTo(처음_customerKey);
    }

    // ── 보조 ─────────────────────────────────────────────────────────────

    /**
     * 카드 한 장(삭제 검사용 base64 빌링키)을 등록하고 <b>그 카드의 id</b> 를 돌려준다.
     * 삭제·기본 지정 검사의 전제조건이라, 실패하면 그 자리에서 드러나야 한다.
     */
    private String 등록한다() {
        tossStub.enqueue(200, 발급응답_BASE64키);
        return 마지막_카드_id(post(ownerToken, customerKey, "test_auth_key_for_delete"));
    }

    /** 발급사·번호를 지정해 등록한다. 여러 장 검사에서 <어느 카드인지> 를 구별하기 위해서다. */
    private String 등록한다(String issuerCode, String number) {
        tossStub.enqueue(200, 발급성공_카드.formatted("key-" + UUID.randomUUID(), issuerCode, number));
        return 마지막_카드_id(post(ownerToken, customerKey, "auth-" + UUID.randomUUID()));
    }

    private static String 마지막_카드_id(Response 응답) {
        assertThat(응답.status())
                .as("등록이 먼저 성공해야 다음 검사를 할 수 있다. 응답 본문=%s", 응답.body())
                .isEqualTo(200);
        JsonNode 목록 = 응답.json().path("methods");
        return 목록.get(목록.size() - 1).path("id").asString();
    }

    private Response 삭제(String token, String id) {
        return request(HttpMethod.DELETE, METHODS + "/" + id, token, null);
    }

    /**
     * 저장된 암호문의 첫 글자를 <b>반드시 다른 글자로</b> 바꿔 "손상된 행" 을 만든다.
     * 고정 글자로 덮어쓰면 원래 값과 우연히 같을 때 아무것도 손상되지 않아 테스트가 조용히 통과한다.
     */
    private void 암호문을_변조한다(String methodId) {
        UUID id = UUID.fromString(methodId);
        String 원본 = jdbcTemplate.queryForObject(
                "SELECT billing_key_enc FROM billing_methods WHERE id = ?", String.class, id);
        String 변조 = (원본.charAt(0) == 'A' ? 'B' : 'A') + 원본.substring(1);
        jdbcTemplate.update("UPDATE billing_methods SET billing_key_enc = ? WHERE id = ?", 변조, id);
    }

    private long 카드_행수(UUID userId) {
        Long n = jdbcTemplate.queryForObject(
                "SELECT count(*) FROM billing_methods WHERE user_id = ?", Long.class, userId);
        return n == null ? 0 : n;
    }

    /** 불변식 "카드가 있으면 기본이 정확히 하나" 를 <b>DB 에서 직접</b> 센다. 응답만 보면 직렬화 버그와 구별이 안 된다. */
    private long 기본_카드_수(UUID userId) {
        Long n = jdbcTemplate.queryForObject(
                "SELECT count(*) FROM billing_methods WHERE user_id = ? AND is_default", Long.class, userId);
        return n == null ? 0 : n;
    }

    private String customerKeyOf(UUID userId) {
        return jdbcTemplate.queryForObject(
                "SELECT billing_customer_key FROM users WHERE id = ?", String.class, userId);
    }

    private Response post(String token, String customerKey, String authKey) {
        return request(HttpMethod.POST, METHODS, token,
                Map.of("authKey", authKey, "customerKey", customerKey));
    }

    private Response get(String token) {
        return request(HttpMethod.GET, METHODS, token, null);
    }

    private String signup(String email) {
        return request(HttpMethod.POST, "/api/auth/signup", null,
                new SignupRequest(email, PASSWORD, null)).json().path("token").asString();
    }

    /** 남의 customerKey 를 얻기 위한 계정 하나. 토큰은 쓰지 않는다. */
    private String signupAndReturnEmail() {
        signup("stranger@example.com");
        return "stranger@example.com";
    }

    private Response request(HttpMethod method, String uri, String token, Object body) {
        var spec = client.method(method).uri(uri);
        if (token != null) {
            spec.header(HttpHeaders.AUTHORIZATION, "Bearer " + token);
        }
        // GET 에는 본문을 붙이지 않는다. 강제로 붙이면 본문 없는 GET 을 표현할 수 없다.
        EntityExchangeResult<byte[]> result = (body == null
                ? spec
                : spec.contentType(MediaType.APPLICATION_JSON).body(body))
                .exchange().expectBody().returnResult();
        return new Response(result.getStatus().value(), decode(result.getResponseBody()));
    }

    private record Response(int status, String body) {
        JsonNode json() {
            return JSON.readTree(body);
        }
    }

    private static final ObjectMapper JSON = new ObjectMapper();

    private static String decode(byte[] raw) {
        return raw == null ? "" : new String(raw, StandardCharsets.UTF_8);
    }
}
