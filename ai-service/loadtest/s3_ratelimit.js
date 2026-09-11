// S3 rate limit 정확성: 동시 요청에서 요청 제한기의 카운터가 새는가.
//
// 설계서: docs/superpowers/specs/2026-09-11-loadtest-pr4a-s3-ratelimit-design.md
//
// 실행 (직접 부르지 말고 s3_context.py before 가 인쇄한 값을 넣는다):
//   cd ai-service && \
//     ROUND=A RUN_ID=<...> OUT=loadtest/results/S3-<runId>-A.json \
//     k6 run loadtest/s3_ratelimit.js
//
// 🔴 <중단하지 않는다.> 판정은 전부 사후에 s3_context.py after 의 judge_round 가 한다.
//    여기서 k6 가 종료코드로 성패를 말하면, 실패해야 하는 판(음성 대조 N)과
//    성공해야 하는 판(A)의 판정 규칙이 서로 반대라 한 파일에 담을 수 없다.
//
// ── S2 와 다른 점 세 가지 ────────────────────────────────────────────────
//
// ① 🔴 setup() 이 없다. 위젯 채팅(POST /api/w/{publicKey}/chat)은 <인증 없이 열린
//    유일한 문>이라 JWT 가 필요 없다. S2 가 겪은 비밀번호 소동이 여기엔 없다.
// ② 🔴 처리량 곡선을 그리지 않는다(설계서 §3 맨 아래). 한도가 분당 20건 = 0.33 req/s 라
//    "지속 부하" 개념이 성립하지 않고, 429 와 200 을 한 곡선에 더하면
//    "초당 500건이 전부 429 인데 빠르다고 읽는" 바로 그 함정을 밟는다.
//    이 파일의 산출물은 곡선이 아니라 <상태코드 개수>다.
// ③ 계단을 쌓지 않는다. 한 번에 쏘고 끝낸다.

import http from 'k6/http';
import exec from 'k6/execution';
import { Counter, Trend } from 'k6/metrics';

const API    = __ENV.API    || 'http://localhost:8080';
const ROUND  = __ENV.ROUND  || 'A';
const RUN_ID = __ENV.RUN_ID;
const OUT    = __ENV.OUT || `loadtest/results/S3-unnamed-${ROUND}.json`;

// 🔴 <가짜> publicKey 가 기본값이다. 형식(pk_ + 22자)만 맞고 DB 에 없는 키다.
//
//    이 시나리오가 싼 이유가 이것이다. WidgetController.chat 의 순서는
//      requirePlausiblePublicKey → rateLimiter.check → chatService.chatAsWidget
//    이고 chatAsWidget 의 첫 줄이 findByPublicKey 다. 형식만 맞고 없는 키를 쓰면
//    <카운터는 정상으로 세면서> 거기서 BOT_NOT_FOUND(404)로 끝난다. LLM 0건.
//
//    ⚠️ 그래서 이 판정에서 "제한기까지 갔다" 의 증거는 200 이 아니라 <404> 다.
//    ⚠️ 진짜 키로 덮으면 LLM 이 20번 돈다. 드라이버(s3_context.py before)가 실행 전에
//       그 키가 실제로 404 를 내는지 한 번 확인하고, 404 가 아니면 중단한다.
const PUBLIC_KEY   = __ENV.PUBLIC_KEY   || 'pk_s3loadtestFAKEkeyAAAAA';
const PUBLIC_KEY_2 = __ENV.PUBLIC_KEY_2 || 'pk_s3loadtestFAKEkeyBBBBB';

// 판 정의. 설계서 §3 표 그대로다.
//
//   판 N (음성 대조) : 한도 100000 으로 띄운 서버. 429 가 0건이어야 한다
//   판 A (본 판정)   : 한도 20(기본값). 404 20 · 429 80
//   판 B (분 경계)   : 고정 윈도우라 경계를 끼면 2N 이 통과한다. 404 40
//   판 C (키 축 분리): 키 2개. 키마다 404 20 · 429 80
//
// expected 는 <보낼 요청 수>다. judge_round 가 합계와 대조해 연결 실패(0)가
// 섞였는지 가른다. "덜 보냈다" 와 "많이 통과했다" 는 다른 사실이다.
const ROUNDS = {
  N: { vus: 100, expected: 100 },
  A: { vus: 100, expected: 100 },
  B: { vus: 20,  expected: 40  },   // 20건 × 2회(0초 · 4초)
  C: { vus: 100, expected: 100 },   // 50 VU 씩 키 둘
};

