# 결제 수단 여러 장 — 설계 (묶음 B 의 1번 PR)

- **날짜**: 2026-09-08
- **출처**: 2026-09-07 배포본 테스트 피드백 "한 장이 아니라 여러 장을 등록해서 골라 쓰고 싶다"
- **위치**: `api/`(Spring) + `web/` 최소 적응. Python·위젯은 한 줄도 안 고친다
- **브랜치**: `feat/billing-multi-card`

## 묶음 B 전체와 이 문서의 자리

| PR | 내용 | 상태 |
|---|---|---|
| **B1** | **다중 카드 백엔드** — V7 · API 목록/추가/개별 삭제/기본 지정 · 프론트 최소 적응 | 🚧 **이 문서** |
| B2 | 마이페이지 `/account` · 실물 카드 모양 · 카드사 색/로고 SVG · 등록/삭제 모션 | ⬜ |
| B3 | 요금제 선택 `/account/plan` — 무료/Pro + 청구 카드 지정 (`users.plan`, V8) | ⬜ |

**다루지 않는 것**: 한도 강제 · 실제 청구 · 디자인. "골라 쓴다"는 이 PR 에서는 **기본 카드 표시**까지다 —
청구가 없으니 기본 카드로 <실제로 결제되는> 일은 아직 없다.

## 데이터 모델 — `billing_methods.is_default`

`users.billing_method_id`(사용자가 카드 하나를 가리킴) 대신 카드 쪽에 플래그를 둔다.
개념이 하나("기본 카드 = 청구에 쓰는 카드")라 결제 수단 화면과 요금제 화면이 어긋날 수 없고,
카드 삭제 때 참조를 풀 단계가 없다.

`V7__billing_methods_multi.sql`
1. `billing_methods_user_id_key`(UNIQUE) 삭제 — 실제 제약 이름은 로컬 DB `\d` 로 확인했다
2. `is_default BOOLEAN NOT NULL DEFAULT false` 추가
3. 기존 행(계정당 1장)은 전부 `true`
4. **부분 유니크 인덱스** `(user_id) WHERE is_default` — "계정당 기본 카드 최대 1장"은 DB 가 보장한다
5. `user_id` 일반 인덱스 — UNIQUE 를 지우면서 인덱스도 사라지므로

## API

| | 경로 | 응답 | 실패 |
|---|---|---|---|
| 목록 | `GET /api/billing/methods` | `{ customerKey, methods: Card[] }` | — |
| 추가 | `POST /api/billing/methods` `{ authKey, customerKey }` | 같은 목록 응답 | 5장 초과 409 · customerKey 불일치 400 · 토스 거절 400 · 토스 장애 503 |
| 삭제 | `DELETE /api/billing/methods/{id}` | 204 | 없음/남의 것 404 · 기본 카드인데 다른 카드가 남아 있으면 409 · 토스 장애 503(행 유지) |
| 기본 지정 | `PUT /api/billing/methods/{id}/default` | 같은 목록 응답 | 없음/남의 것 404 |

`Card = { id, issuerName, cardNumberMasked, registeredAt, isDefault }`. `billingKey` 필드는 여전히 없다.

**추가가 목록을 돌려주는 이유**: 프론트가 등록 직후 재조회하던 왕복이 없어지고, 화면에 보이는 카드의
출처가 응답 하나로 고정된다. **{id} 소유권**은 봇과 같다 — `findByIdAndUserId` 로 쿼리에 못박고
남의 것은 **404**(403 은 존재를 알려준다). 테스트는 "404" 가 아니라 **"토스 스텁에 요청이 안 갔다"** 를 본다.

## 규칙

1. **첫 카드는 자동 기본.** 불변식: 카드가 하나라도 있으면 기본이 정확히 하나. 이후 카드는 지정할 때만.
2. **기본 카드는 다른 카드가 남아 있으면 삭제 거부(409 `BILLING_DEFAULT_METHOD_IN_USE`).** 마지막 한 장이면 삭제된다.
   대안 "자동 승계" 기각: 토스 호출 뒤 DB 쓰기가 두 번(삭제+승계)이라 트랜잭션이 필요한데 이 서비스는 토스 호출
   때문에 `@Transactional` 을 일부러 안 붙인다. 거부는 `if` 한 줄이고 사용자에게 명시적이다.
3. **계정당 최대 5장(`BILLING_METHOD_LIMIT_EXCEEDED` 409).** 토스 발급을 부르기 <전에> 검사한다 — 발급 뒤 거부하면
   회수 불가능한 고아가 남는다. **5 는 근거 없는 상한이다.**
4. **기본 지정만 `@Transactional`.** 토스 호출이 없는 유일한 쓰기다. "이전 기본 해제(JPQL) → 새 기본 설정(더티체킹)"
   두 문장을 이 순서로. 한 문장 `SET is_default = (id = :id)` 는 부분 유니크 인덱스가 행 처리 순서에 따라
   터질 수 있다. 이미 기본이면 아무것도 안 한다 — JPQL 이 영속성 컨텍스트를 우회하므로 엔티티의 `true` 가
   낡은 값이 되어 되돌려지지 않는 버그를 피하기 위해서다.
5. **동시 첫 등록 둘**은 부분 유니크 인덱스가 하나를 거부한다(`DataIntegrityViolationException` → 409
   `BILLING_METHOD_CONFLICT`). 그때 두 번째 빌링키는 고아다 — V6 때와 같은 알려진 한계.

## 오류 코드

- `BILLING_METHOD_ALREADY_EXISTS` → **`BILLING_METHOD_CONFLICT`** 로 이름·문구 변경. 옛 문구 "카드를 바꾸려면 삭제 후 재등록"이 이제 거짓이다.
- 추가: `BILLING_METHOD_LIMIT_EXCEEDED`(409) · `BILLING_DEFAULT_METHOD_IN_USE`(409)

## 프론트 최소 적응 (이 PR 에 포함하는 이유)

`main` 은 Vercel 이 자동 배포한다. 백엔드만 바꾸면 배포된 `/billing` 이 404 로 깨진다.
`types.ts`·`api.ts` 와 `/billing` 을 목록형으로 바꾼다(카드별 삭제 · 기본으로 · 카드 추가). **디자인은 B2.**
착지 처리(`authKey` 한 번만 POST · StrictMode 가드 · 취소 코드 판정)는 그대로 둔다.

## 검증

- 통합 테스트: 기존 18건 새 경로로 + 6건 추가(첫 카드 자동 기본 · 기본 변경 시 정확히 하나 · 기본 카드 삭제 거부 ·
  마지막 한 장 삭제 허용 · 남의 카드 404 + 토스 미호출 · 5장 초과 409 + 토스 미호출)
- 프론트 `tsc`·`lint` + 브라우저: 토스 테스트 키로 두 장 등록 → 기본 변경 → 기본 카드 삭제 거부 → 다른 카드 삭제
- 문서: `docs/DEPLOY.md` 의 결제 검증 절차 경로 · `AGENTS.md` 결제 행 · `decisions.md`
