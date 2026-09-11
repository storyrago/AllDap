// S2 breakpoint: 어디서 선형성이 깨지는가, 그때 무엇이 포화됐는가.
//
// 실행 (직접 부르지 말고 s2_context.py 가 인쇄한 값을 넣는다):
//   cd ai-service && \
//     LOADTEST_PASSWORD='...' \
//     BOT_ID=<...> RUN_ID=<...> OUT=loadtest/results/S2-<runId>.json \
//     k6 run loadtest/s2_breakpoint.js
//   (계정은 loadtest/account.py 가 먼저 만들어둔 측정 전용 계정이다)
//
// 🔴 <중단하지 않는다.> S1 드라이버(s1_baseline.py:42)는 비200 이 하나라도 나오면
//    즉시 멈추지만, S2 에 그 규칙을 물려주면 정확히 반대로 작동한다. S2 는 깨지는
//    지점을 찾는 시나리오라 5xx·타임아웃·연결끊김이 <찾으려는 결과 그 자체>다.
//    특히 2순위 가설(힙 256m + ExitOnOutOfMemoryError)이 맞으면 증상이 "끊기고
//    30초쯤 뒤 돌아온다" 인데, S1 규칙이면 <가설이 맞는 순간 드라이버가 자살하고
//    그 뒤를 못 본다.> 80 까지 끝까지 밀고, 판정은 전부 사후에 파일로 한다.

import http from 'k6/http';
import exec from 'k6/execution';
import { Counter, Trend } from 'k6/metrics';

const API      = __ENV.API      || 'http://localhost:8080';
// 🔴 계정은 <측정 전용>이고 값은 환경변수에서만 온다(loadtest/account.py 가 만든다).
//    예전에는 w2check@example.com / 비밀번호까지 기본값으로 박혀 있었다. 그 계정은
//    W2 검증에 쓰던 것이라 측정 뒤 비밀번호가 원래대로 복원됐고, 그래서 다음 측정이
//    매번 401 이었다. 그리고 박아둔 기본 비밀번호는 그 자체로 저장소에 커밋된 비밀번호다.
const EMAIL    = __ENV.EMAIL    || __ENV.LOADTEST_EMAIL    || 'loadtest@example.com';
const PASSWORD = __ENV.PASSWORD || __ENV.LOADTEST_PASSWORD;
const BOT_ID   = __ENV.BOT_ID;
const RUN_ID   = __ENV.RUN_ID;
const OUT      = __ENV.OUT || 'loadtest/results/S2-unnamed.json';

// 🔴 예비 실행 스위치. k6 는 options.scenarios 가 있으면 --vus/--duration/--stage 를
//    <조용히 무시한다>. 명령줄로 30초 예비 실행을 만들려다 12분을 돌리게 되는 자리다.
//    그래서 스위치를 스크립트 안에 둔다. 본 실행과 <같은 파일·같은 코드경로>를 타야
//    예비 실행이 본 실행의 오염을 대신 걸러줄 수 있다.
const DRYRUN = __ENV.DRYRUN === '1';

// 계단식 6단계. 램프를 두지 않는다. 꺾이는 지점이 단계 경계에 맞아떨어져야
// "20 은 버텼고 40 에서 깨졌다" 를 표로 읽을 수 있다. 램프를 두면 꺾임이 두 단계
// 사이로 번지고, 이 PR 의 산출물이 정확히 그 숫자다.
const STAGES = DRYRUN ? [1] : [1, 5, 10, 20, 40, 80];
const HOLD_S = DRYRUN ? 30 : 120;

// 🔴 각 단계 앞 20초는 집계에서 잘라낸다. 계단식이라 전환 순간 폭주가 있고
//    Prometheus scrape 이 15초라 점 1~2개 분량이다. 잘라내지 않으면
//    "20 단계 p99" 에 전환 충격이 섞인다.
//    ⚠️ 예비 실행은 0 이다. 30초 중 20초를 버리면 표본이 6건쯤 남아 표가 비어 보이는데,
//       예비 실행이 보려는 것은 지연이 아니라 <오염>(fallback·경로 미탐)이라 버릴 이유가 없다.
const WARMUP_MS = DRYRUN ? 0 : 20000;

// 🔴 상태코드별로 <따로> 센다. 처리량 곡선은 2xx 만이다.
//    5xx 를 처리량에 섞으면 "빨라졌다"(빨리 실패한 것)가 개선으로 보인다.
const WATCHED_STATUS = [200, 0, 429, 500, 502, 503, 504];  // 0 = 연결 실패·타임아웃

