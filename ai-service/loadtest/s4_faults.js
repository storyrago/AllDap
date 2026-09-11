// S4 장애 주입 — k6 시나리오. 20 VU 고정, 관리자 채팅 경로.
//
// 실행 (판 하나당 한 번. 드라이버가 주입을 켜고 끄는 것과 <같은 시간축>으로 돈다):
//   k6 run -e ROUND=F1 -e RUN_ID=2026-09-11-F1 -e BOT_ID=... loadtest/s4_faults.js
//   (결과 JSON 은 handleSummary 가 OUT 경로로 직접 쓴다. --summary-export 는 필요 없다)
//
// 설계서: docs/superpowers/specs/2026-09-11-loadtest-pr4b-s4-fault-injection-design.md
//
// 🔴 왜 20 VU 고정인가
// ───────────────────────────────────────────────────────────────────────────
// S2 에서 20 단계는 아직 안 꺾인 구간이다. 계단을 쌓으면 "느려진 것이 포화 때문인가
// 주입 때문인가" 를 못 가른다. 이 저장소가 반복해 낸 <원인이 다른 두 사실을 같은
// 값으로 뭉개는> 부류라, 여기서는 부하를 상수로 두고 주입만 변수로 남긴다.
//
// 🔴 왜 중단하지 않는가
// ───────────────────────────────────────────────────────────────────────────
// S1 드라이버는 "비200 이 하나라도 나오면 즉시 멈춘다" 는 규칙을 갖고 있었다.
// S4 에 그대로 물려주면 <찾으려는 결과가 나오는 순간 드라이버가 자살한다.>
// 503·504 는 이 시나리오의 산출물 그 자체다. 끝까지 밀고 판정은 전부 사후에 한다.

import http from 'k6/http';
import exec from 'k6/execution';
import { Counter, Trend } from 'k6/metrics';

const API      = __ENV.API      || 'http://localhost:8080';
const EMAIL    = __ENV.EMAIL    || 'w2check@example.com';
const PASSWORD = __ENV.PASSWORD || 'S1loadtest!2026';
const BOT_ID   = __ENV.BOT_ID;
const RUN_ID   = __ENV.RUN_ID;
const ROUND    = __ENV.ROUND;
// 결과 JSON 경로. s4_context.py after 가 이 파일을 읽어 판정한다.
const OUT      = __ENV.OUT || `loadtest/results/S4-${__ENV.RUN_ID || 'unnamed'}.json`;

// 각 판의 시간 구성. 드라이버(s4_context.py)가 같은 값을 들고 주입을 켜고 끈다.
//
// 🔴 두 곳에 같은 숫자를 두는 것은 일부러다. 한 곳으로 합치면 둘이 함께 틀렸을 때
//    아무도 못 잡는다. 따로 두고 시작 조건 파일에서 대조하면, 어긋나는 순간 드러난다.
const NORMAL_S  = Number(__ENV.NORMAL_S  || 60);   // 주입 전 대조 구간
const INJECT_S  = Number(__ENV.INJECT_S  || 90);   // 주입 구간
const VUS       = Number(__ENV.VUS       || 20);

// 감시 상태코드. 0 = 연결 실패·타임아웃.
//
// 200 을 감시하는 이유가 S3 와 정반대다. 거기서는 "나오면 안 되는 것" 이었지만
// 여기서는 <정상 구간에 나와야 하는 것>이다. F3(rerank 조용한 실패) 판정이
// "주입 구간에도 200 뿐" 인데, 정상 구간에 200 이 없으면 그 판정은 아무 뜻이 없다.
const WATCHED_STATUS = [200, 0, 422, 429, 500, 502, 503, 504];

const ROUNDS = {
  F1: 'Python 프로세스 종료 — 연결 실패 · 재시도 · 서킷 개폐',
  F2: 'Python 5xx — 재시도가 <안> 도는 것이 산출물',
  F3: 'rerank 조용한 실패 — 모든 외부 신호가 안 바뀌는 것이 산출물',
};

if (!BOT_ID) { throw new Error('BOT_ID 가 필요하다. s4_context.py before 가 인쇄한 값을 넣을 것.'); }
if (!RUN_ID) { throw new Error('RUN_ID 가 필요하다. 세션 id 와 결과 파일 이름이 여기서 나온다.'); }
if (!ROUNDS[ROUND]) { throw new Error(`ROUND 는 ${Object.keys(ROUNDS)} 중 하나여야 한다 (받은 값: ${ROUND}).`); }

// 질문은 S1·S2 의 것을 그대로 쓴다. eval_questions 테이블 원문이라 fallback 이 안 난다.
// 🔴 여기서 새로 적으면 게이트에 걸려 LLM 을 안 타고, 그러면 이 시나리오가 재려는
//    <실패 처리 경로>를 아예 안 지나간다. S1 이 "손으로 적었다가 테이블 문항과
//    16건 중 완전 일치 0건" 으로 데인 자리다.
const QUESTIONS = [
  '정규직의 연차휴가는 며칠인가요?',
  '정규직의 시용 기간은 얼마인가요?',
  '법인카드는 어느 직급부터 쓸 수 있나요?',
  '정규직의 업무용 컴퓨터 교체 주기는 어떻게 되나요?',
  '경조사 휴가는 어떻게 되나요?',
];

