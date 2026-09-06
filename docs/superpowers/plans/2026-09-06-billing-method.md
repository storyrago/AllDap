# 결제 수단 등록 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 계정마다 카드 한 장을 토스페이먼츠 빌링키로 등록·조회·삭제할 수 있게 한다. **금액은 한 곳에도 나오지 않는다.**

**Architecture:** 카드번호는 토스 결제창 안에서만 존재하고 우리는 `authKey` 만 받아 서버에서 `billingKey` 로 바꾼다. `customerKey`(카드보다 오래 산다)는 `users` 에, `billingKey`(카드와 함께 죽는다)는 `billing_methods` 에 **AES-256-GCM 으로 암호화해** 둔다. 토스에는 **빌링키 조회 API 가 없어 우리 DB 가 유일한 사본**이므로, 발급에는 멱등키를, 삭제에는 "토스 먼저·우리 나중" 순서를 쓴다. Python(`ai-service/`)·위젯(`widget/`)은 한 줄도 안 고친다.

**Tech Stack:** Spring Boot 4.0.7 / Java 21 / Flyway / JPA(`ddl-auto=validate`) / `spring-security-crypto`(AES-GCM) / JUnit5 + Testcontainers, Next.js 16.2.12 + React 19.2.4 + TypeScript + `@tosspayments/tosspayments-sdk`

## Global Constraints

- 설계 원본은 `docs/superpowers/specs/2026-09-06-billing-method-design.md`. **금액·플랜·실제 청구는 이 계획의 범위가 아니다.**
- **Python(`ai-service/`)·위젯(`widget/`)을 고치지 않는다.** 고쳐야 할 것 같으면 멈추고 보고한다.
- `spring.jpa.hibernate.ddl-auto` 는 `validate` 다. **엔티티와 마이그레이션이 어긋나면 기동 자체가 실패한다.**
- **`V1`~`V5` 마이그레이션을 절대 고치지 않는다.** Flyway 체크섬이 깨져 다음 기동이 막힌다. 새 파일은 `V6__billing_method.sql`.
- 코드 주석·에러 메시지·테스트 이름은 **한국어**. 에러 응답 포맷은 전 계층 공통 `{ "error": { "code": "...", "message": "..." } }`.
- **JSON 표기 변환은 Spring 책임이다.** 토스는 `issuerCode`(코드)를 주고 프론트는 `issuerName`(이름)을 본다. 매핑을 프론트에 두면 `web/lib/types.ts` 가 거짓이 된다.
- `userId` 는 **`@AuthenticationPrincipal` 로만** 받는다. 쿼리 파라미터·본문으로 받으면 격리가 무너진다.
- 🔴 **응답 DTO 에 `billingKey` 필드를 두지 않는다.** 필드가 있으면 언젠가 실린다.
- **모바일 대응은 범위 밖이다**(2026-08-17 결정). 데스크톱만. 반응형을 먼저 제안하지 않는다.
- **화면·DTO·문서 어디에도 금액을 쓰지 않는다.** `/pricing` 의 "금액이 아직 없다"가 이 저장소의 약속이다.
- **`git add -A` 금지.** 작업 트리에 이 작업과 무관한 미커밋 파일이 있다(`widget/demo.html` 수정본, 미추적 `docs/이해노트-2026-09-01.md`). 경로를 명시해 스테이징한다.
- Spring 테스트: `cd api && ./gradlew test --tests '<클래스명>'` (Docker 필요 — Testcontainers).
- 프론트 검사: `cd web && npx tsc --noEmit && npm run lint`.
- 커밋 메시지 `<타입>: <한국어 요약>`, 본문 끝에 `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- **PR 생성까지가 범위다. CI 는 기다리지 않는다.**
- **거짓 완성 금지.** 검사를 실제로 돌리고 **그 출력을** PR 본문에 붙인다.

## 브랜치

```
main
 └─ docs/billing-method-design   ← 설계 문서 + 이 계획서 (이미 커밋됨)
     ├─ feat/billing-method      ← Task 1~4.  PR: main 으로
     └─ (같은 브랜치에서 Task 5) ← 문서·결정 로그.  PR: main 으로 (별도)
```

Task 1~4 는 `feat/billing-method` 하나 위에서 이어서 하고 Task 4 가 PR 을 연다.
Task 5 만 `docs/billing-method-design` 으로 돌아와 문서를 고치고 **별도 PR** 을 연다.
선례: 사용량 계량이 PR #52(feat) + PR #53(docs) 두 개였다.

> 🔴 **`AGENTS.md` 는 PR #54(핸드오프, 미머지)가 이미 고치고 있다.**
> 이 브랜치는 `main` 기점이라 그 변경이 없다 — `AGENTS.md` 의 W2 표에 사용량 계량 줄이 없고
> `#44~#49` 가 아직 "미머지" 로 적혀 있다. **Task 5 가 같은 표를 건드리므로 충돌한다.**
> Task 5 를 시작하기 전에 **PR #54 를 먼저 머지하고 `git rebase origin/main` 하라.**
> 그러지 않으려면 Task 5 의 `AGENTS.md` 편집을 PR #54 쪽으로 옮긴다. 어느 쪽이든 **사람에게 확인받는다.**

## 설계 문서에서 정제한 것

설계 문서는 삭제 실패를 "4xx 와 5xx 를 호출부가 구분한다" 는 모양으로 적었다.
**구현에서는 `TossClient` 가 4xx 에 예외를 던지지 않고 정상 반환한다.**
호출부가 두 경우에 하는 일이 이미 다르기 때문이다 — 4xx 는 "토스 쪽엔 이미 없다" 라 계속 진행하고,
5xx·I/O 는 "지워졌는지 모른다" 라 예외로 중단해야 한다. 예외의 유무가 그 구분을 그대로 표현하므로
`boolean` 을 돌려주고 호출부에서 `if` 로 나누는 것보다 분기가 하나 적다. 동작은 설계와 동일하다.

## 파일 구조

| 파일 | 책임 |
|---|---|
| `api/src/main/resources/db/migration/V6__billing_method.sql` | `users.billing_customer_key` + `billing_methods`. 다른 테이블을 건드리지 않는다 |
| `api/.../domain/user/entity/User.java` | `billingCustomerKey` 필드와 **생성**. `Bot.create()` 가 `publicKey` 를 만드는 것과 같은 자리 |
| `api/.../global/crypto/BillingCrypto.java` · `BillingCryptoProperties.java` | AES-256-GCM 암복호화 + **기동 시점 키 가드 4가지** |
| `api/.../global/config/TossProperties.java` · `TossClientConfig.java` | 토스 전용 `RestClient`. **`AiServiceClient` 와 빈을 공유하지 않는다** |
| `api/.../domain/billing/client/TossClient.java` + DTO 3개 | 토스 호출과 **실패 변환**. 외부 컨트랙트를 아는 코드는 이 폴더에서 끝난다 |
| `api/.../domain/billing/entity/BillingMethod.java` | 테이블 매핑. `ddl-auto=validate` 가 스키마 드리프트를 잡는다 |
| `api/.../domain/billing/repository/BillingMethodRepository.java` | `findByUserId` |
| `api/.../domain/billing/service/BillingService.java` · `CardIssuer.java` | 등록·조회·삭제 정책. `issuerCode` → 카드사 이름 |
| `api/.../domain/billing/dto/` | `RegisterBillingMethodRequest` · `BillingMethodResponse`(camelCase) |
| `api/.../domain/billing/controller/BillingController.java` | `GET`·`POST`·`DELETE /api/billing/method` |
| `api/.../global/exception/ErrorCode.java` | 4개 추가 |
| `api/.../resources/application{,-prod}.yaml` · `.env{,.prod}.example` · `docker-compose.prod.yml` | 새 환경변수 2개의 **배선** |
| `api/src/test/.../global/crypto/BillingCryptoTest.java` | 암복호화와 **기동 가드**를 테스트로 고정 (이 저장소 최초) |
| `api/src/test/.../support/TossStub.java` | 가짜 토스 서버. `AiServiceStub` 과 같은 패턴 |
| `api/src/test/.../domain/billing/BillingIntegrationTest.java` | 설계의 주장 12가지를 실제 HTTP·실제 DB 로 |
| `web/lib/types.ts` · `api.ts` · `app/(dashboard)/billing/page.tsx` · `layout.tsx` | 결제 수단 화면과 진입점 |
| `docs/decisions.md` · `DEPLOY.md` · `AGENTS.md` | 결정 로그·운영 절차·진행 상황 |

`billing` 을 별도 도메인 패키지로 두는 이유는 `usage` 와 같다 — 결제는 봇·채팅 어디에도 속하지 않는
**계정 단위 관심사**다. 패키지 안의 계층 분할(`controller/dto/entity/repository/service`)은
`domain/usage/` 관례를 그대로 따르고, 거기에 **`client/` 하나를 더한다**: 외부 스키마가 바뀌면
고칠 곳이 그 폴더 안에서 끝나야 한다(`global/client/AiServiceClient` 와 같은 이유).

---
## Task 1: 스키마와 암호화 — 빌링키를 안전하게 담을 자리 만들기

**Files:**
- Create: `api/src/main/resources/db/migration/V6__billing_method.sql`
- Create: `api/src/main/java/com/alldap/api/global/crypto/BillingCryptoProperties.java`
- Create: `api/src/main/java/com/alldap/api/global/crypto/BillingCrypto.java`
- Test: `api/src/test/java/com/alldap/api/global/crypto/BillingCryptoTest.java`
- Modify: `api/src/main/java/com/alldap/api/domain/user/entity/User.java`
- Modify: `api/src/main/resources/application.yaml`
- Modify: `api/src/main/resources/application-prod.yaml`
- Modify: `.env.prod.example`
- Modify: `docker-compose.prod.yml`

**Interfaces:**
- Consumes: 없다. 이 Task 가 브랜치의 첫 커밋이다.
- Produces:
  - `com.alldap.api.global.crypto.BillingCryptoProperties` — `record BillingCryptoProperties(String key)`, `@ConfigurationProperties(prefix = "app.billing-crypto")`
  - `com.alldap.api.global.crypto.BillingCrypto` — `@Service`, `BillingCrypto(BillingCryptoProperties, Environment)` · `String encrypt(String plaintext)` · `String decrypt(String stored)`
  - `com.alldap.api.domain.user.entity.User` — `public static final String BILLING_CUSTOMER_KEY_PREFIX = "bcus_"` · `String getBillingCustomerKey()` (`@Getter` 가 만든다) · `User.create(email, passwordHash, name)` 가 키를 생성해 채운다
  - DB: `users.billing_customer_key`(NOT NULL·UNIQUE) · `billing_methods` 테이블 (엔티티 매핑은 Task 2 에서 붙인다)

---

- [ ] **Step 1: 브랜치를 만든다**

설계 문서가 `docs/billing-method-design` 에 있으므로 거기서 딴다.

```bash
cd /Users/cheonjamin/projects/AllDap
git switch docs/billing-method-design
git switch -c feat/billing-method
git status --short
```

Expected: `feat/billing-method` 로 이동. `git status --short` 는 다음 둘만 보여야 한다 —

```
 M widget/demo.html
?? "docs/이해노트-2026-09-01.md"
```

> ⚠️ 이 두 개는 **이 작업과 무관한 기존 미커밋 파일**이다. 브랜치를 넘나들며 그대로 따라온다. **절대 커밋하지 말 것.** 이 Task 의 마지막 커밋은 경로를 하나씩 명시해 스테이징한다(`git add -A` 금지).
> ⚠️ 만약 `git switch` 가 `widget/demo.html` 때문에 거부되면 그건 `docs/billing-method-design` 과 현재 브랜치에서 그 파일이 서로 다르다는 뜻이다. 그 경우 `git stash push widget/demo.html` → 브랜치 생성 → `git stash pop` 으로 옮기고, **그렇게 했다는 사실을 보고에 적는다.**

---

- [ ] **Step 2: 실패하는 테스트를 먼저 쓴다 — `BillingCryptoTest`**

스프링 컨텍스트를 띄우지 않는 순수 단위 테스트다. `BillingCrypto` 는 프로퍼티 하나와 `Environment` 만 받는 객체라 컨텍스트를 띄울 이유가 없고, 띄우면 느려지는 만큼 자주 안 돌리게 된다(`AiServiceCircuitBreakerTest` 와 같은 판단이다).

`api/src/test/java/com/alldap/api/global/crypto/BillingCryptoTest.java` 를 새로 만든다:

```java
package com.alldap.api.global.crypto;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.mock.env.MockEnvironment;

import java.util.Base64;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 빌링키 암복호화를 테스트로 고정한다.
 *
 * <p><b>왜 이 테스트가 특별한가.</b> 이 저장소에는 "운영에서 공개 기본값이면 죽는다" 가드가
 * 이미 둘 있다({@code JwtService} 의 시크릿 검사, {@code application-prod.yaml} 의 fail-closed).
 * 그런데 <b>테스트로 고정된 것은 하나도 없다.</b> 가드는 조용히 무력해져도 아무도 모른다 —
 * yaml 의 기본값 문자열만 바꾸면 {@code JwtService} 의 블랙리스트 비교가 그냥 빗나간다.
 * 아래 5·6 번이 그 부류를 테스트로 붙드는 첫 사례다.
 *
 * <p>스프링 컨텍스트를 띄우지 않는다. {@link BillingCrypto} 는 프로퍼티와
 * {@code Environment} 만 받는 순수 객체라 그럴 이유가 없고, 컨텍스트를 띄우면
 * 느려지는 만큼 자주 안 돌리게 된다({@code AiServiceCircuitBreakerTest} 와 같은 판단).
 */
@DisplayName("빌링키 암복호화")
class BillingCryptoTest {

    /** Base64("test-only-billing-key-32-bytes!!") — 정확히 32바이트다. */
    private static final String KEY_A = "dGVzdC1vbmx5LWJpbGxpbmcta2V5LTMyLWJ5dGVzISE=";
    /** Base64("another-32-byte-billing-key-here") — 역시 32바이트, 다른 값. */
    private static final String KEY_B = "YW5vdGhlci0zMi1ieXRlLWJpbGxpbmcta2V5LWhlcmU=";

    /** 토스 빌링키를 흉내낸 값. 실제 형식이 중요한 테스트가 아니라 길이만 비슷하게 잡았다. */
    private static final String BILLING_KEY = "bln_20260906_abcdefghijklmnopqrstuvwxyz0123456789";

    /**
     * {@code MockEnvironment} 는 활성 프로파일이 <b>하나도 없는</b> 환경이다.
     * {@code BillingCrypto} 는 그것을 "개발 환경"으로 본다({@code JwtService} 와 같은 판정 기준) —
     * 그래서 여기서는 "저장소 공개 기본값" 가드가 발동하지 않고, 우리가 검사하려는
     * 길이·플레이스홀더 가드만 남는다.
     */
    private BillingCrypto crypto(String key) {
        return new BillingCrypto(new BillingCryptoProperties(key), new MockEnvironment());
    }

    @Test
    @DisplayName("암호화한 값을 다시 복호화하면 원래 빌링키가 나온다")
    void roundTrip() {
        BillingCrypto crypto = crypto(KEY_A);
        assertThat(crypto.decrypt(crypto.encrypt(BILLING_KEY))).isEqualTo(BILLING_KEY);
    }

    @Test
    @DisplayName("같은 값을 두 번 암호화하면 암호문이 다르다 — IV 가 매번 새로 생긴다")
    void sameInputProducesDifferentCiphertext() {
        BillingCrypto crypto = crypto(KEY_A);
        // 같은 평문이 같은 암호문이 되면, DB 만 봐도 "이 둘은 같은 카드다" 가 새어나간다.
        assertThat(crypto.encrypt(BILLING_KEY)).isNotEqualTo(crypto.encrypt(BILLING_KEY));
    }

    @Test
    @DisplayName("🔴 암호문을 한 비트라도 뒤집으면 복호화가 실패한다 — GCM 인증태그가 하는 일")
    void tamperedCiphertextIsRejected() {
        BillingCrypto crypto = crypto(KEY_A);
        byte[] combined = Base64.getDecoder().decode(crypto.encrypt(BILLING_KEY));
        // 인덱스 12 = IV(12바이트) 바로 다음, 즉 암호문의 첫 바이트다.
        // 이게 CBC 였다면 그냥 복호화에 성공하고 우리는 아무것도 눈치채지 못한다.
        combined[12] ^= 0x01;
        String tampered = Base64.getEncoder().encodeToString(combined);

        assertThatThrownBy(() -> crypto.decrypt(tampered))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("복호화하지 못했습니다");
    }

    @Test
    @DisplayName("🔴 다른 키로는 복호화할 수 없다 — 키를 잃으면 재등록뿐이라는 말의 실증")
    void otherKeyCannotDecrypt() {
        String stored = crypto(KEY_A).encrypt(BILLING_KEY);
        BillingCrypto other = crypto(KEY_B);

        // 토스에는 발급된 빌링키를 조회하는 API 가 없다. 우리 DB 가 유일한 사본이라
        // 키를 잃으면 전 고객이 카드를 다시 등록해야 한다 — 그 대가가 실재함을 여기서 못박는다.
        assertThatThrownBy(() -> other.decrypt(stored))
                .isInstanceOf(IllegalStateException.class);
    }

    @Test
    @DisplayName("🔴 키가 32바이트가 아니면 기동이 실패한다 — JCE 는 16바이트를 주면 말없이 AES-128 로 돈다")
    void shortKeyFailsFast() {
        // Base64("sixteen-byte-key") — 16바이트. 이 검사가 없으면 아무 오류 없이 AES-128 로 돌고,
        // 우리는 "AES-256 으로 저장합니다" 라고 말할 근거를 잃는다.
        assertThatThrownBy(() -> crypto("c2l4dGVlbi1ieXRlLWtleQ=="))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("32바이트");
    }

    @Test
    @DisplayName("🔴 ${...} 리터럴이 그대로 들어오면 기동이 실패한다")
    void unresolvedPlaceholderFailsFast() {
        // @ConfigurationProperties 는 해석하지 못한 플레이스홀더를 <예외 없이 리터럴로> 바인딩한다
        // (@Value 와 다르다). 그대로 두면 "${BILLING_CRYPTO_KEY}" 라는 문자열이 Base64 디코딩에
        // 걸려 알 수 없는 영어 예외만 남는다. 무엇을 어떻게 고칠지 한국어로 알려주려면 여기서 잡아야 한다.
        assertThatThrownBy(() -> crypto("${BILLING_CRYPTO_KEY}"))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("BILLING_CRYPTO_KEY");
    }
}
```

---

- [ ] **Step 3: 테스트를 돌려 실패를 확인한다**

```bash
cd /Users/cheonjamin/projects/AllDap/api && ./gradlew test --tests 'BillingCryptoTest'
```

Expected: FAIL — `Task :compileTestJava FAILED` 와 함께

```
src/test/java/com/alldap/api/global/crypto/BillingCryptoTest.java:[줄번호]: error: cannot find symbol
    private BillingCrypto crypto(String key) {
            ^
  symbol:   class BillingCrypto
  location: class BillingCryptoTest
1 error
```

> ⚠️ Docker 가 필요 없다. 이 테스트는 Testcontainers 를 쓰지 않는다. Docker 데몬 관련 오류가 나면 그건 **다른 문제**이니 그 사실을 보고에 적는다.

---

- [ ] **Step 4: `BillingCryptoProperties` 를 만든다**

`api/src/main/java/com/alldap/api/global/crypto/BillingCryptoProperties.java`:

```java
package com.alldap.api.global.crypto;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 빌링키 암호화 설정. {@code application.yaml} 의 {@code app.billing-crypto.*} 를 바인딩한다.
 *
 * <p>record 로 둔 이유는 {@code AiServiceProperties}·{@code JwtProperties} 와 같다 —
 * 설정값은 기동 시점에 정해지고 이후 바뀌지 않으므로 불변이 맞다.
 * 별도 등록은 필요 없다. {@code ApiApplication} 의 {@code @ConfigurationPropertiesScan} 이 찾아준다.
 *
 * @param key AES-256 키. <b>Base64 로 인코딩된 32바이트</b>여야 한다.
 *            생성: {@code openssl rand -base64 32}
 *            검증(길이·플레이스홀더·공개 기본값)은 {@link BillingCrypto} 생성자가 한다 —
 *            여기서 하지 않는 이유는 record 의 compact 생성자에서 던지면
 *            바인딩 실패 예외에 묻혀 <b>우리가 쓴 한국어 안내가 사용자에게 안 보이기</b> 때문이다.
 */
@ConfigurationProperties(prefix = "app.billing-crypto")
public record BillingCryptoProperties(String key) {
}
```

---

- [ ] **Step 5: `BillingCrypto` 를 만든다**

`api/src/main/java/com/alldap/api/global/crypto/BillingCrypto.java`:

```java
package com.alldap.api.global.crypto;

import lombok.extern.slf4j.Slf4j;
import org.springframework.core.env.Environment;
import org.springframework.security.crypto.encrypt.AesBytesEncryptor;
import org.springframework.security.crypto.keygen.KeyGenerators;
import org.springframework.stereotype.Service;

import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Base64;
import java.util.Locale;
import java.util.Set;

/**
 * 토스 빌링키를 DB 에 넣기 전에 암호화하고, 읽을 때 복호화한다.
 *
 * <h2>왜 암호화하는가</h2>
 * 빌링키는 "이 카드에 청구해도 된다"는 <b>열쇠 그 자체</b>다. 그리고 토스에는
 * <b>발급된 빌링키를 조회하는 API 가 없다</b> — 우리 DB 가 유일한 사본이다.
 * 그래서 두 방향이 모두 치명적이다: DB 덤프가 새면 그대로 결제 수단 유출이고,
 * 우리가 키를 잃으면 전 고객이 카드를 다시 등록해야 한다.
 *
 * <h2>왜 새 의존성이 없는가</h2>
 * {@code spring-boot-starter-security} 가 이미 전이로 끌고 오는
 * {@code spring-security-crypto} 의 {@link AesBytesEncryptor} 를 <b>원시 키 생성자</b>로 쓴다.
 * Bouncy Castle 은 클래스패스에 없고, 넣을 이유도 없다.
 *
 * <h2>왜 {@code Encryptors.text()} / {@code delux()} 가 아닌가 (7.0.6 소스로 확인함)</h2>
 * <ul>
 *   <li>{@code Encryptors.text()} 는 GCM 이 아니라 {@code AES/CBC/PKCS5Padding} 이다.
 *       CBC 는 <b>인증이 없어</b> 암호문을 한 바이트 뒤집어도 복호화가 그냥 성공한다.
 *       DB 를 만질 수 있는 공격자가 남의 빌링키로 바꿔치기해도 우리가 눈치채지 못한다.</li>
 *   <li>{@code delux()} 는 GCM 은 맞지만 키를 {@code PBKDF2WithHmacSHA1} <b>1024회</b>로 유도한다.
 *       우리는 이미 32바이트 난수를 환경변수로 갖고 있어 유도할 이유가 없고, 1024회는 2026년 기준으로 낮다.</li>
 * </ul>
 *
 * <h2>키 회전은 만들지 않는다</h2>
 * 막다른 길은 아니다 — 나중에 새 키를 도입할 때 저장값에 {@code v2:} 접두사를 붙이면
 * <b>접두사 없는 행 = 옛 키</b>로 소급 판별된다. 지금 미리 그 문법을 만들 이유가 없다.
 */
@Slf4j
@Service
public class BillingCrypto {

    /**
     * {@code application.yaml} 에 박혀 있는(= 저장소에 공개된) 로컬 개발용 기본 키.
     *
     * <p>여기에 값을 <b>복사해두는 것 자체가 목적</b>이다. "이 값은 이미 공개됐으니 운영에서 쓰면 안 된다"는
     * 블랙리스트이기 때문이다. {@code JwtService.KNOWN_LOCAL_DEFAULT_SECRET} 과 똑같은 약한 고리를
     * 공유한다 — yaml 의 기본값만 바꾸면 이 가드는 아무 말 없이 무력해진다.
     * 그래서 yaml 쪽에도 "이 값을 바꾸면 여기도 함께 바꾸라"는 주석을 남겨뒀다.
     *
     * <p>값은 Base64("alldap-local-dev-billing-key-32b") 로, 디코딩하면 정확히 32바이트다.
     */
    private static final String KNOWN_LOCAL_DEFAULT_KEY = "YWxsZGFwLWxvY2FsLWRldi1iaWxsaW5nLWtleS0zMmI=";

    /**
     * "여긴 개발 환경이다"로 인정할 프로파일 이름들. {@code JwtService} 와 같은 목록·같은 근거다 —
     * 반대로(운영 프로파일을 나열해서) 판단하면 {@code staging} 같은 이름이 생길 때마다 가드가 조용히 뚫린다.
     */
    private static final Set<String> DEVELOPMENT_PROFILES = Set.of("local", "dev", "development", "test");

    private static final int AES_256_KEY_BYTES = 32;

    /**
     * GCM 의 IV(논스) 길이. 12바이트는 NIST SP 800-38D 권장값이다.
     *
     * <p>⚠️ {@code CipherAlgorithm.GCM} 의 <b>기본 IV 생성기는 16바이트</b>다
     * ({@code KeyGenerators.secureRandom(16)}). 기본값에 맡기지 않고 명시하는 이유는
     * 저장 크기를 우리가 계산해 컬럼 폭을 정했기 때문이다 — {@code V6__billing_method.sql} 의
     * {@code billing_key_enc VARCHAR(512)} 주석이 12바이트를 전제로 한다.
     * <b>이 값을 바꾸면 이미 저장된 행을 복호화할 수 없다</b>(IV 를 잘라 읽는 길이가 달라진다).
     */
    private static final int GCM_IV_BYTES = 12;

    /**
     * {@code AesBytesEncryptor} 는 {@code encrypt}/{@code decrypt} 안에서 Cipher 를
     * {@code synchronized} 로 감싸므로 여러 스레드가 공유해도 안전하다. 요청마다 만들지 않는다.
     */
    private final AesBytesEncryptor encryptor;

    /**
     * Lombok {@code @RequiredArgsConstructor} 를 쓰지 않는 이유는 {@code JwtService} 와 같다:
     * {@code encryptor} 는 주입받는 값이 아니라 <b>주입값에서 파생되는 값</b>이다.
     *
     * <p>검증을 생성자에서 하는 것이 핵심이다. 여기서 예외가 나면 스프링 컨텍스트 초기화가 실패해
     * <b>톰캣이 요청을 받기 전에</b> 죽는다. 설정 실수가 "조용히 잘 도는 것"이 최악이다 —
     * 결제에서는 몇 달 뒤 "복호화가 안 된다"로 드러나고, 그때는 되돌릴 방법이 없다.
     */
    public BillingCrypto(BillingCryptoProperties properties, Environment environment) {
        byte[] keyBytes = decodeAndValidate(properties.key(), environment);
        this.encryptor = new AesBytesEncryptor(
                new SecretKeySpec(keyBytes, "AES"),
                KeyGenerators.secureRandom(GCM_IV_BYTES),
                AesBytesEncryptor.CipherAlgorithm.GCM);
    }

    private byte[] decodeAndValidate(String key, Environment environment) {
        // ① 미주입 / 공백 / 해석 안 된 플레이스홀더.
        //    @ConfigurationProperties 는 해석 못 한 ${BILLING_CRYPTO_KEY} 를 예외 없이
        //    <리터럴 문자열로> 바인딩한다(@Value 와 다르다). 그대로 두면 알 수 없는 영어 예외만 남는다.
        if (key == null || key.isBlank() || key.startsWith("${")) {
            throw new IllegalStateException(
                    "결제 수단 암호화 키(app.billing-crypto.key)가 설정되지 않았습니다. "
                            + "BILLING_CRYPTO_KEY 환경변수에 Base64 로 인코딩한 32바이트 난수를 넣어주세요. "
                            + "예: openssl rand -base64 32");
        }

        // ② Base64 로 읽을 수 있는가.
        byte[] decoded;
        try {
            decoded = Base64.getDecoder().decode(key.trim());
        } catch (IllegalArgumentException e) {
            throw new IllegalStateException(
                    "결제 수단 암호화 키(app.billing-crypto.key)가 Base64 형식이 아닙니다. "
                            + "openssl rand -base64 32 의 출력을 그대로 넣어주세요.", e);
        }

        // ③ 저장소에 공개된 로컬 기본값인가. 개발이면 경고, 아니면 기동 중단.
        if (KNOWN_LOCAL_DEFAULT_KEY.equals(key.trim())) {
            String[] activeProfiles = environment.getActiveProfiles();
            // 프로파일이 하나도 없는 경우를 '개발'로 보는 트레이드오프는 JwtService 와 동일하다 —
            // 로컬 bootRun·IDE 실행·통합 테스트가 전부 프로파일 없이 돈다. 잔여 위험도 같이 상속한다.
            boolean development = activeProfiles.length == 0
                    || Arrays.stream(activeProfiles)
                    .anyMatch(profile -> DEVELOPMENT_PROFILES.contains(profile.toLowerCase(Locale.ROOT)));
            if (!development) {
                throw new IllegalStateException("""
                        결제 수단 암호화 키(app.billing-crypto.key)가 저장소에 공개된 로컬 기본값 그대로입니다. \
                        이 값을 아는 사람은 DB 만 손에 넣으면 전 고객의 빌링키를 복호화해 결제를 일으킬 수 있으므로 기동을 중단합니다.
                        → 배포 환경이라면: BILLING_CRYPTO_KEY 환경변수를 설정한 뒤 다시 실행하세요. (openssl rand -base64 32)
                        → 로컬 개발이라면: SPRING_PROFILES_ACTIVE=local 로 실행하거나 프로파일 없이 실행하세요.
                        현재 활성 프로파일: %s""".formatted(Arrays.toString(activeProfiles)));
            }
            log.warn("[BILLING] 저장소에 공개된 로컬 기본 암호화 키로 기동한다. 배포 환경에서는 반드시 BILLING_CRYPTO_KEY 를 설정할 것.");
        }

        // ④ 길이가 정확히 32바이트인가.
        //    🔴 이 검사가 가장 조용한 실패를 막는다 — JCE 는 16바이트 키를 주면 아무 말 없이
        //       AES-128 로 돈다. 확인하지 않으면 "AES-256 으로 저장합니다" 라고 말할 근거가 없다.
        if (decoded.length != AES_256_KEY_BYTES) {
            throw new IllegalStateException(
                    "결제 수단 암호화 키(app.billing-crypto.key)의 길이가 %d바이트입니다. AES-256 은 정확히 32바이트를 요구합니다. "
                            .formatted(decoded.length)
                            + "openssl rand -base64 32 로 새로 만들어 BILLING_CRYPTO_KEY 에 넣어주세요.");
        }
        return decoded;
    }

    /**
     * 평문 빌링키 → 저장 문자열.
     *
     * <p>결과는 {@code Base64(IV 12B ‖ 암호문 ‖ GCM 인증태그 16B)} 한 덩어리다.
     * IV 컬럼을 따로 두지 않는 이유는 {@code V6__billing_method.sql} 주석에 적어뒀다 —
     * IV 는 비밀이 아니고 암호문과 반드시 짝이라, 나누면 한쪽만 갱신·복사되어 어긋날 수 있다.
     */
    public String encrypt(String plaintext) {
        byte[] combined = encryptor.encrypt(plaintext.getBytes(StandardCharsets.UTF_8));
        return Base64.getEncoder().encodeToString(combined);
    }

    /**
     * 저장 문자열 → 평문 빌링키.
     *
     * <p>실패를 <b>한 종류로 뭉쳐서</b> 던진다. 이건 이 저장소가 반복해 낸 "서로 다른 사실을 같은 값으로
     * 뭉개는" 실수와는 성격이 다르다 — 여기서 갈라지는 원인(키가 다르다 · 데이터가 손상됐다 ·
     * Base64 가 깨졌다)은 <b>운영자가 할 일이 전부 같다</b>(고객에게 재등록 안내).
     * 오히려 라이브러리의 영어 {@code IllegalStateException("bad padding")} 을 그대로 흘리면
     * 무엇을 해야 하는지 알 수 없다.
     */
    public String decrypt(String stored) {
        try {
            byte[] combined = Base64.getDecoder().decode(stored);
            return new String(encryptor.decrypt(combined), StandardCharsets.UTF_8);
        } catch (RuntimeException e) {
            // GCM 인증태그 불일치는 AEADBadTagException → BadPaddingException 을 거쳐
            // spring-security-crypto 의 CipherUtils 가 IllegalStateException 으로 바꿔 던진다.
            // Base64 가 깨졌으면 IllegalArgumentException 이다. 둘 다 RuntimeException 이라 한 번에 받는다.
            throw new IllegalStateException(
                    "저장된 결제 수단을 복호화하지 못했습니다. BILLING_CRYPTO_KEY 가 등록 당시와 다르거나 "
                            + "billing_key_enc 값이 손상됐습니다. 고객에게 카드를 다시 등록하도록 안내해주세요.", e);
        }
    }
}
```

---

- [ ] **Step 6: 테스트를 돌려 통과를 확인한다**

```bash
cd /Users/cheonjamin/projects/AllDap/api && ./gradlew test --tests 'BillingCryptoTest' \
  && grep -o 'tests="[0-9]*" skipped="[0-9]*" failures="[0-9]*" errors="[0-9]*"' \
       build/test-results/test/TEST-com.alldap.api.global.crypto.BillingCryptoTest.xml
```

