"""사람이 44건에 충실성 라벨을 매기는 것을 돕는 로컬 페이지.

실행:
    cd ai-service
    .venv/bin/python -m app.judge_label_server      # http://127.0.0.1:8765 를 브라우저로 연다

이 도구는 `testdata/judge_labels.json` 의 `label` 칸을 채우는 <입력 보조>일 뿐이다.
집계도 판정도 하지 않는다. 그건 `app.judge_agreement report` 의 일이다.

왜 이걸 만들었나
─────────────────────────────────────────────────────────────────────────────
라벨 파일은 100KB 짜리 JSON 이고 한 건마다 근거 청크가 5개씩 붙어 있다. 에디터로
`"label": null` 을 44번 찾아 고치면 ① 어디까지 했는지 매번 세어야 하고
② 오타 하나("1.O", 따옴표 빠뜨림)로 `report` 가 통째로 실패한다.
화면 하나에 한 건만 띄우고 버튼으로 찍으면 둘 다 사라진다.

설계 결정 (왜 이렇게 만들었나)
─────────────────────────────────────────────────────────────────────────────
1. 🔴 **이 서버는 DB 에 붙지 않는다.** 읽는 것은 라벨 파일 하나뿐이다. 그 파일에는
   채점자 점수가 <일부러> 빠져 있으므로(`judge_agreement.build_payload`), 화면에
   점수가 샐 통로 자체가 없다. 블라인드는 코드가 아니라 <데이터>가 지킨다.
2. **표준 라이브러리만 쓴다.** Flask 같은 걸 끌어오면 이 보조 도구 때문에
   `requirements.txt` 가 는다. `http.server` 로 충분하다.
3. **왜 파일을 그냥 열지 않고 서버를 띄우나.** `file://` 로 연 HTML 은 브라우저 보안
   정책 때문에 옆에 있는 JSON 을 fetch 로 못 읽고, 읽더라도 <되돌려 쓸> 방법이 없다.
   서버를 두면 버튼을 누르는 즉시 파일에 반영돼서 중간에 닫아도 잃는 것이 없다.
4. **127.0.0.1 에만 바인딩한다.** 이 파일에는 코퍼스 본문(청크 전문)이 들어 있다.
   0.0.0.0 으로 열면 같은 네트워크의 아무나 읽는다.
5. **저장은 원자적으로 한다**(임시 파일에 쓴 뒤 `os.replace`). 쓰는 도중에 죽어도
   반쯤 쓰인 JSON 이 남지 않는다. 44건을 다시 매기는 것보다 훨씬 싸다.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .judge_agreement import DEFAULT_PATH, LABELS


class LabelRejected(ValueError):
    """넣으면 안 되는 라벨이거나 없는 case_id 다."""


def apply_label(data: dict, case_id: str, label: float | None, note: str) -> dict:
    """라벨 파일 내용(dict)에 한 건을 반영한 <새 dict> 를 돌려준다.

    순수 함수로 뺀 이유는 검사할 수 있게 하려는 것이다. 파일 입출력이 섞여 있으면
    "값 검증이 실제로 도는가" 를 확인하려고 매번 디스크를 건드려야 한다.

    label 이 None 이면 "아직 안 매김" 으로 되돌린다(잘못 눌렀을 때 쓴다).
    """
    if label is not None and label not in LABELS:
        raise LabelRejected(f"라벨은 {', '.join(str(v) for v in LABELS)} 중 하나여야 합니다: {label!r}")

    found = False
    cases = []
    for c in data["cases"]:
        if c["case_id"] == case_id:
            # dict(c) 는 얕은 복사다. 원본을 제자리에서 고치지 않으려는 것이고,
            # 안쪽 sources 리스트는 건드리지 않으므로 얕은 복사로 충분하다.
            c = dict(c, label=label, note=note)
            found = True
        cases.append(c)
    if not found:
        raise LabelRejected(f"그런 case_id 가 없습니다: {case_id!r}")
    return dict(data, cases=cases)


def save_atomic(data: dict, path: str) -> None:
    """같은 디렉터리에 임시 파일로 쓴 뒤 이름을 바꿔치기한다.

    같은 디렉터리여야 하는 이유: os.replace 가 원자적인 것은 같은 파일시스템 안에서다.
    /tmp 에 썼다가 옮기면 그 보장이 사라진다.
    """
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".judge_labels.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _handler(path: str) -> type[BaseHTTPRequestHandler]:
    """요청 처리기를 만든다. path 를 닫아 넣으려고 함수 안에서 클래스를 정의한다.

    (BaseHTTPRequestHandler 는 프레임워크가 알아서 인스턴스를 만들기 때문에
     생성자로 값을 넘길 자리가 없다. 이럴 때 쓰는 파이썬 관용구다.)
    """

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # noqa: D102 - 요청마다 찍히는 기본 로그를 끈다
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj: dict) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def do_GET(self) -> None:  # noqa: N802 - 표준 라이브러리가 요구하는 이름
            if self.path == "/":
                self._send(200, PAGE.encode(), "text/html; charset=utf-8")
            elif self.path == "/api/data":
                with open(path, encoding="utf-8") as f:
                    self._send(200, f.read().encode(), "application/json; charset=utf-8")
            else:
                self._json(404, {"error": "그런 주소가 없습니다."})

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/api/label":
                self._json(404, {"error": "그런 주소가 없습니다."})
                return
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self._json(400, {"error": "본문이 JSON 이 아닙니다."})
                return

            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            try:
                data = apply_label(data, body.get("case_id", ""), body.get("label"), body.get("note", ""))
            except LabelRejected as e:
                self._json(400, {"error": str(e)})
                return
            save_atomic(data, path)
            done = sum(1 for c in data["cases"] if c["label"] is not None)
            self._json(200, {"done": done, "total": len(data["cases"])})

    return Handler


def serve(path: str, port: int, open_browser: bool) -> int:
    if not os.path.exists(path):
        print(f"라벨 파일이 없습니다: {path}")
        print("먼저 `python -m app.judge_agreement dump` 를 돌려 만드세요(DB 가 떠 있어야 합니다).")
        return 1

    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    done = sum(1 for c in data["cases"] if c["label"] is not None)
    url = f"http://127.0.0.1:{port}"
    print(f"{path}: {len(data['cases'])}건 중 {done}건이 채워져 있습니다.")
    print(f"브라우저로 {url} 을 여세요. 버튼을 누르면 파일에 바로 저장됩니다.")
    print("끝나면 Ctrl+C 로 서버를 끄고 `python -m app.judge_agreement report --reasons` 를 돌리세요.")
    if open_browser:
        webbrowser.open(url)
    server = ThreadingHTTPServer(("127.0.0.1", port), _handler(path))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n서버를 껐습니다. 채운 라벨은 파일에 남아 있습니다.")
    return 0


PAGE = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>채점자 대조 · 사람 라벨링</title>
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body { margin: 0; font: 15px/1.7 -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", sans-serif;
         background: #f5f5f4; color: #1c1917; }
  header { position: sticky; top: 0; background: #fff; border-bottom: 1px solid #e7e5e4;
           padding: 12px 24px; display: flex; align-items: center; gap: 16px; }
  .bar { flex: 1; height: 8px; background: #e7e5e4; border-radius: 4px; overflow: hidden; }
  .bar > div { height: 100%; background: #16a34a; width: 0; transition: width .2s; }
  main { max-width: 900px; margin: 0 auto; padding: 24px; }
  .card { background: #fff; border: 1px solid #e7e5e4; border-radius: 10px; padding: 20px; margin-bottom: 16px; }
  h2 { font-size: 13px; letter-spacing: .04em; color: #78716c; margin: 0 0 8px; font-weight: 600; }
  .q { font-size: 19px; font-weight: 600; }
  .answer { background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; padding: 6px 14px; }
  .answer.raw { white-space: pre-wrap; padding: 14px; }
  .line { display: flex; gap: 10px; padding: 8px 0; border-top: 1px solid #fde68a; }
  .line:first-child { border-top: 0; }
  .line .n { color: #a16207; font-variant-numeric: tabular-nums; flex: none; }
  .src { border-top: 1px dashed #e7e5e4; padding-top: 12px; margin-top: 12px; }
  .src:first-of-type { border-top: 0; padding-top: 0; margin-top: 0; }
  .src .fn { font-size: 12px; color: #78716c; font-family: ui-monospace, monospace; }
  .src .body { white-space: pre-wrap; }
  .btns { display: flex; gap: 10px; flex-wrap: wrap; }
  button { font: inherit; padding: 10px 16px; border-radius: 8px; border: 1px solid #d6d3d1;
           background: #fff; cursor: pointer; }
  button:hover { background: #f5f5f4; }
  button.on { border-color: #1c1917; background: #1c1917; color: #fff; }
  .ghost { color: #57534e; }
  input[type=text] { width: 100%; padding: 9px 12px; border: 1px solid #d6d3d1; border-radius: 8px; font: inherit; }
  .hint { font-size: 13px; color: #78716c; }
  .rule { border-collapse: collapse; }
  .rule td { padding: 4px 14px 4px 0; vertical-align: top; }
  details summary::-webkit-details-marker { color: #a8a29e; }
  .nav { display: flex; gap: 10px; align-items: center; }
  .err { color: #b91c1c; }
</style>
</head>
<body>
<header>
  <strong id="counter">-</strong>
  <div class="bar"><div id="fill"></div></div>
  <div class="nav">
    <button id="prev" class="ghost">← 이전</button>
    <button id="next" class="ghost">다음 →</button>
    <button id="jump" class="ghost">안 매긴 곳으로</button>
    <input type="text" id="goto" placeholder="번호" style="width:64px; text-align:center">
  </div>
</header>
<main>
  <div class="card">
    <h2>기준</h2>
    <p style="margin:0 0 10px"><strong>답변이 말한 내용이 아래 근거에서 찾아지는가</strong>, 이것만 봅니다.</p>
    <table class="rule">
      <tr><td><strong>1.0</strong></td><td>답변이 말한 게 <strong>전부</strong> 근거에 있다</td></tr>
      <tr><td><strong>0.5</strong></td><td>있는 것과 없는 것이 <strong>섞였다</strong> (답변이 여러 가지를 말할 때만 나옵니다)</td></tr>
      <tr><td><strong>0.0</strong></td><td>답변이 말한 게 <strong>근거에 없다</strong></td></tr>
    </table>
    <ul class="hint" style="margin:12px 0 0; padding-left:18px">
      <li>세는 것은 <strong>답변의 주장</strong>입니다. 근거를 몇 건 썼는지는 안 봅니다.
          근거 1 하나에 다 들어 있어도 1.0 입니다.</li>
      <li>방향은 <strong>답변 → 근거</strong> 한쪽입니다. 근거에 답변보다 많은 내용이 적혀 있는 것,
          답변과 무관한 근거가 섞여 있는 것은 감점하지 않습니다.</li>
      <li>🔴 <strong>세상의 상식으로 맞는 말이어도 근거에 없으면 깎습니다.</strong>
          근거에서 계산하거나 추론해 낸 문장도 근거에 그 말이 없으면 없는 것입니다.</li>
      <li>표현이 달라도 뜻이 같으면 있는 것으로 봅니다("4단계" ↔ "네 등급").</li>
      <li>"자세한 내용은 담당자에게 문의하세요" 같은 안내 문구는 주장이 아니라 세지 않습니다.</li>
    </ul>
    <details style="margin-top:12px">
      <summary class="hint" style="cursor:pointer">0.5 는 언제 나오나 (예시)</summary>
      <div class="hint" style="margin-top:8px">
        답변: "직급은 사원, 선임, 책임, 수석의 4단계입니다. <u>승진 심사는 매년 12월에 진행합니다.</u>"<br>
        앞 문장은 근거에 있고 밑줄 친 문장은 근거 어디에도 없다면, 한 답변 안에 있는 것과 없는 것이
        섞였으므로 0.5 입니다. 답변이 한 가지만 말하면 0.5 가 나올 자리가 없습니다.
      </div>
    </details>
    <details style="margin-top:8px">
      <summary class="hint" style="cursor:pointer">라벨 파일에 적힌 원문 기준</summary>
      <div class="hint" id="readme" style="margin-top:8px"></div>
    </details>
  </div>
  <div class="card">
    <h2>질문</h2>
    <div class="q" id="question"></div>
    <div class="hint" id="gt" style="margin-top:8px"></div>
  </div>
  <div class="card">
    <h2>답변 · 한 줄씩 근거에서 찾아보세요</h2>
    <div class="answer" id="answer"></div>
    <div class="hint" style="margin-top:8px">
      마침표 기준으로 <strong>기계적으로</strong> 나눈 것입니다(내용 판단은 하지 않았습니다).
      한 줄 안에 알려준 정보가 둘이면 머릿속에서 더 쪼개서 보세요.
      <button id="raw" class="ghost" style="padding:2px 8px; font-size:12px; margin-left:6px">원문 보기</button>
    </div>
  </div>
  <div class="card">
    <h2>근거</h2>
    <div id="sources"></div>
  </div>
  <div class="card">
    <h2>충실성</h2>
    <div class="btns">
      <button data-v="1">1.0 · 전부 근거에 있다 <span class="hint">(1)</span></button>
      <button data-v="0.5">0.5 · 일부만 있다 <span class="hint">(2)</span></button>
      <button data-v="0">0.0 · 지어냈다 <span class="hint">(3)</span></button>
      <button data-v="">지우기 <span class="hint">(0)</span></button>
    </div>
    <div style="margin-top:14px">
      <input type="text" id="note" placeholder="메모 (선택). 왜 그렇게 봤는지 한 줄. 입력하면 바로 저장됩니다.">
    </div>
    <div class="hint" id="status" style="margin-top:10px"></div>
  </div>
</main>
<script>
// 데이터는 서버에서 한 번 받아 메모리에 두고, 라벨을 누를 때마다 서버에 한 건씩 보낸다.
// (전체를 통째로 올리면 브라우저 탭을 두 개 열었을 때 한쪽이 다른 쪽을 덮어쓴다)
let data = null, i = 0;

const $ = (id) => document.getElementById(id);

async function boot() {
  data = await (await fetch('/api/data')).json();
  $('readme').textContent = data._readme;
  i = firstUnlabeled();
  render();
}

function firstUnlabeled() {
  const k = data.cases.findIndex(c => c.label === null);
  return k === -1 ? 0 : k;
}

// 마침표·물음표·느낌표 뒤에서만 자른다. 뜻을 보고 자르는 것이 아니라 <글자>를 보고 자른다.
// 🔴 LLM 에게 "주장을 뽑아줘" 를 시키지 않는 이유: 그 순간 사람 기준자에 LLM 판단이 섞여
//    "LLM 채점자를 사람과 대조한다" 는 이 슬라이스의 전제가 무너진다.
function splitSentences(text) {
  return text.split(/(?<=[.!?])\s+/).map(t => t.trim()).filter(Boolean);
}

let rawMode = false;

function renderAnswer(text) {
  const box = $('answer');
  box.innerHTML = '';
  if (rawMode) { box.className = 'answer raw'; box.textContent = text; return; }
  box.className = 'answer';
  const parts = splitSentences(text);
  const marks = '①②③④⑤⑥⑦⑧⑨⑩';
  parts.forEach((t, k) => {
    const row = document.createElement('div');
    row.className = 'line';
    const n = document.createElement('span');
    n.className = 'n';
    n.textContent = k < marks.length ? marks[k] : (k + 1) + '.';
    const b = document.createElement('span');
    b.textContent = t;
    row.append(n, b);
    box.append(row);
  });
}

function render() {
  const c = data.cases[i];
  const done = data.cases.filter(x => x.label !== null).length;
  $('counter').textContent = `${i + 1} / ${data.cases.length} · 채움 ${done}`;
  $('fill').style.width = (done / data.cases.length * 100) + '%';
  $('question').textContent = c.question;
  $('gt').textContent = '참고로 둔 정답(질문 생성 때 만든 것): ' + c.ground_truth;
  renderAnswer(c.generated_answer);
  $('sources').innerHTML = '';
  c.sources.forEach((s, n) => {
    const d = document.createElement('div');
    d.className = 'src';
    const fn = document.createElement('div');
    fn.className = 'fn';
    fn.textContent = `근거 ${n + 1} · ${s.filename} · chunk ${s.chunk_id}`;
    const b = document.createElement('div');
    b.className = 'body';
    b.textContent = s.content;
    d.append(fn, b);
    $('sources').append(d);
  });
  document.querySelectorAll('[data-v]').forEach(btn => {
    const v = btn.dataset.v === '' ? null : parseFloat(btn.dataset.v);
    btn.classList.toggle('on', v !== null && c.label === v);
  });
  $('note').value = c.note || '';
  $('status').textContent = '';
}

async function setLabel(v, advance) {
  const c = data.cases[i];
  const res = await fetch('/api/label', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ case_id: c.case_id, label: v, note: $('note').value })
  });
  const out = await res.json();
  if (!res.ok) { $('status').innerHTML = '<span class="err">저장 실패: ' + out.error + '</span>'; return; }
  c.label = v;
  c.note = $('note').value;
  if (advance && v !== null && i < data.cases.length - 1) { i++; render(); }
  else { render(); $('status').textContent = '저장됨'; }
}

document.querySelectorAll('[data-v]').forEach(btn => {
  btn.onclick = () => setLabel(btn.dataset.v === '' ? null : parseFloat(btn.dataset.v), true);
});
$('prev').onclick = () => { if (i > 0) { i--; render(); } };
$('next').onclick = () => { if (i < data.cases.length - 1) { i++; render(); } };
$('jump').onclick = () => { i = firstUnlabeled(); render(); };
$('raw').onclick = () => { rawMode = !rawMode; $('raw').textContent = rawMode ? '나눠 보기' : '원문 보기'; renderAnswer(data.cases[i].generated_answer); };
$('note').onchange = () => setLabel(data.cases[i].label, false);
$('goto').onchange = () => {
  // 번호로 바로 이동. 재검토처럼 특정 건만 다시 볼 때 44번 다음을 누르지 않게 한다.
  const n = parseInt($('goto').value, 10);
  if (n >= 1 && n <= data.cases.length) { i = n - 1; render(); }
  $('goto').value = '';
  $('goto').blur();
};

// 키보드: 숫자로 채점, 화살표로 이동. 메모 칸에 있을 때는 가로채지 않는다.
document.addEventListener('keydown', (e) => {
  if (e.target.tagName === 'INPUT') return;
  const map = { '1': 1, '2': 0.5, '3': 0, '0': null };
  if (e.key in map) { e.preventDefault(); setLabel(map[e.key], true); }
  if (e.key === 'ArrowLeft') $('prev').click();
  if (e.key === 'ArrowRight') $('next').click();
});

boot();
</script>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="사람 라벨링을 돕는 로컬 페이지를 띄운다")
    p.add_argument("--path", default=DEFAULT_PATH)
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-open", action="store_true", help="브라우저를 자동으로 열지 않는다")
    a = p.parse_args(argv)
    return serve(a.path, a.port, not a.no_open)


if __name__ == "__main__":
    raise SystemExit(main())