const callStatus   = new Counter('chat_status');
const callDuration = new Trend('chat_duration', true);
const fallbackHits = new Counter('chat_fallback');

// phase 태그로 정상 구간과 주입 구간을 가른다. 이 태그가 이 시나리오의 핵심이다.
// 없으면 "주입 때문에 바뀌었다" 를 같은 실행 안에서 말할 수 없다.
const thresholds = {};
['normal', 'inject'].forEach((phase) => {
  WATCHED_STATUS.forEach((code) => {
    // 🔴 항상 참인 threshold 를 거는 이유: k6 는 threshold 가 걸린 서브지표만 요약에
    //    싣는다. 이게 없으면 <0건> 과 <안 셌다> 가 요약에서 똑같이 "키 없음" 이 되어,
    //    s4_context 의 판정이 원리적으로 성립하지 않는다.
    thresholds[`chat_status{phase:${phase},status:${code}}`] = ['count>=0'];
  });
  thresholds[`chat_duration{phase:${phase}}`] = ['p(99)>=0'];
  thresholds[`chat_fallback{phase:${phase}}`] = ['count>=0'];
});

export const options = {
  scenarios: {
    s4: {
      executor: 'constant-vus',
      vus: VUS,
      duration: `${NORMAL_S + INJECT_S}s`,
      exec: 'chat',
    },
  },
  thresholds: thresholds,
  // 판정에 쓰는 것은 상태코드와 phase 별 지연이다. 본문은 isFallback 하나만 본다.
  summaryTrendStats: ['min', 'med', 'p(95)', 'p(99)', 'max', 'avg', 'count'],
};

export function setup() {
  const res = http.post(`${API}/api/auth/login`,
    JSON.stringify({ email: EMAIL, password: PASSWORD }),
    { headers: { 'Content-Type': 'application/json' } });
  if (res.status !== 200) {
    throw new Error(`로그인 실패 ${res.status}: ${res.body}`);
  }
  return { token: res.json('token') };
}

export function chat(data) {
  // 🔴 구간 판정을 <k6 의 시계>로 한다. 드라이버가 주입을 켜는 시각과 이 경계가
  //    정확히 같아야 하므로, 드라이버는 k6 를 띄운 뒤 NORMAL_S 초를 세고 켠다.
  //    경계 몇 초의 어긋남은 어차피 생기므로, 사후 판정은 "정확히 언제" 가 아니라
  //    <구간별 총량>으로 한다(설계서 §5-③).
  const elapsed = (Date.now() - exec.scenario.startTime) / 1000;
  const phase = elapsed < NORMAL_S ? 'normal' : 'inject';

  const question = QUESTIONS[exec.scenario.iterationInTest % QUESTIONS.length];
  const sessionId = `s4-${RUN_ID}-${exec.vu.idInTest}-${exec.vu.iterationInScenario}`;

  const res = http.post(
    `${API}/api/bots/${BOT_ID}/chat`,
    JSON.stringify({ message: question, sessionId: sessionId }),
    {
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${data.token}` },
      // 🔴 넉넉히 준다. 서킷이 열려 있는 동안의 503 은 마이크로초 대지만,
      //    연결 실패 재시도(200ms)나 읽기 지연이 섞이면 수 초까지 간다.
      //    짧게 주면 그 차이가 전부 0(타임아웃)으로 뭉개져 이 시나리오의 산출물이 사라진다.
      timeout: '130s',
      tags: { phase: phase, round: ROUND, name: 'chat' },
    },
  );

  callStatus.add(1, { phase: phase, status: String(res.status) });
  callDuration.add(res.timings.duration, { phase: phase, status: String(res.status) });

  if (res.status === 200) {
    let isFallback = false;
    try { isFallback = res.json('isFallback') === true; } catch (e) { isFallback = false; }
    // fallback 은 주입과 무관하게 0 이어야 한다. 0 이 아니면 게이트에 걸린 것이라
    // 그 요청은 LLM 경로를 안 탔고, 재려던 실패 처리도 안 지났다.
    if (isFallback) { fallbackHits.add(1, { phase: phase }); }
  }
}

export function handleSummary(data) {
  const count = (phase, code) => {
    const m = data.metrics[`chat_status{phase:${phase},status:${code}}`];
    return m && m.values ? (m.values.count || 0) : 0;
  };
  const lines = ['', `S4 ${ROUND} — ${ROUNDS[ROUND]}`, `runId=${RUN_ID} botId=${BOT_ID}`, ''];
  lines.push('구간     ' + WATCHED_STATUS.map((c) => String(c).padStart(6)).join(''));
  ['normal', 'inject'].forEach((phase) => {
    lines.push(phase.padEnd(9) + WATCHED_STATUS.map((c) => String(count(phase, c)).padStart(6)).join(''));
  });
  lines.push('');
  lines.push('🔴 위 숫자는 아직 <판정이 아니다.> s4_context.py after 가 지표 전후 차이와');
  lines.push('   가짜 CF 의 injected 증가분까지 함께 봐야 이 판의 성패가 나온다.');
  lines.push('   특히 F3 은 <아무것도 안 바뀌는 것>이 성공이라, 이 표만 보면 정상으로 읽힌다.');

  const out = {};
  out.stdout = lines.join('\n') + '\n';
  out[OUT] = JSON.stringify(data, null, 2);
  return out;
}
