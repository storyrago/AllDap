# 사용량 계량 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 과금 대상 사건(위젯 답변·완료된 평가 실행)을 계정별 불변 원장에 쌓고, 이번 달 사용량을 API 와 대시보드로 보여준다.

**Architecture:** `usage_events` 를 append-only 원장으로 둔다. 채팅 답변은 `ChatTurnStore.saveAnswer` 와 **같은 트랜잭션의 네이티브 INSERT** 로 기록하고, 평가 실행은 끝나는 것을 Python 이 알기 때문에 Spring 이 조회 직전에 **멱등하게 메꾼다**. 전부 Spring 안에서 끝나며 Python·위젯은 한 줄도 안 고친다.

**Tech Stack:** Spring Boot 4.0.7 / Java 21 / Flyway / JPA(`ddl-auto=validate`) / JUnit5 + Testcontainers, Next.js 16 + React 19 + TypeScript

## Global Constraints

- 설계 원본은 `docs/superpowers/specs/2026-09-05-usage-metering-design.md`. **금액·플랜·결제는 이 계획의 범위가 아니다.**
- **Python(`ai-service/`)·위젯(`widget/`)을 고치지 않는다.** 고쳐야 할 것 같으면 멈추고 보고한다.
- `spring.jpa.hibernate.ddl-auto` 는 `validate` 다. **엔티티와 마이그레이션이 어긋나면 기동 자체가 실패한다.**
- **`V1`~`V4` 마이그레이션을 절대 고치지 않는다.** Flyway 체크섬이 깨져 다음 기동이 막힌다. 새 파일은 `V5__usage_events.sql`.
- 코드 주석과 에러 메시지는 **한국어**. 에러 응답 포맷은 전 계층 공통 `{ "error": { "code": "...", "message": "..." } }`.
- **JSON 표기 변환은 Spring 책임이다.** 프론트는 `camelCase` 를 본다(`web/lib/types.ts` 가 그 전제로 작성돼 있다).
- `userId` 는 **`@AuthenticationPrincipal` 로만** 받는다. 쿼리 파라미터·본문으로 받으면 격리가 무너진다.
- 커밋 메시지 `<타입>: <한국어 요약>`, 본문 끝에 `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- **`git add -A` 금지.** 작업 트리에 이 작업과 무관한 미커밋 파일(`widget/demo.html`, 미추적 `docs/이해노트-2026-09-01.md`)이 있다. 경로를 명시해 스테이징한다.
- Spring 테스트: `cd api && ./gradlew test --tests '<클래스명>'` (Docker 필요 — Testcontainers).
- 프론트 검사: `cd web && npx tsc --noEmit && npm run lint`.
- **PR 생성까지가 범위다. CI 는 기다리지 않는다.**
- **거짓 완성 금지.** 검사를 실제로 돌리고 그 출력을 PR 본문에 붙인다.

## 설계 문서에서 한 가지를 정제했다

설계 문서는 기간 경계를 SQL 안에서 `AT TIME ZONE 'Asia/Seoul'` 로 계산하는 모양으로 적어뒀다. **구현에서는 Java 에서 계산해 `Instant` 두 개를 파라미터로 넘긴다.**

이유는 둘이다. ① 문자열을 이어붙여 날짜를 만드는 SQL 은 읽기 어렵고 형변환 오류가 런타임에만 드러난다. ② 경계 계산을 Java 에 두면 **테스트에서 그 계산만 따로 검증할 수 있다.** 저장은 여전히 `TIMESTAMPTZ` 이고 비교도 그대로라, 동작은 설계와 동일하다.

## 파일 구조

| 파일 | 책임 |
|---|---|
| `api/src/main/resources/db/migration/V5__usage_events.sql` | 원장 테이블 하나. 다른 테이블을 건드리지 않는다 |
| `api/.../domain/usage/entity/UsageEvent.java` | 테이블 매핑. `ddl-auto=validate` 가 스키마 드리프트를 잡아준다 |
| `api/.../domain/usage/repository/UsageEventRepository.java` | 쓰기 2개(채팅 기록·평가 메꾸기)와 집계 1개. **과금 정책이 여기 SQL 안에 있다** |
| `api/.../domain/usage/service/UsageService.java` | 기간 계산 + 메꾸기 + 집계 조합 |
| `api/.../domain/usage/dto/UsageResponse.java` | 응답 DTO(camelCase) |
| `api/.../domain/usage/controller/UsageController.java` | `GET /api/usage` |
| `api/.../domain/chat/service/ChatTurnStore.java` | 답변 저장 트랜잭션에 계량 한 줄 추가 |
| `api/src/test/.../domain/usage/UsageIntegrationTest.java` | 설계의 주장 8가지를 실제 HTTP·실제 DB 로 검증 |
| `web/lib/types.ts`, `web/lib/api.ts`, `web/app/(dashboard)/dashboard/page.tsx` | 대시보드 카드 |

`usage` 를 별도 도메인 패키지로 두는 이유: 청구는 봇·채팅·평가 어디에도 속하지 않는 **계정 단위 관심사**다. `chat` 안에 넣으면 나중에 플랜·결제가 붙을 때 `chat` 이 청구 도메인을 흡수한다.

---

## Task 1: 원장 테이블과 채팅 계량

**Files:**
- Create: `api/src/main/resources/db/migration/V5__usage_events.sql`
- Create: `api/src/main/java/com/alldap/api/domain/usage/entity/UsageEvent.java`
- Create: `api/src/main/java/com/alldap/api/domain/usage/repository/UsageEventRepository.java`
- Modify: `api/src/main/java/com/alldap/api/domain/chat/service/ChatTurnStore.java`
- Test: `api/src/test/java/com/alldap/api/domain/usage/UsageIntegrationTest.java`

**Interfaces:**
- Consumes: `Conversation.CHANNEL_WIDGET` (`"widget"`), `Conversation.CHANNEL_TEST` (`"test"`) — 기존 상수
- Produces:
  - `UsageEvent.KIND_CHAT_ANSWER` = `"chat_answer"`, `UsageEvent.KIND_EVAL_RUN` = `"eval_run"`
  - `UsageEventRepository.recordChatAnswer(UUID messageId, UUID conversationId, boolean isFallback)` → `int` (삽입된 행 수)
  - Task 2 가 같은 리포지토리에 메꾸기·집계 메서드를 더한다

---

- [ ] **Step 1: 브랜치를 딴다**

```bash
cd /Users/cheonjamin/projects/AllDap
git checkout main && git pull && git checkout -b feat/usage-metering
```

- [ ] **Step 2: 실패하는 테스트를 쓴다**

`api/src/test/java/com/alldap/api/domain/usage/UsageIntegrationTest.java` 를 새로 만든다.

기존 `WidgetIntegrationTest` 를 **먼저 읽고** 그 파일의 보조 메서드(`publicRequest`, `request`, `signup`, `Response` record, `decode`, `JSON`)와 필드(`client`, `port`, `aiService`, `rateLimiter`, `jdbcTemplate`, `userRepository`)를 같은 모양으로 가져온다. **이름을 새로 짓지 말고 그 파일과 똑같이 쓴다** — 두 파일을 나란히 읽는 사람이 헷갈리지 않아야 한다.

```java
package com.alldap.api.domain.usage;