// 🔴 400 과 200 을 감시 목록에 넣는 이유 (설계서 §5-①). 둘 다 "안 나와야 정상" 이라
//    세어야만 안다. 세지 않으면 <언제 돌려도 성공을 보고하는> 점검이 된다.
//
//    400 = 2026-09-09 사고의 재현. 그때 점검 명령은 본문에 sessionId 가 없어
//          @Valid 에서 400 이 났고, rateLimiter.check 를 <지나가지도 못한 채>
//          25건 전부 400 이 됐다. 그 모습이 문서의 실패 판정 기준과 겹쳐
//          언제 돌려도 실패를 보고했다. 아래 sessionId 를 반드시 실어 보낸다.
//    200 = 실수로 <진짜> publicKey 를 쓴 것이다. LLM 이 돌았다는 뜻이므로 그 판은 무효다.
//    0   = 연결 실패·타임아웃.
const WATCHED_STATUS = [404, 429, 400, 200, 0, 500, 503];

// ── 지표 ──────────────────────────────────────────────────────────────
//
// 이름을 S2 와 같게 둔다(chat_status · chat_duration). s3_context.py 가 S2 와 같은
// 방식(summary.metrics["chat_status{status:404}"].values.count)으로 읽기 때문이다.
const chatStatus   = new Counter('chat_status');
// D(거절 경로의 비용). 429 의 지연 분포다. Python 을 안 타는 순수 Spring 경로라
// "거절이 실제로 싼가" 를 이 값으로만 말할 수 있다.
const chatDuration = new Trend('chat_duration', true);

// 🔴 RUN_ID 가 없으면 죽는다. 기본값을 두지 않는 이유는 S2 와 같다.
//    세션 id 가 실행끼리 섞이면 "그때 뭘로 쟀지" 를 못 답한다.
//    init 문맥(파일 최상단)에서 던지면 VU 가 하나도 돌기 전에 멈춘다.
if (!RUN_ID) {
  throw new Error('RUN_ID 가 없다. s3_context.py before 가 인쇄한 값을 넣을 것.');
}
if (!ROUNDS[ROUND]) {
  throw new Error(`ROUND 가 N·A·B·C 중 하나여야 한다 (받은 값: ${ROUND})`);
}
// sessionId 는 @Size(max = 64) 다. 넘치면 <400> 이 나고, 그게 정확히 위에서 막으려는
// 사고다. 길이를 여기서 미리 검사해 실행 전에 죽인다. 100건을 쏜 뒤에 알면 늦다.
const SESSION_MAX = `s3-${RUN_ID}-999`.length;
if (SESSION_MAX > 64) {
  throw new Error(`RUN_ID 가 너무 길다. sessionId 가 ${SESSION_MAX}자로 64자를 넘는다.`);
}

// ── 시나리오 ──────────────────────────────────────────────────────────
//
// per-vu-iterations 로 VU 당 정확히 1건. constant-vus 로 "몇 초간" 을 주면
// VU 가 끝나는 대로 다음 반복을 돌아 <몇 건이 갔는지를 우리가 정하지 못한다>.
// 이 PR 의 판정이 개수 전체 일치라 요청 수가 먼저 확정돼야 한다.
const scenarios = {};
if (ROUND === 'B') {
  // 🔴 B 판만 startTime 을 쓴다. 분 경계 <정렬>은 드라이버(s3_context.py)가 하고,
  //    k6 안에서는 0초에 20건 · 4초에 20건만 쏜다. 드라이버가 경계를 두 버스트
  //    사이에 오도록 시작 시각을 맞추면, 앞 20건과 뒤 20건이 서로 다른 윈도우에
  //    들어가 <정상인데도> 404 가 40건이 된다. 그게 이 판이 일부러 재는 현상이다.
  scenarios.pre = {
    executor: 'per-vu-iterations',
    vus: 20, iterations: 1, startTime: '0s', maxDuration: '30s',
    exec: 'widgetChat', tags: { burst: 'pre' },
  };
  scenarios.post = {
    executor: 'per-vu-iterations',
    vus: 20, iterations: 1, startTime: '4s', maxDuration: '30s',
    exec: 'widgetChat', tags: { burst: 'post' },
  };
} else {
  scenarios.burst = {
    executor: 'per-vu-iterations',
    vus: ROUNDS[ROUND].vus, iterations: 1, maxDuration: '60s',
    exec: 'widgetChat', tags: { burst: 'pre' },
  };
}

