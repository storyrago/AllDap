-- V7: 결제 수단을 계정당 여러 장으로 (2026-09-08)
-- 설계: docs/superpowers/specs/2026-09-08-billing-multi-card-design.md
-- ⚠️ V6 는 고치지 않는다(Flyway 체크섬). 여기서 풀고 더한다.

-- ① 계정당 1장 제약을 푼다.
--    이름은 V6 의 인라인 UNIQUE 가 PostgreSQL 에서 자동으로 받은 것이다 — 로컬 DB `\d billing_methods` 로 확인했다.
ALTER TABLE billing_methods DROP CONSTRAINT billing_methods_user_id_key;

-- ② 기본 카드(청구에 쓰는 카드) 플래그. 기존 행은 계정당 1장이었으므로 전부 기본이다.
ALTER TABLE billing_methods ADD COLUMN is_default BOOLEAN NOT NULL DEFAULT false;
UPDATE billing_methods SET is_default = true;

-- ③ "계정당 기본 카드는 최대 1장" 을 DB 가 보장한다.
--    부분 유니크 인덱스라 is_default = false 인 행은 몇 개든 된다. 앱 검사는 친절한 안내용이고
--    마지막 방어선은 이 인덱스다 (V6 의 UNIQUE(user_id) 가 하던 역할과 같다).
CREATE UNIQUE INDEX uq_billing_methods_default ON billing_methods (user_id) WHERE is_default;

-- ④ UNIQUE 를 지우면 그 인덱스도 사라진다. 목록 조회·소유권 확인이 전부 user_id 로 걸리므로 일반 인덱스를 둔다.
CREATE INDEX idx_billing_methods_user_id ON billing_methods (user_id);