// import 는 WidgetIntegrationTest 를 그대로 따른다.

/**
 * 사용량 계량 통합 테스트.
 *
 * <p><b>여기서 지키려는 것은 "무엇이 과금되고 무엇이 안 되는가" 하나다.</b>
 * /pricing 이 이미 고객에게 약속한 내용이라, 이 테스트가 곧 그 약속의 검증이다.
 */
@IntegrationTest
@DisplayName("사용량 계량 통합 테스트")
class UsageIntegrationTest {

    private static final String PASSWORD = "correct-password-1234";

    private static final String 정상응답 = """
            {"answer":"환불은 7일 이내에 가능합니다.",
             "sources":[],"is_fallback":false,"latency_ms":800}""";

    private static final String 거절응답 = """
            {"answer":"문서에서 답을 찾지 못했어요. 담당자에게 문의해주세요.",
             "sources":[],"is_fallback":true,"latency_ms":120}""";

    @Test
    @DisplayName("[과금] 위젯 답변 1건이 사용량 1건으로 남는다")
    void 위젯_답변은_세어진다() {
        aiService.enqueue(200, 정상응답);
        widgetChat(publicKey, "환불 규정이 어떻게 되나요?");

        assertThat(countUsage(userId, "chat_answer")).isEqualTo(1);
    }

    @Test
    @DisplayName("[과금] fallback 답변은 세지 않는다 (/pricing 의 약속)")
    void fallback_은_세지_않는다() {
        aiService.enqueue(200, 거절응답);
        widgetChat(publicKey, "사내 헬스장이 있나요?");

        // 답변 행은 남아야 한다 — 안 남으면 대화 로그가 비어 로그 화면이 깨진다
        assertThat(countMessages(botId)).isEqualTo(2);   // user + assistant
        assertThat(countUsage(userId, "chat_answer")).isZero();
    }

    @Test
    @DisplayName("[과금] 관리자 테스트 채팅은 세지 않는다")
    void 테스트_채팅은_세지_않는다() {
        aiService.enqueue(200, 정상응답);
        request(HttpMethod.POST, "/api/bots/" + botId + "/chat", ownerToken,
                new ChatRequest("환불 규정이 어떻게 되나요?", "test-session-1"));

        aiService.enqueue(200, 정상응답);
        widgetChat(publicKey, "환불 규정이 어떻게 되나요?");

        // 위젯 1건만 세어진다. 테스트 채팅도 LLM 비용은 들지만 과금 대상이 아니다.
        assertThat(countUsage(userId, "chat_answer")).isEqualTo(1);
    }

    @Test
    @DisplayName("[과금] 봇을 지워도 이미 센 사용량은 남는다 (이 설계의 존재 이유)")
    void 봇을_지워도_사용량은_남는다() {
        aiService.enqueue(200, 정상응답);
        widgetChat(publicKey, "환불 규정이 어떻게 되나요?");
        assertThat(countUsage(userId, "chat_answer")).isEqualTo(1);

        // 봇을 지우면 conversations·messages 는 CASCADE 로 사라진다.
        request(HttpMethod.DELETE, "/api/bots/" + botId, ownerToken, null);
        assertThat(countMessages(botId)).isZero();

        // 🔴 그런데 사용량은 남아야 한다. 청구 근거가 삭제 버튼 하나로 사라지면 안 된다.
        assertThat(countUsage(userId, "chat_answer")).isEqualTo(1);
    }

    // ── 테스트 보조 ──────────────────────────────────────────────────────

    private long countUsage(UUID userId, String kind) {
        Long n = jdbcTemplate.queryForObject(
                "SELECT count(*) FROM usage_events WHERE user_id = ? AND kind = ?",
                Long.class, userId, kind);
        return n == null ? 0 : n;
    }

