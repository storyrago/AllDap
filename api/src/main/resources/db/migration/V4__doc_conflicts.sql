-- 문서끼리 어긋나는 곳을 기록한다 (2026-08-05)
--
-- 왜 필요한가 — RAG 는 "문서가 진리" 라고 가정한다
--   그런데 실제 사내 문서는 서로 모순된다. 구버전 규정과 신버전이 같이 올라가 있고,
--   부서별로 다른 숫자를 적어둔다. 그러면 챗봇은 둘 중 하나를 골라 <자신 있게> 답하고,
--   관리자는 틀린 줄도 모른다. 근거를 표시해도 소용없다 — 표시된 그 근거가 틀린 쪽일 수 있다.
--
--   환각 억제(NO_ANSWER·max_distance)는 "문서에 없는 것" 을 막지만
--   "문서에 <둘 다> 있는 것" 은 못 막는다. 이 테이블이 그 빈틈을 맡는다.
--
-- 소유권: Python 이 쓰고 Spring 이 읽는다 (eval_* 과 같은 패턴).
--         AGENTS.md 의 "테이블 소유권" 표에 함께 추가할 것.

CREATE TABLE IF NOT EXISTS doc_conflicts (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  bot_id      UUID NOT NULL REFERENCES bots(id) ON DELETE CASCADE,

  -- 어긋난 두 청크. 청크가 지워지면(문서 삭제·재청킹) 이 행도 함께 사라진다.
  -- 남겨두면 "존재하지 않는 문장이 모순이라고 떠 있는" 상태가 되어 관리자가 못 고친다.
  chunk_a_id  UUID NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
  chunk_b_id  UUID NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,

  -- 판정 결과. 관리자가 <두 청크 원문을 다 읽지 않고도> 무엇이 문제인지 알 수 있어야 한다.
  topic       TEXT NOT NULL,          -- 무엇에 대한 충돌인가  예: "노트북 교체 주기"
  a_says      TEXT NOT NULL,          -- A 쪽 주장            예: "3년"
  b_says      TEXT NOT NULL,          -- B 쪽 주장            예: "4년"

  -- 후보를 고를 때 쓴 임베딩 거리. 판정 근거가 아니라 <튜닝용 기록>이다.
  -- 나중에 "임계값을 얼마로 둬야 했나" 를 데이터로 되짚으려면 남겨둬야 한다.
  distance    REAL,

  -- open    : 모순으로 판정됐고 아직 관리자가 안 봤다   ← 화면에 뜨는 것은 이것뿐
  -- ignored : 관리자가 보고 오탐이라고 표시했다. 다시 올라오면 안 된다
  -- resolved: 문서를 고쳤다
  -- clear   : 판정 결과 모순이 아니었다
  --
  -- 🔴 'clear' 를 굳이 저장하는 이유는 <비용>이다.
  --    모순인 것만 저장하면, 모순 아닌 쌍은 스캔할 때마다 다시 LLM 에 물어보게 된다.
  --    실측으로 청크 80개짜리 봇의 후보가 49쌍인데 그중 모순은 0건이었다 —
  --    즉 재스캔마다 49번을 <같은 답을 받으려고> 다시 부르는 셈이다.
  --    판정 결과는 문서가 그대로인 한 바뀌지 않으므로(temperature=0) 기록해두고 건너뛴다.
  --    문서가 바뀌면 청크가 새로 생기고, 이 행은 FK CASCADE 로 사라져 자동으로 재판정된다.
  status      VARCHAR(10) NOT NULL DEFAULT 'open',

  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 화면이 "이 봇의 open 목록" 을 부르는 것이 기본 조회다.
CREATE INDEX IF NOT EXISTS idx_conflicts_bot_status ON doc_conflicts (bot_id, status);

-- 🔴 같은 쌍을 두 번 넣지 않는다.
--   스캔을 다시 돌려도 이미 있는 쌍은 건너뛰어야 한다 — 특히 관리자가 'ignored' 로
--   치워둔 것이 재스캔마다 되살아나면 그 화면은 두 번 다시 안 보게 된다.
--   (evaluator.sample_chunks 의 NOT EXISTS 와 같은 이유다)
--
--   ⚠️ (a,b) 와 (b,a) 는 같은 쌍이다. 그래서 넣기 전에 <작은 UUID 를 a 로> 정렬한다.
--      정렬을 안 하면 순서만 뒤집힌 중복이 유니크 제약을 통과해버린다.
--      정렬 책임은 애플리케이션에 있다(conflicts.py) — 제약은 그걸 강제하는 그물이다.
CREATE UNIQUE INDEX IF NOT EXISTS uq_conflicts_pair
  ON doc_conflicts (bot_id, chunk_a_id, chunk_b_id);

COMMENT ON TABLE doc_conflicts IS
  '문서 간 사실 충돌. Python 이 임베딩으로 후보를 좁히고 judge 모델로 판정해 채운다.';
COMMENT ON COLUMN doc_conflicts.distance IS
  '후보 선별에 쓴 임베딩 거리. 판정 근거가 아니라 임계값 튜닝용 기록이다.';
COMMENT ON COLUMN doc_conflicts.status IS
  'open | ignored | resolved | clear. 화면에 뜨는 것은 open 뿐이다. '
  'clear 는 "판정해봤더니 모순 아님" 이며, 재스캔에서 같은 쌍을 다시 묻지 않으려고 남긴다.';
