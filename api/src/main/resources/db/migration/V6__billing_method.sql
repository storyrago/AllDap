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
