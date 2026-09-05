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
  --
  -- ON DELETE CASCADE 다 — 이 저장소의 다른 테이블과 같다.
  -- ⚠️ 처음에는 "계정을 지워도 청구 근거는 남아야 한다" 며 CASCADE 를 뺐다가 되돌렸다.
  --    ① 계정 삭제 기능이 <아직 없다>. 없는 기능을 위한 방어였다.
  --    ② 그런데 대가가 실재했다 — 통합 테스트가 전부 userRepository.deleteAll() 로 정리하고
  --       Postgres 컨테이너를 공유해서, 계량된 답변이 하나라도 있으면 FK 가 그 정리를 막아
  --       <이 기능과 무관한 테스트들이 깨졌다.>
  --    이 설계가 지키려는 것은 "계정 삭제" 가 아니라 <"봇을 지워도 청구 근거가 남는다"> 이고,
  --    그건 아래 bot_id 에 FK 를 걸지 않은 것이 담당한다. 그쪽은 그대로다.
  --    계정 삭제 시 미청구분을 어떻게 할지는 4번 조각(청구)에서 정한다.
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
