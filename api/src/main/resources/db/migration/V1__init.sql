-- AllDap 초기 스키마
-- 임베딩 차원 1536 = OpenAI text-embedding-3-small 기준.
-- 다른 모델로 바꾸면 VECTOR(n) 숫자도 반드시 함께 바꿀 것.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- gen_random_uuid()

-- ── 사용자 / 봇 (Spring이 W2부터 관리) ────────────────────────────
CREATE TABLE IF NOT EXISTS users (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email         VARCHAR(255) UNIQUE NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  name          VARCHAR(50),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bots (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id          UUID REFERENCES users(id) ON DELETE CASCADE,
  name             VARCHAR(100) NOT NULL,
  public_key       VARCHAR(32) UNIQUE NOT NULL,
  system_prompt    TEXT,
  welcome_message  TEXT NOT NULL DEFAULT '무엇을 도와드릴까요?',
  fallback_message TEXT NOT NULL DEFAULT '문서에서 답을 찾지 못했어요. 담당자에게 문의해주세요.',
  allowed_origins  TEXT[],
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── 문서 / 청크 (Python AI 서비스가 관리) ─────────────────────────
CREATE TABLE IF NOT EXISTS documents (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  bot_id        UUID NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
  filename      VARCHAR(255) NOT NULL,
  file_type     VARCHAR(10)  NOT NULL,          -- pdf/docx/hwpx/hwp/txt/md
  status        VARCHAR(20)  NOT NULL DEFAULT 'pending',
                                                -- pending/processing/ready/failed
  error_message TEXT,
  char_count    INT,
  chunk_count   INT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_documents_bot ON documents (bot_id);

CREATE TABLE IF NOT EXISTS chunks (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  bot_id      UUID NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
  chunk_index INT  NOT NULL,
  content     TEXT NOT NULL,
  embedding   VECTOR(1536),
  tokens      TEXT,                             -- W4: kiwi 형태소 결과(키워드 검색용)
  meta        JSONB NOT NULL DEFAULT '{}',
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_chunks_bot ON chunks (bot_id);
-- 코사인 거리 기준 HNSW. 데이터가 어느 정도 쌓인 뒤 만드는 게 더 빠르지만,
-- MVP 규모에선 미리 만들어도 무방하다.
CREATE INDEX IF NOT EXISTS idx_chunks_embedding
  ON chunks USING hnsw (embedding vector_cosine_ops);

-- ── 대화 / 메시지 ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS conversations (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  bot_id     UUID NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
  session_id VARCHAR(64) NOT NULL,
  channel    VARCHAR(10) NOT NULL DEFAULT 'widget',   -- widget/test
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_conv_bot_session ON conversations (bot_id, session_id);

CREATE TABLE IF NOT EXISTS messages (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role            VARCHAR(10) NOT NULL,          -- user/assistant
  content         TEXT NOT NULL,
  sources         JSONB,
  is_fallback     BOOLEAN NOT NULL DEFAULT false,
  feedback        SMALLINT,                      -- null / 1 / -1
  latency_ms      INT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages (conversation_id);

-- ── 품질 평가 (W3에서 사용) ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS eval_questions (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  bot_id          UUID NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
  question        TEXT NOT NULL,
  ground_truth    TEXT NOT NULL,
  source_chunk_id UUID REFERENCES chunks(id) ON DELETE SET NULL,
  is_active       BOOLEAN NOT NULL DEFAULT true,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS eval_runs (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  bot_id           UUID NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
  config           JSONB,                        -- {top_k, hybrid, reranker, model}
  avg_faithfulness NUMERIC(4,3),
  avg_relevancy    NUMERIC(4,3),
  answered_rate    NUMERIC(4,3),
  status           VARCHAR(20) NOT NULL DEFAULT 'running',
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS eval_results (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id           UUID NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
  question_id      UUID NOT NULL REFERENCES eval_questions(id) ON DELETE CASCADE,
  generated_answer TEXT,
  retrieved_chunks JSONB,
  faithfulness     NUMERIC(4,3),
  relevancy        NUMERIC(4,3),
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── 로컬 개발용 시드 (봇 1개) ────────────────────────────────────
INSERT INTO bots (id, name, public_key)
VALUES ('00000000-0000-0000-0000-000000000001', '테스트 봇', 'pk_local_dev')
ON CONFLICT DO NOTHING;