// 🔴 질문은 S1 이 쓴 5개를 <그대로> 쓴다. eval_questions 테이블 원문이다.
//    S1 은 손으로 적었다가 테이블 문항과 16건 중 완전 일치 0건이었고, 5건 예행에서
//    2건이 fallback 났다. 회귀가 아니라 <다른 질문을 던진 것>이었다.
//    fallback 은 LLM 을 안 타 0.1초에 끝나므로, 섞이면 재려던 곡선이 통째로 거짓이 된다.
//    (리랭커가 정답 청크를 밀어내는 알려진 2건과 코퍼스에 정답이 없는 1건은
//     S1 이 근거를 적어 빼놨다. 여기서 새로 적으면 그 판단이 사라진다.)
const QUESTIONS = [
  '정규직으로 새로 들어온 직원의 시용 기간은 얼마나 되나요?',
  '정규직의 업무용 컴퓨터를 바꿀 수 있는 주기는 얼마나 되나요?',
  '정규직이 결혼할 때 쉴 수 있는 날이 며칠인가요?',
  '정규직 기준으로 회사의 플라스틱 카드는 어떤 직급부터 쓸 수 있나요?',
  '정규직이 쌍둥이를 낳았을 때 아빠가 쓸 수 있는 휴가는 며칠인가요?',
];

const chatDuration  = new Trend('chat_duration', true);
const chatStatus    = new Counter('chat_status');
const chatFallback  = new Counter('chat_fallback');

// ── 시나리오와 임계값을 프로그램으로 만든다 ────────────────────────────
//
// ⚠️ thresholds 는 <판정용이 아니다.> k6 는 서브지표(chat_duration{stage:20,...})를
//    summary 에 넣어주지 않는데, 임계값을 걸어두면 그 이름이 summary 에 생긴다.
//    그래서 항상 참인 식(`p(99)>=0`)을 건다. 이 PR 은 SLO 를 정하지 않으므로
//    <실패할 수 있는 임계값은 하나도 두지 않는다>. 두면 k6 가 종료코드로 판정을
//    내리게 되고, 판정은 전부 사후에 사람이 하는 것이 이 PR 의 규칙이다.
const scenarios = {};
const thresholds = {
  'chat_status{status:200}': ['count>=0'],
  'chat_fallback': ['count>=0'],
};

STAGES.forEach((vus, i) => {
  scenarios[`vu${vus}`] = {
    executor: 'constant-vus',
    vus: vus,
    duration: `${HOLD_S}s`,
    // startTime 이 <절대 시각>이라 단계가 밀리지 않는다. 앞 단계가 늦게 끝나도
    // 다음 단계는 정해진 초에 시작한다. 결과 표의 "몇 분대가 몇 VU 였나" 가 어긋나면
    // Grafana 시간축과 대조할 수 없다.
    startTime: `${i * HOLD_S}s`,
    exec: 'chat',
    // think time 없는 closed loop. 설계서의 "동시 사용자 N" 을 항상 N건 in-flight 으로
    // 읽는다. 생각시간을 넣으면 breakpoint 탐색에서 부하가 흐려진다.
    tags: { stage: String(vus) },
  };
  thresholds[`chat_duration{stage:${vus},phase:measure}`] = ['p(99)>=0'];
  thresholds[`chat_duration{stage:${vus},phase:warmup}`]  = ['p(99)>=0'];
  thresholds[`chat_fallback{stage:${vus}}`] = ['count>=0'];
  WATCHED_STATUS.forEach((code) => {
    thresholds[`chat_status{stage:${vus},status:${code}}`] = ['count>=0'];
  });
});

export const options = {
  scenarios: scenarios,
  thresholds: thresholds,
  // 🔴 기본 요약은 p90·p95 만 보여주고 p99 가 안 나온다. 이 PR 의 판정 근거가 p95·p99 다.
  //    avg 는 표에 싣되 판정에 쓰지 않는다(평균은 느린 꼬리를 감춘다).
  summaryTrendStats: ['min', 'med', 'p(95)', 'p(99)', 'max', 'avg'],
  // 응답 본문을 버리지 않는다. isFallback 을 읽어야 한다.
  discardResponseBodies: false,
};

export function setup() {
  // 🔴 비밀번호에 기본값이 없다. 없으면 로그인 401 로 죽는데, 그 에러만 보면
  //    "계정이 잘못됐나" 를 먼저 의심하게 된다. 여기서 <무엇이 빠졌는지>로 죽인다.
  if (!PASSWORD) {
    throw new Error('PASSWORD 가 없다. LOADTEST_PASSWORD 를 환경변수로 넘길 것 '
      + '(계정은 loadtest/account.py 가 만든다).');
  }
  // 🔴 하드코딩된 기본값을 두지 않는다. 봇을 지우고 다시 만들면 id 가 바뀌는데,
  //    기본값이 있으면 그때 <다른 코퍼스를 가진 봇>을 조용히 재게 되고
  //    "그때 뭘로 쟀지" 를 못 답한다. 없으면 죽는다.
  if (!BOT_ID) {
    throw new Error('BOT_ID 가 없다. s2_context.py before 가 인쇄한 값을 넣을 것.');
  }
  // 🔴 RUN_ID 가 없으면 세션 id 가 실행끼리 섞인다. S1 이 s1-{i} 를 재사용해
  //    집계가 LIKE 67건 / 시각 66건으로 갈렸다. S2 는 단계당 수천 건이라
  //    같은 구조면 <단계 경계가 뭉개진다>.
  if (!RUN_ID) {
    throw new Error('RUN_ID 가 없다. s2_context.py before 가 인쇄한 값을 넣을 것.');
  }

  // 로그인 1회. 토큰을 재사용한다. 로그인에도 분당 제한이 있다.
  const res = http.post(
    `${API}/api/auth/login`,
    JSON.stringify({ email: EMAIL, password: PASSWORD }),
    { headers: { 'Content-Type': 'application/json' } },
  );
  if (res.status !== 200) {
    throw new Error(`로그인 실패 ${res.status}: ${String(res.body).slice(0, 200)}`);
  }
  return { token: res.json('token') };
}