    private long countMessages(UUID botId) {
        Long n = jdbcTemplate.queryForObject("""
                SELECT count(*) FROM messages m
                  JOIN conversations c ON c.id = m.conversation_id
                 WHERE c.bot_id = ?""", Long.class, botId);
        return n == null ? 0 : n;
    }
}
```

`@BeforeEach` 는 `WidgetIntegrationTest` 의 것을 그대로 따르되 **`userId` 를 필드로 남긴다**(가입한 계정의 id — `userRepository` 로 이메일 조회). `rateLimiter.reset()` 과 `circuitBreaker.reset()` 을 반드시 넣는다. 둘 다 **상태를 가진 싱글턴**이라, 빠뜨리면 실행 순서에 따라 나타났다 사라지는 실패가 난다.

- [ ] **Step 3: 테스트를 돌려 실패를 확인한다**

```bash
cd api && ./gradlew test --tests 'UsageIntegrationTest'
```

Expected: FAIL — `relation "usage_events" does not exist`

- [ ] **Step 4: 마이그레이션을 만든다**

`api/src/main/resources/db/migration/V5__usage_events.sql`:

```sql
-- 과금 대상 사건의 <불변 원장> (2026-09-05)
--
-- 왜 messages 를 그때그때 세지 않는가
--   ① 봇을 지우면 conversations·messages 가 CASCADE 로 사라져 <그 달 청구 근거가 없어진다.>
--      고객에게 청구 내역을 증명할 수도 없다.
--   ② 과금 정책을 바꾸면 <지난달 청구서 숫자까지 함께 바뀐다.> 이미 받은 돈과 화면이 어긋난다.
--   그리고 이 문은 한 방향이다 — 나중에 원장이 필요해져도 지워진 봇의 대화는 소급할 수 없다.
--
-- 소유권: Spring 이 쓰고 Spring 이 읽는다. Python 은 건드리지 않는다.
--         (평가 실행은 Python 이 완료를 알지만, 기록은 Spring 이 메꾼다 — UsageService 참고)
CREATE TABLE IF NOT EXISTS usage_events (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  -- 청구 대상은 <계정>이다. 봇이 아니라 봇의 주인이 낸다.
  -- ON DELETE CASCADE 다 — 이 저장소의 다른 테이블과 같다.
  -- ⚠️ 처음에는 "계정을 지워도 청구 근거는 남아야 한다" 며 CASCADE 를 빼려 했다가 되돌렸다 —
  --    ① 계정 삭제 기능이 <아직 없다>. 없는 기능을 위한 방어였다.
  --    ② 대가는 실재했다 — 통합 테스트가 전부 userRepository.deleteAll() 로 정리하고
  --       Postgres 컨테이너를 공유해서, 계량된 답변이 하나라도 있으면 FK 가 그 정리를 막아
  --       이 기능과 무관한 테스트들이 깨졌다.
  --    이 설계가 지키려는 것은 "계정 삭제" 가 아니라 "봇을 지워도 청구 근거가 남는다" 이고,
  --    그건 아래 bot_id 에 FK 를 걸지 않은 것이 담당한다. 그쪽은 그대로다.
  user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

  -- 🔴 bots 를 FK 로 걸지 않는다. 봇이 지워져도 그 달 기록은 남아야 한다.
  --    어느 봇이었는지는 <값으로만> 들고 있는다(참조 무결성 없음, 화면 표시용).
  bot_id      UUID,

  kind        VARCHAR(20) NOT NULL,   -- 'chat_answer' | 'eval_run'

  -- 이 사건을 만든 원본 행(messages.id 또는 eval_runs.id). 중복 기록을 막는 열쇠다.
  source_ref  UUID NOT NULL,

  -- 🔴 사건이 <실제로 일어난> 시각이다. 기록한 시각이 아니다.
  --    평가 실행은 나중에 메꾸므로 둘이 다를 수 있고, 청구 기간을 가르는 것은 이쪽이다.
  occurred_at TIMESTAMPTZ NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

  -- 🔴 멱등성의 전부다. 같은 원본으로 두 번 세지 않는다.
  --    평가 실행 메꾸기가 매 조회마다 도는데, 이 제약이 없으면 볼 때마다 사용량이 늘어난다.
  CONSTRAINT uq_usage_source UNIQUE (kind, source_ref)
);

-- 청구는 언제나 "이 계정의 이 기간" 으로 조회한다. 그 모양 그대로 인덱스를 만든다.
CREATE INDEX IF NOT EXISTS idx_usage_user_time ON usage_events (user_id, occurred_at);
```

- [ ] **Step 5: 엔티티를 만든다**

`api/src/main/java/com/alldap/api/domain/usage/entity/UsageEvent.java`:

```java
package com.alldap.api.domain.usage.entity;

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

import java.time.Instant;
import java.util.UUID;

/**
 * 과금 대상 사건 한 건. <b>append-only 다 — 만들고 나면 고치지도 지우지도 않는다.</b>
 *
 * <p><b>왜 연관관계(@ManyToOne)를 하나도 두지 않는가.</b>
 * {@code user_id} 는 FK 지만 {@code User} 로 매핑하지 않고 {@code UUID} 그대로 둔다.
 * 이 엔티티에서 사용자나 봇을 타고 갈 일이 없고, LAZY 프록시를 트랜잭션 밖으로 들고 나가
 * 터지는 사고({@code open-in-view=false})를 애초에 만들지 않기 위해서다.
 * {@code bot_id} 는 아예 FK 가 아니다 — 봇이 지워져도 이 행은 남아야 한다.
 *
 * <p><b>이 엔티티는 거의 읽히지 않는다.</b> 쓰기는 네이티브 INSERT 로 하고 집계는 count 로 한다.
 * 그래도 두는 이유는 {@code ddl-auto=validate} 다 — 마이그레이션과 코드가 어긋나면
 * <b>기동 단계에서 바로 실패해</b> 조용한 드리프트를 막아준다.
 */
@Getter
@Entity
@Table(name = "usage_events")
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class UsageEvent extends BaseEntity {

    /** 위젯에서 실제로 만들어진 답변. fallback 은 제외된다 */
    public static final String KIND_CHAT_ANSWER = "chat_answer";
    /** 완료된 품질 평가 실행. partial·failed 는 제외된다 */
    public static final String KIND_EVAL_RUN = "eval_run";

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    @Column(name = "id", nullable = false, updatable = false)
    private UUID id;

    @Column(name = "user_id", nullable = false, updatable = false)
    private UUID userId;

    /** 표시용. 봇이 지워지면 가리키는 대상이 없어진다 — 의도한 것이다 */
    @Column(name = "bot_id", updatable = false)
    private UUID botId;

    @Column(name = "kind", length = 20, nullable = false, updatable = false)
    private String kind;

    @Column(name = "source_ref", nullable = false, updatable = false)
    private UUID sourceRef;

    @Column(name = "occurred_at", nullable = false, updatable = false)
    private Instant occurredAt;
}
```

- [ ] **Step 6: 리포지토리와 채팅 계량 SQL 을 만든다**

`api/src/main/java/com/alldap/api/domain/usage/repository/UsageEventRepository.java`:

```java
package com.alldap.api.domain.usage.repository;

import com.alldap.api.domain.usage.entity.UsageEvent;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.UUID;

public interface UsageEventRepository extends JpaRepository<UsageEvent, UUID> {