// ⚠️ thresholds 는 <판정용이 아니다.> k6 는 태그가 붙은 서브지표를 summary 에
//    넣어주지 않는데, 임계값을 걸어두면 그 이름이 summary 에 생긴다. 그래서 항상
//    참인 식(count>=0)을 건다. 실패할 수 있는 임계값은 하나도 두지 않는다.
//    두면 k6 가 종료코드로 판정을 내리게 된다.
//
// 🔴 그리고 이 등록이 judge_round 의 "0건과 계측 실패를 뭉개지 않는다" 규칙을
//    가능하게 하는 장치다. 임계값을 걸어둔 서브지표는 표본이 0건이어도 summary 에
//    count: 0 으로 나온다. 그러므로
//      키가 있는데 count: 0  → 그 코드가 안 났다 (사실)
//      키가 아예 없다        → k6 가 세지 않았다 (계측 실패. 그 실행은 무효)
//    두 사실이 갈린다. 이 줄을 지우면 둘이 같은 모습이 된다.
const thresholds = {};
WATCHED_STATUS.forEach((code) => {
  thresholds[`chat_status{status:${code}}`] = ['count>=0'];
  // 키 축(C 판). 다른 판에서는 0 으로 나오는 것이 정상이다. 0 이 나오는 것 자체가
  // "이 판은 키를 하나만 썼다" 는 기록이므로 지우지 않는다.
  thresholds[`chat_status{key:1,status:${code}}`] = ['count>=0'];
  thresholds[`chat_status{key:2,status:${code}}`] = ['count>=0'];
  // 버스트 축(B 판). 40건이 앞뒤로 20·20 으로 갈렸는지를 이 둘로 본다.
  thresholds[`chat_status{burst:pre,status:${code}}`] = ['count>=0'];
  thresholds[`chat_status{burst:post,status:${code}}`] = ['count>=0'];
  // D: 거절 경로의 지연. 상태코드별로 <따로> 잰다. 404(통과분)와 429(거절분)를
  // 한 분포에 섞으면 "거절이 싸다" 를 말할 수 없다.
  thresholds[`chat_duration{status:${code}}`] = ['p(99)>=0'];
});

export const options = {
  scenarios: scenarios,
  thresholds: thresholds,
  summaryTrendStats: ['min', 'med', 'p(95)', 'p(99)', 'max', 'avg'],
  // 본문을 버린다. S2 는 isFallback 을 읽어야 해서 남겼지만, 여기서 판정에 쓰는 것은
  // 상태코드뿐이다. 100 VU 가 동시에 도는 순간의 메모리를 아낀다.
  discardResponseBodies: true,
};

