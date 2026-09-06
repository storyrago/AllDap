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
 * 결제 수단 등록·조회 통합 테스트. (삭제는 Task 3)
 *
 * <p><b>여기서 지키려는 주장은 네 개다.</b> 나머지는 배관이다.
 * <ul>
 *   <li>DB 에 <b>평문 빌링키가 없다</b> — 이 조각의 존재 이유</li>
 *   <li>어떤 응답 본문에도 <b>빌링키가 없다</b> — DTO 에 필드를 두지 않은 것의 실증</li>
 *   <li>쿼리로 온 {@code customerKey} 를 <b>신뢰하지 않는다</b> — 신뢰하면 남의 계정에 카드가 붙는다</li>
 *   <li>연결이 끊기면 <b>같은 멱등키로</b> 재시도한다 — 다른 키로 재시도하면 회수 불가능한 고아가 하나 더 는다</li>
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

    /** 토스 v1 에러 본문. {@code {"code","message","data"}} 모양이다. */
    private static final String 발급거절 = """
            {"code":"INVALID_CARD_EXPIRATION",
             "message":"카드 유효기간이 올바르지 않습니다.","data":null}""";

    // ── 삭제 검사 전용 (Task 3) ──────────────────────────────────────────

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

    @Test
    @DisplayName("[결제] 카드를 등록하면 카드사 이름·마스킹 번호·등록일이 돌아온다")
    void 카드_등록_성공() {
        tossStub.enqueue(200, 발급성공.formatted(customerKey, 빌링키));

        Response 응답 = post(ownerToken, customerKey, "auth-key-1");

        assertThat(응답.status()).isEqualTo(200);
        JsonNode json = 응답.json();
        assertThat(json.path("customerKey").asString()).isEqualTo(customerKey);
        // issuerCode "61" → "현대". 코드→이름 변환이 Spring 책임이라는 것을 여기서 못박는다.
        assertThat(json.path("method").path("issuerName").asString()).isEqualTo("현대");
        assertThat(json.path("method").path("cardNumberMasked").asString()).isEqualTo("43301234****123*");
        // KST 오프셋으로 직렬화된다 — UsageResponse.periodStart 와 같은 규칙이다.
        assertThat(json.path("method").path("registeredAt").asString()).endsWith("+09:00");

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
    @DisplayName("[결제] 이미 카드가 있으면 409 다 (계정당 1장)")
    void 이미_등록된_카드가_있으면_409() {
        tossStub.enqueue(200, 발급성공.formatted(customerKey, 빌링키));
        post(ownerToken, customerKey, "auth-key-1");

        Response 두번째 = post(ownerToken, customerKey, "auth-key-2");

        assertThat(두번째.status()).isEqualTo(409);
        assertThat(두번째.json().path("error").path("code").asString())
                .isEqualTo("BILLING_METHOD_ALREADY_EXISTS");
        // 두 번째는 토스를 부르지 않았어야 한다 — 불렀다면 회수 못 하는 고아 빌링키가 생긴다.
        assertThat(tossStub.received()).hasSize(1);
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

        // 🔴 리뷰 지적 ④가 사는 자리다. 고치기 전에는 401 만 따로 뗐고 429 는 <그 밖의 4xx> 로
        //    떨어져 400 BILLING_AUTH_FAILED("카드 정보를 확인해주세요")가 나갔다 — 사용자가
        //    손쓸 수 없는 레이트리밋을 카드 탓으로 돌린 것이다. 같은 429 가 삭제 경로
        //    (TossClient.deleteBillingKey)에서는 이미 503 이다 — 그 주석이 명시한다:
        //    "429(레이트리밋)도 '없다'는 뜻이 전혀 아니다." 발급도 같은 기준을 따라야 한다.
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

    @Test
    @DisplayName("[결제] 카드가 없어도 customerKey 는 내려온다 (결제창을 열려면 필요하다)")
    void 카드가_없으면_method_는_null_이다() {
        Response 응답 = get(ownerToken);

        assertThat(응답.status()).isEqualTo(200);
        assertThat(응답.json().path("customerKey").asString()).isEqualTo(customerKey);
        // 필드가 <있고 값이 null> 이어야 한다. 통째로 빠지면 프론트가 "아직 안 불러온 것" 과 구별 못 한다.
        assertThat(응답.json().path("method").isNull()).isTrue();
    }

    @Test
    @DisplayName("[보안] 남의 결제 수단이 내 조회에 섞이지 않는다")
    void 남의_카드는_내_조회에_안_섞인다() {
        tossStub.enqueue(200, 발급성공.formatted(customerKey, 빌링키));
        post(ownerToken, customerKey, "auth-key-1");

        String 침입자 = signup("intruder@example.com");
        Response 응답 = get(침입자);

        assertThat(응답.status()).isEqualTo(200);
        assertThat(응답.json().path("method").isNull()).isTrue();
        // customerKey 도 자기 것이어야 한다 — 남의 것을 받으면 남의 계정에 카드를 붙일 수 있다.
        assertThat(응답.json().path("customerKey").asString()).isNotEqualTo(customerKey);
    }

    // ── 삭제 (설계 §쓰기 경로 ②) ─────────────────────────────────────────

    @Test
    @DisplayName("[삭제] 우리가 저장한 그 빌링키로 토스에 폐기를 요청한다")
    void 삭제는_토스에_그_키를_보낸다() {
        등록한다();
        tossStub.reset();               // 발급 때의 기록을 지운다 — 아래 검증이 <삭제> 호출만 보게
        tossStub.enqueue(200, "");      // 토스 레퍼런스는 "비어있는 body 에 200" 이라고 한다

        Response 응답 = request(HttpMethod.DELETE, "/api/billing/method", ownerToken, null);

        assertThat(응답.status()).isEqualTo(204);

        var 삭제요청 = tossStub.received().getFirst();
        assertThat(삭제요청.method()).isEqualTo("DELETE");
        // 이 한 줄이 두 가지를 지킨다:
        //  ① 토스를 실제로 불렀다
        //  ② 저장된 암호문을 제대로 복호화했다 — DB 왕복을 거쳐 원래 키가 돌아왔다는 뜻이다
        assertThat(삭제요청.path()).isEqualTo("/v1/billing/" + 빌링키_BASE64);

        // ⚠️ 이 검사가 <못> 하는 것 두 가지를 적어둔다. 이 저장소는 "숫자가 나왔다"에서 멈춰서
        //    사고를 낸 적이 다섯 번 있다.
        //    ① 인코딩: 스텁의 getPath() 가 퍼센트 인코딩을 풀어 돌려주므로, '/' 를 %2F 로 보냈든
        //       그대로 보냈든 같은 문자열이 된다. 토스가 %2F 를 어떻게 해석하는지는
        //       설계 §검사 3(테스트 키 브라우저 종단)에서만 알 수 있다.
        //    ② "먼저": 순서를 증명하는 것은 이 테스트가 아니라 아래 5xx 테스트다.
        //       우리가 먼저 지웠다면 5xx 일 때 행이 남아 있을 수 없다.
    }

    @Test
    @DisplayName("[삭제] 토스가 5xx 면 503 이고 <우리 행이 남는다> — 이 Task 의 핵심 주장")
    void 토스_5xx_면_우리_행이_남는다() {
        등록한다();
        tossStub.enqueue(500, 토스_5xx);

        Response 응답 = request(HttpMethod.DELETE, "/api/billing/method", ownerToken, null);

        assertThat(응답.status()).isEqualTo(503);
        assertThat(응답.json().path("error").path("code").asString())
                .isEqualTo("BILLING_PROVIDER_UNAVAILABLE");

        // 🔴 여기가 전부다. 행이 남아야 <다시 시도해 폐기할 수> 있다.
        //    먼저 지웠다면 토스에는 우리가 값을 모르는 빌링키가 영영 남는다 —
        //    토스에 <빌링키를 조회하는 API 가 없어서> 다시 알아낼 방법이 없다.
        assertThat(카드_행수(userId)).isEqualTo(1);

        // 화면에도 그대로 보여야 한다. 행만 남고 조회가 비면 사용자는 "지워졌다"고 믿고
        // 다시 시도하지 않는다 = 고아를 만드는 것과 결과가 같다.
        assertThat(request(HttpMethod.GET, "/api/billing/method", ownerToken, null)
                .json().path("method").isNull()).isFalse();
    }

    @Test
    @DisplayName("[삭제] 연결이 끊기면 503 이고 <우리 행이 남는다> — 리뷰 수정 ①이 사는 자리")
    void 삭제_중_연결이_끊기면_우리_행이_남는다() {
        등록한다();
        tossStub.enqueueAbort();   // 응답 없이 끊김 — TossClient 가 로그에 URL(빌링키 포함)을 남기면 안 되는 경로

        Response 응답 = request(HttpMethod.DELETE, "/api/billing/method", ownerToken, null);

        assertThat(응답.status()).isEqualTo(503);
        assertThat(응답.json().path("error").path("code").asString())
                .isEqualTo("BILLING_PROVIDER_UNAVAILABLE");

        // 5xx 테스트와 같은 방식으로 행 유지를 증명한다 — DB 행수와 GET 응답 둘 다 본다.
        assertThat(카드_행수(userId)).isEqualTo(1);
        assertThat(request(HttpMethod.GET, "/api/billing/method", ownerToken, null)
                .json().path("method").isNull()).isFalse();
    }

    @Test
    @DisplayName("[삭제] 토스가 401 이면 503 이고 <우리 행이 남는다> — 401 은 '없다'가 아니라 '모른다'다")
    void 삭제_중_토스가_401_이면_우리_행이_남는다() {
        등록한다();
        tossStub.enqueue(401, "{\"code\":\"UNAUTHORIZED_KEY\",\"message\":\"인증되지 않은 요청입니다.\"}");

        Response 응답 = request(HttpMethod.DELETE, "/api/billing/method", ownerToken, null);

        assertThat(응답.status()).isEqualTo(503);
        assertThat(응답.json().path("error").path("code").asString())
                .isEqualTo("BILLING_PROVIDER_UNAVAILABLE");

        // 🔴 404 만 삼키고 그 밖의 4xx(401 포함)는 우리 행을 지우지 않는다는 것을 못박는다.
        //    고치기 전(4xx 전부 삼킴)이었다면 이 테스트는 204 + 행수 0 을 보고 실패했을 것이다 —
        //    시크릿 키가 잘못돼 토스가 빌링키를 쳐다보지도 않았는데 우리만 유일한 사본을 지운 것이다.
        assertThat(카드_행수(userId)).isEqualTo(1);
        assertThat(request(HttpMethod.GET, "/api/billing/method", ownerToken, null)
                .json().path("method").isNull()).isFalse();
    }

    @Test
    @DisplayName("[삭제] 토스가 404 면 우리 행은 지운다 (토스 쪽엔 이미 없다는 뜻) — 바로 위 401 테스트와 짝이다")
    void 토스_404_면_우리_행을_지운다() {
        등록한다();
        tossStub.enqueue(404, 토스_4xx);

        Response 응답 = request(HttpMethod.DELETE, "/api/billing/method", ownerToken, null);

        assertThat(응답.status()).isEqualTo(204);
        assertThat(카드_행수(userId)).isZero();

        // 바로 위 401 테스트(삭제_중_토스가_401_이면_우리_행이_남는다)와 이 테스트가 함께
        // 실제 기준을 증명한다 — 갈리는 것은 "4xx 냐 아니냐"가 아니라 <404 냐 아니냐>다.
        // 401(위)은 행을 남기고, 404(여기)는 행을 지운다.
        // 반대로 잡으면(404 도 유지) 사용자가 카드를 <영영 못 지운다>.
        // 이건 해석이지 확인된 사실이 아니다 — 토스 문서에 이 API 의 에러 코드표가 없다.
        // 해석이 틀리면 토스 쪽에 고아가 남지만, 반대 선택의 대가가 더 크다고 보고 이쪽을 택했다.
    }

    @Test
    @DisplayName("[삭제] 등록된 카드가 없으면 404 이고 토스를 부르지 않는다")
    void 없는_카드를_지우면_404() {
        Response 응답 = request(HttpMethod.DELETE, "/api/billing/method", ownerToken, null);

        assertThat(응답.status()).isEqualTo(404);
        assertThat(응답.json().path("error").path("code").asString())
                .isEqualTo("BILLING_METHOD_NOT_FOUND");

        // "요청이 토스까지 가지 않았다" 를 확인한다. "404 가 났다" 만 보면
        // <토스가 거절해서 404> 인 경우와 구별되지 않는다.
        // (AGENTS.md 의 "테스트도 '404 가 났다'가 아니라 '요청이 Python 까지 가지 않았다'를 확인할 것" 그대로)
        assertThat(tossStub.received()).isEmpty();
    }

    @Test
    @DisplayName("[종단] 삭제 후 다시 등록된다. customerKey 는 그대로다")
    void 삭제하고_다시_등록된다() {
        String 처음_customerKey = request(HttpMethod.GET, "/api/billing/method", ownerToken, null)
                .json().path("customerKey").asString();

        등록한다();
        tossStub.enqueue(200, "");
        assertThat(request(HttpMethod.DELETE, "/api/billing/method", ownerToken, null).status())
                .isEqualTo(204);

        // 다시 등록한다. 여기서 409 가 나면 삭제가 행을 안 지운 것이다.
        등록한다();

        JsonNode 조회 = request(HttpMethod.GET, "/api/billing/method", ownerToken, null).json();
        assertThat(조회.path("method").path("cardNumberMasked").asString()).isEqualTo("43301234****123*");

        // 🔴 customerKey 는 카드보다 오래 산다. 카드를 뺐다 넣어도 같아야 토스 쪽 고객 이력이 이어진다.
        //    users(customerKey) 와 billing_methods(billingKey) 로 테이블을 나눈 이유가 이것이고,
        //    "없음 → 있음 → 없음 → 있음" 을 한 바퀴 돌 수 있어야 종단 검증이 성립한다는 것이
        //    <삭제를 이 조각에 넣은> 이유다(설계 §무엇을 하는가).
        assertThat(조회.path("customerKey").asString()).isEqualTo(처음_customerKey);
    }

    // ── 삭제 검사용 보조 ─────────────────────────────────────────────────

    /**
     * 카드 한 장을 등록해 둔다. 삭제 검사의 전제조건이라, 실패하면 그 자리에서 드러나야 한다
     * (등록이 깨진 채로 "삭제 테스트가 실패했다" 는 로그만 보면 엉뚱한 곳을 파게 된다).
     *
     * <p>⚠️ 브리프 원안은 여기서 {@code request(...)} 를 직접 불러 {@code RegisterBillingMethodRequest}
     * 를 새로 조립했지만, Task 2 가 이미 같은 일을 하는 {@link #post(String, String, String)} 를
     * 만들어 뒀다(POST 본문을 만들어 보내고 응답을 돌려준다) — 그대로 재사용한다.
     * customerKey 도 새로 GET 해서 얻지 않고 {@code @BeforeEach} 가 채워둔 클래스 필드를 쓴다.
     */
    private void 등록한다() {
        tossStub.enqueue(200, 발급응답_BASE64키);

        Response 응답 = post(ownerToken, customerKey, "test_auth_key_for_delete");

        assertThat(응답.status())
                .as("등록이 먼저 성공해야 삭제를 검사할 수 있다. 응답 본문=%s", 응답.body())
                .isEqualTo(200);
    }

    private long 카드_행수(UUID userId) {
        Long n = jdbcTemplate.queryForObject(
                "SELECT count(*) FROM billing_methods WHERE user_id = ?", Long.class, userId);
        return n == null ? 0 : n;
    }

    // ── 테스트 보조 ──────────────────────────────────────────────────────

    private String customerKeyOf(UUID userId) {
        return jdbcTemplate.queryForObject(
                "SELECT billing_customer_key FROM users WHERE id = ?", String.class, userId);
    }

    private Response post(String token, String customerKey, String authKey) {
        return request(HttpMethod.POST, "/api/billing/method", token,
                Map.of("authKey", authKey, "customerKey", customerKey));
    }

    private Response get(String token) {
        return request(HttpMethod.GET, "/api/billing/method", token, null);
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