    /**
     * 위젯 답변 하나를 계량한다. <b>과금 정책 전체가 이 한 문장 안에 있다.</b>
     *
     * <p>이 문장이 동시에 네 가지를 한다.
     * <ol>
     *   <li><b>청구 대상 해결</b> — 위젯 채팅에는 로그인한 사용자가 없다.
     *       대화 → 봇 → 주인으로 거슬러 올라가 <b>봇의 주인</b>을 찾는다</li>
     *   <li><b>테스트 채팅 제외</b> — {@code channel='test'} 면 SELECT 가 0행이라 아무것도 안 들어간다</li>
     *   <li><b>fallback 제외</b> — 같은 방식으로 0행이 된다</li>
     *   <li><b>원자성</b> — 호출부가 답변 저장과 같은 트랜잭션이라
     *       "답변은 남았는데 계량이 안 된" 상태가 존재할 수 없다</li>
     * </ol>
     *
     * <p>🔴 <b>두 제외 조건을 모두 SQL 안에 둔 것이 핵심이다.</b> 호출부에
     * {@code if (isFallback) return;} 을 두고 채널만 여기서 거르면 <b>과금 정책이
     * Java 와 SQL 두 곳으로 나뉜다.</b> 규칙이 두 곳에 있으면 한쪽만 고쳐진다.
     * <b>"무엇이 과금되는가" 를 알고 싶으면 이 문장 하나만 읽으면 된다.</b>
     *
     * @return 삽입된 행 수. 과금 대상이 아니면 0 이다(정상이며 오류가 아니다)
     */
    @Modifying
    @Query(value = """
            INSERT INTO usage_events (user_id, bot_id, kind, source_ref, occurred_at)
            SELECT b.user_id, c.bot_id, 'chat_answer', :messageId, now()
              FROM conversations c
              JOIN bots b ON b.id = c.bot_id
             WHERE c.id = :conversationId
               AND c.channel = 'widget'
               AND :isFallback = false
            """, nativeQuery = true)
    int recordChatAnswer(@Param("messageId") UUID messageId,
                         @Param("conversationId") UUID conversationId,
                         @Param("isFallback") boolean isFallback);
}
```

> ⚠️ **`:isFallback` 에서 타입 추론 오류(`could not determine data type of parameter`)가 나면** `AND CAST(:isFallback AS boolean) = false` 로 바꾼다. Postgres 가 파라미터만으로 타입을 못 정하는 경우가 있다. **테스트로 확인하고, 바꿨다면 그 사실을 보고에 적는다.**

- [ ] **Step 7: `ChatTurnStore.saveAnswer` 에 한 줄을 얹는다**

필드에 리포지토리를 추가하고(`@RequiredArgsConstructor` 가 생성자를 만들어준다), `saveAnswer` 마지막에 호출을 넣는다.

```java
    private final UsageEventRepository usageEventRepository;
```

```java
    @Transactional
    public UUID saveAnswer(UUID conversationId, String content, String sourcesJson,
                           boolean isFallback, Integer latencyMs) {
        Conversation conversation = conversationRepository.getReferenceById(conversationId);
        Message answer = messageRepository.save(
                Message.createAssistantMessage(conversation, content, sourcesJson, isFallback, latencyMs));

        // 🔴 과금 계량. <같은 트랜잭션>이라 "답변은 남았는데 계량이 안 된" 상태가 생길 수 없다.
        //    무엇이 과금 대상인지는 전부 이 쿼리 안에 있다(위젯만 · fallback 제외).
        //    여기에 if 를 두지 않는 이유는 정책이 두 곳으로 나뉘는 것을 막기 위해서다.
        usageEventRepository.recordChatAnswer(answer.getId(), conversationId, isFallback);

        return answer.getId();
    }
```

> ⚠️ `messageRepository.save` 뒤에 계량이 와야 한다. `source_ref` 에 넣을 메시지 id 가 저장 후에야 정해지기 때문이다. **JPA 가 INSERT 를 미루면 네이티브 쿼리 시점에 그 행이 아직 없을 수 있다** — 그래도 `usage_events` 는 `messages` 를 FK 로 걸지 않으므로 실패하지 않는다. 만약 순서 문제로 테스트가 깨지면 `messageRepository.saveAndFlush(...)` 로 바꾼다.

- [ ] **Step 8: 테스트를 돌려 통과를 확인한다**

```bash
cd api && ./gradlew test --tests 'UsageIntegrationTest'
```

Expected: PASS (4건)

- [ ] **Step 9: 전체 테스트를 돌린다**

```bash
cd api && ./gradlew test
```

Expected: PASS. `ChatTurnStore` 를 건드렸으므로 `ChatIntegrationTest`·`WidgetIntegrationTest` 가 함께 확인된다.

- [ ] **Step 10: 커밋한다**

```bash
git add api/src/main/resources/db/migration/V5__usage_events.sql \
        api/src/main/java/com/alldap/api/domain/usage/ \
        api/src/main/java/com/alldap/api/domain/chat/service/ChatTurnStore.java \
        api/src/test/java/com/alldap/api/domain/usage/UsageIntegrationTest.java
git commit -m "$(cat <<'EOF'
feat: 과금 대상 답변을 usage_events 원장에 기록한다

/pricing 이 "답변 수로 과금하고 fallback 은 세지 않는다" 고 이미 약속해뒀는데
스키마에 계량 개념이 하나도 없었다.

조회 시 집계가 아니라 append-only 원장으로 둔 이유는 둘이다.
① 봇을 지우면 conversations·messages 가 CASCADE 로 사라져 그 달 청구 근거가 없어진다
② 정책을 바꾸면 지난달 청구서 숫자까지 함께 바뀐다
그리고 그 문은 한 방향이다 — 지워진 봇의 대화는 소급할 수 없다.

과금 정책(위젯만·fallback 제외)을 전부 SQL 한 문장에 두었다.
호출부에 if 를 두면 정책이 Java 와 SQL 로 나뉘고 한쪽만 고쳐진다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: 평가 실행 메꾸기와 조회 API

**Files:**
- Modify: `api/src/main/java/com/alldap/api/domain/usage/repository/UsageEventRepository.java`
- Create: `api/src/main/java/com/alldap/api/domain/usage/service/UsageService.java`
- Create: `api/src/main/java/com/alldap/api/domain/usage/dto/UsageResponse.java`
- Create: `api/src/main/java/com/alldap/api/domain/usage/controller/UsageController.java`
- Test: `api/src/test/java/com/alldap/api/domain/usage/UsageIntegrationTest.java`

**Interfaces:**
- Consumes: `UsageEvent.KIND_CHAT_ANSWER`, `UsageEvent.KIND_EVAL_RUN`, `UsageEventRepository.recordChatAnswer(...)` (Task 1)
- Produces:
  - `UsageService.findUsage(UUID userId, String month)` → `UsageResponse`
  - `UsageResponse(String month, long chatAnswers, long evalRuns, OffsetDateTime periodStart, OffsetDateTime periodEnd)`
  - `GET /api/usage?month=YYYY-MM` — Task 3(프론트)이 이 응답 모양에 의존한다

---

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`UsageIntegrationTest` 에 4건을 추가한다. 보조 메서드 `insertEvalRun` 과 `usage(...)` 도 함께 넣는다.

