-- 임베딩 차원 1536 → 1024 (2026-08-02)
--
-- 왜 바꾸나
--   임베딩 제공자를 Google Gemini(gemini-embedding-001) 에서
--   Cloudflare Workers AI(@cf/baai/bge-m3) 로 옮긴다.
--   ⚠️ 성능이 좋아서가 아니다. 두 모델을 같은 한국어 검색 벤치마크에서 나란히 잰
--      측정치가 존재하지 않는다. 바꾸는 이유는 <약관과 한도>다 —
--      Gemini 무료 등급은 공식 가격표에 "Used to improve our products: Yes" 로
--      입력을 학습에 쓴다고 명시돼 있고, 이 제품은 고객 사내 문서를 받는 것이 목적이다.
--   bge-m3 의 출력이 1024차원이라 컬럼도 함께 바꾼다.
--
-- ⚠️ 이 마이그레이션은 <기존 벡터를 전부 버린다>.
--   모델이 다르면 벡터 공간이 달라서 옛 벡터와 새 벡터를 섞어 검색하면 결과가 엉망이 된다.
--   NULL 로 비운 뒤 애플리케이션에서 다시 임베딩해야 한다:
--       cd ai-service && .venv/bin/python -m app.reembed
--   재임베딩 전까지 검색은 근거를 하나도 못 찾는다(= 전부 fallback).
--   지금 청크가 7개뿐이라 몇 초면 끝난다. 데이터가 쌓인 뒤였다면 무중단 절차가 필요했다.
--
-- 순서가 중요하다 (실측으로 확인함)
--   ① 인덱스를 먼저 지운다 — 인덱스가 살아 있으면 컬럼 타입을 못 바꾼다
--   ② 값을 NULL 로 비운다 — 데이터가 있는 채로 ALTER 하면
--      "expected 1024 dimensions, not 1536" 로 실패한다
--   ③ 그다음에야 ALTER 가 통과한다
--   ④ 인덱스를 다시 만든다

DROP INDEX IF EXISTS idx_chunks_embedding;

UPDATE chunks SET embedding = NULL;

ALTER TABLE chunks ALTER COLUMN embedding TYPE VECTOR(1024);

-- 코사인 거리 기준 HNSW. V1 과 같은 설정이다.
CREATE INDEX IF NOT EXISTS idx_chunks_embedding
  ON chunks USING hnsw (embedding vector_cosine_ops);

-- 재임베딩이 필요하다는 사실을 DB 에도 남긴다.
-- documents.status 는 'ready' 그대로인데 실제로는 검색이 안 되는 상태이므로,
-- 이걸 안 남기면 나중에 "왜 답을 못 찾지?" 를 추적할 단서가 없다.
COMMENT ON COLUMN chunks.embedding IS
  '@cf/baai/bge-m3 (1024차원). V2 에서 gemini-embedding-001(1536) 에서 교체됨. 모델을 바꾸면 반드시 전체 재임베딩할 것.';