export function widgetChat() {
  // C 판만 키를 둘로 나눈다. 단일 시나리오 안에서 VU id 로 가르는 이유는
  // 시나리오를 둘로 쪼개면 <동시에 시작한다> 는 보장이 흐려지기 때문이다.
  // idInTest 는 1..vus 라 앞쪽 절반/뒤쪽 절반이 정확히 50:50 이다.
  const useSecondKey = ROUND === 'C' && exec.vu.idInTest > ROUNDS.C.vus / 2;
  const publicKey = useSecondKey ? PUBLIC_KEY_2 : PUBLIC_KEY;
  const keyTag = useSecondKey ? '2' : '1';

  // 🔴 sessionId 를 반드시 싣는다. ChatRequest 는 message(@NotBlank, ≤2000) 와
  //    sessionId(@NotBlank, ≤64) 가 <둘 다> 필수다. 빠지면 @Valid 에서 400 이 나
  //    rateLimiter.check 를 지나가지도 못한다. 2026-09-09 사고가 정확히 이것이다.
  const sessionId = `s3-${RUN_ID}-${exec.vu.idInTest}`;

  const res = http.post(
    `${API}/api/w/${publicKey}/chat`,
    JSON.stringify({ message: '부하테스트 S3 요청 제한 확인용 질문입니다.', sessionId: sessionId }),
    {
      headers: { 'Content-Type': 'application/json' },
      // 거절 경로는 순수 Spring 이라 밀리초 단위로 끝난다. 30초면 넉넉하고,
      // 넘으면 그건 지연이 아니라 <포화>이므로 0(연결 실패)으로 세는 것이 맞다.
      timeout: '30s',
      tags: { key: keyTag, name: 'widget-chat' },
    },
  );

  const status = String(res.status);
  chatStatus.add(1, { status: status, key: keyTag });
  chatDuration.add(res.timings.duration, { status: status, key: keyTag });
}

// 사후 판정에 쓸 표를 stdout 으로도 찍는다. 🔴 다만 이 표는 <판정이 아니다>.
// judge_round 가 파일을 읽어 가른다. 여기 인쇄는 사람이 파일을 열기 전에
// "숫자가 대충 맞는지" 를 먼저 보게 하려는 것뿐이다.
export function handleSummary(data) {
  const count = (key) => {
    const m = data.metrics[key];
    // undefined 와 0 을 갈라 돌려준다. 위 thresholds 주석의 이유 그대로다.
    if (!m || !m.values || typeof m.values.count !== 'number') return null;
    return m.values.count;
  };
  const show = (v) => (v === null ? '없음' : String(v));
  const num = (v) => (typeof v === 'number' ? v.toFixed(1) : '-');

  const lines = [
    '',
    `S3 rate limit: runId=${RUN_ID}  판=${ROUND}  기대 요청수=${ROUNDS[ROUND].expected}`,
    `publicKey=${PUBLIC_KEY}${ROUND === 'C' ? `  publicKey2=${PUBLIC_KEY_2}` : ''}`,
    '',
    '상태  전체   키1    키2    앞버스트 뒤버스트   p50(ms)  p95(ms)  max(ms)',
  ];
  let total = 0;
  WATCHED_STATUS.forEach((code) => {
    const all = count(`chat_status{status:${code}}`);
    if (typeof all === 'number') total += all;
    const t = (data.metrics[`chat_duration{status:${code}}`] || {}).values || {};
    lines.push(
      `${String(code).padStart(4)}  ` +
      `${show(all).padStart(5)}  ` +
      `${show(count(`chat_status{key:1,status:${code}}`)).padStart(5)}  ` +
      `${show(count(`chat_status{key:2,status:${code}}`)).padStart(5)}  ` +
      `${show(count(`chat_status{burst:pre,status:${code}}`)).padStart(8)} ` +
      `${show(count(`chat_status{burst:post,status:${code}}`)).padStart(8)}  ` +
      `${num(t.med).padStart(8)} ${num(t['p(95)']).padStart(8)} ${num(t.max).padStart(8)}`,
    );
  });
  lines.push('');
  lines.push(`감시 상태코드 합계 = ${total} (기대 ${ROUNDS[ROUND].expected})`);
  lines.push('');
  lines.push('🔴 위 숫자는 아직 <판정이 아니다.> s3_context.py after 의 judge_round 가');
  lines.push('   히스토그램 <전체 일치>로 가른다. 400 이 1건이라도 있으면(2026-09-09 사고)');
  lines.push('   또는 200 이 1건이라도 있으면(진짜 봇을 때렸다) 그 판은 무효다.');
  lines.push('');

  const out = {};
  out.stdout = lines.join('\n');
  out[OUT] = JSON.stringify(data, null, 2);
  return out;
}