```java
    @Test
    @DisplayName("[과금] completed 평가 실행만 센다 (partial·failed 는 측정이 안 된 것이다)")
    void completed_평가실행만_센다() {
        insertEvalRun(botId, "completed");
        insertEvalRun(botId, "partial");
        insertEvalRun(botId, "failed");

        assertThat(usage(ownerToken, null).json().path("evalRuns").asInt()).isEqualTo(1);
    }

    @Test
    @DisplayName("[과금] 사용량을 여러 번 조회해도 평가 실행이 중복으로 세어지지 않는다")
    void 메꾸기는_멱등하다() {
        insertEvalRun(botId, "completed");

        for (int i = 0; i < 3; i++) {
            assertThat(usage(ownerToken, null).json().path("evalRuns").asInt()).isEqualTo(1);
        }
        // DB 로도 확인한다 — 응답이 1 이어도 행이 3개면 다음 달 청구가 틀어진다
        assertThat(countUsage(userId, "eval_run")).isEqualTo(1);
    }

    @Test
    @DisplayName("[보안] 남의 계정 사용량이 내 숫자에 섞이지 않는다")
    void 계정_격리() {
        aiService.enqueue(200, 정상응답);
        widgetChat(publicKey, "환불 규정이 어떻게 되나요?");
        insertEvalRun(botId, "completed");

        String 침입자 = signup("intruder@example.com");

        JsonNode 남의것 = usage(침입자, null).json();
        assertThat(남의것.path("chatAnswers").asInt()).isZero();
        assertThat(남의것.path("evalRuns").asInt()).isZero();
    }

    @Test
    @DisplayName("[기간] 9월 1일 00:00 KST 를 경계로 8월분과 9월분이 갈린다")
    void 기간_경계는_KST_다() {
        // 2026-08-31 23:59:59 KST = 2026-08-31T14:59:59Z
        insertUsageAt(userId, "chat_answer", Instant.parse("2026-08-31T14:59:59Z"));
        // 2026-09-01 00:00:00 KST = 2026-08-31T15:00:00Z
        insertUsageAt(userId, "chat_answer", Instant.parse("2026-08-31T15:00:00Z"));

        assertThat(usage(ownerToken, "2026-08").json().path("chatAnswers").asInt()).isEqualTo(1);
        assertThat(usage(ownerToken, "2026-09").json().path("chatAnswers").asInt()).isEqualTo(1);
    }

    // ── 테스트 보조 (추가) ────────────────────────────────────────────────

    /** eval_runs 는 Python 소유 테이블이라 테스트에서 직접 넣는다 */
    private void insertEvalRun(UUID botId, String status) {
        jdbcTemplate.update(
                "INSERT INTO eval_runs (bot_id, status, created_at) VALUES (?, ?, now())",
                botId, status);
    }

    /** 기간 경계 검증용. 사건 시각을 직접 정해야 하므로 원장에 바로 넣는다 */
    private void insertUsageAt(UUID userId, String kind, Instant occurredAt) {
        jdbcTemplate.update("""
                INSERT INTO usage_events (user_id, bot_id, kind, source_ref, occurred_at)
                VALUES (?, NULL, ?, gen_random_uuid(), ?)""",
                userId, kind, Timestamp.from(occurredAt));
    }

    private Response usage(String token, String month) {
        String uri = month == null ? "/api/usage" : "/api/usage?month=" + month;
        return request(HttpMethod.GET, uri, token, null);
    }
```

> ⚠️ `request(...)` 는 `WidgetIntegrationTest` 에서 본문을 항상 붙이는 모양이다. GET 에 본문이 없어야 하므로, 그 파일의 `request` 가 `body == null` 을 처리하지 않으면 **처리하도록 이 테스트 파일 안의 사본을 고친다**(다른 테스트 파일은 건드리지 않는다).

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

```bash
cd api && ./gradlew test --tests 'UsageIntegrationTest'
```

Expected: 새 4건 FAIL — `/api/usage` 가 없어 401 또는 404 다.

- [ ] **Step 3: 리포지토리에 메꾸기와 집계를 더한다**

`UsageEventRepository` 에 추가한다.

```java
    /**
     * 완료된 평가 실행을 원장에 <메꾼다>. 이미 있는 것은 건너뛴다.
     *
     * <p><b>왜 메꾸는가 — 기록 시점을 우리가 정할 수 없기 때문이다.</b>
     * 평가 실행이 끝나는 것은 <b>Python 이 안다</b>({@code eval_runs.status} 를 Python 이 갱신한다).
     * 그런데 과금은 Spring 소유다. Python 이 {@code usage_events} 에 쓰면
     * 테이블 소유권 원칙이 깨진다(AGENTS.md 소유권 표).
     *
     * <p><b>왜 폴링에 얹지 않는가.</b> 화면이 실행 상태를 폴링하니 거기서 기록할 수도 있지만,
     * 그러면 <b>아무도 대시보드를 안 열면 계량이 안 된다.</b> 조회 직전에 한 번 도는 쪽이 안전하다.
     *
     * <p>🔴 {@code occurred_at} 이 {@code r.created_at} 인 것이 중요하다. <b>메꾼 시각이 아니라
     * 실행이 시작된 시각</b>이 청구 기간을 가른다. 8월 31일에 시작한 실행을 9월에 메꿨다고
     * 9월분으로 청구하면 안 된다.
     *
     * <p>{@code ON CONFLICT DO NOTHING} 이 멱등성의 전부다 — 몇 번을 돌려도 결과가 같다.
     */
    @Modifying
    @Query(value = """
            INSERT INTO usage_events (user_id, bot_id, kind, source_ref, occurred_at)
            SELECT b.user_id, r.bot_id, 'eval_run', r.id, r.created_at
              FROM eval_runs r
              JOIN bots b ON b.id = r.bot_id
             WHERE b.user_id = :userId
               AND r.status = 'completed'
            ON CONFLICT (kind, source_ref) DO NOTHING
            """, nativeQuery = true)
    int backfillEvalRuns(@Param("userId") UUID userId);

    /**
     * 기간 안의 사건 수. <b>경계는 왼쪽 포함 · 오른쪽 제외</b>({@code >= from}, {@code < to})다.
     * 양쪽을 포함하면 8월 마지막 순간과 9월 첫 순간이 <b>양쪽 달에 모두</b> 세어진다.
     */
    @Query("""
            SELECT count(e) FROM UsageEvent e
             WHERE e.userId = :userId
               AND e.kind = :kind
               AND e.occurredAt >= :from
               AND e.occurredAt < :to
            """)
    long countInPeriod(@Param("userId") UUID userId,
                       @Param("kind") String kind,
                       @Param("from") Instant from,
                       @Param("to") Instant to);
```

- [ ] **Step 4: 응답 DTO 를 만든다**

`api/src/main/java/com/alldap/api/domain/usage/dto/UsageResponse.java`:

