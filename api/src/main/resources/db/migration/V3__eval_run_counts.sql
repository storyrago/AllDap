-- 평가 실행에 "표본이 몇 개였는가"를 기록한다 (2026-08-02)
--
-- 왜 필요한가 — 실제로 속았기 때문이다
--   리랭커 before/after 를 재는데 충실성이 0.714 → 0.789 로 <올랐다.>
--   그런데 파보니 개선이 아니라 <생존 편향>이었다:
--   0점짜리 어려운 질문 2건이 fallback 되면서 채점 대상에서 빠졌고,
--   그만큼 평균이 저절로 올라간 것이다. 그 2건을 0으로 환산하면 0.714 로 동일했다.
--
--   즉 avg_faithfulness 는 <답을 덜 할수록 좋아 보이는> 지표다.
--   단독으로는 설정 비교(W4 의 before/after)에 쓸 수 없다.
--
-- 그런데 기존 컬럼만으로는 그 사실을 <알아챌 수조차 없었다.>
--   저장된 값이 avg_faithfulness 0.789 / answered_rate 0.905 뿐이라
--   "21문항 중 19건만 채점됐다"를 복원할 방법이 없다.
--   분모를 모르면 평균을 해석할 수 없고, 해석할 수 없는 숫자는 비교표에 쓸 수 없다.
--
-- 그래서 분모 두 개를 함께 저장한다.
--   question_count : 이 실행이 대상으로 삼은 활성 질문 수 (비교의 기준 분모)
--   scored_count   : 실제로 채점까지 간 질문 수 (avg_* 의 진짜 분모)
--
-- 이 둘이 있으면 편향에 안 넘어가는 비교 지표를 어디서든 계산할 수 있다:
--   전체 충실성 = avg_faithfulness × scored_count / question_count
--   (= 전체 질문 대비 "근거에 충실하게 답한 정도". 답을 덜 하면 같이 내려간다)
--
-- 옛 실행은 NULL 로 남는다. 채워 넣지 않는 이유: 그때 몇 문항이었는지 <알 수 없다>.
-- 추측해서 넣으면 없는 사실을 지어내는 것이고, 그게 이 컬럼을 만든 이유와 정면으로 어긋난다.
-- 화면은 NULL 이면 "표본 미기록"으로 표시하고 비교 대상에서 빼야 한다.

ALTER TABLE eval_runs ADD COLUMN IF NOT EXISTS question_count INT;
ALTER TABLE eval_runs ADD COLUMN IF NOT EXISTS scored_count   INT;

COMMENT ON COLUMN eval_runs.question_count IS
  '이 실행이 대상으로 삼은 활성 질문 수. avg_* 를 해석하려면 반드시 필요한 분모.';
COMMENT ON COLUMN eval_runs.scored_count IS
  '실제로 채점된 질문 수. avg_faithfulness/avg_relevancy 의 진짜 분모. '
  'question_count 보다 작으면 fallback·처리실패로 빠진 것이 있다는 뜻이다.';
