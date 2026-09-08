# 결제 수단 여러 장 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 계정당 카드 1장 → 최대 5장, 기본 카드 지정. API 를 `/api/billing/methods` 로 바꾸고 `/billing` 화면을 목록형으로 맞춘다.

**Architecture:** V7 로 UNIQUE 를 풀고 `is_default` + 부분 유니크 인덱스. 서비스는 기존 원칙 유지(토스 호출 있는 메서드는 `@Transactional` 없음 · 토스 먼저 우리 나중 · 소유권은 쿼리에). 기본 지정만 트랜잭션. 프론트는 목록형 최소 적응.

**Tech Stack:** Spring Boot 4.0.7 · Flyway · Testcontainers + TossStub · Next.js 16 · Tailwind v4

## Global Constraints

- 설계: `docs/superpowers/specs/2026-09-08-billing-multi-card-design.md`
- `V6__billing_method.sql` 은 수정 금지(체크섬). 변경은 `V7__billing_methods_multi.sql` 로만. `ddl-auto: validate` 유지.
- `billingKey` 평문은 응답·로그 어디에도 안 실린다. `userId` 는 `@AuthenticationPrincipal` 로만.
- 토스 호출이 있는 메서드에 `@Transactional` 금지. 소유권은 `findByIdAndUserId`. 남의 것은 404.
- 통합 테스트는 `BillingIntegrationTest` 하나에 둔다. `tossStub.reset()` 을 `@BeforeEach` 에서.
- 커밋 `<타입>: <한국어 요약>` + Co-Authored-By.

---

### Task 1: V7 · 엔티티 · 리포지토리 · ErrorCode · DTO

**Files:**
- Create: `api/src/main/resources/db/migration/V7__billing_methods_multi.sql`
- Modify: `api/.../billing/entity/BillingMethod.java` (unique 제거 · `isDefault` · `markDefault()` · `create` 인자)
- Modify: `api/.../billing/repository/BillingMethodRepository.java` (`findByUserIdOrderByCreatedAtAsc` · `findByIdAndUserId` · `countByUserId` · `clearDefault`)
- Modify: `api/.../global/exception/ErrorCode.java` (`BILLING_METHOD_CONFLICT` · `BILLING_METHOD_LIMIT_EXCEEDED` · `BILLING_DEFAULT_METHOD_IN_USE`)
- Rename: `dto/BillingMethodResponse.java` → `dto/BillingMethodsResponse.java` (`customerKey` · `List<Card> methods`; `Card` 에 `id`·`isDefault`)

- [ ] V7 작성 (제약 이름 `billing_methods_user_id_key` — 로컬 DB `\d` 로 확인함)
- [ ] 엔티티·리포지토리·ErrorCode·DTO 수정
- [ ] `cd api && ./gradlew compileJava` — 서비스·컨트롤러가 깨지므로 Task 2 와 함께 컴파일한다

### Task 2: 서비스 · 컨트롤러

**Files:**
- Modify: `api/.../billing/service/BillingService.java` — `find` 목록 · `register` (5장 검사 → 토스 → 저장, 첫 카드 기본) · `delete(userId, id)` (기본+타카드 409 → 복호화 → 토스 → 삭제) · `setDefault(userId, id)` `@Transactional`
- Modify: `api/.../billing/controller/BillingController.java` — `/api/billing/methods` · `DELETE /{id}` · `PUT /{id}/default`

- [ ] 구현
- [ ] `cd api && ./gradlew compileJava` 통과

### Task 3: 통합 테스트

**Files:** Modify `api/src/test/java/com/alldap/api/domain/billing/BillingIntegrationTest.java`

- [ ] 기존 18건을 새 경로·응답 모양(`methods[0]`)에 맞춘다. `이미_등록된_카드가_있으면_409` 는 삭제(두 장이 정상이 됐다).
- [ ] 추가 6건: `첫_카드는_자동으로_기본이다` · `기본_지정하면_정확히_하나만_기본이다` · `기본_카드는_다른_카드가_있으면_삭제_거부` · `마지막_한_장은_기본이어도_삭제된다` · `남의_카드는_404_이고_토스에_안_간다` · `여섯_장째는_409_이고_토스에_안_간다`
- [ ] `cd api && ./gradlew test --tests 'com.alldap.api.domain.billing.*'` 전부 통과, 이어서 `./gradlew test` 전체
- [ ] 커밋 `feat: 결제 수단을 계정당 여러 장 등록하고 기본 카드를 지정한다 (V7)`

### Task 4: 프론트 최소 적응

**Files:** Modify `web/lib/types.ts` · `web/lib/api.ts` · `web/app/(dashboard)/billing/page.tsx`

- [ ] `BillingCard` 에 `id`·`isDefault`, `BillingMethodsResponse { customerKey, methods }`
- [ ] `api.billing`: `listBillingMethods` · `registerBillingMethod` · `deleteBillingMethod(id)` · `setDefaultBillingMethod(id)`
- [ ] `/billing`: 카드 목록(기본 배지 · 기본으로 · 삭제[인라인 확인]) · 카드 추가 버튼(5장이면 비활성). 착지 로직 그대로.
- [ ] `cd web && npx tsc --noEmit && npm run lint`
- [ ] 커밋 `feat: 결제 수단 화면을 카드 목록형으로 바꾼다`

### Task 5: 브라우저 종단 (토스 테스트 키)

- [ ] Spring 재기동(새 코드) · dev 서버 · `/billing` 에서 카드 2장 등록 → 기본 변경 → 기본 카드 삭제 거부 확인 → 다른 카드 삭제 → 마지막 카드 삭제
- [ ] DB `SELECT user_id, is_default FROM billing_methods` 로 불변식 확인

### Task 6: 문서 · PR

- [ ] `docs/DEPLOY.md` 결제 검증 절차 경로 · `AGENTS.md` 결제 행 · `decisions.md` 항목(is_default 선택 · 삭제 거부 · 5장)
- [ ] 커밋 `docs: ...` · push · `gh pr create`