```java
package com.alldap.api.domain.usage.dto;

import java.time.OffsetDateTime;

/**
 * 한 계정의 한 달 사용량.
 *
 * <p><b>금액이 없다.</b> 이 단계는 개수만 센다 — 단가·플랜·포함량·초과 계산은 다음 조각이다.
 * {@code /pricing} 도 아직 "금액이 아직 없다" 고 말하고 있어, 여기서만 금액이 있는 척하면
 * 화면끼리 거짓말을 하게 된다.
 *
 * <p>기간을 함께 내려주는 이유: 화면이 "9월"을 어떻게 해석할지 스스로 정하면
 * 서버와 어긋난다(특히 시간대). <b>경계를 서버가 정해서 그대로 보여주게 한다.</b>
 *
 * @param chatAnswers 위젯에서 실제로 만들어진 답변 수(fallback·테스트 채팅 제외)
 * @param evalRuns    완료된 품질 평가 실행 수(partial·failed 제외)
 */
public record UsageResponse(
        String month,
        long chatAnswers,
        long evalRuns,
        OffsetDateTime periodStart,
        OffsetDateTime periodEnd
) {
}
```

- [ ] **Step 5: 서비스를 만든다**

`api/src/main/java/com/alldap/api/domain/usage/service/UsageService.java`:

```java
package com.alldap.api.domain.usage.service;

import com.alldap.api.domain.usage.dto.UsageResponse;
import com.alldap.api.domain.usage.entity.UsageEvent;
import com.alldap.api.domain.usage.repository.UsageEventRepository;
import com.alldap.api.global.exception.ApiException;
import com.alldap.api.global.exception.ErrorCode;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.DateTimeException;
import java.time.Instant;
import java.time.YearMonth;
import java.time.ZoneId;
import java.time.format.DateTimeParseException;
import java.util.UUID;

/**
 * 사용량 조회. <b>계정 단위</b>다 — 봇이 아니라 봇의 주인이 청구 대상이다.
 *
 * <p><b>기간 경계를 SQL 이 아니라 여기서 계산하는 이유.</b> 문자열을 이어붙여 날짜를 만드는
 * SQL 은 읽기 어렵고 형변환 오류가 런타임에만 드러난다. 자바에서 계산하면 그 계산만
 * 따로 검증할 수 있다. 저장은 여전히 {@code TIMESTAMPTZ} 이므로 동작은 같다.
 */
@Service
@RequiredArgsConstructor
public class UsageService {

    /**
     * 청구 기간은 <b>한국 시간 달력 월</b>이다. 국내 서비스이고 청구서를 읽는 사람이 한국에 있다.
     *
     * <p>⚠️ {@code occurred_at} 이 {@code TIMESTAMPTZ}(UTC 저장)라 경계만 KST 로 잡으면 된다.
     * 컬럼을 {@code TIMESTAMP} 로 뒀다면 이 계산이 <b>조용히 틀린다</b> —
     * 9월 1일 오전 8시 KST 사건이 8월분으로 세어진다.
     */
    private static final ZoneId BILLING_ZONE = ZoneId.of("Asia/Seoul");

    private final UsageEventRepository usageEventRepository;

    /**
     * @param month {@code "YYYY-MM"} 또는 null(이번 달)
     */
    @Transactional
    public UsageResponse findUsage(UUID userId, String month) {
        YearMonth target = parseMonth(month);

        // 🔴 세기 <전에> 메꾼다. 순서가 반대면 방금 끝난 평가 실행이 다음 조회까지 안 보인다.
        usageEventRepository.backfillEvalRuns(userId);

        Instant from = target.atDay(1).atStartOfDay(BILLING_ZONE).toInstant();
        Instant to = target.plusMonths(1).atDay(1).atStartOfDay(BILLING_ZONE).toInstant();

        return new UsageResponse(
                target.toString(),
                usageEventRepository.countInPeriod(userId, UsageEvent.KIND_CHAT_ANSWER, from, to),
                usageEventRepository.countInPeriod(userId, UsageEvent.KIND_EVAL_RUN, from, to),
                from.atZone(BILLING_ZONE).toOffsetDateTime(),
                to.atZone(BILLING_ZONE).toOffsetDateTime());
    }

    private YearMonth parseMonth(String month) {
        if (month == null || month.isBlank()) {
            return YearMonth.now(BILLING_ZONE);
        }
        try {
            return YearMonth.parse(month);
        } catch (DateTimeParseException | DateTimeException e) {
            throw new ApiException(ErrorCode.INVALID_INPUT,
                    "조회할 달의 형식이 올바르지 않습니다. 2026-09 처럼 YYYY-MM 으로 보내주세요.");
        }
    }
}
```

> ⚠️ `ErrorCode.INVALID_INPUT` 이 없으면 **`ErrorCode` 를 열어 400 계열로 이미 있는 값을 쓴다.** 새 `ErrorCode` 를 만들지 않는다 — 이 작업에 필요한 것은 "입력이 잘못됐다" 하나뿐이고, 기존 값으로 표현된다. 어떤 값을 썼는지 보고에 적는다.

- [ ] **Step 6: 컨트롤러를 만든다**

`api/src/main/java/com/alldap/api/domain/usage/controller/UsageController.java`:

```java
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
 * <p>{@code SecurityConfig} 를 고칠 필요가 없다 — {@code /api/auth/**} 와 {@code /api/w/**} 만
 * 공개이고 나머지 {@code /api/**} 는 이미 인증을 요구한다.
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
```

- [ ] **Step 7: 테스트를 돌려 통과를 확인한다**

```bash
cd api && ./gradlew test --tests 'UsageIntegrationTest'
```

Expected: PASS (8건)

- [ ] **Step 8: 전체 테스트를 돌린다**

```bash
cd api && ./gradlew test
```

Expected: PASS

- [ ] **Step 9: 커밋한다**