export function chat(data) {
  const stage = exec.scenario.name.slice(2);   // 'vu20' → '20'
  const elapsed = Date.now() - exec.scenario.startTime;
  const phase = elapsed < WARMUP_MS ? 'warmup' : 'measure';

  const question = QUESTIONS[exec.scenario.iterationInTest % QUESTIONS.length];
  // 🔴 세션 id 는 실행·VU·반복이 전부 들어가야 한다. 하나라도 빠지면 다른 단계의
  //    대화가 같은 세션으로 합쳐진다.
  const sessionId = `s2-${RUN_ID}-${exec.vu.idInTest}-${exec.vu.iterationInScenario}`;

  const res = http.post(
    `${API}/api/bots/${BOT_ID}/chat`,
    JSON.stringify({ message: question, sessionId: sessionId }),
    {
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${data.token}`,
      },
      // 🔴 기본 60초로 두면 2순위 가설의 증상("끊기고 30초쯤 뒤 돌아온다")이
      //    타임아웃에 잘려 <연결 실패>로만 보인다. 넉넉히 준다.
      timeout: '120s',
      tags: { stage: stage, phase: phase, name: 'chat' },
    },
  );

  chatStatus.add(1, { stage: stage, status: String(res.status) });

  if (res.status === 200) {
    chatDuration.add(res.timings.duration, { stage: stage, phase: phase });
    // 🔴 fallback 이 0 이 아니면 그 요청들은 LLM 경로를 안 탄 것이고, 그 실행은 무효다.
    //    어느 질문이 걸렸는지까지 남긴다. 개수만으로는 못 고친다.
    let isFallback = false;
    try {
      isFallback = res.json('isFallback') === true;
    } catch (e) {
      isFallback = false;   // 본문이 JSON 이 아니면 fallback 판정을 할 수 없다
    }
    if (isFallback) {
      chatFallback.add(1, { stage: stage, question: question });
    }
  }
}

// 사후 판정에 쓸 표를 stdout 으로도 찍는다. 12분을 기다린 사람이 파일을 열기 전에
// "몇 단계에서 꺾였나" 를 먼저 보게 하려는 것이다.
export function handleSummary(data) {
  const num = (v) => (typeof v === 'number' ? v.toFixed(0) : '-');
  const lines = [
    '',
    `S2 breakpoint: runId=${RUN_ID}  botId=${BOT_ID}`,
    '단계  표본   p50      p95      p99      max      2xx     비2xx   fallback',
  ];
  STAGES.forEach((vus) => {
    const t = (data.metrics[`chat_duration{stage:${vus},phase:measure}`] || {}).values || {};
    let ok = 0;
    let bad = 0;
    WATCHED_STATUS.forEach((code) => {
      const m = data.metrics[`chat_status{stage:${vus},status:${code}}`];
      const c = m && m.values ? (m.values.count || 0) : 0;
      if (code === 200) { ok += c; } else { bad += c; }
    });
    const fb = data.metrics[`chat_fallback{stage:${vus}}`];
    const fbc = fb && fb.values ? (fb.values.count || 0) : 0;
    lines.push(
      `${String(vus).padStart(3)}  ` +
      `${String(num(t.count)).padStart(5)}  ` +
      `${String(num(t.med)).padStart(7)}  ` +
      `${String(num(t['p(95)'])).padStart(7)}  ` +
      `${String(num(t['p(99)'])).padStart(7)}  ` +
      `${String(num(t.max)).padStart(7)}  ` +
      `${String(ok).padStart(6)}  ` +
      `${String(bad).padStart(6)}  ` +
      `${String(fbc).padStart(8)}`,
    );
  });
  lines.push('');
  lines.push('🔴 위 숫자는 아직 <판정이 아니다.> s2_context.py after 로 가짜 CF 호출 수를');
  lines.push('   대조하고, Grafana 재시작 경계 패널을 본 뒤에야 표로 옮길 수 있다.');
  lines.push('');

  const out = {};
  out.stdout = lines.join('\n');
  out[OUT] = JSON.stringify(data, null, 2);
  return out;
}