Expected: PASS (6건) — `BUILD SUCCESSFUL` 과 함께 정확히 이 줄이 나온다:

```
tests="6" skipped="0" failures="0" errors="0"
```

> `BUILD SUCCESSFUL` 만으로는 **테스트가 0건 돌았어도 성공**이다. 그래서 XML 리포트의 건수를 함께 읽는다. **이 줄을 그대로 보고에 붙일 것.**

---

- [ ] **Step 7: `application.yaml` 에 로컬 기본 키를 넣는다**

`api/src/main/resources/application.yaml` 의 `app:` 블록에서 **`jwt:` 바로 위**(= `ai-service:` 와 `jwt:` 사이)에 형제로 끼워 넣는다. 들여쓰기는 두 칸이다(`ai-service:`·`jwt:`·`widget:`·`cors:` 와 같은 깊이).

찾을 위치 — 이 두 줄 사이:
```yaml
    circuit-open-duration: 30s
  jwt:
```

넣을 내용:
```yaml
    circuit-open-duration: 30s
  billing-crypto:
    # 토스 빌링키를 DB 에 넣기 전 암호화하는 AES-256 키. Base64 로 인코딩한 32바이트다.
    # ⚠️ 아래 기본값은 로컬 전용이다. 운영에서는 반드시 BILLING_CRYPTO_KEY 를 주입할 것.
    #    (application-prod.yaml 은 기본값 없이 환경변수를 강제한다)
    # 이 값을 바꾸면 BillingCrypto.KNOWN_LOCAL_DEFAULT_KEY 도 함께 바꿀 것 —
    # "공개된 기본값으로 운영에 뜨는 것"을 막는 기동 가드가 이 문자열을 비교한다.
    # 🔴 그리고 이 키를 바꾸면 <이미 저장된 카드는 복호화되지 않는다.> 토스에 조회 API 가 없어
    #    우리 DB 가 유일한 사본이라, 바꾸는 순간 그 고객들은 카드를 다시 등록해야 한다.
    # 생성: openssl rand -base64 32
    key: ${BILLING_CRYPTO_KEY:YWxsZGFwLWxvY2FsLWRldi1iaWxsaW5nLWtleS0zMmI=}
  jwt:
```

---

- [ ] **Step 8: `application-prod.yaml` 에 기본값 없이 넣는다**

`api/src/main/resources/application-prod.yaml` 의 `app:` 블록, `ai-service:` 와 `jwt:` 사이에 형제로 넣는다.

찾을 위치 — 이 두 줄 사이:
```yaml
    read-timeout: ${AI_SERVICE_READ_TIMEOUT:120s}
  jwt:
```

넣을 내용:
```yaml
    read-timeout: ${AI_SERVICE_READ_TIMEOUT:120s}
  billing-crypto:
    # 🔴 기본값을 두지 않는다. 이 파일의 fail-closed 원칙 그대로다 —
    #    공개된 로컬 키로 운영에 뜨면 DB 를 손에 넣은 사람이 전 고객의 빌링키를 복호화한다.
    #    (BillingCrypto 생성자에도 같은 가드가 있다. 두 겹으로 둔 이유는
    #     프로파일을 깜빡하고 배포하면 이 파일 자체가 안 읽히기 때문이다)
    # 🔴 한 번 정하면 바꿀 수 없다. 바꾸는 순간 이미 등록된 카드가 전부 복호화 불가가 된다.
    key: ${BILLING_CRYPTO_KEY}
  jwt:
```

---

- [ ] **Step 9: 배포 환경변수를 실제로 이어준다**

Step 8 때문에 **prod 는 이제 `BILLING_CRYPTO_KEY` 없이는 기동하지 않는다.** 예시 파일과 compose 에 배선하지 않으면 다음 배포가 그대로 죽는다.

① `.env.prod.example` — `JWT_SECRET=` 줄 바로 아래에 이어 붙인다:

```
# 결제 수단(토스 빌링키) 암호화 키. Base64 로 인코딩한 32바이트. 예: openssl rand -base64 32
# 🔴 이 값을 잃거나 바꾸면 <이미 등록된 카드를 전부 복호화할 수 없다.>
#    토스에는 발급된 빌링키를 조회하는 API 가 없어 우리 DB 가 유일한 사본이고,
#    잃으면 전 고객이 카드를 다시 등록하는 것 말고는 방법이 없다. 백업해둘 것.
BILLING_CRYPTO_KEY=
```

② `docker-compose.prod.yml` 의 `api:` 서비스 `environment:` 에서 `JWT_SECRET: ${JWT_SECRET}` 줄 바로 아래에 넣는다:

```yaml
      # 빌링키 암호화 키. application-prod.yaml 이 기본값을 안 두므로 없으면 기동 실패한다.
      BILLING_CRYPTO_KEY: ${BILLING_CRYPTO_KEY}
```