```bash
git add api/src/main/java/com/alldap/api/domain/usage/ \
        api/src/test/java/com/alldap/api/domain/usage/UsageIntegrationTest.java
git commit -m "$(cat <<'EOF'
feat: 사용량 조회 API 와 평가 실행 메꾸기

평가 실행이 끝나는 것은 Python 이 알지만 과금은 Spring 소유라, Python 이
usage_events 에 쓰면 테이블 소유권이 깨진다. 그래서 조회 직전에 Spring 이 메꾼다.
ON CONFLICT DO NOTHING 으로 멱등하고, occurred_at 은 메꾼 시각이 아니라
실행이 시작된 시각이라 청구 기간이 밀리지 않는다.

기간 경계는 한국 시간 달력 월이고 왼쪽 포함·오른쪽 제외다.
양쪽을 포함하면 8월 마지막 순간이 두 달에 모두 세어진다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: 대시보드 사용량 카드

**Files:**
- Modify: `web/lib/types.ts`
- Modify: `web/lib/api.ts`
- Modify: `web/app/(dashboard)/dashboard/page.tsx`

**Interfaces:**
- Consumes: `GET /api/usage` → `{ month, chatAnswers, evalRuns, periodStart, periodEnd }` (Task 2)
- Produces: 없음. 이 Task 에 의존하는 후속 Task 는 이 계획에 없다

> ⚠️ **Next.js 16.2.12 / React 19.2.4 는 대부분의 모델이 학습한 버전보다 최신이다.** API·관례가 달라졌을 수 있으니, 확신이 안 서면 **`web/node_modules/next/dist/docs/` 를 먼저 읽는다.** 기억으로 구버전 문법을 쓰지 않는다.

---

- [ ] **Step 1: 타입을 더한다**

`web/lib/types.ts` 끝에 추가한다.

```ts
/**
 * 한 계정의 한 달 사용량. `GET /api/usage` 의 응답.
 *
 * 🔴 금액이 없다 — 이 단계는 개수만 센다. 단가·플랜·초과 계산은 다음 조각이다.
 *
 * `interface` 로 둔 이유: 백엔드 응답 <객체의 모양>을 그리는 타입이고,
 * 이 파일의 다른 응답 타입(Bot·EvalRun 등)이 전부 interface 라 맞췄다.
 * (합집합·별칭이 필요할 때만 `type` 을 쓴다 — 예: 위 EvalRunStatus)
 *
 * 필드 이름이 camelCase 인 것은 Spring 이 변환해 내려주기 때문이다.
 * Python 은 snake_case(`is_fallback`)를 쓰지만 프론트까지 오지 않는다.
 */
export interface Usage {
  /** "2026-09" */
  month: string;
  /** 위젯에서 실제로 만들어진 답변 수 (fallback·관리자 테스트 채팅 제외) */
  chatAnswers: number;
  /** 완료된 품질 평가 실행 수 (partial·failed 제외) */
  evalRuns: number;
  /** 서버가 정한 기간 경계(KST). 화면이 "9월"을 제멋대로 해석하지 않게 한다 */
  periodStart: string;
  periodEnd: string;
}
```

- [ ] **Step 2: API 클라이언트를 더한다**

`web/lib/api.ts` 의 `evaluation` 블록 **뒤**, 같은 들여쓰기로 추가한다. `Usage` 를 import 목록에 넣는다.

```ts
  /**
   * 사용량 (요금제 연동 1조각)
   *
   * ✅ 구현되어 동작한다. 추정이 아니다.
   * botId 를 받지 않는 이유: 청구 대상이 <계정>이라 서버가 토큰의 주인으로 조회한다.
   */
  usage: {
    /** @param month "2026-09" 형식. 생략하면 이번 달(한국 시간 기준) */
    current: (month?: string) =>
      request<Usage>(month ? `/api/usage?month=${month}` : "/api/usage"),
  },
```

- [ ] **Step 3: 대시보드에 카드를 붙인다**

`web/app/(dashboard)/dashboard/page.tsx` 를 고친다. 이 파일은 이미 `"use client"` 이고 `useState`/`useEffect`/`useCallback` 로 봇 목록을 불러오는 구조다. **그 구조를 그대로 따른다.**

`Usage` 를 타입 import 에 추가한다(이 파일이 이미 `web/lib/types.ts` 에서 무엇을 가져오는지 먼저 보고 그 줄에 얹는다). 그다음 상태와 로딩 함수를 추가한다.

```tsx
  const [usage, setUsage] = useState<Usage | null>(null);

  /**
   * 사용량을 불러온다.
   *
   * 왜 클라이언트에서 가져오는가: 인증 토큰이 <브라우저에만> 있어서 서버 컴포넌트가
   * 이 요청을 대신 보낼 수 없다. 이 파일이 이미 "use client" 인 이유와 같고,
   * 바로 위 봇 목록도 같은 이유로 여기서 부른다.
   *
   * useCallback 으로 감싸는 이유: 아래 useEffect 의 의존성 배열에 이 함수를 넣어야 하는데,
   * 매 렌더마다 새 함수가 만들어지면 effect 가 매번 다시 돌아 요청이 무한히 나간다.
   *
   * 실패해도 화면을 막지 않는다 — 사용량은 <보조 정보>다. 여기서 에러를 띄우면
   * 봇 목록이라는 주 기능이 부수 기능 때문에 가려진다.
   */
  const loadUsage = useCallback(async () => {
    try {
      setUsage(await api.usage.current());
    } catch {
      setUsage(null);
    }
  }, []);

  useEffect(() => {
    void loadUsage();
  }, [loadUsage]);
```

봇 목록 위에 카드를 렌더한다.

⚠️ **클래스 이름은 이 계획이 지정하지 않는다.** 같은 파일의 봇 목록 `<section>` 이 쓰는 클래스를 먼저 읽고 **그 규칙을 그대로 따른다.** 이 저장소는 디자인 시스템을 `web/app/globals.css` 에 두고 있어, 여기서 새 이름을 지어내면 화면만 어긋난다.

```tsx
      {usage && (
        <section aria-labelledby="usage-heading">
          <h2 id="usage-heading">이번 달 사용량 ({usage.month})</h2>
          <dl>
            <div>
              <dt>답변</dt>
              <dd>{usage.chatAnswers.toLocaleString("ko-KR")}건</dd>
            </div>
            <div>
              <dt>품질 평가 실행</dt>
              <dd>{usage.evalRuns.toLocaleString("ko-KR")}회</dd>
            </div>
          </dl>
          {/* 🔴 /pricing 이 "금액이 아직 없다" 고 말하고 있다.
              여기서만 금액이 있는 척하면 화면끼리 거짓말을 하게 된다. */}
          <p>답하지 못한 질문과 관리자 테스트 채팅은 세지 않습니다. 금액은 아직 없습니다.</p>
        </section>
      )}