> ⚠️ 이 저장소는 **"배포 시점 미검증"으로 실제 사고를 낸 적이 있다**(2026-09-05, PR #44 가 Caddy 재생성 누락으로 운영에 적용조차 안 됐다). 두 줄 배선이 이 Task 에 붙어 있는 이유가 그것이다.
> ⚠️ 실제 배포 검증은 이 Task 의 범위가 아니다. **키를 서버에 넣기 전까지 prod 배포를 하지 말 것.**

---

- [ ] **Step 10: `V6__billing_method.sql` 을 만든다**

`api/src/main/resources/db/migration/V6__billing_method.sql`:

```sql
-- 결제 수단(토스 빌링키) 저장 (2026-09-06)
--
-- 소유권: Spring 이 쓰고 Spring 이 읽는다. Python 은 건드리지 않는다.
--
-- 왜 테이블을 나눴나: customerKey 는 카드보다 오래 산다(카드를 빼도 남아야
-- 재등록 시 토스 쪽 고객 이력이 이어진다). billingKey 는 카드와 함께 죽는다.
-- 수명이 다른 둘을 한 곳에 두면 삭제할 때 반드시 한쪽을 잘못 다루게 된다.

-- ① customerKey 는 users 에.
--    토스 제약(문서 원문): "영문 대소문자, 숫자, 특수문자 - _ = . @ 를 최소 1개 이상 포함한
--    최소 2자 이상 최대 50자 이하". 'bcus_' + 32 hex = 37자로 들어간다.
--
--    users.id(UUID)를 그대로 쓰지 않는 이유: 내부 기본키가 외부 업체의 대시보드·로그·CS 이력에
--    그대로 찍힌다. 저장소에 이미 같은 선례가 있다 — bots.public_key('pk_...') 가 정확히
--    그 패턴이다(봇 UUID 를 고객 사이트 HTML 에 노출하지 않으려고 만든 별도 공개키).
ALTER TABLE users ADD COLUMN IF NOT EXISTS billing_customer_key VARCHAR(50);

-- 기존 계정을 메꾼다. 이걸 안 하면 NOT NULL 을 걸 수 없고,
-- NOT NULL 이 아니면 "customerKey 없는 사용자" 라는 다룰 필요 없는 상태가 영구히 남는다.
UPDATE users SET billing_customer_key = 'bcus_' || replace(gen_random_uuid()::text, '-', '')
 WHERE billing_customer_key IS NULL;

ALTER TABLE users ALTER COLUMN billing_customer_key SET NOT NULL;
ALTER TABLE users ADD CONSTRAINT uq_users_billing_customer_key UNIQUE (billing_customer_key);

-- ② 카드는 별도 테이블. 삭제가 "행 하나 지우기" 가 된다
--    (컬럼 4개를 NULL 로 되돌리는 것보다 의도가 분명하다).
CREATE TABLE IF NOT EXISTS billing_methods (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  -- 🔴 ON DELETE CASCADE 는 필수다. V5 에서 이걸 뺐다가 통합 테스트 11건이 깨졌다 —
  --    전 테스트가 userRepository.deleteAll() 로 정리하는데 그 FK 가 정리를 막았다.
  --    UNIQUE 가 "계정당 카드 1장" 을 DB 수준에서 보장한다. 토스는 같은 카드로
  --    빌링키를 몇 개든 발급해주고 중복 방지 수단이 없으므로, 이 제약이 유일한 방어다.
  user_id            UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,

  -- Base64(IV 12B ‖ 암호문 ‖ GCM 인증태그 16B) 한 덩어리. IV 컬럼을 따로 두지 않는다 —
  -- IV 는 비밀이 아니고 암호문과 반드시 짝이라, 나누면 한쪽만 갱신·복사되어 어긋날 수 있다.
  -- 길이: 빌링키 최대 200자(토스 문서) → 12+200+16 = 228B → Base64 304자. 512 면 넉넉하다.
  -- 컬럼명에 _enc 를 붙여 "여기 든 게 평문이 아니다" 를 스키마에서부터 말한다.
  billing_key_enc    VARCHAR(512) NOT NULL,

  -- ⚠️ 토스가 카드사 <이름> 을 안 준다. 버전 2024-06-01 부터 응답에서 cardCompany 가 제거됐고
  --    card.issuerCode("61" 같은 두 자리 코드)만 온다. 코드→이름 매핑은 우리가 상수로 들고 있는다.
  --    (코드표: https://docs.tosspayments.com/reference/codes)
  issuer_code        VARCHAR(4)  NOT NULL,
  card_number_masked VARCHAR(20) NOT NULL,   -- "43301234****123*" — 토스가 마스킹해서 준다

  created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

> ⚠️ **`V1`~`V5` 는 한 글자도 고치지 말 것.** 이미 적용된 마이그레이션을 고치면 Flyway 체크섬이 어긋나 다음 기동이 막힌다(주석 한 글자도 포함된다).
> ⚠️ `billing_methods` 에 대응하는 JPA 엔티티는 **이 Task 에서 만들지 않는다**(Task 3 의 몫). 매핑되지 않은 테이블은 `ddl-auto=validate` 가 보지 않으므로 기동에 문제가 없다 — 바로 다음 Step 이 그 사실 자체를 이용한다.

---

- [ ] **Step 11: 🔴 `ddl-auto=validate` 의 <비대칭>을 실측한다 — 컨텍스트는 그냥 뜬다**

여기서 확인하려는 것은 "잘 됐다"가 아니라 **"이 검사가 우리를 지켜주지 않는다"** 는 사실이다.

```bash
cd /Users/cheonjamin/projects/AllDap/api && ./gradlew test --tests 'ApiApplicationTests'
```

Expected: **PASS (1건)** — 컬럼을 추가했는데 `User` 엔티티에는 필드가 없는데도 통과한다.

이유: Hibernate 의 `validate` 는 **매핑된 필드 → DB 컬럼** 한 방향만 검사한다(`missing column [x] in table [y]`). **DB 에만 있고 매핑되지 않은 컬럼은 아예 쳐다보지 않는다.** 즉,

| 어긋남 | `validate` | 언제 드러나나 |
|---|---|---|
| 엔티티 필드 O · 컬럼 X | **기동 실패** | 즉시, 시끄럽게 |
| 컬럼 O · 엔티티 필드 X | **조용히 통과** | 🔴 **가입할 때** — Hibernate 의 INSERT 문에 그 컬럼이 없어 NOT NULL 위반 |

이 저장소가 반복해 낸 부류(**"돌았다"와 "제대로 됐다"를 같은 값으로 뭉개기**)가 도구 안에 들어 있는 셈이다. 다음 Step 이 그 두 번째 줄을 눈으로 보여준다.

> ⚠️ Docker 데몬이 필요하다(Testcontainers). `Could not find a valid Docker environment` 가 나면 Docker Desktop 을 켜고 다시 돌린다.
> ⚠️ 만약 여기서 **PASS 가 아니라 FAIL** 이 나면, 그건 Hibernate 가 반대 방향까지 검사한다는 뜻이라 위 표가 틀린 것이다. 그 경우 **에러 전문을 보고에 적고** Step 12 를 건너뛰어 Step 13(엔티티 추가)으로 바로 간다.
> ⚠️ 옛 볼륨이 남아 `Found non-empty schema(s) "public" but no schema history table` 이 나오면 `docker compose down -v` 로 볼륨을 비우고 다시 돌린다. **그렇게 했다면 보고에 적는다.**

---

- [ ] **Step 12: 🔴 마이그레이션만으로는 가입이 깨진다는 것을 실측한다**

```bash
cd /Users/cheonjamin/projects/AllDap/api && ./gradlew test --tests 'AuthIntegrationTest'
```

Expected: **FAIL** — 여러 건이 깨지고, 실패 원인 로그에 정확히 이 문구가 있다:

```
ERROR: null value in column "billing_customer_key" of relation "users" violates not-null constraint
```

가입 응답은 201 이 아니라 **500** 이 된다(`GlobalExceptionHandler` 의 마지막 `@ExceptionHandler(Exception.class)` 에 걸린다).

> ⚠️ **정확한 실패 건수는 중요하지 않다.** 8건 중 로그인/가입을 거치는 테스트만 깨진다(토큰 없이 접근하는 케이스는 그대로 통과한다). 확인해야 할 것은 **위 로그 한 줄**이다 — 그것을 보고에 그대로 붙인다.
> ⚠️ Step 11 이 PASS 였는데 이 Step 이 PASS 라면 무언가 어긋난 것이다(V6 가 실제로 적용되지 않았을 가능성이 크다). 그 경우 `docker compose down -v` 후 다시 돌리고, **그래도 PASS 라면 멈추고 보고한다.**

---

- [ ] **Step 13: `User` 엔티티에 `billingCustomerKey` 를 추가한다**

`api/src/main/java/com/alldap/api/domain/user/entity/User.java` 를 네 군데 고친다.

**① import 두 개 추가** — `java.util.UUID` 위에:

```java
import java.security.SecureRandom;
import java.util.HexFormat;
import java.util.UUID;
```

**② 클래스 javadoc 의 스키마 대조 블록** — `name` 줄과 `created_at` 줄 사이에 한 줄 넣는다:

```java
 * name          VARCHAR(50)              ← nullable
 * billing_customer_key VARCHAR(50) UNIQUE NOT NULL   ← V6. Spring 이 생성해 넣는다
 * created_at    TIMESTAMPTZ NOT NULL     ← BaseEntity
```

**③ 클래스 본문 맨 위(`@Id` 필드 <앞>)에 상수 세 개**:

```java
    /**
     * 토스에 보내는 우리 쪽 고객 식별자의 접두사.
     *
     * <p><b>왜 {@code users.id}(UUID)를 그대로 쓰지 않는가.</b> 토스의 형식 요구는 만족하지만,
     * 그러면 <b>내부 기본키가 외부 업체에 그대로 나간다</b> — 토스 대시보드·로그·CS 이력에 우리 PK 가 찍힌다.
     * {@code Bot.publicKey}('pk_...')가 정확히 같은 이유로 존재한다(봇 UUID 를 고객 사이트 HTML 에
     * 노출하지 않으려고 만든 별도 공개키). 결제도 같은 규칙을 따른다.
     *
     * <p><b>왜 카드가 아니라 사용자에 붙는가.</b> customerKey 는 카드보다 오래 산다 —
     * 카드를 빼도 남아야 재등록 시 토스 쪽 고객 이력이 이어진다.
     * 반대로 billingKey 는 카드와 함께 죽으므로 별도 테이블({@code billing_methods})에 있다.
     */
    public static final String BILLING_CUSTOMER_KEY_PREFIX = "bcus_";

    /**
     * 128비트 난수 → 소문자 hex 32자. 접두사 포함 37자로 {@code VARCHAR(50)} 에 들어간다.
     *
     * <p>{@code Bot.generatePublicKey()} 는 URL-safe Base64 를 쓰는데 여기서는 hex 다.
     * 이유 둘: ① 토스의 허용 문자 제약(영문·숫자·{@code - _ = . @})에 hex 는 고민 없이 들어간다.
     * ② {@code V6__billing_method.sql} 이 기존 계정을 메꿀 때
     * {@code replace(gen_random_uuid()::text,'-','')} 로 <b>같은 모양</b>을 만든다 —
     * 생성 경로가 둘인데 결과 형식이 다르면 나중에 "이건 어느 쪽이 만든 키지"를 따지게 된다.
     */
    private static final int BILLING_CUSTOMER_KEY_RANDOM_BYTES = 16;
    private static final SecureRandom RANDOM = new SecureRandom();
```

**④ `name` 필드 아래에 컬럼 매핑, 그리고 `create()` 와 생성 메서드**:

```java
    @Column(name = "name", length = 50)
    private String name;

    /**
     * 토스에 보내는 고객 식별자. 계정이 사는 동안 바뀌지 않는다 —
     * 카드를 지웠다 다시 넣어도 <b>같은 값이어야</b> 토스 쪽 고객 이력이 이어진다.
     * 그래서 바꾸는 도메인 메서드를 두지 않았다(setter 도 없다).
     *
     * <p>⚠️ 이 필드를 지우면 {@code ddl-auto=validate} 는 <b>통과한다</b>(매핑되지 않은 컬럼은
     * 검사 대상이 아니다). 대신 가입 INSERT 에 컬럼이 빠져 NOT NULL 위반으로 500 이 난다 —
     * 기동이 아니라 <b>첫 가입에서</b> 드러나는 종류의 고장이다.
     */
    @Column(name = "billing_customer_key", length = 50, nullable = false, unique = true)
    private String billingCustomerKey;
```

`create()` 에 한 줄 추가:

```java
    public static User create(String email, String passwordHash, String name) {
        User user = new User();
        user.email = email;
        user.passwordHash = passwordHash;
        user.name = name;
        // 생성 책임을 여기(도메인) 안에 둔다. Bot.create() 가 publicKey 를 만드는 것과 같은 이유 —
        // 생성 위치가 밖에 있으면 "키를 안 넣고 만든 행"이 생길 여지가 남는다.
        // 컬럼이 NOT NULL 이라 그런 행은 DB 가 거절하지만, 거절은 <가입 실패>로 사용자에게 간다.
        // 불변식은 그것을 지켜야 하는 객체 안에서 지키는 게 맞다.
        user.billingCustomerKey = generateBillingCustomerKey();
        return user;
    }

    private static String generateBillingCustomerKey() {
        byte[] bytes = new byte[BILLING_CUSTOMER_KEY_RANDOM_BYTES];
        RANDOM.nextBytes(bytes);
        return BILLING_CUSTOMER_KEY_PREFIX + HexFormat.of().formatHex(bytes);
    }
```

> `User.create` 를 부르는 곳은 `AuthService:94` 하나뿐이고 **시그니처가 그대로**라 호출부는 고칠 것이 없다.

---

- [ ] **Step 14: 가입이 되살아나는지 확인한다**

```bash
cd /Users/cheonjamin/projects/AllDap/api && ./gradlew test --tests 'AuthIntegrationTest' \
  && grep -o 'tests="[0-9]*" skipped="[0-9]*" failures="[0-9]*" errors="[0-9]*"' \
       build/test-results/test/TEST-com.alldap.api.domain.auth.AuthIntegrationTest.xml
```

Expected: PASS (8건) —

```
tests="8" skipped="0" failures="0" errors="0"
```

---

- [ ] **Step 15: 🔴 전체 테스트를 돌려 기존 것이 안 깨졌는지 확인한다**

`User.create` 를 건드렸다 = **모든 통합 테스트가 영향권**이다(전부 `/api/auth/signup` 으로 사용자를 만든다).

```bash
cd /Users/cheonjamin/projects/AllDap/api && ./gradlew cleanTest test \
  && grep -h '<testsuite ' build/test-results/test/*.xml \
     | sed -E 's/.* tests="([0-9]+)".*/\1/' | paste -sd+ - | bc
```

Expected: PASS (129건) — `BUILD SUCCESSFUL` 과 함께 `129` 가 찍힌다. (기존 123 + `BillingCryptoTest` 6)

> `cleanTest` 를 붙이는 이유: 앞 Step 들에서 일부 테스트만 돌려 XML 리포트가 반쪽만 남아 있다. 지우지 않으면 합계가 틀린다.
> ⚠️ 숫자가 129 가 아니면 멈추고 보고한다. **129 보다 작으면** 어떤 클래스가 안 돌았거나 컴파일이 안 된 것이고, **크면** 이 계획이 세지 못한 테스트가 있다는 뜻이다. 어느 쪽이든 실제 숫자와 클래스별 내역을 보고에 적는다.
> ⚠️ 실패가 나면 **원인부터 읽을 것.** `billing_customer_key` 관련이면 Step 13 의 매핑을, `app.billing-crypto.key` 관련이면 Step 7 의 yaml 들여쓰기(두 칸, `app:` 의 직계 자식)를 다시 본다.

---

- [ ] **Step 16: 커밋한다**

`git add -A` 를 쓰지 않는다 — 작업 트리에 이 작업과 무관한 미커밋 파일이 둘 있다(`widget/demo.html`, 미추적 `docs/이해노트-2026-09-01.md`).

```bash
cd /Users/cheonjamin/projects/AllDap
git add \
  api/src/main/resources/db/migration/V6__billing_method.sql \
  api/src/main/java/com/alldap/api/global/crypto/BillingCryptoProperties.java \
  api/src/main/java/com/alldap/api/global/crypto/BillingCrypto.java \
  api/src/test/java/com/alldap/api/global/crypto/BillingCryptoTest.java \
  api/src/main/java/com/alldap/api/domain/user/entity/User.java \
  api/src/main/resources/application.yaml \
  api/src/main/resources/application-prod.yaml \
  .env.prod.example \
  docker-compose.prod.yml
git status --short
```

`git status --short` 로 **스테이징된 것이 위 9개뿐인지** 눈으로 확인한 뒤 커밋한다:

```bash
git commit -m "$(cat <<'EOF'
feat: 결제 수단 스키마와 빌링키 암호화

토스 빌링키를 담을 자리를 만든다. API 는 아직 없다.

- V6: users.billing_customer_key(NOT NULL·UNIQUE) + billing_methods 테이블
- BillingCrypto: AES-256-GCM. 새 의존성 0개 —
  spring-boot-starter-security 가 이미 끌고 오는 spring-security-crypto 를 쓴다.
  Encryptors.text() 는 CBC(인증 없음)라 쓰지 않았다.
- 기동 가드 4개(미주입·${} 리터럴·공개 기본값·32바이트)를 JwtService 패턴으로.
  🔴 이 저장소의 fail-closed 가드가 <테스트로 고정된> 첫 사례다.
- customerKey 생성은 User.create() 안에 둔다 (Bot.create 의 publicKey 와 같은 이유)

실측으로 확인한 것: ddl-auto=validate 는 <매핑된 필드 → 컬럼> 한 방향만 본다.
컬럼만 추가하고 엔티티를 안 고치면 컨텍스트는 그냥 뜨고, 깨지는 것은 <가입>이다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

> ⚠️ Step 11 에서 예상과 다른 결과(FAIL)가 나왔다면 커밋 메시지의 마지막 두 줄을 **실제로 관찰한 내용으로 고쳐 적는다.** 안 본 것을 봤다고 쓰지 않는다.

---

## Task 2: 토스 클라이언트와 등록·조회

**Files:**
- Create: `api/src/main/java/com/alldap/api/global/config/TossProperties.java`
- Create: `api/src/main/java/com/alldap/api/global/config/TossClientConfig.java`
- Create: `api/src/main/java/com/alldap/api/domain/billing/client/TossClient.java`
- Create: `api/src/main/java/com/alldap/api/domain/billing/client/TossIssueBillingKeyRequest.java`
- Create: `api/src/main/java/com/alldap/api/domain/billing/client/TossBillingKeyResponse.java`
- Create: `api/src/main/java/com/alldap/api/domain/billing/client/TossBilling.java`
- Create: `api/src/main/java/com/alldap/api/domain/billing/service/CardIssuer.java`
- Create: `api/src/main/java/com/alldap/api/domain/billing/entity/BillingMethod.java`
- Create: `api/src/main/java/com/alldap/api/domain/billing/repository/BillingMethodRepository.java`
- Create: `api/src/main/java/com/alldap/api/domain/billing/dto/RegisterBillingMethodRequest.java`
- Create: `api/src/main/java/com/alldap/api/domain/billing/dto/BillingMethodResponse.java`
- Create: `api/src/main/java/com/alldap/api/domain/billing/service/BillingService.java`
- Create: `api/src/main/java/com/alldap/api/domain/billing/controller/BillingController.java`
- Modify: `api/src/main/java/com/alldap/api/global/exception/ErrorCode.java`
- Modify: `api/src/main/resources/application.yaml`
- Modify: `api/src/main/resources/application-prod.yaml`
- Modify: `.env.prod.example` · `.env.example` · `docker-compose.prod.yml` (`TOSS_SECRET_KEY` 배선)
- Test: `api/src/test/java/com/alldap/api/support/TossStub.java` (Create)
- Test: `api/src/test/java/com/alldap/api/support/TestcontainersConfiguration.java` (Modify)
- Test: `api/src/test/java/com/alldap/api/domain/billing/BillingIntegrationTest.java` (Create)

> ⚠️ **패키지 배치는 이 저장소의 관례(`domain/<기능>/{controller,dto,entity,repository,service}`)를 그대로 따른다.** 가장 최근 슬라이스인 `domain/usage/` 가 파일 5개를 그 5개 디렉터리에 하나씩 넣은 본보기이고, billing 은 파일이 10개라 관례를 지킬 이유가 **더** 크다(Task 3 도 `domain/billing/service/BillingService.java` 를 전제한다). 그 위에 **토스 컨트랙트를 아는 코드만 `domain/billing/client/` 로 격리**하는데, 그건 `global/client/AiServiceClient` 와 같은 이유다 — 외부 스키마가 바뀌면 고칠 곳이 그 폴더 안에서 끝나야 한다.

**Interfaces:**
- Consumes (Task 1 산출물):
  - `com.alldap.api.global.crypto.BillingCrypto` — `String encrypt(String plaintext)` / `String decrypt(String stored)`
  - `api/src/main/resources/db/migration/V6__billing_method.sql` — `users.billing_customer_key` · `billing_methods` 테이블
  - `com.alldap.api.domain.user.entity.User#getBillingCustomerKey()` · `User.BILLING_CUSTOMER_KEY_PREFIX`
- Produces (Task 3·4 가 의존):
  - `TossClient#issueBillingKey(String authKey, String customerKey) → TossBilling`
  - `TossBilling(String billingKey, String issuerCode, String cardNumberMasked)`
  - `BillingMethod` · `BillingMethodRepository#findByUserId(UUID)`
  - `BillingService#find(UUID)` · `#register(UUID, RegisterBillingMethodRequest)`
  - `BillingController` — `GET`·`POST /api/billing/method`
  - `BillingMethodResponse(String customerKey, Card method)` / `Card(String issuerName, String cardNumberMasked, OffsetDateTime registeredAt)`
  - `ErrorCode.BILLING_AUTH_FAILED` · `BILLING_PROVIDER_UNAVAILABLE` · `BILLING_METHOD_ALREADY_EXISTS` · `BILLING_METHOD_NOT_FOUND`
  - `com.alldap.api.support.TossStub` — `baseUrl()` · `reset()` · `enqueue(int,String)` · `enqueueAbort()` · `received()`
- **Produces 하지 않는 것**: `TossClient#deleteBillingKey(String)`. **Task 3 이 만든다.** 지금 만들면 호출자 없는 코드가 되고, 이 저장소는 이미 그 함정을 한 번 문서화했다(`AiServiceClient.listDocuments` — *"호출자 없는 코드를 미리 만들면 검증되지 않은 채 '동작한다'는 인상만 남는다"*).

---

- [ ] **Step 1: Task 1 산출물이 실제로 있는지 확인한다 (게이트)**

```bash
cd /Users/cheonjamin/projects/AllDap
git branch --show-current
ls api/src/main/resources/db/migration/
grep -n "billingCustomerKey\|BILLING_CUSTOMER_KEY_PREFIX" api/src/main/java/com/alldap/api/domain/user/entity/User.java
ls api/src/main/java/com/alldap/api/global/crypto/ 2>/dev/null
```

Expected: 브랜치가 `feat/billing-method` 이고, `V6__billing_method.sql` 이 있고, `User.java` 에 `billingCustomerKey` 가 있고, `global/crypto/` 에 `BillingCrypto.java`·`BillingCryptoProperties.java` 가 있다.

> ⚠️ **브랜치가 `feat/billing-method` 가 아니면** Task 1 이 안 끝난 것이다. Task 1 을 먼저 끝내고 돌아온다.
>
> ⚠️ **`V6__billing_method.sql` 이나 `User.billingCustomerKey` 가 없으면** Task 1 이 스키마를 만들지 않은 것이다. 이 Task 는 `ddl-auto: validate` 때문에 그 둘 없이는 **기동조차 못 한다.** 아래 두 파일을 이 Step 에서 만들고, **그렇게 했다는 사실을 보고에 적는다.**
>
> `api/src/main/resources/db/migration/V6__billing_method.sql`:
> ```sql
> -- 결제 수단(토스 빌링키) 저장 (2026-09-06)
> --
> -- 소유권: Spring 이 쓰고 Spring 이 읽는다. Python 은 건드리지 않는다.
> --
> -- 왜 테이블을 나눴나: customerKey 는 카드보다 오래 산다(카드를 빼도 남아야
> -- 재등록 시 토스 쪽 고객 이력이 이어진다). billingKey 는 카드와 함께 죽는다.
> -- 수명이 다른 둘을 한 곳에 두면 삭제할 때 반드시 한쪽을 잘못 다루게 된다.
>
> -- ① customerKey 는 users 에.
> --    토스 제약(문서 원문): "영문 대소문자, 숫자, 특수문자 - _ = . @ 를 최소 1개 이상 포함한
> --    최소 2자 이상 최대 50자 이하". 'bcus_' + 32 hex = 37자로 들어간다.
> ALTER TABLE users ADD COLUMN IF NOT EXISTS billing_customer_key VARCHAR(50);
>
> -- 기존 계정을 메꾼다. 이걸 안 하면 NOT NULL 을 걸 수 없고,
> -- NOT NULL 이 아니면 "customerKey 없는 사용자" 라는 다룰 필요 없는 상태가 영구히 남는다.
> UPDATE users SET billing_customer_key = 'bcus_' || replace(gen_random_uuid()::text, '-', '')
>  WHERE billing_customer_key IS NULL;
>
> ALTER TABLE users ALTER COLUMN billing_customer_key SET NOT NULL;
> ALTER TABLE users ADD CONSTRAINT uq_users_billing_customer_key UNIQUE (billing_customer_key);
>
> -- ② 카드는 별도 테이블. 삭제가 "행 하나 지우기" 가 된다
> --    (컬럼 4개를 NULL 로 되돌리는 것보다 의도가 분명하다).
> CREATE TABLE IF NOT EXISTS billing_methods (
>   id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
>
>   -- 🔴 ON DELETE CASCADE 는 필수다. V5 에서 이걸 뺐다가 통합 테스트 11건이 깨졌다 —
>   --    전 테스트가 userRepository.deleteAll() 로 정리하는데 그 FK 가 정리를 막았다.
>   --    UNIQUE 가 "계정당 카드 1장" 을 DB 수준에서 보장한다. 토스는 같은 카드로
>   --    빌링키를 몇 개든 발급해주고 중복 방지 수단이 없으므로, 이 제약이 유일한 방어다.
>   user_id            UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
>
>   -- Base64(IV 12B ‖ 암호문 ‖ GCM 인증태그 16B) 한 덩어리. IV 컬럼을 따로 두지 않는다 —
>   -- IV 는 비밀이 아니고 암호문과 반드시 짝이라, 나누면 한쪽만 갱신·복사되어 어긋날 수 있다.
>   -- 길이: 빌링키 최대 200자(토스 문서) → 12+200+16 = 228B → Base64 304자. 512 면 넉넉하다.
>   -- 컬럼명에 _enc 를 붙여 "여기 든 게 평문이 아니다" 를 스키마에서부터 말한다.
>   billing_key_enc    VARCHAR(512) NOT NULL,
>
>   -- ⚠️ 토스가 카드사 <이름> 을 안 준다. 버전 2024-06-01 부터 응답에서 cardCompany 가 제거됐고
>   --    card.issuerCode("61" 같은 두 자리 코드)만 온다. 코드→이름 매핑은 우리가 상수로 들고 있는다.
>   issuer_code        VARCHAR(4)  NOT NULL,
>   card_number_masked VARCHAR(20) NOT NULL,   -- "43301234****123*" — 토스가 마스킹해서 준다
>
>   created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
> );
> ```
>
> 그리고 `User.java` 에 세 곳을 더한다 — ① `import java.util.UUID;` 는 이미 있다, ② 상수·필드, ③ `create()` 안 한 줄과 생성 메서드:
> ```java
>     /**
>      * 토스에 넘기는 "이 고객" 이름표. 접두사를 두는 이유는 {@code bots.public_key}(pk_) 와 같다 —
>      * <b>내부 기본키(users.id)를 외부 업체에 그대로 흘리지 않는다.</b>
>      * 토스 대시보드·CS 이력에 우리 DB 의 PK 가 찍히게 두지 않으려는 것이다.
>      */
>     public static final String BILLING_CUSTOMER_KEY_PREFIX = "bcus_";
>
>     /**
>      * 카드보다 오래 산다. 카드를 빼도 이 값은 남아야 재등록 시 토스 쪽 고객 이력이 이어진다.
>      * 'bcus_' + UUID 32자 = 37자로 토스의 50자 상한 안이다.
>      */
>     @Column(name = "billing_customer_key", length = 50, nullable = false, unique = true)
>     private String billingCustomerKey;
> ```
> `create(...)` 안, `user.name = name;` 다음 줄에:
> ```java
>         // Bot.create() 가 publicKey 를 만드는 것과 같은 이유로 여기서 만든다 —
>         // 생성 위치가 밖에 있으면 "키를 안 넣고 만든 행" 이 생길 여지가 남는다.
>         user.billingCustomerKey = BILLING_CUSTOMER_KEY_PREFIX
>                 + UUID.randomUUID().toString().replace("-", "");
> ```

---

- [ ] **Step 2: 통합 테스트를 먼저 쓴다**

`api/src/test/java/com/alldap/api/domain/billing/BillingIntegrationTest.java`:

```java
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
```

- [ ] **Step 3: 테스트를 돌려 실패를 확인한다 — 이 실패 목록이 곧 구현 체크리스트다**

```bash
cd /Users/cheonjamin/projects/AllDap/api && ./gradlew test --tests 'BillingIntegrationTest'
```

Expected: FAIL — 컴파일 에러. `error: cannot find symbol` 이 `com.alldap.api.support.TossStub` import 에서 먼저 나고, `tossStub.enqueue`·`tossStub.received()` 에서도 난다. (`BillingMethodResponse` 등은 이 테스트가 JSON 으로만 다루므로 컴파일 대상이 아니다 — 그래서 컴파일이 통과해도 런타임에 404 로 실패한다)

> ⚠️ **Docker 가 안 떠 있으면** `Could not find a valid Docker environment` 로 죽는다. Docker Desktop 을 켜고 다시 돌린다. 컴파일 에러가 먼저 나므로 이 Step 에서는 Docker 없이도 목적을 달성한다.

---

- [ ] **Step 4: `TossProperties` 를 만든다**

`api/src/main/java/com/alldap/api/global/config/TossProperties.java`:

```java
package com.alldap.api.global.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.time.Duration;

/**
 * 토스페이먼츠 API 호출 설정. {@code application.yaml} 의 {@code app.toss.*} 를 바인딩한다.
 *
 * <p>{@code AiServiceProperties} 와 <b>따로 두는 이유는 타임아웃이 정반대이기 때문</b>이다.
 * 그쪽은 읽기 120초(LLM 이 수십 초 걸린다), 이쪽은 10초(사용자가 카드 등록 화면 앞에서 기다린다).
 * 한 record 에 묶으면 둘 중 하나가 반드시 틀린 값을 갖게 된다.
 *
 * @param baseUrl        토스 API 주소. 운영은 {@code https://api.tosspayments.com}
 * @param secretKey      🔴 <b>API 개별 연동 키</b>({@code test_sk_} / {@code live_sk_})다.
 *                       결제위젯 키({@code test_gsk_})를 넣으면 토스가 {@code INVALID_API_KEY} 로 거절한다 —
 *                       토스는 서비스마다 다른 MID 에 각각 키를 발급하고, 세트가 아닌 키를 섞으면 안 받는다.
 * @param connectTimeout TCP 연결 타임아웃
 * @param readTimeout    응답 대기 타임아웃 (근거는 TossClientConfig 주석)
 */
@ConfigurationProperties(prefix = "app.toss")
public record TossProperties(
        String baseUrl,
        String secretKey,
        Duration connectTimeout,
        Duration readTimeout
) {
}
```

- [ ] **Step 5: 설정 파일 두 개에 `app.toss` 를 더한다**

`api/src/main/resources/application.yaml` — `app:` 블록의 `ai-service:` 항목 **바로 다음**(`jwt:` 앞)에 넣는다:

```yaml
  toss:
    base-url: ${TOSS_BASE_URL:https://api.tosspayments.com}
    # 🔴 기본값을 두지 않는다. 토스 대시보드에서 발급받은 <API 개별 연동 키>(test_sk_...)를
    #    TOSS_SECRET_KEY 환경변수로 넣을 것. 결제위젯 키(test_gsk_)는 거부된다.
    #    비워두면 토스가 401 을 주고, TossClient 가 그걸 <우리 설정 문제>로 분류해
    #    503 + 서버 로그 ERROR 로 알린다(사용자에게 "카드를 확인하세요" 라고 하지 않는다).
    secret-key: ${TOSS_SECRET_KEY:}
    # 타임아웃 근거는 TossClientConfig 주석. AI 서비스(3s/120s)와 <일부러 다르다>.
    connect-timeout: 3s
    read-timeout: 10s
```

`api/src/main/resources/application-prod.yaml` — 같은 자리(`ai-service:` 다음, `jwt:` 앞):

```yaml
  toss:
    base-url: ${TOSS_BASE_URL:https://api.tosspayments.com}
    # fail-closed. 기본값을 두지 않는다 — 키 없이 뜨면 카드 등록이 전부 실패하는데
    # 원인이 로그를 뒤져야 나온다. 차라리 기동이 실패하는 편이 안전하다.
    secret-key: ${TOSS_SECRET_KEY}
    connect-timeout: ${TOSS_CONNECT_TIMEOUT:3s}
    read-timeout: ${TOSS_READ_TIMEOUT:10s}
```

🔴 **여기서 멈추면 다음 prod 배포가 기동에서 죽는다.** `application-prod.yaml` 이 기본값 없이
`${TOSS_SECRET_KEY}` 를 요구하는데, 그 값을 **컨테이너에 넣어주는 곳이 아직 없다.**
이 저장소는 이미 같은 부류를 한 번 냈다 — PR #44 의 유일한 실효 조치가 배포 절차 한 줄이 빠져
**운영에 적용조차 안 됐다**(`docs/DEPLOY.md` §9). 배선을 지금 같이 한다.

`.env.prod.example` 끝에 추가 (Task 1 이 `BILLING_CRYPTO_KEY` 를 넣은 바로 아래):

```bash
# 토스페이먼츠 <API 개별 연동> 시크릿 키. 결제위젯 키(gsk)가 아니다.
# 자동결제는 라이브에 <추가 계약>이 필요하다 — 계약 전에는 test_sk_ 만 동작한다.
TOSS_SECRET_KEY=test_sk_...
```

`docker-compose.prod.yml` 의 `api:` → `environment:` 에 추가 (`JWT_SECRET: ${JWT_SECRET}` 바로 아래):

```yaml
      # application-prod.yaml 이 기본값을 안 두므로 없으면 기동 실패한다(JWT_SECRET 과 같다).
      TOSS_SECRET_KEY: ${TOSS_SECRET_KEY}
```

루트 `.env.example`(로컬 개발용)에도 같은 줄을 추가한다. 로컬은 `application.yaml` 이
빈 문자열 기본값을 갖고 있어 기동은 되지만, **키가 없으면 카드 등록이 전부 503 이 된다** —
Task 4 의 브라우저 종단이 그것 때문에 반드시 실패한다.

```bash
# 토스 테스트 키. https://developers.tosspayments.com/my/api-keys 에서 받는다.
# ⚠️ ./gradlew bootRun 은 .env 를 읽지 않는다. 셸에 직접 실어서 띄울 것:
#    TOSS_SECRET_KEY=test_sk_... ./gradlew bootRun
TOSS_SECRET_KEY=
```

> ⚠️ **`.env.prod.example` 에 Task 1 이 넣은 `BILLING_CRYPTO_KEY` 가 안 보이면** Task 1 의 Step 9 가
> 빠진 것이다. 두 줄을 여기서 같이 넣고 **그렇게 했다는 사실을 보고에 적는다.**

- [ ] **Step 6: `TossClientConfig` 를 만든다 — 빈을 공유하지 않는 것이 핵심이다**

`api/src/main/java/com/alldap/api/global/config/TossClientConfig.java`:

```java
package com.alldap.api.global.config;

import lombok.RequiredArgsConstructor;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpHeaders;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

import java.net.http.HttpClient;
import java.nio.charset.StandardCharsets;
import java.util.Base64;

/**
 * 토스페이먼츠 호출용 {@link RestClient}.
 *
 * <p>🔴 <b>{@code aiServiceRestClient} 와 빈을 공유하지 않는다.</b> 공유하면 두 상대가
 * 커넥션 풀과 타임아웃을 나눠 쓰게 되어 <b>토스 장애가 채팅을 끊고, 그 반대도 된다.</b>
 * 이 프로젝트가 이미 문서화한 약점("Python 이 죽으면 채팅이 죽는다")을 결제까지 번지게 하는 셈이다.
 *
 * <p><b>타임아웃을 AI 서비스와 다르게 잡은 이유.</b>
 * <ul>
 *   <li><b>연결 3초</b> — AI 와 같다. 다만 이유는 다르다. 저쪽은 내부망이라 3초면 "안 떠 있다"는 뜻이고,
 *       이쪽은 공인망이라 3초가 그냥 넉넉한 값이다.</li>
 *   <li><b>읽기 10초</b> — AI 는 120초다. 그쪽은 LLM 이 수십 초 걸리는 게 <b>정상</b>이지만,
 *       빌링키 발급은 카드사 인증 결과를 확인만 하는 호출이라 정상값이 1~3초다.
 *       120초를 그대로 쓰면 카드 등록 화면 앞의 사용자를 2분 동안 세워둔다.</li>
 * </ul>
 *
 * <p>⚠️ <b>10초의 대가를 적어둔다.</b> 읽기 타임아웃이 나도 토스는 이미 빌링키를 발급했을 수 있고,
 * 토스에는 <b>빌링키 조회 API 가 없어</b> 그 키는 영원히 회수할 수 없다.
 * 그래서 {@code TossClient} 가 <b>같은 멱등키로</b> 한 번 더 시도한다 — 값을 짧게 잡을 수 있는 것은
 * 그 재시도가 있기 때문이다. 둘은 한 세트다. 한쪽만 바꾸지 말 것.
 *
 * <p><b>HTTP/1.1 을 고정하는 이유</b>는 {@code RestClientConfig} 와 같다. 토스는 HTTPS 라
 * h2c 업그레이드 문제가 없지만, 통합 테스트의 {@code TossStub}(JDK {@code HttpServer}) 은 평문이라
 * 같은 함정에 걸린다. <b>테스트와 운영이 같은 프로토콜을 타야</b> 테스트가 의미를 갖는다.
 */
@Configuration
@RequiredArgsConstructor
public class TossClientConfig {

    private final TossProperties tossProperties;

    @Bean
    public RestClient tossRestClient() {
        HttpClient httpClient = HttpClient.newBuilder()
                .version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(tossProperties.connectTimeout())
                .build();

        JdkClientHttpRequestFactory requestFactory = new JdkClientHttpRequestFactory(httpClient);
        requestFactory.setReadTimeout(tossProperties.readTimeout());

        return RestClient.builder()
                .baseUrl(tossProperties.baseUrl())
                // 인증 헤더를 여기 한 번만 박는다. 호출 지점마다 붙이면 언젠가 한 곳이 빠지고,
                // 그 한 곳은 401 로만 드러난다.
                .defaultHeader(HttpHeaders.AUTHORIZATION, basicAuth(tossProperties.secretKey()))
                .requestFactory(requestFactory)
                .build();
    }

    /**
     * 토스의 Basic 인증: {@code base64(secretKey + ":")}.
     *
     * <p>🔴 <b>콜론이 핵심이다.</b> 토스는 시크릿 키를 <b>아이디</b> 자리에 쓰고 비밀번호는 비운다.
     * 콜론을 빼고 인코딩하면 {@code INCORRECT_BASIC_AUTH_FORMAT} 으로 전부 거절당한다.
     *
     * <p>⚠️ <b>UTF-8 BOM 함정.</b> 시크릿 키를 파일에서 읽어오거나 웹에서 복사해 붙이면
     * 앞에 눈에 안 보이는 BOM({@code U+FEFF})이나 공백이 딸려올 수 있다. 그러면 base64 결과가
     * 달라져 <b>키는 맞는데 401 이 나는</b> 가장 헷갈리는 실패가 된다. 그래서 {@code strip()} 한다
     * (BOM 은 자바의 {@code String.strip()} 이 공백으로 취급해 제거한다 — {@code trim()} 은 못 한다).
     */
    private String basicAuth(String secretKey) {
        String raw = (secretKey == null ? "" : secretKey.strip()) + ":";
        return "Basic " + Base64.getEncoder().encodeToString(raw.getBytes(StandardCharsets.UTF_8));
    }
}
```

- [ ] **Step 7: 컨텍스트가 여전히 뜨는지 확인한다 (`RestClient` 빈이 두 개가 됐다)**

```bash
cd /Users/cheonjamin/projects/AllDap/api && ./gradlew test --tests 'ApiApplicationTests'
```

Expected: PASS (1건)

> ⚠️ **`NoUniqueBeanDefinitionException: expected single matching bean but found 2: aiServiceRestClient,tossRestClient` 로 실패하면**, 이름 기반 해석(필드명 = 빈 이름)이 이 빌드에서 동작하지 않는 것이다. `AiServiceClient` 의 `private final RestClient aiServiceRestClient;` 와 (Step 9 에서 만들) `TossClient` 의 `private final RestClient tossRestClient;` **양쪽 필드에** `@Qualifier("aiServiceRestClient")` / `@Qualifier("tossRestClient")` 를 붙인다(`org.springframework.beans.factory.annotation.Qualifier`). **그렇게 바꿨다면 그 사실을 보고에 적는다.**

---

- [ ] **Step 8: `CardIssuer` 와 토스 DTO 3개를 만든다**

`api/src/main/java/com/alldap/api/domain/billing/service/CardIssuer.java`:

```java
package com.alldap.api.domain.billing.service;

import java.util.Map;

/**
 * 토스 {@code issuerCode} → 카드사 이름.
 *
 * <p><b>왜 우리가 이걸 들고 있는가.</b> 토스가 <b>2024-06-01 버전부터 응답에서
 * {@code cardCompany}(이름)를 제거</b>했다. 이제 {@code card.issuerCode}("61" 같은 코드)만 온다.
 * 화면에 "61" 을 보여줄 수는 없으니 매핑이 어딘가에는 있어야 한다.
 *
 * <p><b>왜 프론트가 아니라 여기인가.</b> 표기 변환은 Spring 책임이라는 것이 이 저장소의 규칙이다
 * (snake_case → camelCase 와 같은 자리). 프론트에 두면 {@code web/lib/types.ts} 가
 * 백엔드 응답과 어긋나고, 위젯·관리자 화면이 각자 사본을 갖게 된다.
 *
 * <p><b>왜 {@code dto} 가 아니라 {@code service} 패키지인가.</b> 코드→이름 매핑은
 * <b>응답을 만드는 일</b>이라 {@code BillingService} 옆이 맞다.
 * {@code dto} 에 두면 DTO 가 아닌 것이 dto 패키지에 섞인다.
 *
 * <p>⚠️ <b>이 표는 완전하지 않다.</b> 토스 코드표(https://docs.tosspayments.com/reference/codes)에는
 * 해외 카드사·선불 사업자 등이 더 있고, 코드가 추가될 수도 있다. 국내에서 실제로 등록될 법한
 * 카드사만 담았다. <b>모르는 코드는 예외를 던지지 않고 {@code "카드"} 로 답한다</b> —
 * 표에 없는 카드사로 등록했다고 해서 등록 자체가 실패하면 안 된다. 사용자는 마스킹된
 * 카드번호로도 자기 카드를 알아본다.
 */
public final class CardIssuer {

    private static final String UNKNOWN = "카드";

    private static final Map<String, String> NAMES = Map.ofEntries(
            Map.entry("11", "국민"),
            Map.entry("15", "카카오뱅크"),
            Map.entry("21", "하나"),
            Map.entry("24", "토스뱅크"),
            Map.entry("30", "KDB산업"),
            Map.entry("31", "BC"),
            Map.entry("33", "우리BC"),
            Map.entry("34", "수협"),
            Map.entry("35", "전북"),
            Map.entry("36", "씨티"),
            Map.entry("37", "우체국예금보험"),
            Map.entry("38", "새마을"),
            Map.entry("39", "저축은행중앙회"),
            Map.entry("41", "신한"),
            Map.entry("42", "제주"),
            Map.entry("46", "광주"),
            Map.entry("51", "삼성"),
            Map.entry("61", "현대"),
            Map.entry("62", "신협"),
            Map.entry("71", "롯데"),
            Map.entry("91", "NH농협"),
            Map.entry("3A", "케이뱅크"),
            Map.entry("3K", "기업BC"),
            Map.entry("W1", "우리"));

    private CardIssuer() {
    }

    /** 모르는 코드·null 은 {@code "카드"}. 호출자가 null 을 걱정하지 않아도 된다. */
    public static String nameOf(String issuerCode) {
        return NAMES.getOrDefault(issuerCode, UNKNOWN);
    }
}
```

> ⚠️ **표의 코드는 토스 코드표 페이지 기준으로 적은 것이다.** 브라우저 종단 확인(설계 §검사 3)에서 실제 카드로 등록했는데 `"카드"` 로 나오면, 그때 응답의 `issuerCode` 를 로그에서 확인해 여기에 한 줄 더한다. **더했다면 그 코드와 이름을 보고에 적는다.**

`api/src/main/java/com/alldap/api/domain/billing/client/TossIssueBillingKeyRequest.java`:

```java
package com.alldap.api.domain.billing.client;

/**
 * {@code POST /v1/billing/authorizations/issue} 요청 본문.
 *
 * <p>🔴 {@code customerKey} 는 <b>브라우저가 보낸 값이 아니라 우리 DB 에서 읽은 값</b>이어야 한다.
 * 판단은 {@code BillingService.register} 가 하고, 여기는 실어 나르기만 한다.
 */
public record TossIssueBillingKeyRequest(String authKey, String customerKey) {
}
```

`api/src/main/java/com/alldap/api/domain/billing/client/TossBillingKeyResponse.java`:

```java
package com.alldap.api.domain.billing.client;

/**
 * {@code POST /v1/billing/authorizations/issue} 성공 응답 중 <b>우리가 쓰는 것만</b>.
 *
 * <p>토스는 {@code mId}·{@code method}·{@code authenticatedAt}·{@code card.acquirerCode}·
 * {@code card.cardType}·{@code card.ownerType} 등을 함께 준다. 선언하지 않은 필드는 무시된다 —
 * <b>Jackson 3 부터 {@code FAIL_ON_UNKNOWN_PROPERTIES} 가 기본 off</b> 라서
 * {@code @JsonIgnoreProperties} 를 붙일 필요가 없다(2.x 에서는 기본 on 이었다).
 * 토스 문서가 "하위호환을 위해 모르는 필드를 무시하도록 설정하라" 고 권고하는 그 요건이
 * 기본 동작으로 이미 충족된다. 통합 테스트의 성공 응답 JSON 이 이걸 못박는다.
 *
 * <p>🔴 <b>{@code cardCompany}·{@code cardNumber} 를 쓰지 않는다.</b>
 * 2024-06-01 버전부터 응답에서 <b>제거된</b> 필드다. 옛 예제를 그대로 붙여넣으면
 * 로컬에서는 값이 null 이라 조용히 지나가고 운영에서 NPE 가 난다.
 * 카드 정보는 반드시 {@code card.issuerCode} / {@code card.number} 에서 읽는다.
 *
 * @param card 카드 상세. 계좌 자동결제였다면 없을 수 있으므로 호출자가 null 을 확인한다.
 */
public record TossBillingKeyResponse(String billingKey, Card card) {

    /**
     * @param issuerCode 카드 발급사 코드("61" 등). 이름은 {@code CardIssuer} 가 붙인다
     * @param number     토스가 마스킹해서 준 번호("43301234****123*").
     *                   <b>우리가 마스킹하는 것이 아니다</b> — 전체 카드번호는 우리 서버에 닿지 않는다
     */
    public record Card(String issuerCode, String number) {
    }
}
```

`api/src/main/java/com/alldap/api/domain/billing/client/TossBilling.java`:

```java
package com.alldap.api.domain.billing.client;

/**
 * 발급 결과 중 <b>우리 도메인이 아는 것만</b> 추린 값.
 *
 * <p>{@code TossBillingKeyResponse}(토스 스키마)를 서비스 계층까지 들여보내지 않는 이유는
 * {@code AiServiceClient} 가 {@code client/dto} 를 밖으로 안 내보내는 것과 같다 —
 * 외부 컨트랙트가 바뀌었을 때 고칠 곳이 {@code client} 패키지 안에서 끝나야 한다.
 *
 * @param billingKey 🔴 <b>평문이다.</b> 이 값을 로그에 찍거나 응답 DTO 에 담지 말 것.
 *                   {@code BillingService} 가 즉시 암호화해 저장하고 그 뒤로는 아무도 보지 않는다.
 */
public record TossBilling(String billingKey, String issuerCode, String cardNumberMasked) {
}
```

- [ ] **Step 9: `TossClient` 를 만든다**

`api/src/main/java/com/alldap/api/domain/billing/client/TossClient.java`:

```java
package com.alldap.api.domain.billing.client;

import com.alldap.api.global.config.TossProperties;
import com.alldap.api.global.exception.ApiException;
import com.alldap.api.global.exception.ErrorCode;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestClientResponseException;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.time.Duration;
import java.util.UUID;

/**
 * 토스페이먼츠 호출 담당. <b>토스 컨트랙트를 아는 코드는 이 파일과 같은 패키지의 DTO 뿐이다.</b>
 *
 * <p><b>실패 변환을 여기서 끝낸다.</b> 호출 지점마다 try-catch 를 적으면 반드시 한 곳이 빠지고,
 * 빠진 곳에서 {@code RestClientException} 이 그대로 올라가 <b>500</b> 이 나간다 —
 * "토스가 카드를 거절했다" 가 "우리 서버가 고장났다" 로 둔갑한다.
 * {@code AiServiceClient} 가 같은 이유로 같은 모양을 하고 있다.
 *
 * <p><b>코드를 나누는 기준도 같다 — "누구 잘못인가".</b>
 * <ul>
 *   <li>토스 4xx(카드 거절·유효기간·정지) → 400 {@code BILLING_AUTH_FAILED} + <b>토스의 한국어 문구 그대로</b></li>
 *   <li>토스 401 → 503. 이건 사용자 잘못이 아니라 <b>우리 키 설정 문제</b>다. 아래 참고</li>
 *   <li>토스 5xx·타임아웃·연결 실패 → 503 {@code BILLING_PROVIDER_UNAVAILABLE}</li>
 * </ul>
 *
 * <p>🔴 <b>서킷브레이커를 달지 않는다.</b> {@code AiServiceCircuitBreaker} 를 재사용하면
 * 토스 장애가 채팅을 끊는다. 그렇다고 결제용을 새로 만들 근거도 아직 없다 —
 * 서킷의 목적은 "죽은 상대를 계속 두드려 우리 스레드를 소모하는 것"을 막는 건데,
 * 카드 등록은 <b>사용자가 버튼을 눌러야만</b> 일어나 트래픽이 구조적으로 낮다.
 * 자동 청구(4번 조각)가 붙어 배치가 토스를 두드리기 시작하면 그때 필요해진다.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class TossClient {

    /**
     * 총 시도 횟수(재시도 횟수가 아니다). 2 = 최초 1회 + 재시도 1회.
     *
     * <p>설정으로 빼지 않았다. 튜닝할 값이 아니라 <b>"한 번만 더"</b> 라는 결정 자체이고,
     * 늘리면 고아 빌링키가 늘 위험만 커진다(멱등키 유효기간 15일 안에서는 안전하지만,
     * 시도가 늘수록 사용자 대기 시간이 그대로 길어진다).
     */
    private static final int MAX_ATTEMPTS = 2;
    private static final Duration RETRY_DELAY = Duration.ofMillis(300);

    private final RestClient tossRestClient;

    /** 토스 에러 본문 {@code {"code","message"}} 를 읽는 데만 쓴다. Boot 4 가 자동 구성하는 Jackson 3 매퍼다. */
    private final ObjectMapper objectMapper;

    /** 실패 로그에 "어디로 못 붙었는지" 를 남긴다. 주소를 모르면 로그만 보고 원인을 못 좁힌다. */
    private final TossProperties tossProperties;

    /**
     * 카드 등록 인증({@code authKey})을 <b>빌링키</b>로 바꾼다.
     *
     * <p>🔴 <b>이 프로젝트에서 유일하게 "실패가 복구 불가능한" 호출이다.</b>
     * 토스에는 <b>빌링키를 조회하는 API 가 없다.</b> 발급은 됐는데 우리가 응답을 못 받으면
     * 그 키는 영원히 회수할 수 없다(폐기하려면 키를 알아야 하는데 알아낼 방법이 없다).
     *
     * @param customerKey 🔴 <b>반드시 우리 DB 에서 읽은 값</b>이어야 한다. 브라우저가 준 값을
     *                    그대로 넘기면 남의 계정에 카드를 붙일 수 있다. 검증은 {@code BillingService} 가 한다.
     */
    public TossBilling issueBillingKey(String authKey, String customerKey) {
        // 🔴 멱등키는 <루프 밖에서> 한 번만 만든다. 안에서 만들면 재시도가 새 키를 쓰게 되고,
        //    그러면 토스는 이걸 <다른 요청>으로 보고 빌링키를 하나 더 발급한다 = 고아가 하나 더 는다.
        String idempotencyKey = UUID.randomUUID().toString();

        TossBillingKeyResponse response = issue(idempotencyKey,
                new TossIssueBillingKeyRequest(authKey, customerKey));

        // 200 인데 우리가 필요한 값이 없는 경우. 🔴 여기 오면 이미 발급된 키를 잃은 것이다.
        // 조용히 넘기면 "등록됐다는데 카드가 안 보인다" 가 되므로 크게 남기고 실패시킨다.
        if (response == null || response.billingKey() == null || response.billingKey().isBlank()) {
            log.error("[토스] 발급 응답에 billingKey 가 없다. 발급된 키를 잃었을 수 있다(조회 API 없음). "
                    + "idempotencyKey={} customerKey={}", idempotencyKey, customerKey);
            throw new ApiException(ErrorCode.BILLING_PROVIDER_UNAVAILABLE);
        }
        if (response.card() == null) {
            // 계좌 자동결제 등 카드가 아닌 수단. 이 조각은 카드만 다룬다(설계 §범위).
            log.error("[토스] 발급 응답에 card 가 없다. 카드가 아닌 수단으로 등록됐을 수 있다. "
                    + "idempotencyKey={}", idempotencyKey);
            throw new ApiException(ErrorCode.BILLING_AUTH_FAILED,
                    "카드로만 등록할 수 있습니다. 결제 수단을 카드로 선택한 뒤 다시 시도해주세요.");
        }

        return new TossBilling(response.billingKey(),
                response.card().issuerCode(), response.card().number());
    }

    /**
     * 🔴 <b>I/O 실패에만, 같은 멱등키로, 한 번 재시도한다.</b>
     *
     * <p>⚠️ <b>{@code AiServiceClient} 의 재시도 논리를 그대로 가져오면 안 된다.</b>
     * 그쪽은 <i>"재시도의 전제는 직전 시도가 아무 일도 하지 않았다는 것"</i> 이라
     * <b>연결 실패에만</b> 재시도하고 읽기 타임아웃은 제외한다. 결제에서는 그 전제가 안 선다 —
     * <b>읽기 타임아웃이어도 토스는 이미 빌링키를 발급했을 수 있고</b>, 조회 API 가 없어
     * 그 키는 영원히 회수할 수 없다. 즉 "재시도하지 않는 것" 이 더 안전한 선택이 아니다.
     *
     * <p>그 전제를 <b>멱등키가 대신 세워준다.</b> 같은 (멱등키·API 키·주소·메서드) 조합이면
     * 토스가 같은 응답을 돌려준다(처음 쓴 날부터 15일 유효). 그래서 여기서는
     * 연결 실패든 읽기 타임아웃이든 응답 도중 끊김이든 <b>I/O 실패 전부</b> 재시도한다.
     * <b>멱등키 없이 이 정책을 쓰면 고아 빌링키가 하나 더 늘 뿐이다.</b>
     *
     * <p>반대로 <b>HTTP 응답이 온 경우(4xx·5xx)는 재시도하지 않는다.</b> 토스가 판단해서 답한 것이라
     * 같은 요청은 같은 답을 받는다. 5xx 도 마찬가지다 — 응답이 왔다는 것 자체가 요청이 도달했다는 뜻이다.
     */
    private TossBillingKeyResponse issue(String idempotencyKey, TossIssueBillingKeyRequest body) {
        for (int attempt = 1; ; attempt++) {
            try {
                return tossRestClient.post()
                        .uri("/v1/billing/authorizations/issue")
                        .header("Idempotency-Key", idempotencyKey)
                        .contentType(MediaType.APPLICATION_JSON)
                        .body(body)
                        .retrieve()
                        .body(TossBillingKeyResponse.class);

            } catch (RestClientResponseException e) {
                // ⚠️ RestClientResponseException 은 RestClientException 의 하위 타입이다.
                //    순서를 바꾸면 4xx·5xx 까지 아래 I/O 분기로 들어가 <재시도>하게 된다.
                throw translateHttpFailure(e);

            } catch (RestClientException e) {
                boolean ioFailure = e instanceof ResourceAccessException
                        || e.getCause() instanceof IOException;

                if (!ioFailure) {
                    // 응답은 멀쩡히 받았는데 JSON 을 우리 DTO 로 해석하지 못한 경우 =
                    // 토스가 스키마를 바꿨거나 우리 DTO 가 낡았다.
                    // 🔴 재시도하면 안 된다. 요청은 성공했고 <다시 보내도 똑같이 못 읽는다>.
                    //    그리고 이 경우 발급된 키를 이미 잃었다.
                    log.error("[토스] 발급 응답을 해석하지 못했다. 발급된 키를 잃었을 수 있다(조회 API 없음). "
                            + "idempotencyKey={}", idempotencyKey, e);
                    throw new ApiException(ErrorCode.BILLING_PROVIDER_UNAVAILABLE);
                }

                if (attempt >= MAX_ATTEMPTS) {
                    log.error("[토스] 발급 실패 — {} 와의 통신에 {}회 실패했다. "
                                    + "빌링키가 발급됐는데 우리가 못 받았을 수 있다(조회 API 없음). idempotencyKey={}",
                            tossProperties.baseUrl(), attempt, idempotencyKey, e);
                    throw new ApiException(ErrorCode.BILLING_PROVIDER_UNAVAILABLE);
                }

                log.warn("[토스] 발급 통신 실패. {} 뒤 <같은 멱등키로> 재시도 ({}/{}). idempotencyKey={}",
                        RETRY_DELAY, attempt + 1, MAX_ATTEMPTS, idempotencyKey);
                sleep();
            }
        }
    }

    /** 상태 코드를 "누구 잘못인가" 로 번역한다. */
    private ApiException translateHttpFailure(RestClientResponseException e) {
        HttpStatusCode status = e.getStatusCode();

        // 🔴 401 만 따로 뗀다. 4xx 라고 사용자에게 "카드를 확인하세요" 라고 하면 <거짓말>이다 —
        //    사용자는 손쓸 수 없고, 고칠 사람은 TOSS_SECRET_KEY 를 넣을 우리다.
        //    (INVALID_API_KEY 는 결제위젯 키를 넣었을 때 나온다. 자동결제는 API 개별 연동 키다)
        if (status.isSameCodeAs(HttpStatus.UNAUTHORIZED)) {
            log.error("[토스] 인증 키가 거절됐다. TOSS_SECRET_KEY 가 <API 개별 연동 키>(test_sk_/live_sk_)인지, "
                    + "앞뒤에 공백·BOM 이 섞이지 않았는지 확인할 것. body={}", e.getResponseBodyAsString());
            return new ApiException(ErrorCode.BILLING_PROVIDER_UNAVAILABLE);
        }

        if (status.is4xxClientError()) {
            // 토스의 문구를 그대로 내려보낸다. 여기 오는 말은 애초에 <구매자에게 보여주려고 쓴 한국어>다.
            // 예: "카드 유효기간이 올바르지 않습니다." · "정지된 카드입니다."
            // 우리 기본 문구로 뭉개면 사용자가 다음에 뭘 해야 하는지를 잃는다(AGENTS.md 작업 규칙 4).
            log.warn("[토스] 발급 거절 status={} body={}", status, e.getResponseBodyAsString());
            return new ApiException(ErrorCode.BILLING_AUTH_FAILED, extractTossMessage(e));
        }

        log.error("[토스] 발급 실패 — 토스가 {} 응답. body={}", status, e.getResponseBodyAsString());
        return new ApiException(ErrorCode.BILLING_PROVIDER_UNAVAILABLE);
    }

    /**
     * 토스 v1 에러 본문 {@code {"code":"...","message":"..."}} 에서 문구만 꺼낸다.
     *
     * <p>꺼내지 못하면 null 을 돌려주고, 그러면 {@link ApiException} 이 {@link ErrorCode} 의
     * 기본 문구를 쓴다 — 실패해도 사용자 응답은 여전히 온전하다.
     * <b>파싱 실패로 예외를 던지면 "에러를 만들다가 에러가 나는" 최악의 모양</b>이 된다
     * ({@code AiServiceClient.extractDetail} 과 같은 이유).
     */
    private String extractTossMessage(RestClientResponseException e) {
        try {
            JsonNode message = objectMapper.readTree(e.getResponseBodyAsString()).path("message");
            // ⚠️ Jackson 3 에서 isTextual() 이 isString() 으로 바뀌었다. 2.x 예제를 그대로 쓰면 deprecated 다.
            return message.isString() && !message.asString().isBlank() ? message.asString() : null;
        } catch (RuntimeException ignored) {
            return null;
        }
    }

    private void sleep() {
        try {
            Thread.sleep(RETRY_DELAY.toMillis());
        } catch (InterruptedException ie) {
            // 인터럽트를 삼키면 상위(요청 취소·종료)가 신호를 잃는다. 복원하고 즉시 포기한다.
            Thread.currentThread().interrupt();
            throw new ApiException(ErrorCode.BILLING_PROVIDER_UNAVAILABLE);
        }
    }

    // TODO(Task 3): deleteBillingKey(String billingKey) — DELETE /v1/billing/{billingKey}.
    //   지금 만들지 않는 이유는 호출자가 없기 때문이다. 이 저장소는 호출자 없는 메서드가
    //   "검증되지 않은 채 동작한다는 인상만 남긴다" 는 것을 AiServiceClient.listDocuments 에서
    //   이미 문서화했다.
}
```

- [ ] **Step 10: `ErrorCode` 에 4개를 더한다**

`api/src/main/java/com/alldap/api/global/exception/ErrorCode.java` 의 `EVAL_NOT_READY(...)` 항목 **바로 다음**, `// ── 그 외 ──` 주석 **앞**에 넣는다:

```java
    // ── 결제 수단 (토스 빌링키) ───────────────────────────────────────────
    // 🔴 INVALID_INPUT 하나로 뭉치지 않는 이유: 프론트가 "카드를 바꿔 다시 시도하세요" 와
    //    "우리 쪽 문제라 잠시 후 다시 시도하세요" 를 <다르게> 안내해야 하기 때문이다.
    //    뭉치면 사용자가 카드를 몇 번이나 다시 넣어보게 만든다.
    //
    // ⚠️ BILLING_AUTH_FAILED 의 기본 문구는 실제로는 거의 쓰이지 않는다 —
    //    토스가 상황별로 더 구체적인 한국어를 주고(예: "카드 유효기간이 올바르지 않습니다.")
    //    TossClient 가 그 문구를 그대로 실어 보낸다. 여기 문구는 파싱에 실패했을 때의 보루다.
    BILLING_AUTH_FAILED(HttpStatus.BAD_REQUEST, "BILLING_AUTH_FAILED",
            "카드 등록에 실패했습니다. 카드 정보를 확인한 뒤 다시 시도하거나 다른 카드로 등록해주세요."),
    BILLING_PROVIDER_UNAVAILABLE(HttpStatus.SERVICE_UNAVAILABLE, "BILLING_PROVIDER_UNAVAILABLE",
            "결제 서비스에 일시적으로 연결할 수 없습니다. 잠시 후 다시 시도해주세요."),
    BILLING_METHOD_ALREADY_EXISTS(HttpStatus.CONFLICT, "BILLING_METHOD_ALREADY_EXISTS",
            "이미 등록된 카드가 있습니다. 카드를 바꾸려면 등록된 카드를 삭제한 뒤 다시 등록해주세요."),
    BILLING_METHOD_NOT_FOUND(HttpStatus.NOT_FOUND, "BILLING_METHOD_NOT_FOUND",
            "등록된 카드가 없습니다. 결제 수단 화면에서 카드를 먼저 등록해주세요."),

```

> ⚠️ `BILLING_METHOD_NOT_FOUND` 는 **Task 3(삭제)에서만 쓰인다.** 지금 함께 넣는 이유는 enum 상수 하나가 파일 한 곳을 두 번 건드리게 만들 값을 하지 않기 때문이다. 계획서의 고정 인터페이스가 4개를 함께 못박은 것도 같은 이유다.

- [ ] **Step 11: 엔티티와 리포지토리를 만든다**

`api/src/main/java/com/alldap/api/domain/billing/entity/BillingMethod.java`:

```java
package com.alldap.api.domain.billing.entity;

import com.alldap.api.domain.billing.service.CardIssuer;
import com.alldap.api.global.common.BaseEntity;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.util.UUID;

/**
 * 계정에 등록된 결제 수단(토스 빌링키) 한 장. <b>계정당 최대 1장</b>이다.
 *
 * <p>스키마 대조 ({@code V6__billing_method.sql}):
 * <pre>
 * id                 UUID PRIMARY KEY
 * user_id            UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE
 * billing_key_enc    VARCHAR(512) NOT NULL   ← Base64(IV ‖ 암호문 ‖ GCM 태그)
 * issuer_code        VARCHAR(4)   NOT NULL
 * card_number_masked VARCHAR(20)  NOT NULL
 * created_at         TIMESTAMPTZ  NOT NULL   ← BaseEntity
 * </pre>
 * updated_at 컬럼은 없다. 카드는 고치는 게 아니라 지우고 다시 등록하는 것이다.
 *
 * <p><b>왜 {@code @ManyToOne User} 가 아니라 {@code UUID userId} 인가.</b>
 * {@code UsageEvent} 와 같은 이유다 — 여기서 사용자를 타고 갈 일이 없고,
 * {@code open-in-view=false} 라 LAZY 프록시를 트랜잭션 밖으로 들고 나가면 터진다.
 *
 * <p>🔴 <b>이 엔티티에 빌링키 평문이 들어오는 일은 없다.</b> 필드 이름이 {@code billingKeyEnc} 인 것이
 * 그 약속이다. 복호화는 {@code BillingCrypto} 만 하고, 그 결과는 토스로 나갈 때만 존재한다.
 *
 * <p><b>setter 도 도메인 메서드도 두지 않는다.</b> 카드 정보를 바꾸는 연산이 없기 때문이다
 * (교체 = 삭제 후 재등록). 상태 전이가 없으면 만들지 않는다.
 */
@Getter
@Entity
@Table(name = "billing_methods")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class BillingMethod extends BaseEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    @Column(name = "id", nullable = false, updatable = false)
    private UUID id;

    @Column(name = "user_id", nullable = false, updatable = false, unique = true)
    private UUID userId;

    /** Base64(IV 12B ‖ 암호문 ‖ GCM 인증태그 16B). 평문이 아니다. */
    @Column(name = "billing_key_enc", length = 512, nullable = false, updatable = false)
    private String billingKeyEnc;

    /** 토스 카드 발급사 코드("61"). 이름은 {@link CardIssuer} 가 붙인다. */
    @Column(name = "issuer_code", length = 4, nullable = false, updatable = false)
    private String issuerCode;

    /** 토스가 마스킹해서 준 번호("43301234****123*"). 전체 번호는 우리 서버에 닿지 않는다. */
    @Column(name = "card_number_masked", length = 20, nullable = false, updatable = false)
    private String cardNumberMasked;

    public static BillingMethod create(UUID userId, String billingKeyEnc,
                                       String issuerCode, String cardNumberMasked) {
        BillingMethod method = new BillingMethod();
        method.userId = userId;
        method.billingKeyEnc = billingKeyEnc;
        method.issuerCode = issuerCode;
        method.cardNumberMasked = cardNumberMasked;
        return method;
    }
}
```

`api/src/main/java/com/alldap/api/domain/billing/repository/BillingMethodRepository.java`:

```java
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
```

- [ ] **Step 12: 요청·응답 DTO 를 만든다**

`api/src/main/java/com/alldap/api/domain/billing/dto/RegisterBillingMethodRequest.java`:

```java
package com.alldap.api.domain.billing.dto;

import jakarta.validation.constraints.NotBlank;

/**
 * {@code POST /api/billing/method} 요청 본문.
 *
 * <p>🔴 <b>{@code customerKey} 를 받으면서도 신뢰하지 않는다.</b> 토스가 리다이렉트 쿼리로
 * 돌려준 값을 브라우저가 그대로 실어 보내는 것이라, 신뢰하면 남의 {@code customerKey} 를
 * 적어 보내는 것만으로 <b>카드가 남에게 붙는다.</b>
 * 서버는 JWT 사용자의 것을 DB 에서 읽어 토스에 넘기고, 이 값은 <b>대조에만</b> 쓴다.
 *
 * <p>그럼 왜 받는가: 대조가 있어야 <b>결제창을 연 계정과 지금 로그인한 계정이 다르다</b>는
 * 상황(브라우저 탭 두 개, 세션 만료 후 재로그인)을 잡아낼 수 있다.
 * 안 받으면 그 경우 엉뚱한 계정에 조용히 등록된다.
 *
 * <p>{@code userId} 는 본문에 없다 — {@code @AuthenticationPrincipal} 로만 받는다.
 * 이 저장소의 규칙이자, 위 사고를 막는 같은 원리다.
 */
public record RegisterBillingMethodRequest(

        @NotBlank(message = "카드 인증 정보가 없습니다. 카드 등록을 처음부터 다시 진행해주세요.")
        String authKey,

        @NotBlank(message = "고객 식별 정보가 없습니다. 카드 등록을 처음부터 다시 진행해주세요.")
        String customerKey
) {
}
```

`api/src/main/java/com/alldap/api/domain/billing/dto/BillingMethodResponse.java`:

```java
package com.alldap.api.domain.billing.dto;

import com.alldap.api.domain.billing.service.CardIssuer;

import java.time.OffsetDateTime;

/**
 * 결제 수단 조회·등록 응답.
 *
 * <p>🔴 <b>{@code billingKey} 필드가 없다. 앞으로도 두지 않는다.</b> 필드가 있으면 언젠가 실린다.
 *
 * <p><b>카드가 없어도 {@code customerKey} 는 항상 내려간다.</b> 프론트가 토스 결제창을 열려면
 * 그 값이 필요하기 때문이다 — 카드를 등록하기 <b>전에</b> 알아야 하는 값이라
 * "카드가 없으면 응답이 비어 있다" 로 만들면 등록 자체를 시작할 수 없다.
 *
 * <p>{@code method} 는 카드가 없으면 {@code null} 이다. 필드를 통째로 빼지 않는 이유:
 * 프론트가 "카드가 없다" 와 "아직 안 불러왔다" 를 구별해야 한다.
 *
 * @param method 등록된 카드. 없으면 null
 */
public record BillingMethodResponse(String customerKey, Card method) {

    /**
     * @param issuerName       카드사 <b>이름</b>. 토스는 코드("61")만 주므로 Spring 이 변환한다
     *                         ({@link CardIssuer}). 프론트에 매핑을 두면 {@code web/lib/types.ts} 가
     *                         백엔드 응답과 어긋난다.
     * @param cardNumberMasked 토스가 마스킹해서 준 번호
     * @param registeredAt     우리 {@code created_at} 을 한국 시간 오프셋으로 내려준다.
     *                         토스의 {@code authenticatedAt} 을 저장하지 않은 이유는
     *                         카드를 한 장만 두는 동안 둘을 구별해 쓸 일이 없기 때문이다.
     */
    public record Card(String issuerName, String cardNumberMasked, OffsetDateTime registeredAt) {
    }
}
```

- [ ] **Step 13: `BillingService` 를 만든다 (find · register)**

`api/src/main/java/com/alldap/api/domain/billing/service/BillingService.java`:

```java
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

    // TODO(Task 3): delete(UUID userId) — 토스 먼저, 우리 나중.
    //   순서를 뒤집으면 토스 호출이 실패했을 때 우리는 키를 이미 지운 뒤라 영영 폐기할 수 없다.
}
```

- [ ] **Step 14: `BillingController` 를 만든다**

`api/src/main/java/com/alldap/api/domain/billing/controller/BillingController.java`:

```java
package com.alldap.api.domain.billing.controller;

import com.alldap.api.domain.billing.dto.BillingMethodResponse;
import com.alldap.api.domain.billing.dto.RegisterBillingMethodRequest;
import com.alldap.api.domain.billing.service.BillingService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.UUID;

/**
 * 결제 수단 API. 인증 필요.
 *
 * <p>🔴 <b>{@code userId} 를 경로·쿼리·본문으로 받지 않는다.</b> {@code @AuthenticationPrincipal}
 * 로만 받는다 — 파라미터로 받으면 남의 id 를 적어 보내는 것만으로 남의 카드를 보거나 붙일 수 있다.
 * 봇 소유권 검사가 없는 이유도 같다: 이 리소스는 <b>토큰의 주인</b> 자체로 좁혀져 있다.
 *
 * <p>{@code SecurityConfig} 를 고칠 필요가 없다 — 공개 경로는
 * {@code /api/auth/signup}·{@code /api/auth/login}·{@code /api/w/**}·{@code /actuator/health}·
 * {@code /widget/**} 뿐이고, 나머지 {@code /api/**} 는 {@code anyRequest().authenticated()} 로
 * 이미 인증을 요구한다.
 *
 * <p>DELETE 는 Task 3 에서 붙인다.
 */
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/billing/method")
public class BillingController {

    private final BillingService billingService;

    /** GET /api/billing/method — 카드가 없으면 {@code method: null}, customerKey 는 항상 온다 */
    @GetMapping
    public ResponseEntity<BillingMethodResponse> get(@AuthenticationPrincipal UUID userId) {
        return ResponseEntity.ok(billingService.find(userId));
    }

    /**
     * POST /api/billing/method — 토스 {@code authKey} 를 빌링키로 바꿔 저장한다.
     *
     * <p>201 이 아니라 200 인 이유: 프론트가 등록 직후 카드 정보를 그대로 화면에 그려야 해서
     * 본문이 필요하고, 이 리소스는 계정당 하나뿐이라 클라이언트가 따라갈 새 주소가 없다
     * (Location 헤더로 가리킬 것이 {@code GET} 과 같은 주소다).
     */
    @PostMapping
    public ResponseEntity<BillingMethodResponse> register(
            @AuthenticationPrincipal UUID userId,
            @Valid @RequestBody RegisterBillingMethodRequest request) {
        return ResponseEntity.ok(billingService.register(userId, request));
    }
}
```

- [ ] **Step 15: `TossStub` 을 만든다**

`api/src/test/java/com/alldap/api/support/TossStub.java`:

```java
package com.alldap.api.support;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Queue;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * 토스페이먼츠 자리에 세우는 <b>가짜 HTTP 서버</b>. {@link AiServiceStub} 과 같은 패턴이다.
 *
 * <h2>왜 진짜 HTTP 서버를 세우는가 (Mockito 대신)</h2>
 * 이 슬라이스에서 검증하려는 것 대부분이 <b>HTTP 경계에서만 드러난다.</b>
 * <ul>
 *   <li>{@code Authorization} 이 {@code base64(secretKey + ":")} 인가 — <b>바이트를 봐야</b> 안다.
 *       콜론이 빠져도 자바 코드는 멀쩡히 컴파일되고, 실패는 토스에서만 드러난다</li>
 *   <li>재시도가 <b>같은 {@code Idempotency-Key}</b> 를 쓰는가 — 실제로 나간 두 요청을 비교해야 안다.
 *       {@code TossClient} 를 Mockito 로 흉내내면 "우리가 상상한 호출" 만 검증하게 된다</li>
 *   <li>연결이 끊겼을 때 어떤 예외가 오는가 — 진짜로 끊어야 재현된다.
 *       이 저장소는 <b>통합 테스트 71건이 전부 초록불인 상태에서</b> HTTP/2 업그레이드 버그를 놓쳤다</li>
 * </ul>
 *
 * <h2>왜 WireMock 이 아니라 JDK 내장 서버인가</h2>
 * {@code com.sun.net.httpserver.HttpServer} 는 JDK 에 들어 있어 <b>의존성이 0개</b>다.
 * 필요한 기능이 "정해둔 응답 돌려주기 + 받은 요청 기록하기" 둘뿐이라
 * 라이브러리를 하나 더 들이는 값을 하지 못한다.
 *
 * <h2>⚠️ {@code setExecutor} 를 빠뜨리면 테스트가 서로를 오염시킨다</h2>
 * {@link AiServiceStub} 클래스 주석에 겪은 사고가 적혀 있다. 여기도 같은 이유로 스레드 풀을 준다
 * (지금은 느린 응답 기능이 없어 증상이 덜하지만, 나중에 누가 추가하는 순간 같은 함정에 빠진다).
 *
 * <h2>포트를 0으로 여는 이유</h2>
 * OS 가 비어 있는 포트를 고르게 한다. 실제 포트는 {@link #baseUrl()} 로 알아내
 * {@code app.toss.base-url} 에 주입한다({@link TestcontainersConfiguration} 참고).
 */
public class TossStub implements AutoCloseable {

    private final HttpServer server;
    private final ExecutorService executor = Executors.newCachedThreadPool();

    /** 테스트가 미리 넣어두는 응답 대기열. 요청 처리 스레드와 테스트 스레드가 다르므로 Concurrent 계열이다. */
    private final Queue<Canned> canned = new ConcurrentLinkedQueue<>();

    /** 스텁이 실제로 받은 요청들. "무엇이 나갔는지" 를 확인하는 데 쓴다. */
    private final List<Recorded> received = Collections.synchronizedList(new ArrayList<>());

    private record Canned(int status, String body, boolean abort) {
    }

    /**
     * @param headers 요청 헤더. 이름은 <b>소문자로 정규화</b>해 담는다(HTTP 헤더는 대소문자를 구분하지 않는다).
     */
    public record Recorded(String method, String path, String body, Map<String, String> headers) {

        /** 없으면 null. {@code Idempotency-Key} → {@code "idempotency-key"} 로 찾는다. */
        public String header(String name) {
            return headers.get(name.toLowerCase(Locale.ROOT));
        }
    }

    public TossStub() {
        try {
            server = HttpServer.create(new InetSocketAddress(0), 0);
        } catch (IOException e) {
            throw new IllegalStateException("가짜 토스 서버를 띄우지 못했습니다.", e);
        }
        server.createContext("/", this::handle);
        server.setExecutor(executor);
        server.start();
    }

    public String baseUrl() {
        return "http://localhost:" + server.getAddress().getPort();
    }

    /**
     * 스프링이 {@code AutoCloseable} 빈의 {@code close()} 를 소멸 콜백으로 잡아준다.
     * 디스패처 스레드와 풀이 데몬이 아니라, 정리하지 않으면 JVM 이 종료되지 않을 수 있다.
     */
    @Override
    public void close() {
        server.stop(0);
        executor.shutdownNow();
    }

    // ── 테스트가 쓰는 조작 API ────────────────────────────────────────────

    /** 다음 요청에 이 응답을 돌려준다. */
    public void enqueue(int status, String body) {
        canned.add(new Canned(status, body, false));
    }

    /**
     * 다음 요청에 <b>응답하지 않고 연결을 끊는다.</b> "토스와의 통신이 끊겼다" 를 재현한다.
     * 클라이언트가 받는 결과는 연결 거부·읽기 타임아웃과 같은 "응답을 못 받은 I/O 실패" 라
     * {@code TossClient} 의 같은 재시도 분기를 탄다.
     */
    public void enqueueAbort() {
        canned.add(new Canned(0, null, true));
    }

    public List<Recorded> received() {
        return List.copyOf(received);
    }

    /** 테스트 사이의 격리. 대기열과 기록을 함께 비운다. */
    public void reset() {
        canned.clear();
        received.clear();
    }

    // ── 요청 처리 ────────────────────────────────────────────────────────

    private void handle(HttpExchange exchange) throws IOException {
        byte[] requestBody = exchange.getRequestBody().readAllBytes();

        Map<String, String> headers = new HashMap<>();
        exchange.getRequestHeaders().forEach((name, values) ->
                headers.put(name.toLowerCase(Locale.ROOT), String.join(",", values)));

        received.add(new Recorded(
                exchange.getRequestMethod(),
                exchange.getRequestURI().getPath(),
                new String(requestBody, StandardCharsets.UTF_8),
                headers));

        Canned response = canned.poll();
        if (response == null) {
            // 준비 안 된 요청을 조용히 성공시키지 않는다. 500 으로 답해야
            // "테스트가 예상 못 한 호출이 나갔다" 는 사실이 드러난다.
            respond(exchange, 500, "{\"code\":\"STUB_NOT_READY\",\"message\":\"스텁에 준비된 응답이 없습니다\"}");
            return;
        }

        if (response.abort()) {
            exchange.close();   // 응답 헤더도 안 보내고 끊는다 → 클라이언트는 I/O 실패로 본다
            return;
        }

        respond(exchange, response.status(), response.body());
    }

    private void respond(HttpExchange exchange, int status, String body) throws IOException {
        byte[] bytes = body == null ? new byte[0] : body.getBytes(StandardCharsets.UTF_8);

        // 토스의 한국어 에러 문구가 오가므로 charset 을 명시한다. 빠뜨리면 클라이언트가
        // 기본 charset 으로 디코딩해 문구가 깨지고, "코드는 멀쩡한데 테스트만 실패" 한다.
        exchange.getResponseHeaders().add("Content-Type", "application/json; charset=utf-8");
        exchange.sendResponseHeaders(status, status == 204 || bytes.length == 0 ? -1 : bytes.length);

        if (bytes.length > 0 && status != 204) {
            try (OutputStream out = exchange.getResponseBody()) {
                out.write(bytes);
            }
        }
        exchange.close();
    }
}
```

- [ ] **Step 16: `TestcontainersConfiguration` 에 `TossStub` 을 등록한다**

`api/src/test/java/com/alldap/api/support/TestcontainersConfiguration.java` 의 `aiServicePropertiesRegistrar(...)` 메서드 **다음**, 클래스 닫는 `}` **앞**에 넣는다:

```java
    /**
     * 토스페이먼츠 자리에 세우는 가짜 서버. <b>{@link AiServiceStub} 과 같은 이유로 여기(공유 설정)에 둔다</b> —
     * 결제 테스트에만 필요하다고 그쪽에 두면 그 테스트만 {@code @SpringBootTest} 설정이 달라져
     * 컨텍스트가 하나 더 생기고 Docker 컨테이너도 하나 더 뜬다.
     */
    @Bean
    TossStub tossStub() {
        return new TossStub();
    }

    /**
     * 가짜 토스의 주소와 짧은 타임아웃을 주입한다.
     *
     * <p>{@code DynamicPropertyRegistrar} 빈을 <b>따로 두는 이유</b>: 위 AI 용 등록부에 섞으면
     * 한 메서드가 서로 무관한 두 상대의 설정을 들고 있게 된다. 스프링은 등록부 빈을 전부 모아 적용한다.
     *
     * <p>{@code secret-key} 를 넣는 이유: {@code application.yaml} 의 기본값이 비어 있어서
     * ({@code ${TOSS_SECRET_KEY:}}) 그대로 두면 {@code Authorization} 이 {@code Basic Og==}(":" 만)이
     * 되어, "콜론이 붙는가" 를 검증하는 테스트가 <b>키가 비어도 통과</b>한다.
     */
    @Bean
    DynamicPropertyRegistrar tossPropertiesRegistrar(TossStub stub) {
        return registry -> {
            registry.add("app.toss.base-url", stub::baseUrl);
            registry.add("app.toss.secret-key", () -> "test_sk_stub_secret");
            registry.add("app.toss.connect-timeout", () -> "1s");
            registry.add("app.toss.read-timeout", () -> "2s");
        };
    }
```

> ⚠️ **컨텍스트가 `app.billing-crypto.key` 를 못 찾아 기동에 실패하면** Task 1 이 `application.yaml` 에 로컬 기본값을 넣지 않은 것이다. 위 등록부에 한 줄을 더한다 — `registry.add("app.billing-crypto.key", () -> "dGVzdC1vbmx5LTMyLWJ5dGUta2V5LWZvci1nY20hIQ==");` (Base64 32바이트). **그렇게 했다면 그 사실을 보고에 적는다.**

- [ ] **Step 17: 테스트를 돌려 통과를 확인한다**

```bash
cd /Users/cheonjamin/projects/AllDap/api && ./gradlew test --tests 'BillingIntegrationTest'
```

Expected: PASS (10건)

> ⚠️ **`SchemaManagementException` / `Schema-validation: missing table [billing_methods]` 로 실패하면** DB 볼륨에 V6 가 안 붙은 것이 아니라(Testcontainers 는 매번 새 DB 다) `V6__billing_method.sql` 이 `src/main/resources/db/migration/` 에 없는 것이다. Step 1 로 돌아간다.
>
> ⚠️ **`카드_등록_성공` 이 `issuerName` 에서 `"카드"` 를 받으면** `CardIssuer` 에 `"61"` 이 빠진 것이다. Step 8 의 표를 확인한다.
>
> ⚠️ **`연결이_끊기면_같은_멱등키로_재시도한다` 가 `received()` 크기 1 로 실패하면** 예외가 `ResourceAccessException` 이 아니라 다른 타입으로 온 것이다. `TossClient.issue` 의 `catch (RestClientException e)` 안에서 `log.warn("[디버그] 실패 타입={}", e.getClass().getName(), e)` 를 임시로 찍어 실제 타입을 확인하고, `ioFailure` 판정에 그 타입을 더한다. **더했다면 그 타입 이름을 보고에 적는다.**
>
> **실제 출력의 결과 줄을 그대로 보고에 붙인다.** "돌려봤다" 로는 이 저장소의 검증 기준을 만족하지 않는다.

- [ ] **Step 18: 전체 테스트로 회귀를 확인한다**

```bash
cd /Users/cheonjamin/projects/AllDap/api && ./gradlew test
```

Expected: PASS — 실패 0건. `RestClient` 빈이 둘로 늘고 `User.create` 가 컬럼을 하나 더 채우게 됐으므로 **기존 인증·봇·문서·채팅·로그·평가·사용량 테스트가 전부 그대로 통과해야 한다.**

> ⚠️ 총 건수는 Task 1 이 더한 `BillingCryptoTest` 만큼 함께 늘어난다. 숫자를 미리 적어두지 않는다 — **실제 출력의 마지막 요약 줄을 그대로 보고에 붙인다.**
>
> ⚠️ **기존 테스트가 `NoUniqueBeanDefinitionException` 으로 무더기로 깨지면** Step 7 의 탈출구(`@Qualifier`)를 적용한다.

- [ ] **Step 19: 커밋한다**

```bash
cd /Users/cheonjamin/projects/AllDap
git add \
  api/src/main/java/com/alldap/api/global/config/TossProperties.java \
  api/src/main/java/com/alldap/api/global/config/TossClientConfig.java \
  api/src/main/java/com/alldap/api/domain/billing/ \
  api/src/main/java/com/alldap/api/global/exception/ErrorCode.java \
  api/src/main/resources/application.yaml \
  api/src/main/resources/application-prod.yaml \
  .env.example .env.prod.example docker-compose.prod.yml \
  api/src/test/java/com/alldap/api/support/TossStub.java \
  api/src/test/java/com/alldap/api/support/TestcontainersConfiguration.java \
  api/src/test/java/com/alldap/api/domain/billing/
git status --short
```

> ⚠️ **`git add -A` 를 쓰지 말 것.** 작업 트리에 이 작업과 무관한 미커밋 파일이 있다(`widget/demo.html` 수정본, 미추적 `docs/이해노트-2026-09-01.md`). `git status --short` 출력에 그 둘이 **스테이징되지 않은 채로** 남아 있는지 확인하고 넘어간다.
>
> ⚠️ Step 1 의 탈출구를 써서 `V6__billing_method.sql` 과 `User.java` 를 이 Task 에서 만들었다면 그 두 경로도 `git add` 에 더한다.

```bash
git commit -m "$(cat <<'EOF'
feat: 토스 빌링키 발급 연동과 결제 수단 등록·조회

GET·POST /api/billing/method 를 붙였다. 삭제는 다음 조각이다.

- TossClient 는 RestClient 빈과 서킷을 AiServiceClient 와 공유하지 않는다.
  공유하면 토스 장애가 채팅을 끊고 그 반대도 된다.
- 🔴 I/O 실패에 <같은 멱등키로> 1회 재시도한다. AiServiceClient 의
  "연결 실패에만" 논리를 쓸 수 없다 — 읽기 타임아웃이어도 토스는 이미
  발급했을 수 있고, 토스에 빌링키 조회 API 가 없어 그 키는 영구히 회수 불가다.
  멱등키가 "직전 시도가 아무 일도 하지 않았다" 는 전제를 대신 세워준다.
- 실패 변환은 TossClient 안에서 끝낸다. 4xx 는 토스의 한국어 문구를 그대로
  싣고, 401 만 따로 떼어 503 으로 돌린다(사용자 잘못이 아니라 키 설정 문제다).
- register 는 쿼리로 온 customerKey 를 신뢰하지 않는다. DB 의 값을 토스에
  넘기고 요청 값과 다르면 400 — 신뢰하면 카드가 남의 계정에 붙는다.
- 응답 DTO 에 billingKey 필드를 두지 않는다. 있으면 언젠가 실린다.
- BillingService 에 @Transactional 을 붙이지 않았다. 외부 호출을 트랜잭션에
  넣으면 커넥션 풀이 말라 결제와 무관한 요청까지 멈춘다(채팅에서 겪은 것).
  중복의 마지막 방어선은 DB 의 UNIQUE(user_id) 다.
- 통합 테스트 10건: 진짜 톰캣 + 진짜 Postgres + TossStub(JDK HttpServer).

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: 결제 수단 삭제 — 토스 먼저, 우리 나중

**Files:**
- Modify: `api/src/main/java/com/alldap/api/domain/billing/client/TossClient.java`
- Modify: `api/src/main/java/com/alldap/api/domain/billing/service/BillingService.java`
- Modify: `api/src/main/java/com/alldap/api/domain/billing/controller/BillingController.java`
- Test: `api/src/test/java/com/alldap/api/domain/billing/BillingIntegrationTest.java` (확장)

> ⚠️ **위 4개 경로는 Task 1·2 가 실제로 만든 위치와 다를 수 있다.** 이 계획서는 저장소 관례
> (`domain/x/{controller,service,entity,repository,dto,client}`)를 가정했다.
> Step 1 의 `find` 결과가 다르면 **그 경로를 쓰고, 바꿨다는 사실을 보고에 적는다.**

**Interfaces:**
- Consumes (Task 1·2 가 만든 것):
  - `BillingCrypto#decrypt(String stored) -> String`
  - `BillingMethodRepository#findByUserId(UUID) -> Optional<BillingMethod>`, `JpaRepository#delete(BillingMethod)`
  - `BillingMethod#getBillingKeyEnc() -> String`
  - `ErrorCode.BILLING_METHOD_NOT_FOUND`(404) · `ErrorCode.BILLING_PROVIDER_UNAVAILABLE`(503)
  - `RegisterBillingMethodRequest(String authKey, String customerKey)`
  - `TossStub#baseUrl()` · `#reset()` · `#enqueue(int, String)` · `#received()`
  - `RestClient tossRestClient` 빈 (`TossClientConfig`)
- Produces (Task 4·5 가 의존):
  - `TossClient#deleteBillingKey(String billingKey) -> void`
  - `BillingService#delete(UUID userId) -> void`
  - `DELETE /api/billing/method` → **204** (없으면 404, 토스 5xx·타임아웃이면 503)

---

- [ ] **Step 1: 앞 Task 가 남긴 실제 이름·경로를 확인한다**

이 Task 는 처음부터 만드는 것이 하나도 없고 **전부 기존 파일에 얹는다.** 필드명·경로를 추측하면
컴파일이 깨지므로 먼저 눈으로 본다.

```bash
cd /Users/cheonjamin/projects/AllDap
git branch --show-current
find api/src/main/java/com/alldap/api/domain/billing api/src/test/java/com/alldap/api/domain/billing -type f | sort
echo '--- TossClient ---';      cat api/src/main/java/com/alldap/api/domain/billing/client/TossClient.java
echo '--- BillingService ---';  cat api/src/main/java/com/alldap/api/domain/billing/service/BillingService.java
echo '--- Controller ---';      cat api/src/main/java/com/alldap/api/domain/billing/controller/BillingController.java
echo '--- TossStub 공개 API ---'; grep -n "public " api/src/test/java/com/alldap/api/support/TossStub.java
echo '--- Test 필드·보조 ---';   grep -n "private \|@Autowired\|@LocalServerPort\|record Response" api/src/test/java/com/alldap/api/domain/billing/BillingIntegrationTest.java
```

확인할 것 다섯 가지. **하나라도 어긋나면 아래 코드의 그 이름만 바꿔 쓰고, 바꿨다는 사실을 보고에 적는다.**

| 확인 | 이 계획이 가정한 것 |
|---|---|
| 현재 브랜치 | `feat/billing-method` (Task 1 이 만든 것). 아니면 `git switch feat/billing-method` |
| `TossClient` 의 RestClient 필드명 | `tossRestClient` |
| `BillingService` 의 필드명 | `tossClient` · `billingCrypto` · `billingMethodRepository` |
| `BillingService`/`TossClient` 에 `@Slf4j` | 붙어 있다 (없으면 `lombok.extern.slf4j.Slf4j` 를 import 하고 붙인다) |
| 테스트 클래스의 필드 | `client` · `tossStub` · `ownerToken` · `userId` · `jdbcTemplate`, 보조 `request(HttpMethod, String, String, Object)` 와 `record Response(int status, String body)` |

> ⚠️ **`TossStub#received()` 가 없으면** (Task 2 가 기록 기능을 안 만들었으면) 이 Task 의 Step 3
> 테스트가 컴파일되지 않는다. 그럴 때는 `api/src/test/java/com/alldap/api/support/AiServiceStub.java`
> 의 `Recorded` record · `received` 리스트 · `handle()` 안의 `received.add(...)` · `received()` ·
> `reset()` 의 `received.clear()` 를 **그대로 옮겨 붙인다**(같은 패턴으로 만들라는 것이 설계 §검사 2 의 지시다).
> **옮겨 붙였다면 그 사실을 보고에 적는다.**

- [ ] **Step 2: `BillingService` 에 `@Transactional` 이 붙어 있는지 확인하고, 붙어 있으면 뗀다**

```bash
grep -n "Transactional" api/src/main/java/com/alldap/api/domain/billing/service/BillingService.java
```

**클래스에도 메서드에도 `@Transactional` 이 없어야 한다.** 하나라도 있으면 지운다(import 도 함께).

왜 지우는가는 다음 Step 의 주석에 다 적지만, 요지는 이것이다 — 이 서비스의 주 작업은 DB 트랜잭션이
아니라 **수 초 걸리는 외부 HTTP 호출**이다. 트랜잭션 안에 넣으면 그동안 DB 커넥션 하나가 묶이고,
기본 풀이 10 이라 결제 화면 몇 개가 **채팅까지 멈춘다.** `DocumentService` · `EvalService` ·
`ConflictService` 가 전부 같은 이유로 클래스 애너테이션을 안 붙였다.

> ⚠️ **`register` 에서 지운 경우** — 등록도 토스를 부르므로 같은 이유로 없는 게 맞다.
> 다만 Task 2 의 테스트가 그 애너테이션에 기대고 있었다면 Step 6 전체 실행에서 드러난다.
> 깨지면 되돌리지 말고 **왜 깨졌는지 원인을 보고에 적는다** — 트랜잭션 없이 깨지는 등록 로직이라면
> 그건 이 Task 가 발견한 진짜 문제다.

- [ ] **Step 3: 실패하는 테스트 5건을 먼저 쓴다**

`BillingIntegrationTest` 의 **마지막 `@Test` 아래, "테스트 보조" 절 위에** 아래를 붙인다.
상수 4개는 클래스 상단의 다른 상수 옆에 둔다.

```java
    // ── 삭제 (설계 §쓰기 경로 ②) ─────────────────────────────────────────

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
    @DisplayName("[삭제] 토스가 4xx 면 우리 행은 지운다 (토스 쪽엔 이미 없다는 뜻)")
    void 토스_4xx_면_우리_행을_지운다() {
        등록한다();
        tossStub.enqueue(404, 토스_4xx);

        Response 응답 = request(HttpMethod.DELETE, "/api/billing/method", ownerToken, null);

        assertThat(응답.status()).isEqualTo(204);
        assertThat(카드_행수(userId)).isZero();

        // 반대로 잡으면(4xx 도 유지) 사용자가 카드를 <영영 못 지운다>.
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
     */
    private void 등록한다() {
        tossStub.enqueue(200, 발급응답_BASE64키);
        String customerKey = request(HttpMethod.GET, "/api/billing/method", ownerToken, null)
                .json().path("customerKey").asString();

        Response 응답 = request(HttpMethod.POST, "/api/billing/method", ownerToken,
                new RegisterBillingMethodRequest("test_auth_key_for_delete", customerKey));

        assertThat(응답.status())
                .as("등록이 먼저 성공해야 삭제를 검사할 수 있다. 응답 본문=%s", 응답.body())
                .isEqualTo(200);
    }

    private long 카드_행수(UUID userId) {
        Long n = jdbcTemplate.queryForObject(
                "SELECT count(*) FROM billing_methods WHERE user_id = ?", Long.class, userId);
        return n == null ? 0 : n;
    }
```

필요한 import 가 없으면 추가한다: `com.alldap.api.domain.billing.dto.RegisterBillingMethodRequest`(Step 1
의 `find` 결과 경로), `org.springframework.http.HttpMethod`, `tools.jackson.databind.JsonNode`,
`java.util.UUID`, `static org.assertj.core.api.Assertions.assertThat`.

> ⚠️ **Task 2 가 이미 같은 일을 하는 보조(예: `register(...)`)나 발급 응답 상수를 만들어 뒀으면
> 그것을 쓰고 위 `등록한다()`·상수를 새로 만들지 말 것.** 다만 **빌링키에 `/` 와 `+` 가 든
> 응답 상수는 반드시 하나 있어야 한다** — 없으면 위 `발급응답_BASE64키` 만 추가한다.
>
> ⚠️ **`발급응답_BASE64키` 의 필드 이름(`billingKey` · `card.issuerCode` · `card.number`)은
> Task 2 의 `TossClient` 가 실제로 파싱하는 이름과 같아야 한다.** Step 1 에서 읽은
> `TossClient`(또는 Task 2 의 응답 DTO)와 대조해 다르면 **그쪽에 맞춘다.**

- [ ] **Step 4: 테스트를 돌려 실패를 확인한다**

```bash
cd /Users/cheonjamin/projects/AllDap/api && ./gradlew test --tests 'BillingIntegrationTest'
```

Expected: **FAIL — 5건.** `DELETE /api/billing/method` 매핑이 아직 없어 스프링이
`HttpRequestMethodNotSupportedException` 을 던지고 `GlobalExceptionHandler` 가 **405** 로 바꾼다.

```
삭제는_토스에_그_키를_보낸다()   expected: 204 but was: 405
토스_5xx_면_우리_행이_남는다()   expected: 503 but was: 405
토스_4xx_면_우리_행을_지운다()   expected: 204 but was: 405
없는_카드를_지우면_404()         expected: 404 but was: 405
삭제하고_다시_등록된다()          expected: 204 but was: 405
```

> ⚠️ **컴파일 에러가 나면 그건 실패가 아니라 Step 1 을 건너뛴 것이다.** `cannot find symbol` 이
> 나온 이름을 Step 1 의 표와 대조해 고친 뒤 다시 돌린다. **"405 5건" 이 나오기 전에는 다음으로 가지 않는다** —
> 컴파일이 안 된 상태로 구현하면 "구현했더니 통과했다"가 아니라 "처음부터 뭘 재는지 몰랐다"가 된다.

- [ ] **Step 5: `TossClient.deleteBillingKey` 를 추가한다**

`TossClient` 클래스 안, `issueBillingKey` **아래에** 붙인다.

```java
    /**
     * 빌링키 폐기. {@code DELETE {base}/v1/billing/{billingKey}}
     *
     * <h2>🔴 반환값이 {@code void} 인 것이 이 메서드의 설계다</h2>
     * 4xx 와 5xx 를 호출부에 구분해 넘겨야 할 것 같지만, 실제로 <b>호출부가 두 경우에 하는 일이 같다</b> —
     * 둘 다 우리 행을 지운다.
     * <ul>
     *   <li><b>200</b> — 토스가 지웠다 → 우리 행도 지운다</li>
     *   <li><b>4xx</b> — 토스 쪽엔 <b>이미 없다</b>. 치울 게 없으니 우리 행만 지운다</li>
     *   <li><b>5xx · I/O</b> — <b>지워졌는지 모른다</b> → 예외를 던진다. 우리 행이 남아야 다시 시도할 수 있다</li>
     * </ul>
     * 즉 호출부가 필요한 신호는 "지워도 되는가 / 아직 아닌가" 하나뿐이고, 그건 <b>예외를 던지느냐</b>로
     * 이미 표현된다. {@code boolean} 을 돌려주는 안도 검토했지만, 호출부가 그 값으로 분기할 일이
     * 없는데 반환값이 있으면 <b>"여기서 뭔가 갈라져야 하는 것 아닌가"</b> 하는 잘못된 인상만 남긴다.
     *
     * <h2>4xx 를 "이미 없다"로 보는 것은 우리 <b>추측</b>이다</h2>
     * 토스 문서에 이 API 의 에러 코드표가 없다 — 없는 빌링키를 지울 때 무슨 코드가 오는지 모른다.
     * 추측이 틀리면(예: 인증 오류도 4xx 다) 토스 쪽에 고아 빌링키가 남는다. 그래도 이쪽을 택한 이유는
     * 반대 선택("4xx 도 유지")이면 <b>사용자가 카드를 영영 못 지우는</b> 상태가 되기 때문이다.
     * 그래서 삼키되 <b>반드시 WARN 으로 남긴다</b> — 고아가 생겼다면 이 로그가 유일한 흔적이다.
     *
     * <h2>멱등키를 붙이지 않는다</h2>
     * 발급({@code issueBillingKey})에는 붙였지만 여기는 아니다. <b>DELETE 는 메서드 자체가 멱등</b>이라
     * (같은 키를 두 번 지워도 결과가 같다) 중복 실행이 새 부작용을 만들지 않는다.
     * 발급이 멱등키를 필요로 했던 이유는 정확히 반대다 — POST 는 부를 때마다 빌링키가
     * <b>하나씩 더 생기고</b>, 조회 API 가 없어 회수할 방법이 없다.
     *
     * <h2>응답 본문을 읽지 않는다</h2>
     * <b>토스 문서가 자기모순이다.</b> API 레퍼런스는 "비어있는 body 에 200 응답만 내려갑니다" 라고
     * 하는데 연동 가이드 FAQ 는 {@code {"billingKey":"..."}} 를 보여준다. 어느 쪽이 맞는지 우리가
     * 정할 수 없으므로 <b>HTTP 상태로만 판정한다.</b> {@code toBodilessEntity()} 가 그 결정을 코드로
     * 못박은 것이다 — 본문을 DTO 로 받게 해두면 언젠가 "그 필드를 쓰는" 코드가 붙고, 그날 토스가
     * 레퍼런스대로 빈 본문을 주면 조용히 깨진다.
     *
     * <p>재시도하지 않는다. 실패해도 <b>우리 행이 남으므로</b> 사용자가 버튼을 다시 누르면 된다 —
     * 그게 "토스 먼저, 우리 나중" 순서가 사주는 것이다.
     */
    public void deleteBillingKey(String billingKey) {
        try {
            tossRestClient.delete()
                    // ⚠️ 문자열로 이어붙이지 말 것. 토스의 빌링키는 base64 라 '/' 와 '+' 가 들어온다
                    //    (문서 예시: "IuLQlvcbmS/5jVDkbnRnAmCn88YZLfnGpVBGpLJ+abU=").
                    //    URI 템플릿 변수로 넘겨야 스프링이 경로 세그먼트 규칙대로 인코딩한다.
                    .uri("/v1/billing/{billingKey}", billingKey)
                    .retrieve()
                    .toBodilessEntity();

        } catch (RestClientResponseException e) {
            if (e.getStatusCode().is4xxClientError()) {
                log.warn("[토스] 빌링키 폐기를 {} 로 거절당했다. 이미 없는 키로 보고 우리 행만 지운다. body={}",
                        e.getStatusCode(), e.getResponseBodyAsString());
                return;   // 삼킨다 = "토스 쪽엔 이미 없다"
            }
            log.error("[토스] 빌링키 폐기 실패 — 토스가 {} 응답. body={}",
                    e.getStatusCode(), e.getResponseBodyAsString());
            throw new ApiException(ErrorCode.BILLING_PROVIDER_UNAVAILABLE);

        } catch (RestClientException e) {
            // 연결 실패·타임아웃·응답 도중 끊김. 전부 <지워졌는지 모르는> 상태다.
            //
            // AiServiceClient 는 여기서 연결 실패(503)와 읽기 타임아웃(504)을 갈랐지만, 그건
            // 사용자가 할 수 있는 행동이 달랐기 때문이다("기다려라" vs "질문을 줄여라").
            // 삭제에는 그런 차이가 없다 — 어느 쪽이든 답은 "잠시 후 다시 눌러주세요" 하나라
            // 나누면 코드만 늘고 안내는 같아진다. ResourceAccessException 도 RestClientException 의
            // 하위 타입이라 이 한 블록이 다 받는다.
            log.error("[토스] 빌링키 폐기 실패 — 토스와 통신하지 못했다.", e);
            throw new ApiException(ErrorCode.BILLING_PROVIDER_UNAVAILABLE);
        }
    }
```

없으면 추가할 import: `org.springframework.web.client.RestClientException`,
`org.springframework.web.client.RestClientResponseException`,
`com.alldap.api.global.exception.ApiException`, `com.alldap.api.global.exception.ErrorCode`.
클래스에 `@Slf4j` 가 없으면 붙인다.

> ⚠️ **`catch` 순서를 바꾸지 말 것.** `RestClientResponseException` 은 `RestClientException` 의
> 하위 타입이라, 순서를 뒤집으면 **자바가 "이미 잡혔다"고 컴파일을 거부**하거나(같은 try) 4xx·5xx 가
> 전부 아래 블록으로 빨려 들어가 **4xx 도 503 이 된다** = 사용자가 카드를 못 지운다.

- [ ] **Step 6: `BillingService.delete` 를 추가한다**

`BillingService` 안, `register` **아래에** 붙인다.

```java
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
     * <b>죽은 키를 가진 행</b>이 남는다. 그런데 그 상태는 스스로 낫는다 — 사용자가 다시 삭제하면
     * 토스가 4xx 를 주고, {@code TossClient} 의 4xx 분기가 "이미 없다"로 보고 행을 지운다.
     * <b>4xx 를 삼키는 설계가 이 사고의 복구 경로이기도 하다.</b>
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
        log.info("[billing] 결제 수단 삭제 userId={}", userId);
    }
```

없으면 추가할 import: `com.alldap.api.global.exception.ApiException`,
`com.alldap.api.global.exception.ErrorCode`, `java.util.UUID`, `BillingMethod`(Step 1 의 경로).
클래스에 `@Slf4j` 가 없으면 붙인다.

- [ ] **Step 7: `BillingController` 에 DELETE 매핑을 추가한다**

```java
    /**
     * DELETE /api/billing/method — 등록된 카드 삭제. 성공하면 본문 없이 <b>204</b>.
     *
     * <p>토스 쪽 빌링키도 함께 폐기된다({@code BillingService.delete} 주석 참고).
     * 실패는 {@code GlobalExceptionHandler} 가 공통 포맷으로 바꿔 내려준다 —
     * 등록된 카드가 없으면 <b>404</b>, 토스가 죽었거나 응답이 없으면 <b>503</b>(이때 카드는 그대로 남는다).
     *
     * <p>경로에 식별자가 없다. 계정당 카드는 한 장이고 "누구의 것인가"는
     * {@code @AuthenticationPrincipal} 이 이미 정한다 — id 를 받으면 남의 id 를 적어 보낼 자리가 생긴다.
     */
    @DeleteMapping("/api/billing/method")
    public ResponseEntity<Void> deleteBillingMethod(@AuthenticationPrincipal UUID userId) {
        billingService.delete(userId);
        return ResponseEntity.noContent().build();
    }
```

없으면 추가할 import: `org.springframework.web.bind.annotation.DeleteMapping`.

- [ ] **Step 8: 결제 테스트를 돌려 통과를 확인한다**

```bash
cd /Users/cheonjamin/projects/AllDap/api && ./gradlew test --tests 'BillingIntegrationTest'
```

Expected: **PASS (15건)** — Task 2 의 10건 + 이 Task 의 5건.

> ⚠️ **`삭제는_토스에_그_키를_보낸다` 만 `path()` 불일치로 깨지면**, 스텁이 받은 실제 경로를 찍어
> 확인한다: 테스트에 임시로 `System.out.println(삭제요청.path())` 를 넣고 한 번 돌린 뒤 지운다.
> `%2F` 가 그대로 보인다면 스텁이 `getRequestURI().getPath()`(디코딩됨)가 아니라 `toString()`(원본)을
> 기록하는 것이다 — 그럴 때는 **테스트의 기댓값을 그 원본 문자열로 바꾸지 말고**, 스텁이
> `AiServiceStub` 과 같이 `getPath()` 를 쓰도록 맞춘다(두 스텁이 다르게 기록하면 나중에
> 둘을 비교하는 사람이 반드시 헷갈린다). **어느 쪽으로 고쳤든 보고에 적는다.**
>
> ⚠️ **`등록한다()` 의 단언(`등록이 먼저 성공해야…`)에서 깨지면** 삭제 코드가 아니라 Task 2 의
> 등록 경로 또는 위 발급 응답 JSON 의 필드 이름 문제다. 붙어 나온 응답 본문을 그대로 보고에 옮기고
> Step 3 의 ⚠️(필드 이름 대조)로 돌아간다.

- [ ] **Step 9: 전체 테스트를 돌려 회귀가 없는지 확인한다**

```bash
cd /Users/cheonjamin/projects/AllDap/api && ./gradlew cleanTest test \
  && grep -h '<testsuite ' build/test-results/test/*.xml \
     | sed -E 's/.* tests="([0-9]+)".*/\1/' | paste -sd+ - | bc
```

Expected: **PASS (144건)**

```
123  Task 시작 전 (2026-09-06 기준 실측)
+ 6  Task 1  BillingCryptoTest        (설계 §검사 1 의 6항목)
+ 10 Task 2  BillingIntegrationTest   (설계 §검사 2 의 1~7 · 12 + 멱등키 재시도 · method=null)
+ 5  Task 3  BillingIntegrationTest   (8~11 · 재등록)
───
 144
```

> `cleanTest` 를 붙이는 이유는 Task 1 Step 15 와 같다 — 앞 Step 에서 일부만 돌려 XML 리포트가
> 반쪽이면 합계가 틀린다. **소스의 `@Test` 개수를 세지 않는다.** 그건 컴파일만 되면
> 전부 실패해도 같은 숫자가 나와서 "돌렸다" 와 "통과했다" 를 뭉갠다 —
> 이 저장소가 반복해서 낸 부류다.

> ⚠️ **총계가 144 가 아니어도 그 자체는 문제가 아니다** — Task 1·2 가 항목을 쪼개거나 합쳤을 수 있다.
> 확인해야 할 것은 숫자가 아니라 **실패가 0 건인가**이다. 실제 총계를 보고에 적는다.
>
> ⚠️ **결제와 무관한 테스트가 깨졌다면** 십중팔구 Step 2 에서 뗀 `@Transactional`, 아니면
> `@BeforeEach` 의 `tossStub.reset()` 누락이다(이 저장소가 "실행 순서에 따라 나타났다 사라지는
> 실패"로 두 번 겪은 부류다). **깨진 테스트 이름과 원인을 보고에 그대로 적는다 — 되돌려서 초록불을
> 만들지 말 것.**
>
> **📋 보고에는 실제 gradle 출력을 붙인다.** "돌려봤다" 가 아니라 실행 결과다.

- [ ] **Step 10: 커밋한다**

```bash
cd /Users/cheonjamin/projects/AllDap
git add api/src/main/java/com/alldap/api/domain/billing/client/TossClient.java \
        api/src/main/java/com/alldap/api/domain/billing/service/BillingService.java \
        api/src/main/java/com/alldap/api/domain/billing/controller/BillingController.java \
        api/src/test/java/com/alldap/api/domain/billing/BillingIntegrationTest.java
git status --short
git commit -F - <<'EOF'
feat: 결제 수단 삭제 — 토스 먼저 폐기하고 우리 행은 나중에 지운다

DELETE /api/billing/method 를 붙였다. 순서가 이 슬라이스의 전부다.

토스에는 빌링키를 <조회>하는 API 가 없어서 우리 DB 가 그 키의 유일한 사본이다.
우리 행을 먼저 지우고 토스 호출이 실패하면 그 키는 영영 폐기할 수 없는 고아가 된다.
그래서 토스 200/4xx 일 때만 우리 행을 지우고, 5xx·타임아웃이면 행을 남기고 503 을 준다.

4xx 를 "토스 쪽엔 이미 없다"로 삼키는 것은 해석이다 — 토스 문서에 이 API 의
에러 코드표가 없다. 틀리면 고아가 남지만, 반대로 잡으면 사용자가 카드를 영영 못 지운다.
그 대신 부수 효과가 하나 있다: 토스 200 과 우리 DELETE 사이에서 프로세스가 죽어
죽은 키를 가진 행이 남아도, 다시 삭제하면 그 4xx 분기가 알아서 치운다.

- TossClient.deleteBillingKey 는 void 다. 호출부가 200 과 4xx 에 하는 일이 같아서
  필요한 신호는 "예외를 던지느냐" 하나뿐이다. 응답 본문은 읽지 않는다(토스 문서가
  레퍼런스와 FAQ 에서 서로 다른 말을 한다). 멱등키도 안 붙인다 — DELETE 는 멱등이다.
- BillingService.delete 에 @Transactional 을 붙이지 않았다. 수 초짜리 외부 호출을
  트랜잭션에 넣으면 커넥션 풀(10)이 말라 채팅까지 멈춘다. 다만 ChatTurnStore 처럼
  빈을 나눌 필요는 없다 — 조회 1번·삭제 1번이라 같은 트랜잭션일 이유가 없다.
- 통합 테스트 5건 추가. 핵심은 "토스가 5xx 면 우리 행이 남는다".
  빌링키에 '/' 와 '+' 가 든 base64 를 쓴다(토스 문서 예시 그대로).

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

> ⚠️ **`git add -A` 를 쓰지 말 것.** 작업 트리에 이 Task 와 무관한 미커밋 파일이 있다
> (`widget/demo.html` 수정, 미추적 `docs/이해노트-2026-09-01.md`). 위 `git status --short` 출력에
> 그 둘만 남아 있는지 확인하고, 결제 관련 파일이 스테이징되지 않은 채 남아 있으면 경로를 명시해 추가한다.

---

## Task 4: 결제 수단 화면

**Files:**
- Modify: `web/package.json` · `web/package-lock.json` (토스 SDK 설치)
- Modify: `web/.env.local.example`
- Modify: `web/.env.local` (커밋하지 않는다 — `.gitignore` 가 막는다)
- Modify: `web/lib/types.ts`
- Modify: `web/lib/api.ts`
- Create: `web/app/(dashboard)/billing/page.tsx`
- Modify: `web/app/(dashboard)/layout.tsx`
- Test: 자동 테스트 없음. **브라우저 종단 1회(Step 9)가 이 Task 의 검증이다** — `web/` 에는 테스트 러너가 설치돼 있지 않고(`package.json` 의 scripts 는 dev·build·start·lint 넷뿐), 이 Task 를 위해 도입하지 않는다. 대신 Step 8(`tsc`+`lint`)과 Step 9(브라우저)를 **둘 다** 통과해야 한다.

**Interfaces:**
- Consumes (Task 3 이 만든 것):
  - `GET /api/billing/method` → `{ "customerKey": "bcus_…", "method": null }` 또는 `{ "customerKey": "bcus_…", "method": { "issuerName": "현대", "cardNumberMasked": "43301234****123*", "registeredAt": "2026-09-06T14:03:11+09:00" } }`
  - `POST /api/billing/method` body `{ "authKey": "...", "customerKey": "bcus_…" }` → 위와 같은 200. 이미 있으면 409(`BILLING_METHOD_ALREADY_EXISTS`), 토스 4xx 면 400(`BILLING_AUTH_FAILED`, 메시지는 토스의 한국어 문장), 토스 5xx·타임아웃이면 503(`BILLING_PROVIDER_UNAVAILABLE`), 쿼리 `customerKey` 가 내 것과 다르면 400
  - `DELETE /api/billing/method` → **204(본문 없음)**. 없으면 404(`BILLING_METHOD_NOT_FOUND`), 토스 5xx 면 503이고 **우리 행은 남는다**
- Produces:
  - `web/lib/types.ts`: `export interface BillingCard { issuerName: string; cardNumberMasked: string; registeredAt: string }` · `export interface BillingMethodResponse { customerKey: string; method: BillingCard | null }`
  - `web/lib/api.ts`: `api.billing.getBillingMethod()` · `api.billing.registerBillingMethod(authKey, customerKey)` · `api.billing.deleteBillingMethod()`
  - 이 Task 에 의존하는 후속 Task 는 없다(Task 5 는 문서만 고친다).

> ⚠️ **함수 이름 3개는 설계가 고정한 것이다.** `getBillingMethod` / `registerBillingMethod` / `deleteBillingMethod` — 한 글자도 바꾸지 말 것. 다만 **놓는 자리는 `api` 객체 안의 `billing` 블록**이다. 이 파일의 모든 엔드포인트가 `api.usage.*` · `api.conflicts.*` 처럼 묶여 있어서, 여기만 최상위 export 로 빼면 화면 코드가 `import { api, getBillingMethod }` 가 되어 관례가 깨진다.

> ⚠️ **Next.js 16.2.12 / React 19.2.4 는 대부분의 모델이 학습한 버전보다 최신이다.** 기억으로 구버전 문법을 쓰지 말 것. Step 1 에서 문서를 먼저 읽는다.

> ⚠️ **모바일 대응은 범위 밖이다**(2026-08-17 결정). 이 화면은 데스크톱만 맞춘다. `sm:` 같은 브레이크포인트를 새로 도입하지 말 것.

---

- [ ] **Step 1: 브랜치를 확인하고 Next 16 문서를 먼저 읽는다**

Task 1~3 이 만든 `feat/billing-method` 위에서 이어서 작업한다. 새로 브랜치를 따지 않는다.

```bash
cd /Users/cheonjamin/projects/AllDap && git branch --show-current
```

Expected: `feat/billing-method`

> ⚠️ 다른 브랜치가 나오면 **거기서 멈추고** `git switch feat/billing-method` 를 한 뒤 다시 확인한다. 그래도 없으면 Task 1 이 안 끝난 것이다 — 보고에 그 사실을 적고 멈춘다.

그다음 이 Task 가 실제로 쓰는 두 API 문서를 읽는다. **읽지 않고 기억으로 쓰지 말 것.**

```bash
cd /Users/cheonjamin/projects/AllDap/web
sed -n '1,120p' node_modules/next/dist/docs/01-app/03-api-reference/04-functions/use-search-params.md
sed -n '1,80p'  node_modules/next/dist/docs/01-app/03-api-reference/04-functions/use-router.md
```

확인할 것은 하나다 — **`useSearchParams` 를 쓰면 가장 가까운 `<Suspense>` 경계까지가 클라이언트 렌더로 떨어지고, 정적으로 프리렌더되는 페이지에서 경계 없이 쓰면 `next build` 가 "Missing Suspense boundary with useSearchParams" 로 실패한다.** 문서에 그렇게 적혀 있다.

그래서 이 계획은 **`useSearchParams` 를 쓰지 않는다.** 착지 파라미터는 딱 한 번, effect 안에서 `window.location.search` 로 읽는다. 이유는 Step 6 의 주석에 그대로 적어둔다.

> ⚠️ 문서를 읽어보니 이 서술과 다르면(경계 없이도 빌드가 통과한다는 등) **그 사실을 보고에 적고**, 그래도 계획대로 `window.location.search` 를 쓴다. 어차피 우리는 URL 을 한 번 읽고 즉시 비우므로 반응형 구독이 필요 없다.

- [ ] **Step 2: 토스 SDK 를 설치하고 실제 버전을 기록한다**

```bash
cd /Users/cheonjamin/projects/AllDap/web && npm install @tosspayments/tosspayments-sdk --save
```

그다음 **실제로 박힌 버전을 눈으로 확인한다.** 토스 문서가 버전을 명시하지 않으므로 계획서가 버전을 지정할 수 없다.

```bash
cd /Users/cheonjamin/projects/AllDap/web && node -p "require('./package.json').dependencies"
```

Expected: `next` · `react` · `react-dom` 에 더해 `@tosspayments/tosspayments-sdk` 가 보인다. 2026-09-06 조사 시점의 최신은 **`2.8.1`** 이었다.

🔴 **여기서 나온 버전 문자열을 그대로 보고에 적는다.** `2.8.1` 이 아니면 그 사실도 적는다 — 아래 코드가 쓰는 것은 `loadTossPayments` · `.payment({customerKey})` · `.requestBillingAuth({method,successUrl,failUrl})` 셋뿐이고 이건 v2 내내 같은 모양이지만, **적어두지 않으면 나중에 무엇으로 검증했는지 알 수 없다.**

> ⚠️ 설치가 네트워크 문제로 실패하면 **여기서 멈추고 보고한다.** 이 화면은 SDK 없이는 아무 의미가 없으므로 우회하지 말 것.

**이게 `web/` 의 첫 런타임 의존성 추가다**(지금까지 `next`·`react`·`react-dom` 셋뿐이었다). 근거는 Step 10 의 커밋 메시지에 적는다.

- [ ] **Step 3: 클라이언트 키 환경변수를 넣는다**

`web/` 은 환경변수를 **`.env.local`(gitignore 됨) + `.env.local.example`(커밋됨)** 두 벌로 관리한다. `.gitignore` 가 `.env*` 를 막으면서 `!.env.local.example` 만 예외로 뚫어놨다. 기존 `NEXT_PUBLIC_API_BASE_URL` · `NEXT_PUBLIC_DEMO_PUBLIC_KEY` 와 **정확히 같은 방식**을 따른다.

먼저 `web/.env.local.example` **끝에** 붙인다.

```bash
# 토스페이먼츠 클라이언트 키. 결제 수단 등록 화면(/billing)이 결제창을 띄울 때 씁니다.
#
# ⚠️ 반드시 "API 개별 연동 키" 의 클라이언트 키(test_ck_...)여야 합니다.
#    결제위젯 키(test_gck_...)를 넣으면 SDK 가 NotSupportedWidgetKeyError 로 거부합니다.
#    토스는 서비스마다 다른 MID 에 각각 키를 발급하고, 세트가 아닌 키를 섞으면 안 받습니다.
#    개발자센터 > API 키 메뉴에서 확인합니다.
#
# 클라이언트 키는 브라우저에 노출되는 것이 정상입니다(비밀값이 아닙니다).
# 🔴 시크릿 키(test_sk_...)는 여기에 절대 넣지 마세요. 그건 Spring 쪽 환경변수(TOSS_SECRET_KEY)이며,
#    NEXT_PUBLIC_ 접두사가 붙은 값은 브라우저 번들에 그대로 들어갑니다.
NEXT_PUBLIC_TOSS_CLIENT_KEY=
```

그다음 **자기 `web/.env.local` 에도 같은 줄을 넣되 실제 테스트 키 값을 채운다.** `.env.local` 은 커밋되지 않는다.

> ⚠️ **테스트 키를 갖고 있지 않다면 여기서 값을 지어내지 말 것.** `.env.local.example` 만 고치고 `.env.local` 은 빈 값으로 두고 진행한다. 화면이 그 상태를 직접 안내하도록 Step 6 에 가드를 넣어둔다. 키는 Step 9 에서 사람에게 요청한다.

- [ ] **Step 4: 타입을 더한다**

`web/lib/types.ts` **맨 끝**(`Usage` 인터페이스 뒤)에 붙인다. 이 파일은 응답 타입마다 "백엔드 DTO 와 어떻게 맞췄는지"를 주석으로 적어두는 관례가 있다 — `Usage` 를 보고 그 밀도를 따른다.

```ts
/* ───────────────────────── 결제 수단 (요금제 연동 3조각) ───────────────────────── */

/**
 * 등록된 카드 한 장. Spring 의 `BillingMethodResponse.Card` 와 1:1 로 맞춘 모양이다.
 *
 * 🔴 `billingKey` 필드가 <없다>. 백엔드 DTO 에도 없다.
 *    타입에 자리를 만들어두면 언젠가 그 자리에 값이 실린다. 결제 열쇠는
 *    우리 DB 밖으로 한 번도 나가지 않는 것이 이 조각의 핵심 주장이다.
 *
 * 왜 `issuerCode`("61" 같은 두 자리 코드)가 아니라 `issuerName`("현대") 인가:
 * 토스는 2024-06-01 버전부터 카드사 <이름>을 안 주고 코드만 준다. 코드→이름 매핑을
 * 프론트에 두면 백엔드가 아는 것과 프론트가 아는 것이 갈라진다.
 * 표기 변환은 Spring 책임이라는 이 저장소의 규칙(snake_case → camelCase)과 같은 이유다.
 */
export interface BillingCard {
  /** "현대" · "신한" 등. 모르는 코드는 서버가 "카드" 로 내려준다 */
  issuerName: string;
  /** "43301234****123*" — 토스가 마스킹해서 준다. 우리가 자르는 게 아니다 */
  cardNumberMasked: string;
  /** 우리 DB 의 created_at. ISO-8601 문자열 */
  registeredAt: string;
}

/**
 * `GET`/`POST /api/billing/method` 의 응답.
 *
 * `interface` 로 둔 이유: 백엔드 응답 <객체의 모양>을 그리는 타입이고,
 * 이 파일의 다른 응답 타입(Bot·Usage·EvalRun)이 전부 interface 라 맞췄다.
 *
 * 🔴 `method` 가 `BillingCard | null` 인 것이 핵심이다. `customerKey` 는 카드가 없어도
 *    <항상> 있다 — 카드보다 오래 사는 값이라 users 테이블에 있기 때문이다.
 *    이 화면이 결제창을 띄우려면 카드가 없는 상태에서도 customerKey 가 필요하다.
 *    두 값을 한 덩어리로 묶어 `null` 로 뭉갰다면 "카드 없음" 상태에서 등록을 시작할 수 없다.
 */
export interface BillingMethodResponse {
  /** "bcus_…" — 토스에 넘기는 우리 쪽 고객 이름표. 카드를 빼도 남는다 */
  customerKey: string;
  /** 등록된 카드가 없으면 null */
  method: BillingCard | null;
}
```

- [ ] **Step 5: API 클라이언트를 더한다**

먼저 **`request()` 가 이미 할 수 있는 일을 눈으로 확인한다.** 없다고 가정하고 코드를 고치면 안 된다.

```bash
cd /Users/cheonjamin/projects/AllDap/web && grep -n 'method?: "GET"' -A 1 lib/api.ts && grep -n "status === 204" -B 1 -A 2 lib/api.ts
```

Expected: 두 가지가 **이미 있다**.
- `method?: "GET" | "POST" | "PATCH" | "DELETE";` ← `DELETE` 가 유니온에 있다. **넓힐 필요 없다.**
- `if (response.status === 204) { return undefined as T; }` ← 204 를 이미 다룬다. `response.json()` 을 부르지 않으므로 빈 본문에 터지지 않는다. (문서 삭제 `api.documents.remove` 가 이미 `request<void>` 로 같은 길을 쓴다.)

> ⚠️ 둘 중 하나라도 없으면 **그때만** 고친다: 유니온에 `| "DELETE"` 를 더하거나, 204 분기를 `if (response.status === 204) return undefined as T;` 로 추가한다. **그렇게 고쳤다면 그 사실을 보고에 적는다.**

`web/lib/api.ts` 의 `import type { ... }` 목록에 **알파벳 순서를 지켜** `BillingMethodResponse` 를 넣는다(`AuthResponse` 와 `Bot` 사이).

그다음 `api` 객체의 **`usage` 블록 뒤, `conflicts` 블록 앞**에 같은 들여쓰기로 추가한다.

```ts
  /**
   * 결제 수단 (요금제 연동 3조각)
   *
   * botId 를 받지 않는 이유: 청구 대상이 <계정>이라 서버가 토큰의 주인으로 조회한다.
   * 위 usage 와 같다.
   *
   * 함수 이름이 `get`·`register`·`remove` 가 아니라 `getBillingMethod` 처럼 긴 것은
   * 설계 문서가 고정한 이름이기 때문이다. 짧게 줄이지 말 것.
   */
  billing: {
    /** 카드가 없어도 customerKey 는 항상 온다 (결제창을 띄우려면 그게 필요하다) */
    getBillingMethod: () => request<BillingMethodResponse>("/api/billing/method"),
    /**
     * 토스 결제창에서 돌아온 authKey 로 빌링키를 발급받아 저장한다.
     *
     * 🔴 customerKey 를 같이 보내지만 서버는 그 값을 <신뢰하지 않는다> — 토큰의 주인 것을
     *    DB 에서 읽어 쓰고, 여기 실린 값은 <대조만> 하고 다르면 400 이다.
     *    신뢰했다면 남의 customerKey 를 적어 보내는 것만으로 카드가 남에게 붙는다.
     *    userId 를 @AuthenticationPrincipal 로만 받는 이 저장소의 규칙과 같은 이유다.
     *
     * 실패 코드가 셋으로 갈린다 — 프론트가 "카드를 바꿔 다시" 와 "우리 버그" 를 구분해
     * 안내해야 해서다: BILLING_AUTH_FAILED(400) · BILLING_PROVIDER_UNAVAILABLE(503) ·
     * BILLING_METHOD_ALREADY_EXISTS(409). 셋 다 ApiError.message 에 한국어 안내가 들어 있다.
     */
    registerBillingMethod: (authKey: string, customerKey: string) =>
      request<BillingMethodResponse>("/api/billing/method", {
        method: "POST",
        body: { authKey, customerKey },
      }),
    /**
     * 204 를 돌려주므로 반환값이 없다. request() 가 204 를 이미 다룬다(본문을 파싱하지 않는다).
     *
     * ⚠️ 서버는 <토스를 먼저> 부르고 우리 행을 나중에 지운다. 그래서 503 이 오면
     *    카드가 <그대로 남아 있다> — 화면은 그 경우 목록을 다시 부르지 말고
     *    오류만 띄워야 한다(page.tsx 의 handleDelete 참고).
     */
    deleteBillingMethod: () =>
      request<void>("/api/billing/method", { method: "DELETE" }),
  },
```

- [ ] **Step 6: `/billing` 화면을 만든다**

`web/app/(dashboard)/billing/page.tsx` 를 새로 만든다. `(dashboard)` 그룹 아래 두면 괄호 그룹은 URL 에 안 들어가므로 경로는 **`/billing`** 이 되고, 상위 `layout.tsx` 의 토큰 가드·헤더를 그대로 물려받는다.

```tsx
"use client";

/*
 * `/billing` — 결제 수단(카드) 등록 · 조회 · 삭제.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * 왜 이 파일에 "use client" 가 붙는가 (서버 컴포넌트와의 경계)
 * ─────────────────────────────────────────────────────────────────────────────
 * 이유가 둘 겹친다. 하나만으로도 클라이언트 컴포넌트여야 한다.
 *
 * ① 토스 SDK 가 <브라우저 전용>이다. loadTossPayments 는 문서에
 *    <script src="https://js.tosspayments.com/v2/standard"> 를 꽂고 결제창을 iframe 으로 띄운다.
 *    document 도 window 도 없는 서버에서는 실행 자체가 불가능하다.
 *    ⚠️ npm 패키지는 <로더>일 뿐이고 실제 SDK 는 매번 토스 CDN 에서 내려온다.
 *       인터넷이 막힌 환경에서는 등록 버튼이 동작하지 않는다 — 알고 남기는 제약이다.
 *
 * ② JWT 가 localStorage 에 있다. 서버 컴포넌트는 그걸 읽을 수 없어 사용자를 대신해
 *    Spring 을 부를 수 없다. 상위 (dashboard)/layout.tsx 주석과 같은 이유이고,
 *    그래서 이 화면의 데이터도 <브라우저에서> 가져온다.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * 호출하는 Spring API
 *   GET    /api/billing/method  → BillingMethodResponse
 *   POST   /api/billing/method  → BillingMethodResponse  (authKey 로 빌링키 발급)
 *   DELETE /api/billing/method  → 204
 * ─────────────────────────────────────────────────────────────────────────────
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { loadTossPayments } from "@tosspayments/tosspayments-sdk";
import { ApiError, api } from "@/lib/api";
import type { BillingMethodResponse } from "@/lib/types";
import { PageHeader } from "@/components/PageHeader";
import { Section } from "@/components/Form";

/*
 * 빌드 시점에 값이 그대로 박힌다(NEXT_PUBLIC_ 접두사의 뜻). lib/api.ts 의 API_BASE_URL 과 같은 방식.
 *
 * ⚠️ process.env.NEXT_PUBLIC_* 는 <통짜 표현식>으로 써야 치환된다.
 *    구조분해하거나 변수로 키를 만들면 undefined 가 된다.
 * ⚠️ 값을 바꾸면 dev 서버를 다시 띄워야 반영된다.
 */
const TOSS_CLIENT_KEY = process.env.NEXT_PUBLIC_TOSS_CLIENT_KEY ?? "";

export default function BillingPage() {
  const router = useRouter();

  /*
   * 상태를 뭉치지 않고 나눈 이유는 대시보드 화면과 같다 —
   * "아직 안 불러옴" 과 "불러왔는데 카드가 없음" 은 화면에 다르게 보여야 한다.
   * 전자는 "불러오는 중…", 후자는 "아직 등록된 카드가 없습니다" + 등록 버튼이다.
   */
  const [data, setData] = useState<BillingMethodResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  /* 결제창을 여는 중. 연타로 창이 두 번 뜨는 것을 막는다. */
  const [opening, setOpening] = useState(false);
  /* 삭제 확인 패널이 열렸는가. window.confirm 을 대신한다(handleDelete 주석 참고). */
  const [armed, setArmed] = useState(false);
  const [deleting, setDeleting] = useState(false);

  /*
   * 착지 처리를 이미 했는가. <상태가 아니라 ref 다> — 이 값이 바뀐다고 화면을 다시 그릴
   * 필요가 없고, 오히려 다시 그리면 안 된다.
   *
   * 왜 필요한가: 개발 모드의 React StrictMode 는 effect 를 일부러 두 번 실행한다
   * (setup → cleanup → setup). 가드가 없으면 <일회용인 authKey 가 두 번 POST 된다.>
   * 두 번째는 토스가 거절하므로, 방금 카드를 성공적으로 등록한 화면에 빨간 오류가 뜬다.
   * ref 는 같은 컴포넌트 인스턴스에서 그대로 살아남아 두 번째 실행을 막아준다.
   */
  const landedRef = useRef(false);

  /**
   * 서버가 아는 현재 상태를 가져온다.
   *
   * useCallback 으로 감싸는 이유: 아래 useEffect 의 의존성 배열에 이 함수가 들어가는데,
   * 매 렌더마다 새 함수가 만들어지면 의존성이 매번 바뀐 것으로 보여 effect 가 무한히 돈다.
   * 바깥 값을 쓰지 않으므로 의존성은 빈 배열이고, 따라서 이 함수는 <항상 같은 함수>다.
   */
  const load = useCallback(async () => {
    try {
      setData(await api.billing.getBillingMethod());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "결제 수단을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // StrictMode 의 두 번째 실행을 여기서 끊는다 (landedRef 주석 참고).
    if (landedRef.current) return;
    landedRef.current = true;

    void (async () => {
      /*
       * 🔴 useSearchParams() 를 <일부러 안 쓴다.>
       *
       * Next 문서(01-app/.../use-search-params.md)가 명시한다 — 정적으로 프리렌더되는
       * 페이지에서 Suspense 경계 없이 쓰면 production 빌드가
       * "Missing Suspense boundary with useSearchParams" 로 <실패>한다.
       * 경계를 두려면 이 페이지를 컴포넌트 둘로 쪼개야 한다.
       *
       * 우리가 필요한 건 "돌아온 직후 딱 한 번 읽고 즉시 지우는" 것뿐이라 구독이 필요 없다.
       * effect 안이므로 여기는 반드시 브라우저다 — window 가 없을 걱정이 없다.
       */
      const params = new URLSearchParams(window.location.search);
      const authKey = params.get("authKey");
      const failCode = params.get("code");

      /*
       * 착지 결과를 <먼저 계산>하고 setState 는 아래 await 뒤에 몰아서 한다.
       * 이렇게 두면 eslint 의 react-hooks/set-state-in-effect 규칙과도 맞고
       * ("effect 에서 곧바로 setState 하는" 모양을 만들지 않는다),
       * 분기마다 "여기서 로딩을 언제 끄더라" 를 따로 챙길 필요도 없어진다.
       */
      let landedError: string | null = null;
      let landedNotice: string | null = null;

      if (failCode) {
        // 토스가 실패 사유를 한국어 message 로 실어 보낸다. 우리가 다시 쓰지 않고 그대로 보여준다.
        landedError =
          params.get("message") ??
          "카드 등록에 실패했습니다. 카드를 확인한 뒤 다시 시도해주세요.";
      } else if (authKey) {
        try {
          /*
           * customerKey 가 비어 오면 서버가 @NotBlank 로 400 을 준다 — 조용히 넘어가지 않는다.
           * 어차피 서버는 이 값을 신뢰하지 않고 <대조만> 하므로, 여기서 미리 판단할 것이 없다.
           */
          await api.billing.registerBillingMethod(authKey, params.get("customerKey") ?? "");
          landedNotice = "카드를 등록했습니다.";
        } catch (e) {
          landedError = e instanceof ApiError ? e.message : "카드를 등록하지 못했습니다.";
        }
      }

      /*
       * 🔴 URL 을 비운다. 안 비우면 새로고침 한 번에 <이미 소모된 authKey> 가 다시 POST 되고,
       *    토스가 그걸 거절해서 방금 성공한 화면에 빨간 오류가 뜬다.
       *    authKey 는 한 번만 쓸 수 있는 값이다 — 브라우저 주소창에 남겨둘 이유가 없다.
       *    같은 라우트로의 replace 라 컴포넌트는 다시 마운트되지 않는다.
       */
      if (failCode || authKey) router.replace("/billing");

      /*
       * 등록 응답에도 카드 정보가 들어 있지만 <쓰지 않고> 다시 조회한다.
       * 화면에 보이는 카드의 출처를 GET 한 곳으로 묶어두면 "등록 직후만 다르게 보이는" 버그가
       * 생길 자리가 없어진다. 왕복 한 번은 등록 직후에만 일어나므로 값싸다.
       */
      await load();
      if (landedError) setError(landedError);
      if (landedNotice) setNotice(landedNotice);
    })();
  }, [load, router]);
  /*
   * 의존성에 load 와 router 를 적는 이유: 이 안에서 쓰는 <바깥 값>이 정확히 그 둘이다.
   * 둘 다 사실상 고정이라(load 는 useCallback [], router 는 Next 가 안정적으로 준다)
   * 이 effect 는 마운트 때 한 번만 돈다. 그럼에도 배열을 []로 비우지 않는 이유는,
   * 비우면 lint 가 "빠진 의존성" 을 경고하고 <나중에 load 가 인자를 받게 바뀌었을 때>
   * 조용히 옛 함수를 계속 쓰는 버그가 나기 때문이다.
   *
   * landedRef 는 의존성에 넣지 않는다 — ref 는 값이 바뀌어도 렌더를 유발하지 않는
   * "상자" 라서 React 가 의존성으로 추적하지 않는다(lint 도 요구하지 않는다).
   *
   * ⚠️ 이 파일은 이 저장소의 다른 화면과 달리 cancelled 플래그를 쓰지 않는다.
   *    landedRef 가드와 함께 쓰면 StrictMode 에서 <첫 실행의 cleanup 이 cancelled 를 켜고
   *    두 번째 실행은 가드에 막혀> 아무것도 그려지지 않기 때문이다.
   *    화면을 떠난 뒤 응답이 와서 setState 가 불리는 것은 React 18+ 에서 무시된다(경고도 없다).
   */

  /**
   * 토스 결제창을 띄워 카드 등록을 요청한다.
   *
   * 🔴 카드번호는 <토스 창 안에서만> 존재한다. 우리 페이지도 우리 서버도 만지지 않는다.
   *    우리가 받는 건 authKey 하나뿐이다 — PCI-DSS 대상 데이터를 우리가 갖지 않는다는 뜻이다.
   */
  async function handleOpenBillingWindow() {
    if (!data) return;
    setError(null);
    setNotice(null);
    setOpening(true);
    try {
      const tossPayments = await loadTossPayments(TOSS_CLIENT_KEY);

      /*
       * ⚠️ `.widgets()` 가 아니라 `.payment()` 다. 가장 헷갈리기 쉬운 자리다.
       *    `.widgets()` 는 주문서형·결제창형(결제위젯) 쪽이고 <자동결제 등록 메서드가 아예 없다.>
       *    키 세트도 다르다 — 자동결제는 API 개별 연동 키(test_ck_)를 쓰고,
       *    결제위젯 키(test_gck_)를 넣으면 SDK 가 NotSupportedWidgetKeyError 를 던진다.
       */
      const payment = tossPayments.payment({ customerKey: data.customerKey });

      await payment.requestBillingAuth({
        method: "CARD",
        /*
         * 🔴 successUrl·failUrl 은 <오리진을 포함해야 한다>(토스 요구).
         *    경로만 주면 IncorrectSuccessUrlFormatError 가 난다.
         *    성공·실패 모두 이 화면으로 돌려보낸다 — 착지 처리 코드가 위 useEffect 한 곳뿐이라
         *    화면을 나누면 같은 로직을 두 벌 갖게 된다.
         *    성공이면 ?customerKey=..&authKey=.. , 실패면 ?code=..&message=.. 가 붙어 온다.
         */
        successUrl: `${window.location.origin}/billing`,
        failUrl: `${window.location.origin}/billing`,
      });
    } catch (e) {
      /*
       * 사용자가 창을 그냥 닫으면 SDK 가 USER_CANCEL 을 던진다. 이건 오류가 아니라 <취소>다.
       * 빨간 문구를 띄우면 "닫았을 뿐인데 뭐가 고장났나" 로 읽힌다.
       *
       * 에러 객체의 모양을 확신할 수 없어(실제 SDK 는 CDN 에서 오고 타입이 없다)
       * code 를 조심스럽게 꺼낸다.
       */
      const code =
        typeof e === "object" && e !== null && "code" in e
          ? String((e as { code: unknown }).code)
          : "";
      if (code !== "USER_CANCEL") {
        setError(
          e instanceof Error
            ? e.message
            : "카드 등록창을 열지 못했습니다. 잠시 후 다시 시도해주세요.",
        );
      }
      setOpening(false);
    }
    // 성공하면 브라우저가 토스로 이동하므로 이 아래에 도달하지 않는다. opening 을 끄지 않는 게 맞다.
  }

  /*
   * 🔴 window.confirm 을 쓰지 않는 이유 (2026-08-10, 문서 삭제에서 겪었다)
   * ─────────────────────────────────────────────────────────────────────
   * 크롬은 같은 페이지에서 대화상자가 반복되면 "추가 대화상자를 만들지 않도록 차단"
   * 체크박스를 띄운다. 켜지면 confirm() 은 <항상 false> 를 돌려주고, 요청조차 안 나가고,
   * 오류도 안 뜬다. 밖에서 보면 "버튼이 고장났다" 와 구별할 수 없다.
   * 그래서 봇 삭제(settings)와 같은 <인라인 패널>을 쓴다.
   *
   * ⚠️ 실패해도 load() 를 부르지 않는다. 서버는 <토스를 먼저> 부르고 우리 행을 나중에 지우므로,
   *    503(토스 5xx)이면 카드가 그대로 남아 있다. 다시 조회하면 같은 카드가 다시 그려질 뿐이고,
   *    "지워진 것 같은데 남아 있네" 라는 깜빡임만 만든다. 오류만 띄우고 화면은 그대로 둔다.
   */
  async function handleDelete() {
    setDeleting(true);
    setError(null);
    setNotice(null);
    try {
      await api.billing.deleteBillingMethod();
      setArmed(false);
      setNotice("카드를 삭제했습니다.");
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "카드를 삭제하지 못했습니다.");
      setArmed(false);
    } finally {
      setDeleting(false);
    }
  }

  if (loading) return <p className="text-sm text-muted">불러오는 중…</p>;
  if (!data) {
    return (
      <p role="alert" className="text-sm text-danger">
        {error ?? "결제 수단을 불러오지 못했습니다."}
      </p>
    );
  }

  return (
    <>
      <PageHeader
        title="결제 수단"
        description="자동결제에 쓸 카드를 한 장 등록합니다. 카드 번호는 토스페이먼츠 결제창에서만 입력되며 AllDap 서버에는 저장되지 않습니다."
      />

      {/*
        🔴 거짓 완성 금지. 지금은 토스 <테스트 키>로만 동작한다 — 라이브 전환에는
        전자결제 계약 + 자동결제 추가 계약이 필요하고 둘 다 사업자등록이 전제다.
        적어두지 않으면 사용자는 진짜 카드를 넣고 결제가 된다고 믿는다.
        같은 이유로 이 화면에는 <금액이 한 글자도 없다> — /pricing 이 "금액이 아직 없다" 고
        말하고 있어서, 여기서만 있는 척하면 화면끼리 거짓말을 하게 된다.
        선례: 봇 설정의 "저장만 되고 답변에는 반영되지 않습니다" 경고와 같은 자리다.
      */}
      <p className="mt-4 rounded-md border border-warning bg-warning-surface px-3 py-2 text-xs text-warning">
        ⚠️ 지금은 <b>테스트 환경</b>입니다. 카드를 등록해도 <b>실제로 결제되지 않습니다.</b>
      </p>

      {error && (
        <p
          role="alert"
          className="mt-4 rounded-md border border-danger bg-danger-surface px-3 py-2 text-sm text-danger"
        >
          {error}
        </p>
      )}
      {notice && <p className="mt-4 text-sm text-success">{notice}</p>}

      <Section title="등록된 카드">
        {data.method ? (
          <>
            <dl className="grid grid-cols-3 gap-3">
              <div>
                <dt className="text-xs text-muted">카드사</dt>
                <dd className="mt-1 text-sm font-medium">{data.method.issuerName}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted">카드 번호</dt>
                <dd className="mt-1 font-mono text-sm font-medium">
                  {data.method.cardNumberMasked}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted">등록일</dt>
                <dd className="mt-1 text-sm font-medium">
                  {new Date(data.method.registeredAt).toLocaleDateString("ko-KR")}
                </dd>
              </div>
            </dl>
            {/*
              카드 <교체>는 만들지 않았다. 삭제 후 재등록으로 같은 일이 되고,
              상태 전이가 하나 늘면 그만큼 틀릴 자리가 는다. 계정당 한 장은 DB 의
              UNIQUE(user_id) 가 보장하므로 등록 버튼을 여기서 숨긴다(눌러도 409 다).
            */}
            <p className="text-xs text-muted">
              카드를 바꾸려면 아래에서 지운 뒤 다시 등록해주세요. 계정당 한 장만 등록할 수 있습니다.
            </p>
          </>
        ) : (
          <>
            <p className="text-sm text-muted">아직 등록된 카드가 없습니다.</p>
            <button
              type="button"
              onClick={() => void handleOpenBillingWindow()}
              disabled={opening || !TOSS_CLIENT_KEY}
              className="rounded-md bg-foreground px-4 py-2 text-sm font-medium text-surface disabled:opacity-50"
            >
              {opening ? "결제창을 여는 중…" : "카드 등록"}
            </button>
            {/*
              키가 없으면 버튼이 조용히 실패하는 대신 <무엇을 어떻게 하면 되는지>를 말한다.
              이 저장소의 에러 규약(PRD §10.3)을 화면 안내에도 그대로 적용한 것이다.
            */}
            {!TOSS_CLIENT_KEY && (
              <p role="alert" className="text-xs text-danger">
                <code>NEXT_PUBLIC_TOSS_CLIENT_KEY</code> 가 설정되지 않았습니다.{" "}
                <code>web/.env.local</code> 에 토스 <b>API 개별 연동</b> 클라이언트 키(
                <code>test_ck_…</code>)를 넣고 개발 서버를 다시 띄워주세요.
              </p>
            )}
          </>
        )}
      </Section>

      {data.method && (
        <Section title="위험 구역">
          {/* 🔴 "토스페이먼츠에서도 함께 폐기됩니다" 는 사실이다 —
              토스에 DELETE /v1/billing/{billingKey} 가 있고 서버가 그걸 먼저 부른다.
              (설계 초안은 폐기 API 가 없다고 적었는데 문서를 직접 확인해 뒤집었다) */}
          <p className="text-xs text-muted">
            등록된 카드를 삭제합니다. <b>토스페이먼츠에서도 함께 폐기됩니다.</b>
          </p>

          {!armed ? (
            <button
              type="button"
              onClick={() => setArmed(true)}
              className="rounded-md border border-danger px-3 py-1.5 text-sm text-danger"
            >
              카드 삭제
            </button>
          ) : (
            /*
              confirm 이 보여주던 것을 그대로 화면에 옮겼다 — <어느 카드인지>와 <무엇이 사라지는지>.
              카드사와 마스킹 번호를 다시 적는 이유: 지우기 직전에 한 번 더 눈으로 확인시킨다.
            */
            <div className="rounded-md border border-danger bg-danger-surface p-3">
              <p className="text-sm">
                <b>
                  {data.method.issuerName} {data.method.cardNumberMasked}
                </b>{" "}
                카드를 정말 삭제할까요?
              </p>
              <p className="mt-1 text-xs">
                토스페이먼츠에서도 함께 폐기되어 <b>되돌릴 수 없습니다.</b> 다시 쓰려면 카드를
                새로 등록해야 합니다.
              </p>
              <div className="mt-3 flex gap-2">
                {/* 취소를 <먼저> 둔다. 습관적으로 왼쪽을 누르는 사람이 실수로 지우지 않도록
                    (봇 설정 화면과 같은 규칙이다). */}
                <button
                  type="button"
                  onClick={() => setArmed(false)}
                  disabled={deleting}
                  className="rounded-md border border-subtle bg-surface px-3 py-1.5 text-sm disabled:opacity-50"
                >
                  취소
                </button>
                <button
                  type="button"
                  onClick={() => void handleDelete()}
                  disabled={deleting}
                  className="rounded-md bg-danger px-3 py-1.5 text-sm font-medium text-surface disabled:opacity-50"
                >
                  {deleting ? "삭제 중…" : "삭제합니다"}
                </button>
              </div>
            </div>
          )}
        </Section>
      )}
    </>
  );
}
```

> ⚠️ `import { loadTossPayments } from "@tosspayments/tosspayments-sdk";` 에서 타입 오류가 나면 **Step 2 의 설치가 안 된 것이다.** 임의로 `any` 나 `// @ts-expect-error` 로 덮지 말고 설치를 다시 확인한다. **그래도 안 되면 그 오류 문구를 그대로 보고하고 멈춘다.**

> ⚠️ `Section` 이 `@/components/Form` 에 없으면(파일이 옮겨졌다면) 그 파일을 열어 실제 export 이름을 확인해 맞춘다. **바꿨다면 보고에 적는다.**

- [ ] **Step 7: 헤더에 진입점을 뚫는다**

이 저장소에는 **계정 수준 라우트가 하나도 없었다** — `settings` 는 `bot/[botId]/settings` 뿐이고 봇 단위다. 대시보드 헤더도 로고와 로그아웃 둘뿐이라, 새 화면으로 갈 길이 없으면 만들어도 아무도 못 간다.

`web/app/(dashboard)/layout.tsx` 를 연다. `Link` 는 이미 import 돼 있다. 로고와 로그아웃 버튼이 `justify-between` 으로 붙어 있는 부분에서, **로그아웃 버튼을 감싸는 묶음**을 만들어 그 왼쪽에 링크를 넣는다.

바꾸기 전 (현재 코드):

```tsx
          {/* 사용자 이름을 띄우려면 GET /api/auth/me 가 필요한데 아직 없다.
              지금은 로그아웃만 둔다 — 토큰을 지우고 /auth 로 보낸다. */}
          <button
            type="button"
            onClick={handleLogout}
            className="text-xs text-muted hover:text-foreground"
          >
            로그아웃
          </button>
```

바꾼 뒤:

```tsx
          {/* 사용자 이름을 띄우려면 GET /api/auth/me 가 필요한데 아직 없다.
              지금은 계정 메뉴 자리에 결제 수단과 로그아웃 둘만 둔다.

              결제 수단이 <봇 화면이 아니라 헤더>에 있는 이유: 청구 대상이 계정이라
              봇을 여러 개 만들어도 카드는 한 장이다. 봇 하위에 두면 "봇마다 카드가
              따로인가?" 라는 잘못된 인상을 준다. 사용량 카드가 /dashboard 에 있는 것과 같은 판단이다. */}
          <div className="flex items-center gap-4">
            <Link
              href="/billing"
              className="text-xs text-muted hover:text-foreground"
            >
              결제 수단
            </Link>
            <button
              type="button"
              onClick={handleLogout}
              className="text-xs text-muted hover:text-foreground"
            >
              로그아웃
            </button>
          </div>
```

- [ ] **Step 8: 타입 검사와 린트를 돌린다**

```bash
cd /Users/cheonjamin/projects/AllDap/web && npx tsc --noEmit && npm run lint
```

Expected: **둘 다 아무 출력 없이 종료(exit 0)**. 이 저장소는 지금 tsc·eslint 가 완전히 깨끗한 상태라, 한 줄이라도 나오면 **이번 변경이 만든 것이다.**

> ⚠️ `react-hooks/exhaustive-deps` 가 useEffect 의존성에 대해 경고하면 **배열에서 값을 빼는 방향으로 고치지 말 것.** lint 가 요구하는 값을 넣고, 왜 들어갔는지 주석을 갱신한다. 배열을 비워 경고를 지우는 것은 규칙을 이긴 게 아니라 버그를 숨긴 것이다.
>
> ⚠️ `react-hooks/set-state-in-effect` 가 걸리면 effect 안에서 `await` 보다 <앞에> 있는 setState 가 남아 있다는 뜻이다. Step 6 의 코드처럼 결과를 지역 변수(`landedError`/`landedNotice`)에 모았다가 `await load()` <뒤>에 한 번에 적용하는 모양으로 옮긴다. **그렇게 고쳤다면 어디를 옮겼는지 보고에 적는다.**

- [ ] **Step 9: 브라우저로 한 바퀴 돈다 — 등록 → 조회 → 삭제 → 재등록**

**"타입이 통과했다" 는 화면 확인이 아니다.** 이 저장소는 통합 테스트 71건이 전부 초록불인 상태에서 HTTP/2 업그레이드 버그와 iframe Origin 버그를 냈다. 진짜로 띄워보기 전까지 검증했다고 말하지 않는다.

**먼저 키가 있는지 확인한다.**

```bash
cd /Users/cheonjamin/projects/AllDap/web && grep -c "NEXT_PUBLIC_TOSS_CLIENT_KEY=test_ck_" .env.local
```

Expected: `1`

🔴 **`0` 이 나오면(= 테스트 키가 없다면) 여기서 멈추고 사람에게 요청한다.** 키를 지어내지 말고, "키가 없어서 못 돌렸다" 를 "돌렸다" 로 바꿔 적지도 말 것. 이렇게 물어본다:

> 토스페이먼츠 테스트 키가 필요합니다.
> https://developers.tosspayments.com/my/api-keys 에서 **API 개별 연동 키**의
> 클라이언트 키(`test_ck_…`)를 `web/.env.local` 의 `NEXT_PUBLIC_TOSS_CLIENT_KEY` 에,
> 시크릿 키(`test_sk_…`)를 Spring 쪽 `TOSS_SECRET_KEY` 에 넣어주세요.
> ⚠️ **결제위젯 키(`test_gck_`/`test_gsk_`)가 아닙니다** — 섞으면 `INVALID_API_KEY` 가 납니다.
> 사업자등록은 필요 없습니다(테스트 키까지가 이 조각의 범위입니다).

키를 받으면 이어서 진행한다. 끝내 못 받으면 **Step 10 의 커밋·PR 은 그대로 진행하되, 보고와 PR 체크리스트에 "브라우저 종단 미실행 — 테스트 키 미확보" 를 명시한다.**

**3-스택을 띄운다.**

```bash
cd /Users/cheonjamin/projects/AllDap && docker compose up -d
# 🔴 키를 셸에 직접 싣는다. bootRun 은 .env 를 읽지 않는다. 빠뜨리면 카드 등록이
#    전부 503(BILLING_PROVIDER_UNAVAILABLE) 인데, 화면만 보면 원인이 안 보인다 —
#    토스가 401 을 준 것을 우리가 503 으로 번역하기 때문이다.
cd /Users/cheonjamin/projects/AllDap/api && TOSS_SECRET_KEY=test_sk_... ./gradlew bootRun   # 별도 터미널
cd /Users/cheonjamin/projects/AllDap/web && npm run dev                  # 별도 터미널
```

(Python 서비스는 이 화면과 무관하므로 띄우지 않아도 된다.)

**한 바퀴 돈다.** 로그인 → 헤더의 "결제 수단" → `/billing`.

| # | 하는 일 | 봐야 하는 것 |
|---|---|---|
| 1 | 첫 진입 | "아직 등록된 카드가 없습니다" + 카드 등록 버튼. **테스트 환경 경고 문구가 보인다.** 금액은 어디에도 없다 |
| 2 | "카드 등록" 클릭 | 토스 결제창(iframe)이 뜬다 |
| 3 | 카드 정보 입력 → 완료 | `/billing` 로 돌아오고 **주소창에 `authKey` 가 남아 있지 않다**(router.replace 확인) · "카드를 등록했습니다" · 카드사·마스킹 번호·등록일 |
| 4 | **새로고침(F5)** | 🔴 **오류가 뜨지 않는다.** 카드가 그대로 보인다. 여기서 빨간 오류가 뜨면 URL 비우기가 안 된 것이다 |
| 5 | "카드 삭제" → 패널의 "삭제합니다" | "카드를 삭제했습니다" · 다시 "등록된 카드가 없습니다" |
| 6 | **다시 등록** | 1~3 이 그대로 된다. 🔴 **customerKey 가 같아야 한다** — DB 에서 확인한다 |
| 7 | 결제창에서 그냥 닫기(X) | **빨간 오류가 뜨지 않는다**(USER_CANCEL 은 취소지 오류가 아니다) |

6번의 customerKey 확인:

```bash
docker compose exec -T db psql -U alldap -d alldap -c \
  "SELECT email, billing_customer_key FROM users;"
```

> ⚠️ DB 접속 정보(사용자·DB 이름)가 다르면 `docker-compose.yml` 을 열어 실제 값으로 바꾼다.

**토스 테스트 환경의 특례 — 모르면 여기서 막힌다:**

- 🔴 **전용 테스트 카드번호 목록이 제공되지 않는다.** 자동결제 테스트는 **카드번호 앞 6자리(BIN)만 유효하면 등록된다.** 즉 실제로 존재하는 국내 카드의 BIN 6자리로 시작하고 나머지 자리를 아무 숫자로 채우면 통과한다.
- **휴대폰 인증번호는 `000000`.**
- 유효기간·생년월일·비밀번호 앞 2자리는 형식만 맞으면 아무 값이나 된다.
- **국내 발급 카드만 지원된다**(토스 제약).
- 실패 경로를 강제로 보고 싶으면 서버가 토스로 보내는 요청에 `TossPayments-Test-Code: INVALID_CARD_EXPIRATION` 헤더를 붙인다(라이브에서는 무시된다). **선택 사항이다 — Task 3 의 통합 테스트가 `TossStub` 으로 4xx·5xx 를 이미 덮는다.** 여기서 굳이 하지 않아도 된다.

**본 화면(카드 등록 후)과 삭제 확인 패널을 캡처해 둔다.** PR 본문에 붙일 것이다.

> ⚠️ 결제창이 안 뜨고 콘솔에 `NotSupportedWidgetKeyError` 가 보이면 **키 종류가 틀린 것이다**(결제위젯 키를 넣었다). `test_ck_` 로 시작하는 API 개별 연동 키로 바꾸고 dev 서버를 재시작한다. **그렇게 고쳤다면 보고에 적는다.**
>
> ⚠️ 서버가 `INVALID_API_KEY` 를 돌려주면 **Spring 쪽 시크릿 키가 클라이언트 키와 짝이 아니다.** 같은 MID 의 `test_ck_`/`test_sk_` 쌍을 쓰는지 확인한다.
>
> ⚠️ 등록은 됐는데 카드사가 "카드" 로만 뜨면 `CardIssuer.nameOf` 가 그 코드를 모르는 것이다. **버그가 아니다**(설계가 그렇게 정했다). 다만 **어떤 코드였는지 보고에 적어라** — 흔한 코드가 빠졌다면 Task 3 에 한 줄 더할 근거가 된다.

- [ ] **Step 10: 커밋하고 PR 을 연다**

🔴 **`git add -A` 를 쓰지 말 것.** 작업 트리에 이번 작업과 무관한 미커밋 파일이 있다(`widget/demo.html` 수정본, 미추적 `docs/이해노트-2026-09-01.md`). 경로를 하나씩 적는다. `.env.local` 은 `.gitignore` 가 막지만 **`-f` 로 억지로 넣지 말 것** — 키가 저장소에 박힌다.

```bash
cd /Users/cheonjamin/projects/AllDap
git add web/package.json web/package-lock.json web/.env.local.example \
        web/lib/types.ts web/lib/api.ts \
        "web/app/(dashboard)/billing/page.tsx" \
        "web/app/(dashboard)/layout.tsx"
git status --short
```

Expected: 위 7개만 스테이징돼 있다(`M`/`A`). `widget/demo.html` 과 `docs/이해노트-2026-09-01.md` 는 **스테이징되지 않은 채로** 남아 있어야 한다.

```bash
git commit -m "$(cat <<'EOF'
feat: 결제 수단 등록·조회·삭제 화면을 만들었다

/billing 을 새로 만들고 대시보드 헤더에 진입점을 뚫었다. 이 저장소의 첫
계정 수준 라우트다 — settings 는 봇 단위뿐이었다. 청구 대상이 계정이라
봇 하위에 두면 "봇마다 카드가 따로인가" 라는 잘못된 인상을 준다.

web/ 의 첫 런타임 의존성으로 @tosspayments/tosspayments-sdk 를 넣었다
(지금까지 next·react·react-dom 셋뿐이었다). next/script + 전역 객체 대신
npm 패키지를 고른 이유는 타입이 있고 토스가 문서화한 경로라서다.
결제창은 몇 줄로 대체할 수 있는 것이 아니다.

착지 처리 후 router.replace 로 URL 을 비운다. 안 비우면 새로고침 한 번에
이미 소모된 authKey 가 다시 POST 되어, 방금 성공한 화면에 오류가 뜬다.
개발 모드 StrictMode 의 effect 이중 실행도 ref 가드로 같이 막았다.

useSearchParams 는 일부러 안 썼다. Suspense 경계 없이 쓰면 production
빌드가 실패한다(Next 문서 명시). 한 번 읽고 즉시 지우는 값이라 구독이 필요 없다.

삭제 확인은 window.confirm 이 아니라 인라인 패널이다. 크롬이 반복
대화상자를 차단하면 confirm 이 항상 false 를 돌려줘 조용히 아무 일도
일어나지 않는다(2026-08-10 문서 삭제에서 겪었다).

화면에 금액을 한 글자도 쓰지 않았고, 테스트 환경이라 실제 결제가 되지
않는다는 안내를 남겼다. /pricing 이 "금액이 아직 없다" 고 말하는데
여기서만 있는 척하면 화면끼리 거짓말을 하게 된다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
git push -u origin feat/billing-method
```

그다음 PR 을 연다.

```bash
gh pr create --title "feat: 결제 수단 등록 — 토스 빌링키 발급·암호화 저장·폐기" \
  --body-file /tmp/billing-pr-body.md
```

🔴 **PR 본문은 여기서 새로 짓지 말 것.** 이 계획서 맨 뒤 **"PR 본문 — feat/billing-method"** 절을 그대로 `/tmp/billing-pr-body.md` 에 저장해 쓴다(`<!-- -->` 자리는 실제 실행 결과로 채운다). `.github/PULL_REQUEST_TEMPLATE.md` 가 체크리스트가 아니라 **설명**을 요구하는 템플릿이라, 즉석에서 지어낸 문장은 면접에서 그대로 말할 수 없는 글이 된다. Step 9 에서 찍은 캡처를 "어떻게 해결했나요" 칸에 붙인다.

> ⚠️ **CI 를 기다리지 말 것.** `gh pr create` 까지가 이 Task 의 끝이다. 폴링하지 않는다.

---

## Task 5: 문서와 결정 로그 (별도 `docs` 브랜치 · 별도 PR)

> 🔴 **이 Task 는 Task 1~4 가 전부 끝난 뒤에 한다.** 이유는 하나다 — 여기 적는 숫자와 상태가
> **실제 실행 결과**여야 하기 때문이다. 이 저장소의 PR 템플릿이 *"'돌려봤다'가 아니라 실제 실행 결과를
> 그대로"* 를 요구하고, `AGENTS.md` 가 **거짓 완성 금지**를 명시한다.
> Task 1~4 를 안 돌린 상태에서 이 Task 를 먼저 하면 **반드시 지어낸 숫자를 쓰게 된다.**
>
> 🔴 **브랜치도 이 Task 만 다르다.** Task 1~4 는 `feat/billing-method` 에서 했다.
> 이 Task 는 그 기점인 **`docs/billing-method-design`** 으로 돌아가 거기서 이어 작업하고 **별도 PR** 을 연다.
> 선례: 사용량 계량이 PR #52(feat) + PR #53(docs) 두 개였고, #53 은
> `decisions.md` + `plans/` + `specs/` 만 담은 순수 문서 PR이었다.

**Files:**
- Modify: `/Users/cheonjamin/projects/AllDap/docs/decisions.md`
- Modify: `/Users/cheonjamin/projects/AllDap/docs/DEPLOY.md`
- Modify: `/Users/cheonjamin/projects/AllDap/AGENTS.md`
- Modify (조건부 — Step 7): `/Users/cheonjamin/projects/AllDap/.env.prod.example`
- Modify (조건부 — Step 8): `/Users/cheonjamin/projects/AllDap/docs/superpowers/handoff-2026-09-06.md`
- Test: 없음 (문서 변경). 대신 **Step 1 이 Task 1~4 의 실제 출력을 수집하는 것**이 이 Task 의 검증이다

**Interfaces:**
- Consumes (앞 Task 들이 만들어 놓은 **사실**. 코드가 아니라 실측치를 소비한다):
  - `api/src/main/resources/db/migration/V6__billing_method.sql` (Task 1)
  - 환경변수 이름 3개: `BILLING_CRYPTO_KEY` · `TOSS_SECRET_KEY` · `NEXT_PUBLIC_TOSS_CLIENT_KEY`
  - `./gradlew test` 총 통과 건수 (Task 1·2·3)
  - `cd web && npx tsc --noEmit && npm run lint` 결과 (Task 4)
  - Task 4 의 브라우저 종단 1회(등록 → 조회 → 삭제 → 재등록) **실제 수행 여부**
  - `feat/billing-method` PR 번호와 머지 여부
- Produces: 없음. 이 Task 뒤에 오는 Task 가 없다. 산출물은 문서 PR 하나다.

---

- [ ] **Step 1: Task 1~4 의 실제 결과를 수집해 스크래치에 적어둔다**

문서에 박을 숫자를 여기서 **한 번만** 확정한다. 이 단계를 건너뛰면 뒤 Step 들에서 기억에 의존하게 되고,
그게 정확히 이 저장소가 금지한 "거짓 완성"이다.

```bash
cd /Users/cheonjamin/projects/AllDap
git switch feat/billing-method
git log --oneline docs/billing-method-design..feat/billing-method
```

테스트를 실제로 다시 돌려 총 건수를 뽑는다 (Docker 필요 — Testcontainers).

```bash
cd /Users/cheonjamin/projects/AllDap/api && ./gradlew test
```

```bash
cd /Users/cheonjamin/projects/AllDap/api && \
grep -o 'tests="[0-9]*"' build/test-results/test/TEST-*.xml | grep -o '[0-9]*' | paste -sd+ - | bc
```

프론트도 확인한다.

```bash
cd /Users/cheonjamin/projects/AllDap/web && npx tsc --noEmit && npm run lint
```

PR 상태를 확인한다.

```bash
cd /Users/cheonjamin/projects/AllDap && gh pr list --head feat/billing-method --state all --json number,state,title
```

수집한 것을 스크래치에 적는다. **여기 적히지 않은 숫자는 뒤 Step 에서 쓰지 않는다.**

```bash
cat > /private/tmp/claude-501/-Users-cheonjamin-projects-AllDap/4c5c3296-6a65-4049-807f-ebb92ea901fe/scratchpad/task5-facts.md <<'EOF'
# Task 5 가 문서에 박을 사실 (전부 실측)

- gradlew test 총 통과 건수:            (Step 1 의 bc 출력 그대로)
- 새 테스트 클래스:                      BillingCryptoTest / BillingIntegrationTest
- BillingIntegrationTest 건수:           (테스트 리포트에서 확인)
- web tsc --noEmit:                     (통과 / 실패)
- web npm run lint:                     (통과 / 실패)
- 브라우저 종단 1회(등록→조회→삭제→재등록): (했다 / 안 했다 — 안 했으면 "안 했다"라고 적는다)
- 실패 경로(TossPayments-Test-Code) 확인: (했다 / 안 했다)
- feat/billing-method PR 번호:           (#NN / 아직 없음)
- feat PR 머지 여부:                     (머지됨 / 오픈, 미머지)
- V6 마이그레이션 파일명:                 V6__billing_method.sql
EOF
```

> ⚠️ **`./gradlew test` 가 실패하면 여기서 멈춘다.** 실패한 상태로 문서에 "통과"라고 적는 것이
> 이 Task 가 막으려는 바로 그 사고다. 실패 원인이 Task 1~4 의 미완성이면 **그 Task 로 돌아가고,
> 그렇게 되돌아갔다는 사실을 보고에 적는다.**
>
> ⚠️ **Docker 가 안 떠서 테스트를 못 돌렸다면** 스크래치에 "돌리지 못함 — Docker 미기동"이라고
> 적고, 뒤 Step 들에서도 그대로 "통과"가 아니라 **"이번 세션에서는 재실행하지 못했다"** 로 쓴다.
> "안 나빠졌다"와 "재보지 않았다"는 다르다는 것이 이 저장소가 반복해 적어온 문장이다.

- [ ] **Step 2: docs 브랜치로 돌아간다**

```bash
cd /Users/cheonjamin/projects/AllDap && git switch docs/billing-method-design && git status --short
```

Expected: `docs/billing-method-design` 으로 전환되고, 작업 트리에 이 Task 와 무관한 변경만 남는다
(`widget/demo.html` 수정 · 미추적 `docs/이해노트-2026-09-01.md` 등).

> ⚠️ **`git switch` 가 "local changes would be overwritten" 로 실패하면** `feat/billing-method` 에
> 커밋 안 된 변경이 남은 것이다. Task 1~4 중 하나가 커밋을 빠뜨렸다는 뜻이므로,
> 그 변경을 확인해 해당 브랜치에 커밋한 뒤 다시 전환한다. **`git stash` 로 덮지 말 것** —
> 어느 브랜치의 것인지 잃는다. **그렇게 커밋했다면 무엇을 커밋했는지 보고에 적는다.**

- [ ] **Step 3: `docs/decisions.md` 에 결정 6줄을 추가한다**

먼저 형식을 눈으로 확인한다. 이 파일은 **한 줄 = 한 결정**(`날짜 | 무엇을 | 왜 그렇게 | 검토한 대안`)이고,
부연은 `  ↳` 로 들여쓴 줄에 단다.

```bash
cd /Users/cheonjamin/projects/AllDap && head -5 docs/decisions.md && echo "...(중략)..." && tail -3 docs/decisions.md
```

파일 끝에 그대로 덧붙인다.

```bash
cd /Users/cheonjamin/projects/AllDap && cat >> docs/decisions.md <<'EOF'

2026-09-06 | `customerKey` 를 `users.id` 가 아니라 `bcus_` + 32 hex 전용 랜덤 키로 두고 `users` 컬럼에 저장한다 | 두 가지가 겹친 결정이다. ① **내부 기본키를 외부 업체에 흘리지 않는다** — `users.id` 는 UUIDv4 라 토스의 형식 요구(추측 불가·개인정보 금지)를 그대로 만족하지만, 넘기는 순간 우리 DB 의 PK 가 토스 대시보드·로그·CS 이력에 영구히 찍힌다. 저장소에 같은 선례가 이미 있다 — `bots.public_key`(`pk_...`)가 봇 UUID 를 고객 사이트 HTML 에 노출하지 않으려고 만든 별도 공개키다. 그래서 "왜 UUID 를 안 썼나요?"에 일관된 답이 된다: 내부 식별자를 외부에 흘리지 않는 규칙을 봇에 이미 적용했고 결제도 같게 뒀다. ② **수명이 다른 둘을 한 곳에 두지 않는다** — `customerKey` 는 카드를 빼도 남아야 재등록 시 토스 쪽 고객 이력이 이어지고, `billingKey` 는 카드와 함께 죽는다. 그래서 `customerKey` 는 `users` 컬럼이고 카드는 `billing_methods` 행이다. 삭제가 "행 하나 지우기"가 되어 컬럼 네 개를 NULL 로 되돌리는 것보다 의도가 분명하다 | ① `users.id` 를 그대로 `customerKey` 로 쓰기: 컬럼도 생성 로직도 안 늘지만 내부 PK 가 외부에 나가고, 봇에는 별도 공개키를 만들어 놓고 결제에는 안 만든 이유를 설명할 수 없다 ② `customerKey` 를 `billing_methods` 에 함께 두기: 카드를 지우면 `customerKey` 도 함께 사라져 재등록 때 토스가 새 고객으로 잡는다 — 수명이 다른 둘을 한 행에 둔 대가가 정확히 여기서 나온다 ③ `customer_keys` 별도 테이블: 계정당 1행이라 `users` 와 1:1 인데 조인만 하나 는다
  ↳ **생성 위치는 `User.create()` 안이다.** `Bot.create()` 가 `publicKey` 를 만드는 것과 같은 이유다 — 생성이 밖에 있으면 키를 안 넣고 만든 행이 생길 여지가 남는다. 기존 계정은 `V6__billing_method.sql` 의 `UPDATE` 로 메꾸고 나서 `NOT NULL` 을 건다. 메꾸지 않으면 NOT NULL 을 걸 수 없고, NOT NULL 이 아니면 "customerKey 없는 사용자"라는 다룰 필요 없는 상태가 영구히 남는다.

2026-09-06 | 빌링키를 앱 레벨 **AES-256-GCM** 으로 암호화해 저장한다(`spring-security-crypto` 의 `AesBytesEncryptor` 원시 키 생성자, 새 의존성 0개) — **이 저장소의 첫 암호화 결정이다** | `billingKey` 는 카드번호가 아니지만 "이 카드에 청구해도 된다"는 열쇠다. DB 덤프·RDS 스냅샷·백업 파일이 한 번 새면 전 고객의 청구 열쇠가 그대로 나간다. GCM(인증 암호)을 고른 것이 핵심인데, 이유는 기밀성보다 **무결성**이다 — 토스에 빌링키 조회 API 가 없어 우리 DB 가 유일한 사본이고, 그래서 값이 바뀌었는지 대조할 상대가 세상에 없다. 대조할 수 없다면 암호문 자체가 자기 무결성을 증명해야 한다 | ① 평문 저장: 덤프 한 번이면 전부 나간다 ② `Encryptors.text()`: 7.0.6 바이트코드로 확인한 결과 GCM 이 아니라 `AES/CBC/PKCS5Padding` 이다. CBC 는 인증이 없어 암호문을 한 바이트 뒤집어도 복호화가 그냥 성공한다 — DB 를 만질 수 있는 공격자가 남의 빌링키로 바꿔치기해도 우리가 눈치채지 못한다 ③ `Encryptors.delux()`: GCM 은 맞지만 키를 PBKDF2WithHmacSHA1 **1024회**로 유도한다. 우리는 이미 32바이트 난수를 환경변수로 갖고 있어 유도할 이유가 없고, 1024회는 2026년 기준으로 낮다 ④ KMS·Secrets Manager: 1인 운영에서 운영할 것의 개수가 늘고 AWS 프리티어 밖이다. PRD §11.2 원칙과 충돌한다 ⑤ Bouncy Castle: 클래스패스에 없다 — 새 의존성 0개로 되는 일에 하나를 더한다
  ↳ 🔴 **키 <길이> 검사가 이 결정의 핵심이다.** JCE 는 16바이트 키를 주면 **말없이 AES-128 로 돈다.** 확인하지 않으면 "AES-256 으로 저장합니다"라고 말할 근거가 없다. 생성자에서 네 가지(미주입·공백 / `${` 로 시작 / 저장소에 공개된 로컬 기본값 / 32바이트 아님)를 확인하고, 개발 프로파일이 아니면 기동을 중단한다 — `JwtService` 와 `application-prod.yaml` 의 fail-closed 를 그대로 복제했다.
  ↳ **`${` 검사가 왜 따로 필요한가**: `@ConfigurationProperties` 는 해석하지 못한 플레이스홀더를 예외 없이 **리터럴 문자열로 바인딩**한다. 즉 환경변수를 안 넣어도 "값이 있다"로 보이고, 그 리터럴이 Base64 로 디코딩되면 조용히 엉뚱한 키로 돌 수 있다.
  ↳ **이 저장소에 fail-closed 가드는 이미 둘 있었지만(`JwtService`·`application-prod.yaml`) 테스트로 고정된 것은 하나도 없었다.** `BillingCryptoTest` 의 5·6번이 그 부류의 첫 회귀 테스트다.
  ↳ **대가를 그대로 적는다: 키를 잃으면 전 고객이 카드를 다시 등록해야 한다.** 조회 API 가 없어 다른 길이 없다. **키 회전은 만들지 않는다** — 막다른 길은 아니다. 나중에 새 키를 도입할 때 `v2:` 접두사를 붙여 저장하면 접두사 없는 행 = 옛 키로 소급 판별된다. 지금 미리 문법을 만들 이유가 없다.

2026-09-06 | 결제 수단 삭제를 **토스 먼저·우리 나중** 순서로 하고, 토스의 4xx 와 5xx 를 다르게 다룬다(4xx → 우리 행도 지우고 204, 5xx·타임아웃 → 우리 행을 남기고 503) | 순서를 뒤집으면 토스 호출이 실패했을 때 우리는 그 키를 이미 지운 뒤라 **영영 폐기할 수 없는 고아**가 된다 — 조회 API 가 없어 다시 알아낼 방법이 없기 때문이다. 4xx 와 5xx 를 가르는 기준은 `AiServiceClient` 의 원칙 그대로 **"누구 잘못인가"** 다: 4xx 는 토스 쪽에 이미 없다는 뜻이라 치울 게 없고, 5xx·타임아웃은 다시 시도하면 치울 수 있으므로 지금 지우면 그 기회를 버린다. 삭제 응답 body 는 파싱하지 않고 **HTTP 상태로만** 판정하는데, 토스 문서가 자기모순이기 때문이다 — API 레퍼런스는 "비어있는 body 에 200 응답만 내려갑니다", 연동 가이드 FAQ 는 `{"billingKey": "..."}` 를 보여준다 | ① 우리 먼저 지우고 토스는 best-effort: 화면은 즉시 반응하지만 실패 시 회수 불가능한 고아가 남는다. "우리 화면의 반응성"과 "되돌릴 수 없는 상태"를 맞바꾸는 거래라 성립하지 않는다 ② 4xx·5xx 를 같이 취급(둘 다 삭제): 5xx 에서 재시도 기회를 버린다 ③ 4xx·5xx 를 같이 취급(둘 다 유지): 이미 토스에 없는 카드를 사용자가 영원히 못 지운다 — 넣을 수만 있고 뺄 수 없으면 기능이 아니라 함정이다 ④ 삭제 body 를 파싱해 판정: 문서 두 곳이 서로 다른 형태를 말하므로 어느 쪽에 맞춰도 절반은 틀린다
  ↳ **화면 문구가 이 결정에 딸려 있다.** 폐기 API 가 실제로 있으므로 "등록된 카드를 삭제합니다. 토스페이먼츠에서도 함께 폐기됩니다."라고 사실대로 쓸 수 있다. 핸드오프 서술이 맞았다면 "우리가 잊을 뿐 폐기되지는 않습니다"라고 적어야 했다.
  ↳ **알고 남긴 한계**: 삭제 API 의 에러 코드표가 토스 문서에 없다. 없는 빌링키를 지울 때 어떤 코드가 오는지 모른 채 4xx 를 전부 "토스 쪽엔 이미 없다"로 해석한다. **이 해석이 틀리면 고아가 남는다.**

2026-09-06 | 빌링키 **발급** 호출에만 `Idempotency-Key` 헤더와 I/O 실패 1회 재시도를 둔다 — `AiServiceClient` 의 "연결 실패에만 재시도" 논리를 여기에는 쓸 수 없다 | `AiServiceClient` 의 재시도 전제는 *"직전 시도가 아무 일도 하지 않았다"* 이고, 그게 보장되는 것은 연결이 안 된 경우뿐이라 5xx·읽기 타임아웃은 재시도하지 않는다(재시도하면 문서 행이 중복되거나 LLM 이 두 번 과금된다). 결제는 그 전제가 서지 않는다 — **읽기 타임아웃이어도 토스는 이미 발급했을 수 있고, 조회 API 가 없어 그 빌링키를 영원히 회수할 수 없다.** 즉 여기서는 "재시도 안 함"이 안전한 기본값이 아니다. 그대로 두면 고아가 남는다. `Idempotency-Key` 가 그 전제를 대신 세워준다 — 같은 (멱등키·API 키·주소·메서드) 조합이면 토스가 같은 응답을 돌려주므로 재시도가 새 빌링키를 만들지 않는다(처음 쓴 날부터 15일 유효). 삭제에는 붙이지 않는다: 실패해도 우리 행이 남아 다시 시도할 수 있고, 같은 키를 두 번 지우는 것은 4xx 로 끝난다 | ① 재시도 없음: 타임아웃 한 번에 회수 불가능한 고아가 하나 남는다 ② 멱등키 없이 재시도: 재시도할 때마다 고아가 하나씩 는다 — 안 하느니 못하다 ③ 발급 전에 우리 행을 먼저 만들어 두고 사후 대조: 대조할 상대가 없다(조회 API 부재) ④ 재시도 대신 사용자에게 "다시 시도" 안내: 사용자가 누르는 재시도는 새 `authKey` 발급부터 다시 가므로 앞의 고아는 그대로 남는다
  ↳ 🔴 **`AiServiceClient` 와 `RestClient` 빈도 서킷브레이커도 공유하지 않는다.** 공유하면 토스 장애가 채팅을 끊고, 그 반대도 된다. 같은 이유로 실패 변환은 `TossClient` 안에서 끝낸다 — 호출 지점마다 try-catch 를 적으면 한 곳이 빠지고, 거기서 예외가 그대로 올라가 500 이 나가 "토스가 거절했다"가 "우리 서버가 고장났다"로 둔갑한다.

2026-09-06 | 요금제 연동 4조각 중 **2번(플랜·포함량)보다 3번(결제 수단 등록)을 먼저** 한다 | 2번은 숫자를 요구한다 — 월 정액·포함 답변 수·초과 단가. 그런데 PRD 부록 A-1 #10 이 금액 결정을 **"파일럿 4주 후"** 로 미뤄뒀고 그 근거가 *"실사용 데이터 없이 정하면 근거 없는 숫자가 된다"* 이다. 지금 2번을 만들면 `/pricing` 화면은 "금액이 아직 없다"고 말하는데 DB 에는 금액이 있게 되어 제품과 데이터가 어긋나고, 이 저장소가 여러 번 지켜온 원칙(근거 없는 숫자를 쓰지 않는다)을 정면으로 어긴다. **3번에는 숫자가 하나도 나오지 않는다** — "이 고객의 카드를 저장한다"까지가 전부라 파일럿 데이터를 기다릴 이유가 없다 | ① 번호 순서대로 2번 먼저: 지금 정할 수 없는 금액을 지어내야 하고, 그 숫자가 화면·DB·문서에 동시에 박힌 뒤 파일럿 결과로 전부 갈아엎게 된다 ② 2·3번을 한 PR 로 함께: 마찬가지로 금액이 필요하고, PR 이 리뷰 가능한 크기를 넘는다 ③ 4번(청구)으로 건너뛰기: 청구할 금액도 청구할 열쇠도 없다 — 3번이 그 열쇠를 만드는 조각이다

2026-09-06 | ~~토스에는 빌링키를 폐기하는 API 가 없다~~ → **틀린 것으로 드러났다. 있다**(`DELETE /v1/billing/{billingKey}`) | 2026-09-06 핸드오프 문서 §③ 에 "만료도 없고 취소 엔드포인트도 없다"고 적혀 있었고, 설계 전에 토스 문서를 직접 확인해 뒤집었다. 이 서술 위에 **화면 문구와 삭제 순서 설계가 통째로 얹혀 있었다** — 틀린 채로 갔다면 사용자에게 "우리가 잊을 뿐 폐기되지는 않습니다"라는 사실과 다른 안내가 나갔을 것이다. 🔴 **그리고 진짜 제약은 반대쪽에 있었다 — 빌링키를 <조회>하는 API 가 없다.** 토스 문서 원문: *"발급된 빌링키를 조회하는 API는 제공되지 않습니다 … 빌링키 중복 발급을 방지하는 방법은 없습니다."* 이쪽이 훨씬 무겁다. 이 사실 하나가 세 곳을 바꿨다: ① 암호화 키를 잃으면 전 고객이 카드를 재등록해야 한다(우리 DB 가 유일한 사본이다) ② 발급 타임아웃이 회수 불가능한 고아를 남긴다(그래서 멱등키를 붙였다) ③ 같은 카드로 빌링키가 몇 개든 생기므로 `UNIQUE(user_id)` 가 유일한 방어다. **없는 줄 알았던 것은 있었고, 있는 줄 알았던 것이 없었다** | 이 줄을 지우고 맞는 사실만 새로 쓰기: 이 저장소는 반증된 판단을 지우지 않고 "틀린 것으로 드러났다" 형태로 남긴다(2026-09-04 의 `X-Forwarded-For` 항목이 그 예다 — 리뷰의 전제가 실측으로 반증됐지만 그 과정을 그대로 남겼다). 무엇을 어떻게 잘못 알았는지가 면접 재료이고, 지우면 같은 실수를 다시 한다
  ↳ **일반화**: 외부 API 는 "무엇이 있는가"보다 **"무엇이 없는가"** 가 설계를 결정한다. 있는 기능은 문서 목차에 보이지만 없는 기능은 안 보이므로, 전제를 세울 때는 반드시 원문을 확인해야 한다. 이번엔 확인해서 잡았고, 확인하지 않았다면 화면 문구까지 틀린 채로 배포됐다.
EOF
```

- [ ] **Step 4: 추가된 6줄을 눈으로 확인한다**

```bash
cd /Users/cheonjamin/projects/AllDap && grep -c '^2026-09-06 |' docs/decisions.md && grep -n '^2026-09-06 |' docs/decisions.md | cut -c1-120
```

Expected: `6` 이 출력되고, 6줄의 앞머리가 각각 `customerKey` · `빌링키를 앱 레벨` · `결제 수단 삭제를` ·
`빌링키 **발급** 호출에만` · `요금제 연동 4조각 중` · `~~토스에는 빌링키를 폐기하는` 로 시작한다.

> ⚠️ **6이 아니라 다른 숫자가 나오면** heredoc 이 잘렸거나 이미 한 번 실행된 것이다.
> `git diff docs/decisions.md` 로 확인하고 `git checkout -- docs/decisions.md` 로 되돌린 뒤 Step 3 을 다시 한다.

- [ ] **Step 5: `AGENTS.md` "테이블 소유권" 표에 `usage_events` 와 `billing_methods` 를 추가한다**

🔴 **별도 Step 으로 둔 이유가 있다 — 이 저장소는 바로 직전 조각에서 이걸 빠뜨렸다.**
`docs/decisions.md` 2026-09-05 항목과 `UsageEventRepository.java:68` 이 둘 다
*"AGENTS.md 소유권 표: usage_events 는 Spring이 쓰고 Spring이 읽는다"* 라고 **표를 근거로 인용하는데,
실제 표에는 그 줄이 없다.** 근거로 삼은 문서가 실제로는 그 말을 하지 않는 상태다.
이번에 `billing_methods` 를 넣으면서 **그 누락도 같이 메운다.**

먼저 현재 표를 확인한다.

```bash
cd /Users/cheonjamin/projects/AllDap && sed -n '117,124p' AGENTS.md
```

Expected: 표 헤더와 5줄(`users, bots` / `documents` / `chunks` / `conversations, messages` / `eval_*`)이
보이고 **`usage_events` 도 `billing_methods` 도 없다.**

Edit 도구로 아래를 치환한다.

old_string:
```
| `eval_*` | **Python** | Spring | 평가 실행은 Python, 조회는 Spring |
```

new_string:
```
| `eval_*` | **Python** | Spring | 평가 실행은 Python, 조회는 Spring |
| `usage_events` | Spring | — | 과금 원장(V5, 2026-09-05). append-only. 평가 실행분도 Python 이 아니라 **Spring 이 조회 직전에 멱등하게 메꾼다** |
| `billing_methods` | Spring | — | 결제 수단·토스 빌링키(V6, 2026-09-06). Python 은 건드리지 않음. `billing_key_enc` 는 **암호문**이라 SQL 로 읽어도 못 쓴다 |
```

> ⚠️ **`usage_events` 줄이 이미 있으면**(다른 브랜치가 먼저 메웠다면) `billing_methods` 한 줄만 넣는다.
> **그렇게 한 줄만 넣었다면 그 사실을 보고에 적는다.**
>
> ⚠️ `users` 행의 "쓰기(owner)"는 그대로 **Spring** 이다. `V6` 가 `users` 에
> `billing_customer_key` 컬럼을 더하지만 그건 스키마 변경이고, 쓰는 쪽은 여전히 Spring 뿐이다.
> 이 표는 *데이터* 소유권이지 *스키마* 소유권이 아니다(`decisions.md` 2026-07-31 Flyway 항목).

- [ ] **Step 6: `AGENTS.md` "W2 세부 상태" 표에 이 조각을 한 줄 추가한다**

먼저 표의 마지막 줄 형식을 확인한다. **Step 1 의 스크래치 파일을 열어 놓고 쓴다.**

```bash
cd /Users/cheonjamin/projects/AllDap && grep -n '^| 백엔드 코드 리뷰 수정 6건\|^| 사용량 계량' AGENTS.md
cat /private/tmp/claude-501/-Users-cheonjamin-projects-AllDap/4c5c3296-6a65-4049-807f-ebb92ea901fe/scratchpad/task5-facts.md
```

표의 **마지막 줄 바로 뒤**에 아래를 넣는다. `<...>` 안은 전부 Step 1 의 실측치로 채운다.

```
| 결제 수단 등록 (2026-09-06) | ✅ **PR #<번호> 머지됨.** 요금제 연동 4조각 중 **3번**. 토스 빌링키 발급·조회·삭제 + `billing_methods`(V6) + **앱 레벨 AES-256-GCM** 암호화(이 저장소의 첫 암호화) + `/billing` 화면. 통합 테스트 **<N>건 통과**. 🔴 **테스트 키 기준이다 — 라이브 전환은 <자동결제 추가 계약>이 필요해 이 조각으로 되지 않는다.** 금액·플랜·실제 청구·웹훅·영수증은 없다(2·4번 조각). 🔴 **토스에 빌링키 <조회> API 가 없어 우리 DB 가 유일한 사본이다** — `BILLING_CRYPTO_KEY` 를 잃으면 전 고객이 재등록해야 한다(`docs/DEPLOY.md` 참고) |
```

> ⚠️ **feat PR 이 아직 머지 안 됐으면 `✅ ... 머지됨` 이 아니라 `🚧 **PR #<번호> 오픈, 미머지.**` 로 쓴다.**
> 바로 위 `백엔드 코드 리뷰 수정 6건` 줄이 정확히 그 형태로 쓰였던 선례다.
> **PR 번호를 아직 모르면 `PR 준비 중`** 이라고 쓴다. **없는 번호를 지어내지 말 것.**
>
> ⚠️ **브라우저 종단 1회를 실제로 안 했으면** "실측 통과" 라고 쓰지 말고
> **"통합 테스트만 통과 · 실제 토스 테스트 키로 브라우저 종단은 미수행"** 이라고 쓴다.
> 이 저장소의 반복된 교훈이 *"통합 테스트가 초록불이어도 진짜 상대와 붙여보기 전까지는
> 연동을 검증했다고 말하지 않는다"*(HTTP/2 업로드 422 · 위젯 iframe Origin 403) 이다.
> **그렇게 바꿔 적었다면 그 사실을 보고에 적는다.**

- [ ] **Step 7: `docs/DEPLOY.md` 에 환경변수 3개와 라이브 제약을 넣는다 — 4곳**

먼저 넣을 자리들을 확인한다.

```bash
cd /Users/cheonjamin/projects/AllDap && sed -n '32,36p;161,183p;270,281p' docs/DEPLOY.md
```

**(1) 체크리스트 7번** — Edit.

old_string:
```
| 7 | `git clone` → `.env.prod` 채우기 | `DB_HOST`·`JWT_SECRET`·`CF_*` 가 비어 있지 않음 |
```

new_string:
```
| 7 | `git clone` → `.env.prod` 채우기 | `DB_HOST`·`JWT_SECRET`·`CF_*`·`BILLING_CRYPTO_KEY`·`TOSS_SECRET_KEY` 가 비어 있지 않음 |
```

**(2) 체크리스트 11번** — Edit.

old_string:
```
| 11 | **Vercel** 배포 (Root `web`, `NEXT_PUBLIC_API_BASE_URL`) | Vercel 주소로 로그인 화면이 뜸 |
```

new_string:
```
| 11 | **Vercel** 배포 (Root `web`, `NEXT_PUBLIC_API_BASE_URL`, `NEXT_PUBLIC_TOSS_CLIENT_KEY`) | Vercel 주소로 로그인 화면이 뜸 |
```

**(3) §6 배포 절 끝에 결제 환경변수 절을 새로 만든다** — Edit.

old_string:
```
t3.micro 는 느려서 Spring 기동에 2~3분 걸릴 수 있다(`start_period: 180s`).

## 7. Vercel (프론트)
```

new_string:
```
t3.micro 는 느려서 Spring 기동에 2~3분 걸릴 수 있다(`start_period: 180s`).

### 결제 수단(토스) 환경변수 — 2026-09-06 추가

`.env.prod` 에 두 개가 더 필요하다. **둘 다 비어 있으면 `prod` 프로파일에서 기동이 실패한다**(fail-closed).

```bash
# 빌링키 암호화 키 — Base64 32바이트. 반드시 이 명령으로 만든다.
openssl rand -base64 32
```

```
BILLING_CRYPTO_KEY=<위 명령의 출력>
TOSS_SECRET_KEY=test_sk_...
```

> 🔴 **`BILLING_CRYPTO_KEY` 를 잃으면 전 고객이 카드를 다시 등록해야 한다.**
> 토스에는 **빌링키를 조회하는 API 가 없다** — 우리 DB 의 `billing_methods.billing_key_enc` 가
> 세상에 하나뿐인 사본이고, 그 값은 이 키로만 열린다. 키를 잃으면 DB 가 멀쩡해도 내용물이 영원히 잠긴다.
> **이 키는 DB 백업과 <함께> 백업 대상이다.** RDS 자동 스냅샷은 암호문만 지킬 뿐 키를 지켜주지 않는다.
> 서버를 옮기거나 `.env.prod` 를 새로 만들 때 **이 값만은 새로 만들지 말고 그대로 옮길 것.**
> 키 회전 기능은 없다(`docs/decisions.md` 2026-09-06 항목 참고).
>
> ⚠️ **길이가 정확히 32바이트여야 한다.** JCE 는 16바이트 키를 주면 **말없이 AES-128 로 돈다.**
> `BillingCrypto` 생성자가 길이를 확인해 아니면 기동을 중단하지만, 애초에 위 명령을 그대로 쓰면 된다.
>
> ⚠️ **키 <종류>를 틀리면 `INVALID_API_KEY` 가 난다.** 자동결제는 **API 개별 연동 키**
> (`test_ck_` / `test_sk_`)를 쓴다. 결제위젯 키(`test_gck_` / `test_gsk_`)가 아니다.
> 토스는 서비스마다 다른 MID 에 각각 키를 발급하고, 세트가 아닌 키를 섞으면 거부한다.
> 클라이언트 키(`test_ck_`)와 시크릿 키(`test_sk_`)는 **같은 세트**여야 한다.

### 🔴 배포한다고 결제가 되는 것은 아니다

토스 문서(https://docs.tosspayments.com/guides/v2/billing) 원문:

> "자동결제는 리스크 검토 및 추가 계약 후 사용할 수 있습니다. 정기 구독형 서비스가 아니라면
> 정책적으로 자동결제 사용이 제한되니 유의하세요."

라이브 키를 받으려면 **전자결제 계약 + 자동결제 추가 계약** 두 개가 필요하고 둘 다 사업자등록이 전제다.
**테스트 키(`test_sk_` / `test_ck_`)로는 사업자등록 없이 전 흐름이 돈다** — 카드 등록창·빌링키 발급·삭제까지.
그래서 이 기능의 배포 완료 조건은 **테스트 키 기준**이고, 배포된 화면 어디에도 "결제됩니다"라고 쓰지 않는다.
실제 청구(4번 조각)는 아직 만들지도 않았다 — **지금 카드를 등록해도 돈이 빠져나가는 경로가 코드에 없다.**

## 7. Vercel (프론트)
```

**(4) §7 Vercel 환경변수 · "알려진 구멍"** — Edit 2회.

old_string:
```
- **환경변수**: `NEXT_PUBLIC_API_BASE_URL=https://alldap.duckdns.org`
```

new_string:
```
- **환경변수**: `NEXT_PUBLIC_API_BASE_URL=https://alldap.duckdns.org`
- **환경변수**: `NEXT_PUBLIC_TOSS_CLIENT_KEY=test_ck_...` — 토스 카드 등록창을 여는 데 쓴다.
  `NEXT_PUBLIC_` 이라 **브라우저 번들에 그대로 들어간다.** 클라이언트 키는 원래 공개돼도 되는 값이라
  괜찮지만, **시크릿 키(`test_sk_`)를 여기 넣으면 안 된다** — 그러면 누구나 우리 계정으로 API 를 부른다.
  위 `.env.prod` 의 `TOSS_SECRET_KEY` 와 **같은 세트의 키**여야 한다(다르면 `INVALID_API_KEY`).
```

old_string:
```
- **프리티어 12개월이 끝나면 월 $23 쯤 나간다.** 만료 전에 정리하거나 옮길 것.
```

new_string:
```
- **프리티어 12개월이 끝나면 월 $23 쯤 나간다.** 만료 전에 정리하거나 옮길 것.
- 🔴 **결제는 테스트 키로만 돈다.** 라이브 전환에 자동결제 추가 계약이 필요하다(위 §6 참고).
  그리고 실제 청구 로직 자체가 아직 없다 — 카드를 저장하는 데까지가 전부다.
- 🔴 **`BILLING_CRYPTO_KEY` 는 DB 백업과 함께 백업해야 하는 값이다.** 이것만 잃어도
  `billing_methods` 전체가 쓸모없어지고, 토스에 조회 API 가 없어 복구 수단이 없다.
```

- [ ] **Step 8: `.env.prod.example` 에도 같은 변수를 넣는다 — 단, feat 브랜치가 이미 넣었는지 먼저 본다**

🔴 **먼저 확인한다.** 양쪽 브랜치가 같은 파일의 같은 자리를 건드리면 머지에서 충돌한다.

```bash
cd /Users/cheonjamin/projects/AllDap && git show feat/billing-method:.env.prod.example | grep -n 'TOSS_SECRET_KEY' || echo "feat 브랜치에 없음 → 여기서 넣는다"
```

**"feat 브랜치에 없음"이 나온 경우에만** 아래를 실행한다.

```bash
cd /Users/cheonjamin/projects/AllDap && cat >> .env.prod.example <<'EOF'

# ── 결제 수단 (토스페이먼츠 — Spring API 만 사용한다) ──────────────────
# 🔴 BILLING_CRYPTO_KEY 를 잃으면 전 고객이 카드를 다시 등록해야 한다.
#    토스에 빌링키 <조회> API 가 없어서, billing_methods.billing_key_enc 가
#    세상에 하나뿐인 사본이고 그 값은 이 키로만 열린다.
#    → DB 백업과 <함께> 백업할 것. 서버를 옮길 때 새로 만들지 말고 그대로 옮길 것.
# ⚠️ 반드시 아래 명령으로 만든다. 길이가 32바이트가 아니면 기동이 중단된다
#    (JCE 는 16바이트 키를 주면 말없이 AES-128 로 돌기 때문에 직접 확인한다).
#      openssl rand -base64 32
BILLING_CRYPTO_KEY=

# 토스 시크릿 키. https://developers.tosspayments.com → 내 개발정보
# ⚠️ 자동결제는 <API 개별 연동 키>(test_sk_)를 쓴다. 결제위젯 키(test_gsk_)가 아니다.
#    프론트(Vercel)의 NEXT_PUBLIC_TOSS_CLIENT_KEY(test_ck_)와 <같은 세트>여야 한다.
# 🔴 라이브 키는 자동결제 추가 계약 후에만 나온다. 지금은 테스트 키만 쓴다.
TOSS_SECRET_KEY=
EOF
```

> ⚠️ **`feat` 브랜치에 이미 있으면 이 Step 을 통째로 건너뛴다.** 그리고 그 사실을 보고에 적는다 —
> 그때는 `.env.prod.example` 이 feat PR 쪽에 담긴 것이 맞다.
>
> ⚠️ 로컬용 `.env.example` 과 `web/.env.local.example` 은 **Task 1·4 의 몫이다.** 여기서 건드리지 말 것.
> 대신 아래로 확인하고, 없으면 **보고에 "feat 브랜치에 로컬 예시 파일 갱신이 빠졌다"고 적는다.**
> ```bash
> cd /Users/cheonjamin/projects/AllDap && git show feat/billing-method:.env.example | grep -c 'BILLING_CRYPTO_KEY'; git show feat/billing-method:web/.env.local.example | grep -c 'NEXT_PUBLIC_TOSS_CLIENT_KEY'
> ```

- [ ] **Step 9: 핸드오프 문서가 이 브랜치에 있으면 반증 표시를 단다 (조건부)**

```bash
cd /Users/cheonjamin/projects/AllDap && test -f docs/superpowers/handoff-2026-09-06.md && sed -n '88,92p' docs/superpowers/handoff-2026-09-06.md || echo "이 브랜치에 핸드오프 문서 없음 → Step 9 건너뜀"
```

**파일이 있는 경우에만** Edit 로 아래를 치환한다. 이 저장소는 **반증된 서술을 지우지 않고 표시만 단다**
(`decisions.md` 2026-09-04 · 2026-09-05 항목이 그 형태다).

old_string:
```
**③ ⚠️ 토스에는 빌링키를 폐기하는 API 가 없다.**
```

new_string:
```
**③ ~~⚠️ 토스에는 빌링키를 폐기하는 API 가 없다.~~ → 🔴 틀린 것으로 드러났다 (2026-09-06).**

> **`DELETE /v1/billing/{billingKey}` 가 실제로 있다.** 설계 단계에서 토스 문서를 직접 확인해 뒤집었다.
> 그리고 **진짜 제약은 반대쪽이었다 — 빌링키를 <조회>하는 API 가 없다.** 우리 DB 가 유일한 사본이라는
> 뜻이고, 이쪽이 훨씬 무겁다(암호화 키 분실 = 전 고객 재등록 · 발급 타임아웃 = 회수 불가 고아 ·
> 중복 발급을 토스가 막아주지 않음). 아래 문단은 그 <틀린 전제 위에> 쓰인 것이므로 그대로 믿지 말 것.
> 정정된 설계는 `docs/superpowers/specs/2026-09-06-billing-method-design.md`,
> 결정 기록은 `docs/decisions.md` 2026-09-06 항목이다.
```

> ⚠️ **핸드오프 문서는 `docs/handoff-2026-09-06` 라는 <다른 브랜치>에만 있을 수 있다**(미머지).
> 그 경우 이 Step 은 건너뛰고, **보고에 "핸드오프 문서의 §③ 이 여전히 틀린 채로 남아 있다.
> 그 브랜치가 머지될 때 함께 정정해야 한다"고 적는다.** 다른 브랜치를 여기서 고치지 말 것.

- [ ] **Step 10: 변경 전체를 한 번 읽고, 지어낸 숫자가 없는지 대조한다**

```bash
cd /Users/cheonjamin/projects/AllDap && git diff --stat && git diff -- AGENTS.md docs/DEPLOY.md
```

**대조 항목 — 하나씩 눈으로 확인한다.**

| 확인할 것 | 어디서 확인 |
|---|---|
| 통합 테스트 건수가 Step 1 의 `bc` 출력과 같은가 | `task5-facts.md` |
| PR 번호가 실제 번호인가 (또는 "PR 준비 중") | `gh pr list` 출력 |
| "실측 통과"라고 쓴 것이 실제로 브라우저에서 돌린 것인가 | `task5-facts.md` |
| `V6__billing_method.sql` 파일명이 실제와 같은가 | `ls api/src/main/resources/db/migration/` |
| 환경변수 이름 3개가 실제 코드가 읽는 이름과 한 글자도 다르지 않은가 | `git grep -n 'BILLING_CRYPTO_KEY\|TOSS_SECRET_KEY\|NEXT_PUBLIC_TOSS_CLIENT_KEY' feat/billing-method` |

```bash
cd /Users/cheonjamin/projects/AllDap && git grep -n 'BILLING_CRYPTO_KEY\|TOSS_SECRET_KEY\|NEXT_PUBLIC_TOSS_CLIENT_KEY' feat/billing-method -- api web
```

Expected: `application.yaml`·`application-prod.yaml`(Task 1)과 `web/` 의 결제 페이지(Task 4)에서
같은 이름이 나온다.

> ⚠️ **이름이 하나라도 다르면 문서 쪽을 코드에 맞춘다**(코드가 사실이다).
> **바꿨다면 어느 이름을 무엇으로 고쳤는지 보고에 적는다.** 배포 문서의 변수 이름이 한 글자 틀리면
> 배포한 사람은 "값을 넣었는데 기동이 안 된다"는 상태에 갇힌다 — fail-closed 라 조용히 틀리지도 않는다.

- [ ] **Step 11: 커밋한다 (경로를 명시해 스테이징 — `git add -A` 금지)**

작업 트리에 이 Task 와 무관한 변경이 있다(`widget/demo.html` 수정 · 미추적 `docs/이해노트-2026-09-01.md`).
`-A` 로 담으면 문서 PR 에 그것들이 섞여 들어간다.

```bash
cd /Users/cheonjamin/projects/AllDap && git add docs/decisions.md docs/DEPLOY.md AGENTS.md
```

Step 8 을 실제로 했다면 함께 담는다.

```bash
cd /Users/cheonjamin/projects/AllDap && git add .env.prod.example
```

Step 9 를 실제로 했다면 함께 담는다.

```bash
cd /Users/cheonjamin/projects/AllDap && git add docs/superpowers/handoff-2026-09-06.md
```

계획서(`docs/superpowers/plans/`)가 아직 커밋 안 됐으면 함께 담는다 — PR #53 의 선례가
`decisions.md` + `plans/` + `specs/` 세 가지를 한 PR 에 담은 것이다.

```bash
cd /Users/cheonjamin/projects/AllDap && git status --short docs/superpowers/
```

```bash
cd /Users/cheonjamin/projects/AllDap && # 설계 문서와 계획서는 이 브랜치에 <이미 커밋돼 있다>. 여기서 add 하지 않는다.
git status --short docs/superpowers/
```

스테이징된 것만 확인하고 커밋한다.

```bash
cd /Users/cheonjamin/projects/AllDap && git status --short && git diff --cached --stat
```

Expected: `docs/decisions.md` · `docs/DEPLOY.md` · `AGENTS.md`(+ 조건부 파일들)만 스테이징돼 있고,
`widget/demo.html` 은 **스테이징되지 않은 채로** 남아 있다.

```bash
cd /Users/cheonjamin/projects/AllDap && git commit -m "$(cat <<'EOF'
docs: 결제 수단 등록의 결정 6건·배포 절차·소유권 표를 반영한다

- decisions.md 6줄: customerKey 전용 키 / AES-256-GCM(첫 암호화 결정) /
  삭제는 토스 먼저·4xx 와 5xx 를 가름 / 발급에만 멱등키+1회 재시도 /
  2번보다 3번을 먼저 / 핸드오프의 "폐기 API 없다"가 반증된 기록
- DEPLOY.md: BILLING_CRYPTO_KEY·TOSS_SECRET_KEY·NEXT_PUBLIC_TOSS_CLIENT_KEY.
  키를 잃으면 전 고객 재등록이라는 경고와 백업 대상 명시.
  라이브 자동결제는 추가 계약이 필요하다는 사실도 함께 적었다
- AGENTS.md: 소유권 표에 billing_methods 추가.
  usage_events 는 decisions.md 와 코드가 표를 근거로 인용하는데
  정작 표에 없던 것을 이번에 함께 메웠다

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

> ⚠️ **Step 5 에서 `usage_events` 를 넣지 않았다면**(이미 있었다면) 커밋 메시지의 마지막 항목을
> 그에 맞게 줄인다. **거짓 완성 금지는 커밋 메시지에도 적용된다.**

- [ ] **Step 12: 푸시하고 docs PR 을 연다**

```bash
cd /Users/cheonjamin/projects/AllDap && git push -u origin docs/billing-method-design
```

```bash
cd /Users/cheonjamin/projects/AllDap && gh pr create \
  --base main --head docs/billing-method-design \
  --title "docs: 결제 수단 등록(토스 빌링키) — 설계·계획·결정 로그·배포 절차" \
  --body-file .github/PULL_REQUEST_TEMPLATE.md
```

Expected: PR URL 이 출력된다.

> 🔴 **PR 본문은 여기서 쓰지 않는다.** 템플릿을 그대로 올려두고 끝낸다 — 본문은 상위 에이전트가 따로 쓴다.
> 템플릿 대신 요약을 지어 넣으면 "한계 & 트레이드오프" 와 "검토한 대안" 칸이 빈 채로 굳는데,
> 이 저장소가 *"그 두 칸이 핵심이고, 비어 있으면 대개 안 본 것"* 이라고 못박은 자리다.
>
> 🔴 **CI 는 기다리지 않는다.** `gh pr create` 까지가 이 Task 의 몫이다. 폴링 금지.
>
> ⚠️ **`gh pr create` 가 "no commits between main and docs/billing-method-design" 로 실패하면**
> Step 11 의 커밋이 다른 브랜치에 올라간 것이다. `git log --oneline -3` 으로 확인할 것.
>
> ⚠️ **이미 이 브랜치의 PR 이 열려 있다면** `gh pr create` 가 그렇게 알려준다.
> 그때는 새로 만들지 말고 **푸시로 끝난다**(기존 PR 에 커밋이 얹힌다).
> **그렇게 됐다면 기존 PR 번호를 보고에 적는다.**

**최종 보고에 반드시 담을 것** (상위 에이전트가 PR 본문을 쓸 재료다):

1. Step 1 에서 실제로 나온 숫자 — 테스트 총 건수, `tsc`/`lint` 결과, 브라우저 종단 수행 여부
2. 조건부 Step(7·8·9) 중 **건너뛴 것과 그 이유**
3. Step 10 에서 **이름이 안 맞아 고친 것**이 있으면 무엇을 무엇으로
4. `feat` 브랜치에 빠진 것(로컬 `.env.example`·`web/.env.local.example` 갱신 등)
5. 핸드오프 문서 §③ 을 정정했는지, 못 했으면 어느 브랜치에 남아 있는지
6. docs PR URL

---


---

## 멈춰야 하는 지점 — 사람에게 보고할 것

| 조건 | 왜 |
|---|---|
| `ai-service/` 나 `widget/` 을 고쳐야 할 것 같으면 | 이 계획의 범위 밖이다. 설계가 틀렸다는 신호다 |
| `V1`~`V5` 를 고쳐야 할 것 같으면 | Flyway 체크섬이 깨져 기동이 막힌다. **절대 고치지 않는다** |
| 기동이 `ddl-auto=validate` 로 실패하면 | 엔티티와 `V6` 이 어긋난 것이다. 맞출 때까지 진행하지 않는다 |
| 기존 테스트가 깨지면 | `User.create` 는 **모든 통합 테스트가 지나간다**. 원인부터 읽는다 |
| **토스 테스트 키가 없으면** | Task 4 Step 9(브라우저 종단)를 못 한다. 사람에게 요청하고, 못 받으면 **미실행 사실을 PR 에 명시**한다 |
| **Task 5 전에 PR #54 가 아직 열려 있으면** | `AGENTS.md` 가 충돌한다. 위 "브랜치" 절 참고 |
| 새 `ErrorCode` 가 4개보다 더 필요해 보이면 | 기존 400 계열로 표현되는지 먼저 확인한다 |
| 금액·플랜을 만들어야 할 것 같으면 | **2번 조각이다.** 파일럿 데이터 없이 숫자를 만들지 않는다 |

## 이 계획이 하지 않는 것 (설계에서 축소한 것)

- **`TossPayments-Test-Code` 헤더로 실패 경로를 강제하는 것.** 설계 §검사 3 이 요구했지만
  그 헤더를 토스로 보내는 코드 경로를 만들지 않는다 — 4xx·5xx 는 이미 통합 테스트가 스텁으로 덮는다.
  실제 카드사 거절 문구를 눈으로 보고 싶어지면 그때 `TossClient` 에 헤더 주입을 붙인다.
- **설계 §검사 2-8 "삭제 시 토스를 <먼저> 부른다" 의 직접 증명.** 순서를 직접 관찰하는 테스트 대신
  **9번(토스 5xx면 우리 행이 남는다)** 이 그 필요조건을 잡는다 — 우리가 먼저 지웠다면 행이 남을 수 없다.
- **키 회전.** 나중에 `v2:` 접두사로 소급 도입 가능하다는 것까지만 확인해뒀다.

---

## PR 본문 — `feat/billing-method`

Task 4 Step 10 이 이 절을 `/tmp/billing-pr-body.md` 에 저장해 `--body-file` 로 쓴다.
`<!-- -->` 자리는 **실제 실행 출력**으로 채운다. 지어내지 않는다.

```markdown
## 해결하려는 문제가 무엇인가요?

요금제 연동 4조각 중 **3번**입니다. 계정마다 카드 한 장을 등록·조회·삭제할 수 있게 합니다.
**금액은 한 곳에도 나오지 않습니다** — 그건 4번(청구)의 일이고, 그 앞의 2번(플랜·포함량)은
PRD §13.1 이 금액을 "파일럿 4주 후" 로 미뤄둬서 아직 만들 수 없습니다.

## 왜 해야 하나요?

원래 순서는 1 → 2 → 3 이었는데 **2번과 3번을 바꿨습니다.**
2번은 월 정액·포함 답변 수·초과 단가라는 숫자를 요구하는데, `/pricing` 의 중심 주장이
"금액이 아직 없다"이고 그게 의도입니다. 지금 만들면 화면은 "금액 없다"고 하는데 DB엔 금액이 있게 되고,
이 저장소가 지켜온 원칙("근거 없는 숫자를 쓰지 않는다")을 정면으로 어깁니다.
**3번은 금액이 하나도 필요 없습니다.**

## 어떻게 해결했나요?

카드번호는 토스 결제창 안에서만 존재하고 우리는 `authKey` 만 받습니다 —
**PCI-DSS 대상 데이터를 우리가 갖지 않습니다.**

**① `customerKey` 와 `billingKey` 를 다른 테이블에 둡니다 — 수명이 다릅니다.**
`customerKey` 는 카드를 빼도 남아야 재등록 시 토스 쪽 고객 이력이 이어지고, `billingKey` 는
카드와 함께 죽습니다. 한 곳에 두면 삭제할 때 반드시 한쪽을 잘못 다루게 됩니다.
`users.id` 를 그대로 쓰지 않은 것은 `bots.public_key` 와 같은 이유입니다 —
**내부 기본키를 외부 업체 로그·대시보드·CS 이력에 흘리지 않습니다.**

**② `billingKey` 를 AES-256-GCM 으로 암호화해 저장합니다. 이 저장소의 첫 암호화입니다.**
새 의존성은 0개입니다 — `spring-boot-starter-security` 가 이미 끌고 오는 `spring-security-crypto` 의
`AesBytesEncryptor` 를 원시 키 생성자로 씁니다. `Encryptors.text()` 를 안 쓴 이유는
**그게 GCM 이 아니라 CBC** 라서입니다(7.0.6 바이트코드로 확인). CBC 는 인증이 없어 암호문을
한 바이트 뒤집어도 복호화가 성공하고, DB 를 만질 수 있는 공격자가 남의 빌링키로 바꿔치기해도
우리가 눈치채지 못합니다. 키 관리는 `JwtService` 의 fail-closed 패턴을 그대로 복제했고,
**"키 길이 32바이트" 검사를 하나 더** 넣었습니다 — JCE 는 16바이트 키를 주면 말없이 AES-128 로 돕니다.

**③ 핸드오프에 적힌 전제가 틀렸고, 문서를 직접 확인해 뒤집었습니다.**
"토스에는 빌링키 폐기 API 가 없다" → **있습니다**(`DELETE /v1/billing/{billingKey}`).
대신 진짜 제약은 **조회 API 가 없다는 것**이고 그게 더 무겁습니다 — 우리 DB 가 유일한 사본입니다.
그래서 발급에 **멱등키 + I/O 실패 1회 재시도**를 붙였습니다. `AiServiceClient` 의
"연결 실패에만 재시도" 논리를 여기 쓸 수 없습니다 — 읽기 타임아웃이어도 토스는 이미 발급했을 수 있고,
그 키는 영구히 회수 불가입니다. 멱등키가 "직전 시도가 아무 일도 하지 않았다"는 전제를 대신 세워줍니다.

**④ 삭제는 토스 먼저, 우리 나중입니다.** 반대로 하면 토스 호출이 실패했을 때 우리는 키를 이미
지운 뒤라 **영영 폐기할 수 없는 고아**가 남습니다. 토스 5xx·타임아웃이면 우리 행을 **유지하고 503**,
4xx 면 "토스 쪽엔 이미 없다"로 보고 우리 행만 지웁니다.

**검사 (실제 출력)**

<!-- Task 1 Step 3 의 FAIL, Task 1 Step 15 의 129건,
     Task 2 Step 3 의 FAIL 목록, Task 3 Step 8 의 15건, Task 3 Step 9 의 144건,
     Task 4 Step 8 의 tsc·lint, Task 4 Step 9 의 브라우저 한 바퀴 결과를 그대로 붙일 것 -->

## 이 PR의 한계 & 트레이드오프

- 🔴 **라이브 전환이 안 됩니다.** 토스 자동결제는 전자결제 계약에 더해 **자동결제 추가 계약**이
  필요하고 사업자등록이 전제입니다. 이 PR 은 **테스트 키 기준**으로만 검증했습니다.
- 🔴 **`BILLING_CRYPTO_KEY` 를 잃으면 전 고객이 카드를 다시 등록해야 합니다.** 토스에 조회 API 가
  없어 다른 길이 없습니다. 백업 대상이고, `docs/DEPLOY.md` 에 그 경고를 적었습니다.
- **키 회전을 만들지 않았습니다.** 나중에 `v2:` 접두사로 소급 구분이 가능하다는 것까지만 확인했습니다.
- **토스가 중복 발급을 막아주지 않습니다.** 같은 카드로 빌링키가 몇 개든 생깁니다.
  우리 `UNIQUE(user_id)` 가 유일한 방어라, **카드 여러 장을 지원하면 그 방어가 사라집니다.**
- **삭제 API 의 에러 코드표가 토스 문서에 없습니다.** 없는 빌링키를 지울 때 어떤 코드가 오는지 몰라
  4xx 를 전부 "이미 없다"로 취급합니다. 이 해석이 틀리면 고아가 남습니다.
- **등록 성공이 청구 성공을 보장하지 않습니다.** 토스 문서상 잔고 부족·한도 초과는
  결제 승인을 요청할 때 확인됩니다. 4번 조각의 실패 처리가 그래서 필요합니다.
- **국내 발급 카드만 지원됩니다**(토스 제약).
- **`TossPayments-Test-Code` 로 실패 경로를 강제하지 않았습니다.** 4xx·5xx 는 스텁 통합 테스트가
  덮습니다. 실제 카드사 거절 문구를 봐야 할 때 붙입니다.
- 삭제 시 "토스를 **먼저** 부른다"를 직접 관찰하는 테스트는 없습니다.
  "토스 5xx 면 우리 행이 남는다"가 그 필요조건을 잡습니다.

## 기존 기능에 미치는 영향

`User.create` 를 건드려 **모든 통합 테스트가 영향권**입니다(전부 `/api/auth/signup` 으로 사용자를 만듭니다).
그래서 Task 1 과 Task 3 이 전체 테스트를 돌려 회귀를 확인합니다.
`billing_methods.user_id` 에 **`ON DELETE CASCADE` 를 걸었습니다** — V5 에서 이걸 뺐다가
`userRepository.deleteAll()` 정리가 막혀 무관한 테스트 11건이 깨진 적이 있습니다.
`RestClient` 빈이 둘이 되므로 컨텍스트 기동을 별도 Step 으로 확인합니다.

## Edge Case & 실패 시나리오

- 남의 `customerKey` 를 본문에 실어 보냄 → 400 (서버는 DB 의 값을 씁니다)
- 이미 카드가 있는데 또 등록 → 409
- 토스가 카드 거절 → 400 + **토스의 한국어 문구 그대로**
- 토스 죽음/타임아웃 → 503, 카드 행은 그대로
- 발급 중 연결 끊김 → **같은 멱등키로 1회 재시도**
- 소모된 `authKey` 로 새로고침 → `router.replace` 가 URL 을 비워 재전송되지 않음
- 시크릿 키 미설정 → 토스 401 → **503 + 서버 ERROR 로그**(사용자에게 "카드를 확인하세요" 라고 하지 않음)

## 검토한 대안과 선택 이유

- **`customerKey` 로 `users.id`(UUID)** — 형식은 통과하지만 내부 PK 가 토스 대시보드·로그에 그대로
  나갑니다. `bots.public_key` 선례와 어긋납니다.
- **`billingKey` 평문 저장**(대부분의 튜토리얼) — 동작은 같지만 *"결제 수단을 어떻게 저장했나요?"* 에
  *"평문으로 넣었습니다"* 로 끝납니다.
- **`Encryptors.text()` / `delux()`** — 전자는 CBC(인증 없음), 후자는 GCM 이지만 키를
  PBKDF2 1024회로 유도합니다. 우리는 이미 32바이트 난수를 환경변수로 갖고 있어 유도할 이유가 없습니다.
- **`users` 에 컬럼 4개 추가**(테이블 분리 대신) — 삭제가 "컬럼 4개를 NULL 로 되돌리기" 가 되고,
  인증에 쓰이는 테이블에 결제 관심사가 섞입니다.
- **`AiServiceClient` 의 `RestClient`·서킷 재사용** — 토스 장애가 채팅을 끊고 그 반대도 됩니다.
- **재시도 없음 / 멱등키 없이 재시도** — 전자는 타임아웃 때 고아 빌링키를 영구히 남기고,
  후자는 고아를 **하나 더** 만듭니다.
- **카드 교체 기능** — 삭제 후 재등록으로 같은 일이 되고 상태 전이만 하나 늡니다.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

---

## PR 본문 — `docs/billing-method-design`

Task 5 가 씁니다. 위 PR 이 **무엇을 왜 했는지**를 저장소 문서에 남기는 PR 이라,
본문은 짧게 두고 `decisions.md` 항목을 그대로 인용합니다.

```markdown
## 해결하려는 문제가 무엇인가요?

`feat/billing-method`(결제 수단 등록)의 설계 문서·구현 계획·결정 로그와,
새 환경변수 2개의 운영 절차를 저장소에 남깁니다.

## 왜 해야 하나요?

이 조각에는 **나중에 반드시 다시 물어볼 결정**이 셋 있습니다 —
왜 `users.id` 를 `customerKey` 로 안 썼나, 왜 평문이 아니라 암호화인가, 왜 삭제를 토스부터 부르나.
그리고 **핸드오프에 적힌 전제 하나가 틀렸다는 것**도 남겨야 합니다.
이 저장소는 반증된 판단을 지우지 않고 "틀린 것으로 드러났다" 형태로 남기는 관례가 있습니다.

## 어떻게 해결했나요?

<!-- decisions.md 에 실제로 추가된 항목 수(grep -c 결과)와
     AGENTS.md 테이블 소유권 표·W2 표의 diff 를 붙일 것 -->

## 이 PR의 한계 & 트레이드오프

- `docs/DEPLOY.md` 에 적은 **배포 절차는 아직 실행되지 않았습니다.** 배포 자체가 보류 중입니다
  (RDS 프리티어 충돌, `decisions.md`). 다음 배포 때 `BILLING_CRYPTO_KEY` · `TOSS_SECRET_KEY` 를
  빠뜨리면 **기동이 실패합니다** — 그 사실을 문서에 적었지만 실측하지는 못했습니다.
- `AGENTS.md` 의 진행 상황 표는 **테스트 키 기준**으로 적었습니다. 라이브 전환은 안 됩니다.

## 검토한 대안과 선택 이유

feat PR 과 문서 PR 을 하나로 합치는 안 — 사용량 계량(PR #52·#53)과 같은 이유로 나눴습니다.
문서 변경은 코드 리뷰의 관심사가 다르고, 합치면 **"무엇을 왜 바꿨는지"가 코드 diff 에 묻힙니다.**

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```