```

- [ ] **Step 4: 타입 검사와 린트를 돌린다**

```bash
cd web && npx tsc --noEmit && npm run lint
```

Expected: 둘 다 오류 없음

- [ ] **Step 5: 브라우저로 확인한다**

백엔드 3-스택을 띄우고 실제로 본다. **"타입이 통과했다"는 화면 확인이 아니다.**

```bash
docker compose up -d
cd api && ./gradlew bootRun     # 별도 터미널
cd ai-service && .venv/bin/uvicorn app.main:app --port 8001   # 별도 터미널
cd web && npm run dev
```

가입 → 봇 생성 → 위젯 또는 테스트 채팅으로 답변 1건 → `/dashboard` 에서 숫자가 오르는지 본다.
**관리자 테스트 채팅으로는 숫자가 안 올라야 한다** — 그게 이 기능의 핵심 정책이다. 화면 캡처를 PR 에 붙인다.

- [ ] **Step 6: 커밋하고 PR 을 연다**

```bash
git add web/lib/types.ts web/lib/api.ts "web/app/(dashboard)/dashboard/page.tsx"
git commit -m "$(cat <<'EOF'
feat: 대시보드에 이번 달 사용량 카드를 붙였다

계정 단위 정보라 봇 화면이 아니라 대시보드에 뒀다.
금액은 표시하지 않는다 — /pricing 이 "금액이 아직 없다" 고 말하고 있어
여기서만 있는 척하면 화면끼리 어긋난다.

사용량 조회가 실패해도 화면을 막지 않는다. 보조 정보가 주 기능(봇 목록)을
가리면 안 된다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
git push -u origin feat/usage-metering
gh pr create --title "feat: 사용량 계량 — 과금 대상 사건을 원장에 쌓고 대시보드에 보여준다" --body "$(cat <<'EOF'
## 무엇을 왜 바꿨나요

`/pricing` 은 이미 과금 방식을 **약속**해뒀습니다.

> **답변 수** — 답하지 못한 질문은 세지 않습니다.

그런데 **지금 아무것도 세지 않습니다.** 스키마에 `plan`·`quota`·`usage` 개념이 하나도 없었습니다.
셀 줄 모르는 상태에서 결제를 먼저 붙이면 청구할 금액을 계산할 수 없습니다.

이 PR 은 요금제 연동 4조각(계량 → 플랜 → 결제 수단 → 청구) 중 **1번**입니다.
**금액·플랜·결제는 여기 없습니다.**

## 어떻게 해결했나요

`usage_events` 를 **append-only 원장**으로 뒀습니다. 조회 시 집계가 아닌 이유가 둘입니다.

1. 봇을 지우면 `conversations`·`messages` 가 CASCADE 로 사라져 **그 달 청구 근거가 없어집니다.**
2. 정책을 바꾸면 **지난달 청구서 숫자까지 함께 바뀝니다.**

그리고 이 문은 **한 방향**입니다 — 나중에 원장이 필요해져도 지워진 봇의 대화는 소급할 수 없습니다.

**과금 정책 전체가 SQL 한 문장 안에 있습니다** (위젯만·fallback 제외·청구 대상 해결·원자성).
호출부에 `if` 를 두면 정책이 Java 와 SQL 로 나뉘고, 규칙이 두 곳에 있으면 한쪽만 고쳐집니다.

평가 실행은 **Spring 이 조회 직전에 멱등하게 메꿉니다.** 끝나는 것을 아는 쪽은 Python 인데
과금은 Spring 소유라, Python 이 쓰면 테이블 소유권이 깨집니다.

<!-- 실제 실행 결과를 붙일 것: Task1 Step3 의 FAIL, Task2 Step7 의 PASS(8건),
     Task1 Step9 의 전체 테스트, Task3 Step4 의 tsc·lint, Step5 의 화면 캡처 -->

## 한계 & 트레이드오프

- **평가 실행 메꾸기는 원자적이지 않습니다.** 봇이 지워지면 아직 안 메꾼 실행은 사라집니다.
  채팅 답변과 달리 같은 트랜잭션이 아닙니다. 창을 좁히는 것은 4번 조각(청구)의 마감이 합니다.
- **`bot_id` 에 참조 무결성이 없습니다.** 봇이 지워지면 화면에 "삭제된 봇" 으로 남습니다.
  의도한 것입니다 — 무결성을 걸면 청구 근거가 삭제에 딸려 사라집니다.
- **과거 데이터는 세어지지 않습니다.** 이 기능 이전의 답변에는 이벤트가 없습니다.
  평가 실행만 메꾸기가 과거 것까지 집어서 **둘의 시작점이 다릅니다.**
- **금액이 없습니다.** 개수만 셉니다.
- `user_id` 에 `ON DELETE CASCADE` 를 걸지 않았습니다. 이 저장소의 다른 테이블과 반대인데
  의도한 것입니다 — 계정 삭제 기능을 만들 때 "청구가 안 끝난 계정은 못 지운다" 를 DB 가 강제합니다.

## 검토한 대안

- **조회 시 집계(`messages` 를 그때그때 COUNT)** — 새 테이블이 0개지만 위 두 가지가 깨지고,
  그 문이 한 방향입니다.
- **월별 스냅샷 테이블** — 4번 조각에서 필요하지만 지금은 이릅니다. 마감할 달이 아직 없습니다.
- **Python 이 평가 실행을 직접 기록** — 테이블 소유권 원칙을 깹니다.
- **폴링에 메꾸기를 얹기** — 아무도 대시보드를 안 열면 계량이 안 됩니다.
- **관리자 테스트 채팅도 과금** — LLM 비용은 똑같이 들지만, 고객이 <품질을 확인하려고> 쓰는
  기능입니다. 여기 과금하면 확인을 덜 하게 되고 품질이 나쁜 봇이 방치됩니다.
  `/pricing` 의 "억지로 답하게 만들 이유를 만들지 않는다" 와 같은 논리입니다.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## 멈춰야 하는 지점 — 사람에게 보고할 것

| 조건 | 왜 |
|---|---|
| `ai-service/` 나 `widget/` 을 고쳐야 할 것 같으면 | 이 계획의 범위를 벗어난다. 설계가 틀렸다는 신호다 |
| `V1`~`V4` 를 고쳐야 할 것 같으면 | Flyway 체크섬이 깨져 기동이 막힌다. **절대 고치지 않는다** |
| 새 `ErrorCode` 가 필요해 보이면 | 기존 400 계열로 표현되는지 먼저 확인한다 |
| 기존 테스트가 깨지면 | `ChatTurnStore` 는 채팅·위젯 전 경로가 지나간다 |
| 기동이 `ddl-auto=validate` 로 실패하면 | 엔티티와 `V5` 가 어긋난 것이다. 맞출 때까지 진행하지 않는다 |
