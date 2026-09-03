"use client";

/*
 * ─────────────────────────────────────────────────────────────────────────────
 * ReceptionHero — 랜딩 히어로 "안내 데스크"
 * ─────────────────────────────────────────────────────────────────────────────
 * Claude Design 의 `AllDap Reception Hero.dc.html` 을 React 로 옮긴 것이다.
 * 원본은 three.js 3D 씬이었는데, <의존성 없이> 가려고 CSS/DOM 판으로 다시 받았다.
 * 그래서 이 파일에 외부 라이브러리가 하나도 안 들어간다 — 디오라마 전체가
 * 그냥 `<div>` + gradient + border-radius + box-shadow 다.
 *
 * ── 왜 "use client" 인가 ────────────────────────────────────────────────────
 * 스크롤 위치·마우스 위치를 매 프레임 읽어 DOM 을 직접 만진다. 서버에는
 * window 도 requestAnimationFrame 도 없다. 그래서 이 파일부터 브라우저 코드다.
 * (SEO 용 metadata 는 서버 컴포넌트에서만 export 할 수 있어서, 이 컴포넌트를
 *  부르는 app/page.tsx 는 서버 컴포넌트로 남겨뒀다.)
 *
 * ── 왜 useState 가 아니라 useRef 로 스크롤 진행도를 다루나 ──────────────────
 * 진행도 p 는 <매 프레임> 바뀐다. state 에 넣으면 초당 60번 리렌더가 돌아
 * 화면이 버벅인다. 그래서 p 는 ref 에 두고 `node.style.transform = ...` 으로
 * DOM 을 직접 쓴다. React 가 관여할 필요가 없는 값이다.
 * 반대로 armsOpen 은 <구조가 바뀌는> 상태(버튼 글자까지 바뀐다)라 state 가 맞다.
 *
 * ── 왜 인라인 style 인가 (프로젝트는 Tailwind 인데) ─────────────────────────
 * 디오라마는 1440×900 좌표계 위에 픽셀 단위로 배치된 오브젝트 60여 개다.
 * 디자인 스펙이 이미 raw CSS 수치로 확정돼 있어서, Tailwind 클래스로 옮기면
 * `left-[594px] top-[472px]` 같은 임의값 클래스가 될 뿐 읽기만 나빠진다.
 * UI 레이어(헤더·CTA)도 원본 수치를 그대로 유지하려고 같은 방식으로 뒀다.
 */

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

/** 씬의 기준 좌표계. 모든 오브젝트 위치가 이 크기 안의 절대 좌표다. */
const SCENE_W = 1440;
const SCENE_H = 900;

/* ── 진행 방식 ─────────────────────────────────────────────────────────────
 * 스크롤 한 번이 <문 하나>를 연다. 그 뒤로는 입력과 무관하게 정해진 시간 동안
 * 그 문이 끝까지 열리고, 열린 문은 우리를 지나쳐 뒤로 사라진다.
 * 문을 다 지나야 안내 데스크와 로봇이 드러나고, 거기서 CTA 가 떠 있다.
 *
 * 입력량에 비례해 쌓는 방식(굴린 만큼 들어감)도 만들어봤지만, 사용자가
 * <계속 굴려야> 장면이 진행돼서 구경이 아니라 작업이 됐다. 단계 방식이면
 * 한 번 굴리고 손을 떼도 그 문이 끝까지 열린다.
 */

/** 문 하나를 지나는 데 걸리는 시간(ms). <키우면 더 느긋해진다.> */
const STEP_DURATION_MS = 1150;

/**
 * 이 탭에서 이미 문을 다 열어봤는가. 값은 쓰지 않고 <있느냐>만 본다.
 *
 * sessionStorage 라 탭을 닫으면 사라진다 — 처음 온 사람은 언제나 연출을 전부 보고,
 * 이미 본 사람만 건너뛴다. localStorage 로 두면 몇 달 뒤에 다시 온 사람도
 * 이 랜딩의 유일한 볼거리를 영영 못 보게 된다.
 */
const SEEN_KEY = "alldap:hero-seen";

/**
 * 마지막 장면 우상단 메뉴. `(site)` 헤더(web/app/(site)/layout.tsx)와 <같은 항목>이라
 * 두 화면에서 같은 곳으로 간다.
 *
 * ⚠️ 고용하기(/auth)는 넣지 않는다. 가운데 CTA 가 이미 그 자리이고, 같은 목적지를
 *    한 화면에 두 번 두면 "어느 쪽을 눌러야 하나"가 된다.
 * ⚠️ 문이 열리는 동안에는 이 메뉴가 보이지 않는다. 구석 메뉴를 걷어낸 결정(f66eff0,
 *    "기능은 레버가 대신한다")은 그 구간에서 그대로 유지된다.
 */
const SCENE_NAV = [
  { label: "기능", href: "/features" },
  { label: "요금제", href: "/pricing" },
  { label: "FAQ", href: "/faq" },
] as const;

const ACCENT = "#7ED0C0";

/**
 * 지나는 문의 개수.
 *
 * 원래는 구석 메뉴 3개(기능·요금제·FAQ)가 각각 문이었다. 요금제·FAQ 를 빼면서
 * 문도 하나가 됐고, 남은 <기능>은 페이지로 보내는 링크가 아니라 로봇 팔을
 * 내렸다 올리는 버튼이 됐다(아래 FEATURES).
 * 복도를 다시 길게 만들고 싶으면 이 숫자만 올리면 된다 — 문이 라벨을 들고 있지
 * 않으므로 개수 말고는 정할 것이 없다.
 *
 * ⚠️ 랜딩에서 /pricing · /faq 로 가는 길은 이제 없다. 다만 완전히 고립된 것은
 *    아니다 — (site) 레이아웃 헤더가 그 셋을 계속 링크한다(/auth · /features 등).
 */
const DOOR_COUNT = 2;

/**
 * 로봇 팔이 내려와 들고 있는 기능 목록.
 *
 * label 은 판에 <한 줄>로 걸린다(줄바꿈 없음). detail 은 마우스를 올렸을 때만 펼쳐진다.
 * ⚠️ detail 문구는 `/features` 페이지의 설명을 <그대로> 옮겼다. 랜딩만 다른 말을 하면
 *    같은 제품이 두 화면에서 다른 소개를 하게 된다. label 은 그 제목을 짧게 줄인 것이라
 *    새로 지어낸 주장이 아니다.
 * len 은 팔 길이(px) — 전부 같으면 팔이 아니라 <표>로 보인다.
 */
const FEATURES = [
  {
    x: 13,
    len: 104,
    label: "한글 문서 그대로",
    detail:
      "PDF · DOCX · HWPX · TXT · MD 를 지원합니다. 국내 규정과 안내문 상당수가 한글 문서인데, 비개발자용 챗봇 빌더 상당수가 이를 다루지 못합니다.",
  },
  {
    x: 31.5,
    len: 176,
    label: "출처가 붙는 답변",
    detail:
      "질문과 가까운 문서 조각을 찾아 그것만 근거로 답합니다. 답변 아래에 출처가 표시되므로 관리자가 맞는지 바로 확인할 수 있습니다.",
  },
  {
    x: 50,
    len: 82,
    label: "모르면 답하지 않음",
    detail:
      "근거를 못 찾으면 지어내는 대신 담당자에게 문의하라고 안내합니다. 검색 단계와 생성 단계에 방어선을 두 겹으로 두었습니다.",
  },
  {
    x: 68.5,
    len: 166,
    label: "품질을 숫자로",
    detail:
      "문서에서 테스트 질문을 자동 생성하고, 답변을 다른 계열의 모델이 채점합니다. 검색 설정을 바꿔가며 같은 질문으로 재실행해 before/after 를 비교할 수 있습니다.",
  },
  {
    // ⚠️ 오른쪽 끝만 팔이 길다. 짧게 두면 판이 오른쪽 위 "도입 문의" 와 겹친다.
    x: 85,
    len: 222,
    label: "설치는 한 줄",
    detail:
      "고객 사이트에 한 줄을 붙여넣으면 우측 하단에 상담 버튼이 생깁니다. 허용한 도메인 밖에서는 열리지 않습니다.",
  },
] as const;

/**
 * 진행도를 나누는 구간 수 = 문 + 마지막 다가감 한 구간.
 * 마지막 구간이 따로 필요한 이유: 문이 열린 <직후>에 로봇이 저 멀리 있으면
 * "만났다"가 아니라 "보인다"에 그친다. 한 구간을 더 남겨 다가가야 얼굴이 된다.
 * ⚠️ 이건 <진행도>의 구간 수이지 사용자가 밟는 걸음 수가 아니다. 그 마지막 구간은
 *    스크롤 한 번이 아니라 마지막 문 열기와 한 전환으로 이어 붙는다(stepBy 참고).
 */
const STEPS = DOOR_COUNT + 1;

/**
 * 문을 다 지나 안내 데스크가 드러나는 지점(진행도 0~1 기준).
 * ⚠️ 이 값을 숫자로 박아두면 안 된다 — 문 개수를 3개에서 1개로 줄였을 때
 *    CTA 가 영영 안 뜨는 버그가 실제로 났다(드러나는 지점이 0.75 → 0.5 로
 *    옮겨졌는데 상수는 0.75 를 보고 있었다). 개수에서 계산한다.
 */
const REVEAL = DOOR_COUNT / STEPS;

/** 0~1 로 자른 뒤 부드럽게 만드는 보간. 스크롤 매핑은 전부 이걸 쓴다. */
function smoothstep(a: number, b: number, x: number) {
  const k = Math.min(1, Math.max(0, (x - a) / (b - a)));
  return k * k * (3 - 2 * k);
}
const mix = (a: number, b: number, k: number) => a + (b - a) * k;

export function ReceptionHero() {
  /* 로봇 팔이 내려와 있는가. 구조가 바뀌는 상태라 ref 가 아니라 state 다
     (버튼 글자도 이 값에 따라 바뀐다). */
  const [armsOpen, setArmsOpen] = useState(false);

  /* 끝까지 봤다는 사실을 이미 저장했는가. sessionStorage 쓰기는 동기 I/O 라
     매 프레임 부르면 애니메이션 프레임을 갉아먹는다. 한 번만 쓰려고 둔다. */
  const seenSavedRef = useRef(false);

  const scrollRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<HTMLDivElement>(null);
  const cloudsRef = useRef<HTMLDivElement>(null);
  const wallRef = useRef<HTMLDivElement>(null);
  const headRef = useRef<HTMLDivElement>(null);
  const deskRef = useRef<HTMLDivElement>(null);
  const frontRef = useRef<HTMLDivElement>(null);
  const eyeLRef = useRef<HTMLDivElement>(null);
  const eyeRRef = useRef<HTMLDivElement>(null);
  const mouthRef = useRef<HTMLDivElement>(null);
  const bulbRef = useRef<HTMLDivElement>(null);
  /* 인사 팻말. 스크롤이 시작되면 팔이 걷어 올린다(모양은 CSS 가 정한다). */
  const greetRef = useRef<HTMLDivElement>(null);
  const ctaRef = useRef<HTMLDivElement>(null);
  /* 우상단 메뉴. CTA 와 <같은 값>으로 함께 나타난다. */
  const navRef = useRef<HTMLElement>(null);
  const hintRef = useRef<HTMLButtonElement>(null);
  /* 문 레이어들. 매 프레임 DOM 을 직접 만지므로 배열 ref 로 모아 둔다.
     ⚠️ 아래 JSX 의 ref 콜백을 반드시 중괄호로 감쌀 것 —
        React 19 부터 ref 콜백이 <반환한 값을 정리(cleanup) 함수로 취급>한다.
        `ref={(n) => (arr[i] = n)}` 처럼 화살표로 값을 반환하면 노드를 정리 함수로
        오해해 런타임 에러가 난다. */
  const doorRefs = useRef<(HTMLDivElement | null)[]>([]);
  /* 로봇을 누르면 데모 화면으로 간다. 문 뒤에 있는 동안에는 눌리면 안 되므로
     레버와 같은 이유로 클릭 가능 여부를 진행도에 따라 켜고 끈다. */
  const robotHitRef = useRef<HTMLAnchorElement>(null);
  /* 마지막 문에 붙은 레버. 문에 <타고> 있어서 문이 열리면 함께 밀려나간다. */
  const leverRef = useRef<HTMLDivElement>(null);

  /* 매 프레임 읽고 쓰는 값들. state 로 두면 리렌더가 폭주한다. */
  const anim = useRef({
    p: 0,          // 현재 진행도(관성 적용된 값)
    target: 0,     // 스크롤이 알려준 목표 진행도
    step: 0,       // 사용자가 밟은 단계 (0 ~ DOOR_COUNT). target 은 stepBy 참고 — 마지막 단계만 1 이다
    mx: 0, my: 0,  // 커서 현재값
    mtx: 0, mty: 0,// 커서 목표값
    fit: 1,        // 씬(1440×900)을 화면에 채우는 배율
    shake: 1,      // prefers-reduced-motion 이면 0
    touchY: 0,     // 터치 시작 y
    transFrom: 0,  // 이번 전환의 출발 진행도
    transStart: 0, // 전환 시작 시각(ms). 0 이면 전환 중이 아니다
    /* 이번 전환의 길이(ms). 전환마다 <이동 거리가 다르므로> 고정값을 쓸 수 없다.
       마지막 전환은 다른 단계의 2배를 움직이는데, 길이를 고정하면 그 구간만 2배 빨라져
       문이 열리자마자 카메라가 튀어 들어간다. */
    transMs: STEP_DURATION_MS,
    cloudBase: [] as { own: number; slot: number }[],
    cloudSpan: 2800,
  });

  /**
   * 문 하나만큼(한 단계) 앞뒤로 옮기는 전환을 <시작>시킨다. 여기서는 목적지와
   * 시작 시각만 정하고, 실제 재생은 rAF 루프가 시간을 보며 한다.
   * 휠·스와이프·키·힌트 클릭이 전부 이 한 곳으로 모인다.
   */
  const stepBy = useCallback((dir: 1 | -1) => {
    const a = anim.current;
    // 문이 열리는 <중>에는 입력을 받지 않는다. 안 막으면 트랙패드 한 번에
    // wheel 이벤트가 수십 개 날아와 문 세 개를 한 프레임에 지나쳐 버린다.
    if (a.transStart > 0) return;
    /* 사용자가 밟는 단계는 <문 개수>까지다. 예전에는 STEPS(= 문 + 1)까지 밟을 수 있어서,
       고용하기가 뜬 뒤에도 스크롤이 한 번 더 먹으며 카메라만 로봇 앞으로 다가갔다.
       그 마지막 걸음은 사라진 게 아니라 아래 target 계산에서 <마지막 문 열기와 한
       전환으로 합쳐졌다>. */
    const next = Math.min(DOOR_COUNT, Math.max(0, a.step + dir));
    if (next === a.step) return; // 양 끝에서는 더 가지 않는다
    a.step = next;
    /* 화면이 움직이면 팔은 걷는다. 안 그러면 문이 닫히거나 로봇에게 다가가는
       동안에도 팔이 천장에 매달린 채 따라다닌다. */
    setArmsOpen(false);
    // <현재 위치>에서 출발한다. 전환 도중에 방향을 바꿔도 튀지 않는다.
    a.transFrom = a.p;
    /* 마지막 단계의 목적지는 문이 다 열리는 지점(REVEAL)이 아니라 <끝>(1)이다.
       그래야 한 번의 전환 안에서 앞부분은 마지막 문이 열리고(→REVEAL),
       뒷부분은 카메라가 로봇 앞으로 들어간다(REVEAL→1).
       ⚠️ STEPS 나 REVEAL 을 바꾸지 않는다 — 문 열림 구간·CTA 페이드·로봇 클릭 조건이
          전부 그 둘에서 계산되므로 한꺼번에 흔들린다(REVEAL 선언부 주석 참고). */
    a.target = next === DOOR_COUNT ? 1 : next / STEPS;
    /* 길이는 이동 거리에 비례시킨다. 한 단계(1/STEPS)를 움직이면 STEP_DURATION_MS 그대로고,
       마지막 전환은 그 2배를 움직이므로 2배 길어진다 — 눈에 보이는 속도가 같아진다. */
    a.transMs = STEP_DURATION_MS * Math.abs(a.target - a.transFrom) * STEPS;
    a.transStart = performance.now();
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    const stage = stageRef.current;
    if (!el || !stage) return;

    // 흔들림을 싫어하는 사용자 설정을 존중한다. 진폭 0 이면 화면이 완전히 정지한다.
    anim.current.shake = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 1;

    /* 이 탭에서 이미 끝까지 본 적이 있으면 연출을 재생하지 않고 <마지막 상태로 놓는다>.
       /demo 에 갔다가 뒤로가기나 로고로 돌아오면 문부터 다시 열어야 했던 것이 이 화면의
       불편이었다. 전환(transStart)을 걸지 않으므로 애니메이션 없이 그 자리에서 시작한다.

       ⚠️ 읽기를 이 effect <안>에서 하는 이유: 서버에는 sessionStorage 가 없다.
          초기 렌더에서 읽으면 서버가 그린 HTML 과 브라우저의 첫 렌더가 어긋난다
          (이 저장소가 로그인 유지에서 같은 부류의 버그를 이미 한 번 냈다). */
    try {
      if (sessionStorage.getItem(SEEN_KEY)) {
        const a = anim.current;
        a.step = DOOR_COUNT;
        a.p = 1;
        a.target = 1;
        a.transStart = 0; // 전환 중이 아니라 <이미 도착한> 상태다
        seenSavedRef.current = true; // 이미 저장돼 있으니 다시 쓸 필요가 없다
      }
    } catch {
      /* 사파리 사생활 보호 모드 등에서는 sessionStorage 접근 <자체>가 예외를 던진다.
         기억을 못 하는 것은 불편일 뿐이라, 연출을 처음부터 보여주고 넘어간다. */
    }

    /* ── 입력: 굴린 만큼 진행도에 쌓는다 ──────────────────────────────────
     * passive:false 로 걸고 preventDefault 한다. 페이지가 실제로 스크롤되면
     * 화면이 밀려버려서, 이 히어로는 "스크롤"이 아니라 <스크롤 제스처>만 받는다. */
    const onWheel = (e: WheelEvent) => {
      // Ctrl(트랙패드 핀치 포함) + 휠은 브라우저 확대다. 여기서 막으면 이 화면에서는
      // 확대가 안 되고 문만 열린다 — 확대는 접근성 기능이라 가로채면 안 된다.
      if (e.ctrlKey) return;
      e.preventDefault();
      if (Math.abs(e.deltaY) < 4) return; // 손 떨림 수준의 미세 입력 무시
      // 방향만 본다. 얼마나 세게 굴렸는지는 안 본다 — 연출 길이는 항상 같아야 한다.
      stepBy(e.deltaY > 0 ? 1 : -1);
    };
    const onTouchStart = (e: TouchEvent) => {
      anim.current.touchY = e.touches[0].clientY;
    };
    const onTouchEnd = (e: TouchEvent) => {
      const dy = anim.current.touchY - e.changedTouches[0].clientY;
      if (Math.abs(dy) < 40) return; // 탭이나 손 떨림은 스와이프가 아니다
      stepBy(dy > 0 ? 1 : -1);
    };
    /* 네이티브 스크롤을 없앴으므로 키보드 이동도 우리가 직접 붙여야 한다.
       안 붙이면 마우스 없는 사용자는 이 화면을 진행시킬 방법이 없다. */
    const onKey = (e: KeyboardEvent) => {
      // 입력창에 포커스가 있으면 키는 <글자>다. 가로채면 안 된다.
      if (document.activeElement instanceof HTMLInputElement) return;
      const down = e.key === "ArrowDown" || e.key === "PageDown" || e.key === " ";
      const up = e.key === "ArrowUp" || e.key === "PageUp";
      if (!down && !up) return;
      e.preventDefault();
      stepBy(down ? 1 : -1);
    };
    const onMove = (e: MouseEvent) => {
      anim.current.mtx = (e.clientX / window.innerWidth) * 2 - 1;
      anim.current.mty = (e.clientY / window.innerHeight) * 2 - 1;
    };
    const measure = () => {
      // 씬이 화면을 꽉 채우도록 <더 큰 쪽>에 맞춘다(레터박스가 생기면 안 된다).
      anim.current.fit = Math.max(stage.clientWidth / SCENE_W, stage.clientHeight / SCENE_H);
    };

    el.addEventListener("wheel", onWheel, { passive: false });
    el.addEventListener("touchstart", onTouchStart, { passive: true });
    el.addEventListener("touchend", onTouchEnd, { passive: true });
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousemove", onMove, { passive: true });
    window.addEventListener("resize", measure);

    const cl = cloudsRef.current;
    if (cl) {
      const step = anim.current.cloudSpan / cl.children.length;
      anim.current.cloudBase = Array.from(cl.children).map((c, i) => ({
        own: (c as HTMLElement).offsetLeft,
        slot: i * step,
      }));
    }
    measure();

    let raf = 0;
    const loop = () => {
      raf = requestAnimationFrame(loop);
      const a = anim.current;
      const now = performance.now();

      /* ── 줌 전환 ──────────────────────────────────────────────────────────
       * 시간 기반이다. "목표를 향해 매 프레임 조금씩"(지수 보간)이 아니라
       * <정해진 길이의 연출을 재생>한다. 지수 보간은 시작이 가장 빠르고 끝에서
       * 기어가는데, 우리가 원하는 건 반대다 — 살며시 출발해 살며시 멈추는 것.
       * smoothstep 이 그 곡선(ease-in-out)이다.
       * ⚠️ prefers-reduced-motion 이면 즉시 도착시킨다. 화면 전체가 확대되는 모션은
       *    전정기관에 민감한 사용자에게 실제로 불편을 준다. */
      if (a.transStart > 0) {
        if (a.shake === 0) {
          a.p = a.target;
          a.transStart = 0;
        } else {
          const k = Math.min(1, (now - a.transStart) / a.transMs);
          a.p = a.transFrom + (a.target - a.transFrom) * (k * k * (3 - 2 * k));
          if (k >= 1) a.transStart = 0;
        }
      }
      const p = a.p;

      /* 끝까지 왔다는 사실을 이 탭에 남긴다. 다음에 이 랜딩을 열면 문을 건너뛴다.
         0.999 로 재는 이유: 이 전환은 지수 보간이 아니라 <정해진 길이를 재생>하는
         방식이라(위 "줌 전환" 주석 참고) k >= 1 이면 p 는 target 에 정확히 도달한다.
         그런데도 딱 1 과 비교하지 않는 이유는 부동소수점이다 —
         transFrom + (target - transFrom) * eased 계산이 반올림 오차로 target 과
         1비트(ulp) 어긋날 수 있다. 게다가 마지막 프레임까지 기다릴 이유도 없다 —
         저장은 한 번만 하면 충분하다. */
      if (!seenSavedRef.current && p >= 0.999) {
        seenSavedRef.current = true;
        try {
          sessionStorage.setItem(SEEN_KEY, "1");
        } catch {
          /* 저장 못 해도 이번 방문의 연출에는 영향이 없다. 다음에 다시 문부터 볼 뿐이다. */
        }
      }
      const t = now / 1000;

      /* ── 씬의 진행도(pz)는 문의 진행도(p)와 <따로 간다> ──────────────────
       * 문이 열리는 구간(p 0 → REVEAL(2/3))에서는 씬이 거의 멈춰 있고, 마지막 문을
       * 지난 뒤에야 다가간다. 하나로 묶으면 문이 반쯤 열렸을 때 이미 로봇이
       * 코앞에 와 있어서 "마지막 문에서 만난다"가 성립하지 않는다.
       * 아래에서 <문·카드는 p 를, 씬·카메라·시선은 pz 를> 쓴다. */
      const pz = smoothstep(REVEAL, 1, p);

      /* ── 문 ───────────────────────────────────────────────────────────────
       * 문 i 는 p 가 [i/STEPS, (i+1)/STEPS] 인 동안 열린다. q 가 그 구간 안의 진행도다.
       * 두 짝이 갈라지는 <동시에> 레이어 전체가 커지며 흐려진다. 옆으로 비켜나기만
       * 하면 "문이 열렸다"에 그치는데, 커지면서 사라져야 <우리가 그 문을 통과했다>가 된다.
       * 그래서 마지막 문이 열리고 나서야 안내 데스크가 드러난다. */
      for (let i = 0; i < DOOR_COUNT; i++) {
        const q = Math.min(1, Math.max(0, (p - i / STEPS) * STEPS));
        const eq = q * q * (3 - 2 * q); // 살며시 열리고 살며시 멈춘다
        const layer = doorRefs.current[i];
        if (layer) {
          // CSS 변수로 넘기는 이유: 문짝 두 짝 + 빛줄기까지 ref 를 세 개 더 두는 대신
          // 부모에 값 하나만 쓰면 자식들이 각자 calc() 로 받아 쓴다.
          layer.style.setProperty("--open", String(eq));
          /* 빛의 <세기>. 틈이 좁을 때가 "새어 나온다" 이고, 활짝 열린 뒤에도 남아 있으면
             빛이 아니라 문 사이에 낀 초록 판으로 보인다. 열릴수록 걷어낸다. */
          layer.style.setProperty("--glow", String(1 - smoothstep(0.06, 0.4, q)));
          layer.style.transform = `scale(${1 + eq * 1.25})`;
          layer.style.opacity = String(1 - smoothstep(0.62, 1, q));
          // 다 지난 문이 화면에 남아 클릭을 가로채면 안 된다
          layer.style.visibility = q >= 1 ? "hidden" : "visible";
        }
      }

      /* ── 레버 ── 마지막 문 앞에 <서 있을 때만> 보이고 당겨진다.
       * ⚠️ 클릭 가능 여부를 따로 끄는 이유: 레버는 마지막 문에 붙어 있고 그 문은
       *    처음에 앞 문 <뒤>에 가려 있다. 그런데 문짝은 pointerEvents 를 받지 않으므로,
       *    끄지 않으면 <닫힌 첫 문을 통과해> 레버가 당겨진다. 보이지도 않는 것이 눌리는 셈이다. */
      const lever = leverRef.current;
      if (lever) {
        const leverDoor = (DOOR_COUNT - 1) / STEPS;
        const ql = Math.min(1, Math.max(0, (p - leverDoor) * STEPS));
        const f =
          smoothstep(leverDoor - 0.07, leverDoor + 0.01, p) *
          (1 - smoothstep(0.05, 0.3, ql));
        lever.style.opacity = String(f);
        lever.style.pointerEvents = f > 0.8 ? "auto" : "none";
        lever.style.visibility = f > 0.04 ? "visible" : "hidden";
      }

      /* 로봇은 <다 드러난 뒤에만> 눌린다. 문짝이 pointerEvents 를 받지 않으므로
         끄지 않으면 닫힌 문을 통과해 눌린다(레버와 같은 함정이다). */
      const hit = robotHitRef.current;
      /* ⚠️ 기준은 pz 가 아니라 p 다. pz 는 <마지막 한 걸음>에서야 0 에서 오르기 시작해서,
         pz 로 걸면 로봇이 화면에 뻔히 보이는데도 눌리지 않는 구간이 생긴다. */
      if (hit) {
        const live = p > REVEAL - 0.02;
        hit.style.pointerEvents = live ? "auto" : "none";
        /* ⚠️ pointerEvents 만으로는 부족하다. 그건 <마우스·터치>만 막을 뿐,
           키보드 Tab 은 화면에 안 보이는 링크도 그대로 찾아가 포커스를 준다.
           레버와 같은 함정이다 — visibility 를 함께 꺼야 포커스도 함께 막힌다. */
        hit.style.visibility = live ? "visible" : "hidden";
        /* 말풍선을 띄우는 것도 같은 조건이다. 클래스만 토글하고 <모양은 CSS 가> 정한다 —
           떠 있는 애니메이션까지 매 프레임 계산할 이유가 없다.
           (toggle 은 값이 그대로면 아무 일도 하지 않아 매 프레임 불러도 괜찮다) */
        hit.classList.toggle("is-live", live);
      }

      /* ── UI 레이어: 스크롤에 따라 사라지고 나타난다 ── */
      /* 스크롤이 시작되면 팻말을 걷어 올린다. 문이 열리는 것과 <동시에> 일어나야
         "로봇이 인사를 거두고 문을 연다" 로 읽힌다. 올라가는 모양·속도는 CSS 가 갖는다. */
      const greet = greetRef.current;
      if (greet) greet.dataset.open = p < 0.02 ? "true" : "false";

      const hint = hintRef.current;
      if (hint) {
        const f = 1 - smoothstep(0.01, 0.12, p);
        hint.style.opacity = String(f);
        hint.style.pointerEvents = f < 0.1 ? "none" : "auto";
        /* 🔴 button 인데 visibility 를 안 끄면 안 보이는 채로 Tab 포커스를 받는다.
           CTA·로봇 링크·레버에서 세 번 겪은 함정의 네 번째다. 예전에는 이 구간을
           스쳐 지나가고 말아서 안 드러났는데, 이번 브랜치의 복원 기능(SEEN_KEY) 때문에
           마지막 장면이 재방문자의 <첫 화면>이 되면서 힌트가 숨은 상태가 상주 화면이 됐다 —
           그만큼 노출이 커져 지금 고친다. */
        hint.style.visibility = f > 0.01 ? "visible" : "hidden";
      }
      /* 마지막 문이 열려 로봇이 드러나는 순간에 이미 떠 있어야 한다. 그전까지 화면을
         진행시키던 힌트는 첫 문에서 사라졌으므로, 여기서 CTA 마저 늦게 뜨면
         <누를 것도 없고 다음으로 갈 안내도 없는> 정지 화면이 된다.
         ⚠️ 블록 밖에 둔 이유: 아래 우상단 메뉴가 <같은 값>을 써야 한다.
            따로 계산하면 둘이 어긋나고, 한쪽만 고쳤을 때 조용히 벌어진다. */
      const ctaIn = smoothstep(REVEAL - 0.12, REVEAL + 0.01, p);

      const cta = ctaRef.current;
      if (cta) {
        cta.style.opacity = String(ctaIn);
        cta.style.pointerEvents = ctaIn > 0.6 ? "auto" : "none";
        /* ⚠️ pointerEvents 는 클릭만 막는다. opacity 0 인 동안에도 Tab 키는
           이 링크를 그대로 찾아가 포커스를 주고 Enter 로 /auth 까지 이동한다 —
           방문자에게는 아무것도 안 보이는 상태에서 일어나는 이동이라 혼란스럽다.
           레버·로봇 링크와 같은 이유로 visibility 를 함께 토글한다. */
        cta.style.visibility = ctaIn > 0.01 ? "visible" : "hidden";
        cta.style.transform = `translateX(-50%) translateY(${26 - ctaIn * 26}px)`;
      }

      /* 우상단 메뉴는 CTA 와 <같은 값>으로 나타난다. */
      const nav = navRef.current;
      if (nav) {
        nav.style.opacity = String(ctaIn);
        nav.style.pointerEvents = ctaIn > 0.6 ? "auto" : "none";
        /* 🔴 opacity 만 끄면 안 된다. 안 보이는 상태에서도 Tab 키는 이 링크들을 찾아가
           포커스를 주고 Enter 로 이동시킨다 — 방문자에게는 아무것도 안 보이는 상태에서
           일어나는 이동이다. CTA·로봇 링크·레버에서 세 번 겪은 함정이라 함께 토글한다. */
        nav.style.visibility = ctaIn > 0.01 ? "visible" : "hidden";
      }

      /* ── 핸드헬드 카메라: 주파수가 다른 사인 여러 개를 겹친다 ──
         하나만 쓰면 규칙적으로 흔들려 "기계"처럼 보인다. 서로 안 맞는 주기를
         겹쳐야 사람이 카메라를 들고 있는 것처럼 불규칙해진다. */
      const s = a.shake;
      const sw = (f: number, amp: number, ph: number) => Math.sin(t * f + ph) * amp;
      const shX = (sw(0.23, 11, 0.4) + sw(0.61, 3.8, 1.9) + sw(1.7, 1.0, 3.1)) * s;
      const shY = (sw(0.19, 8.5, 2.2) + sw(0.73, 2.8, 0.7) + sw(2.1, 0.8, 1.2)) * s;
      const roll = (sw(0.17, 0.5, 0.9) + sw(0.47, 0.2, 2.4)) * s;
      const breath = 1 + Math.sin(t * 0.31) * 0.006 * s;

      /* ── 줌: 멀리서 데스크 전체 → 카운터 → 로봇 얼굴, <한 번에 이어서> ──
         원본 3D 는 카메라를 z 로 밀어넣었는데, 여기서는 scale + transform-origin
         이동으로 같은 인상을 만든다. origin 이 함께 움직여야 "다가간다"가 되고,
         고정하면 그냥 "커진다"로 보인다.

         🔴 예전에는 구간을 둘로 나누고 <각 구간에 이징을 따로> 걸었다
         (`seg = pz < 0.55 ? pz/0.55 : (pz-0.55)/0.45` 를 매번 smoothstep).
         그러면 속도가 0 → 1.91 → <0> → 2.43 → 0 이 되어, 카메라가 절반쯤에서
         완전히 멈췄다가 다시 출발한다 — 한 번 다가가는 게 아니라 "두 번 확대"로 보인다.
         이징을 전체에 한 번만 걸어 속도가 도중에 0 이 되지 않게 했다.

         ⚠️ 거쳐 가는 화면은 그대로다. 카운터 크기(1.42)를 지나는 지점이
            pz 0.55 → 0.49 로 옮겨질 뿐이라 "데스크 → 카운터 → 얼굴" 순서는 유지된다.
            사라진 것은 그 중간의 <멈춤>뿐이다. */
      const zoom = mix(0.72, 2.15, smoothstep(0, 1, pz));
      const ox = mix(50, 48.6, smoothstep(0, 1, pz));
      const oy = mix(58, 38, smoothstep(0, 1, pz));
      const panY = mix(9, -1, smoothstep(0, 0.7, pz));

      const scene = sceneRef.current;
      if (scene) {
        scene.style.transformOrigin = `${ox}% ${oy}%`;
        scene.style.transform =
          `translate(${shX}px,${shY + panY * a.fit * 0.9}px) ` +
          `rotate(${roll}deg) scale(${a.fit * zoom * breath})`;
      }

      /* ── 패럴랙스: 멀리 있는 층일수록 덜 움직인다 ──
         이게 3D 없이 깊이를 만드는 유일한 장치다. 전부 같은 비율로 움직이면
         한 장의 그림을 확대하는 것과 구분이 안 된다. */
      const far = (ref: React.RefObject<HTMLDivElement | null>, k: number) => {
        const n = ref.current;
        if (n) n.style.transform = `translate(${-shX * k * 0.5}px,${-panY * k * 2.2}px) scale(${1 - k * 0.06 + pz * k * 0.05})`;
      };
      const near = (ref: React.RefObject<HTMLDivElement | null>, k: number) => {
        const n = ref.current;
        if (n) n.style.transform = `translate(${shX * k * 0.35}px,0) scale(${1 + pz * k * 0.045})`;
      };
      far(cloudsRef, 1.0);
      far(wallRef, 0.62);
      near(deskRef, 0.5);
      near(frontRef, 1.0);

      /* 구름은 화면 밖으로 나가면 반대편으로 돌아온다(무한 흐름) */
      const clouds = cloudsRef.current;
      if (clouds) {
        for (let i = 0; i < clouds.children.length; i++) {
          const c = clouds.children[i] as HTMLElement;
          const b = a.cloudBase[i];
          if (!b) continue;
          let x = (b.slot + t * 13) % a.cloudSpan;
          if (x < 0) x += a.cloudSpan;
          c.style.transform = `translate(${x - 680 - b.own}px,${Math.sin(t * 0.29 + i * 1.7) * 6}px)`;
        }
      }

      /* ── 로봇: 몸은 고정, 시선만 커서를 따라간다 ──
         gaze 를 곱하는 이유: 멀리서(p 작을 때) 눈알이 굴러가면 소름끼친다.
         가까이 왔을 때만 반응하게 해야 "쳐다본다"가 애교로 읽힌다. */
      a.mx += (a.mtx - a.mx) * 0.09;
      a.my += (a.mty - a.my) * 0.09;
      const gaze = smoothstep(0.3, 0.75, pz);
      if (headRef.current) {
        headRef.current.style.transform =
          `translate(${a.mx * 7 * gaze}px,${a.my * 4 * gaze}px) ` +
          `rotate(${a.mx * 1.6 * gaze}deg)`;
      }
      const cyc = t % 4.6;
      const blink = cyc < 0.14 ? Math.max(0.08, Math.abs(cyc - 0.07) / 0.07) : 1;
      const ex = a.mx * 7 * gaze;
      const ey = a.my * 5 * gaze;
      /* ⚠️ 예전에는 여기 채팅 모달의 "말하는 중" 표정(hk, 눈 반쯤 감기·입 벌리기)이
         걸려 있었다. 모달을 걷어내며 hk 가 항상 0 으로 고정됐는데, 식만 남아 있으면
         죽은 채로 남는다. hk=0 을 그대로 대입해 식을 접었다(결과는 이전과 같다). */
      [eyeLRef, eyeRRef].forEach((r) => {
        const n = r.current;
        if (!n) return;
        n.style.transform = `translate(${ex}px,${ey}px) scaleY(${blink})`;
        n.style.borderRadius = "12px";
      });
      if (mouthRef.current) {
        mouthRef.current.style.transform = `translate(${ex * 0.5}px,${ey * 0.4}px) scale(1,1)`;
      }
      if (bulbRef.current) {
        const g = 0.72 + Math.sin(t * 2.2) * 0.28;
        bulbRef.current.style.opacity = String(g);
        bulbRef.current.style.boxShadow = `0 0 ${18 + g * 20}px rgba(126,208,192,.85)`;
      }

    };
    raf = requestAnimationFrame(loop);

    return () => {
      cancelAnimationFrame(raf);
      el.removeEventListener("wheel", onWheel);
      el.removeEventListener("touchstart", onTouchStart);
      el.removeEventListener("touchend", onTouchEnd);
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("resize", measure);
    };
    // 사실상 마운트 시 1회만 건다. 나머지 값들은 전부 ref 라 최신값을 알아서 읽는다 —
    // state 를 의존성에 넣으면 그때마다 리스너와 rAF 루프가 통째로 재생성된다.
    // stepBy 는 useCallback([]) 이라 <절대 안 바뀌므로> 넣어도 재실행되지 않는다.
    // (경고를 억누르는 대신 넣는다 — 억누르면 나중에 진짜 의존성이 빠져도 안 보인다)
  }, [stepBy]);

  return (
    <div
      ref={scrollRef}
      style={{
        position: "relative",
        // 네이티브 스크롤이 없다. 휠·스와이프·키를 <제스처>로만 받아 단계를 옮긴다.
        // 그래서 높이는 딱 한 화면이고 넘치는 것은 잘라낸다.
        height: "100dvh",
        overflow: "hidden",
        background: "#EAE0DE",
        color: "#171514",
      }}
    >
      <div>
        <div
          ref={stageRef}
          style={{
            position: "absolute",
            inset: 0,
            overflow: "hidden",
            background: "radial-gradient(120% 90% at 50% 30%, #F2E9E7 0%, #E4D6D3 55%, #D6C5C2 100%)",
          }}
        >
          {/* ── 디오라마 ── 1440×900 좌표계. 화면 중앙에 두고 fit 배율로 채운다. */}
          <div
            ref={sceneRef}
            style={{
              position: "absolute",
              left: "50%",
              top: "50%",
              width: SCENE_W,
              height: SCENE_H,
              marginLeft: -SCENE_W / 2,
              marginTop: -SCENE_H / 2,
            }}
          >
            {/* 구름 — box-shadow 를 여러 겹 써서 덩어리 하나로 뭉게구름을 만든다 */}
            <div ref={cloudsRef} style={{ position: "absolute", left: -600, right: -600, top: 0, bottom: 0, pointerEvents: "none" }}>
              <div style={{ position: "absolute", left: 60, top: 120, width: 230, height: 96, borderRadius: 48, background: "#FBF7F6", boxShadow: "70px -34px 0 -12px #FBF7F6, -54px -22px 0 -22px #FBF7F6, 150px -6px 0 -22px #FBF7F6" }} />
              <div style={{ position: "absolute", left: 1080, top: 70, width: 270, height: 110, borderRadius: 55, background: "#FBF7F6", boxShadow: "-84px -40px 0 -14px #FBF7F6, 78px -26px 0 -26px #FBF7F6" }} />
              <div style={{ position: "absolute", left: 470, top: 44, width: 180, height: 74, borderRadius: 37, background: "#FDFAFA", boxShadow: "56px -26px 0 -12px #FDFAFA, -46px -14px 0 -20px #FDFAFA" }} />
              <div style={{ position: "absolute", left: 1210, top: 330, width: 150, height: 64, borderRadius: 32, background: "#FBF7F6", boxShadow: "-46px -22px 0 -12px #FBF7F6" }} />
              <div style={{ position: "absolute", left: 20, top: 392, width: 132, height: 58, borderRadius: 29, background: "#FBF7F6", boxShadow: "40px -20px 0 -12px #FBF7F6" }} />
              <div style={{ position: "absolute", left: 740, top: 158, width: 196, height: 82, borderRadius: 41, background: "#FBF7F6", boxShadow: "62px -30px 0 -14px #FBF7F6, -50px -16px 0 -22px #FBF7F6" }} />
              <div style={{ position: "absolute", left: 300, top: 286, width: 158, height: 66, borderRadius: 33, background: "#FDFAFA", boxShadow: "48px -24px 0 -12px #FDFAFA" }} />
              <div style={{ position: "absolute", left: 900, top: 376, width: 140, height: 60, borderRadius: 30, background: "#FBF7F6", boxShadow: "-42px -20px 0 -14px #FBF7F6" }} />
            </div>

            {/* 뒷벽 + 벽 장식(시계·액자·선반·책) */}
            <div ref={wallRef} style={{ position: "absolute", inset: 0, pointerEvents: "none" }}>
              <div style={{ position: "absolute", left: "50%", top: 34, width: 1180, height: 600, marginLeft: -590, borderRadius: "600px 600px 48px 48px", background: "linear-gradient(180deg,#F5EAE7 0%,#F0E2DF 46%,#E9D9D6 100%)", boxShadow: "inset 0 -30px 60px rgba(150,116,110,.14)" }} />
              <div style={{ position: "absolute", left: 246, top: 176, width: 132, height: 132, borderRadius: "50%", background: "#FFFFFF", border: "9px solid #F7F1EE", boxShadow: "0 10px 26px rgba(120,88,82,.12)" }} />
              <div style={{ position: "absolute", left: 308, top: 206, width: 5, height: 52, borderRadius: 3, background: "#2A2422", transformOrigin: "50% 100%", transform: "rotate(28deg)" }} />
              <div style={{ position: "absolute", left: 308, top: 222, width: 5, height: 36, borderRadius: 3, background: "#7A6C69", transformOrigin: "50% 100%", transform: "rotate(-64deg)" }} />
              <div style={{ position: "absolute", left: 962, top: 186, width: 196, height: 132, borderRadius: 12, background: "#D9D2EC", boxShadow: "0 12px 28px rgba(120,88,82,.14)", border: "8px solid #FFFFFF" }} />
              <div style={{ position: "absolute", left: 930, top: 372, width: 270, height: 15, borderRadius: 8, background: "#FFFFFF", boxShadow: "0 8px 20px rgba(120,88,82,.14)" }} />
              <div style={{ position: "absolute", left: 966, top: 314, width: 32, height: 58, borderRadius: 5, background: "#D79B84" }} />
              <div style={{ position: "absolute", left: 1006, top: 326, width: 28, height: 46, borderRadius: 5, background: "#E7C3C0" }} />
              <div style={{ position: "absolute", left: 1042, top: 306, width: 34, height: 66, borderRadius: 5, background: "#EFD6D3" }} />
            </div>

            {/* 바닥 */}
            <div style={{ position: "absolute", left: 0, right: 0, top: 560, bottom: 0, background: "linear-gradient(180deg,#E4D5D2 0%,#DCCBC8 100%)" }} />
            <div style={{ position: "absolute", left: "50%", top: 646, width: 1520, height: 300, marginLeft: -760, borderRadius: "50%", background: "radial-gradient(closest-side, rgba(150,112,106,.16), rgba(150,112,106,0))" }} />

            {/* 로봇 */}
            <div style={{ position: "absolute", left: 0, top: 0, width: "100%", height: "100%" }}>
              <div style={{ position: "absolute", left: 560, top: 596, width: 280, height: 52, borderRadius: "50%", background: "radial-gradient(closest-side, rgba(140,102,96,.26), rgba(140,102,96,0))" }} />
              <div style={{ position: "absolute", left: 594, top: 472, width: 212, height: 186, borderRadius: 74, background: "linear-gradient(170deg,#FFFBF9 0%,#F7F1EE 52%,#EADFDA 100%)", boxShadow: "inset -12px -14px 22px rgba(160,128,120,.16)" }} />
              <div style={{ position: "absolute", left: 652, top: 512, width: 96, height: 62, borderRadius: 22, background: ACCENT, boxShadow: "inset 0 -6px 12px rgba(0,0,0,.08), 0 0 22px rgba(126,208,192,.5)" }} />
              <div style={{ position: "absolute", left: 570, top: 482, width: 44, height: 150, borderRadius: 24, background: "linear-gradient(160deg,#FDF8F6,#EFE6E1)", transformOrigin: "50% 8%", transform: "rotate(22deg)", boxShadow: "inset -6px -6px 12px rgba(160,128,120,.14)" }} />
              <div style={{ position: "absolute", left: 786, top: 482, width: 44, height: 150, borderRadius: 24, background: "linear-gradient(200deg,#FDF8F6,#EFE6E1)", transformOrigin: "50% 8%", transform: "rotate(-22deg)", boxShadow: "inset 6px -6px 12px rgba(160,128,120,.14)" }} />
              <div style={{ position: "absolute", left: 510, top: 592, width: 60, height: 60, borderRadius: "50%", background: "linear-gradient(160deg,#FFFBF9,#EDE3DE)", boxShadow: "inset -5px -6px 10px rgba(160,128,120,.16)" }} />
              <div style={{ position: "absolute", left: 830, top: 592, width: 60, height: 60, borderRadius: "50%", background: "linear-gradient(200deg,#FFFBF9,#EDE3DE)", boxShadow: "inset 5px -6px 10px rgba(160,128,120,.16)" }} />

              <div ref={headRef} style={{ position: "absolute", left: 600, top: 290, width: 200, height: 196 }}>
                <div style={{ position: "absolute", left: -2, top: -38, width: 10, height: 46, marginLeft: 98, borderRadius: 6, background: "#EFE6E1" }} />
                <div ref={bulbRef} style={{ position: "absolute", left: 82, top: -64, width: 32, height: 32, borderRadius: "50%", background: ACCENT, boxShadow: "0 0 26px rgba(126,208,192,.85)" }} />
                <div style={{ position: "absolute", left: -30, top: 74, width: 36, height: 56, borderRadius: 18, background: "linear-gradient(160deg,#F9F3F0,#E9DED9)", boxShadow: "inset -4px -4px 8px rgba(160,128,120,.16)" }} />
                <div style={{ position: "absolute", left: 194, top: 74, width: 36, height: 56, borderRadius: 18, background: "linear-gradient(200deg,#F9F3F0,#E9DED9)", boxShadow: "inset 4px -4px 8px rgba(160,128,120,.16)" }} />
                <div style={{ position: "absolute", inset: 0, borderRadius: 66, background: "linear-gradient(165deg,#FFFCFB 0%,#F7F1EE 50%,#EBE0DB 100%)", boxShadow: "inset -14px -16px 26px rgba(160,128,120,.16), 0 18px 36px rgba(140,102,96,.18)" }} />
                <div style={{ position: "absolute", left: 22, top: 44, width: 156, height: 110, borderRadius: 38, background: "linear-gradient(170deg,#3A322F,#211C1A)", boxShadow: "inset 0 4px 10px rgba(0,0,0,.4)" }} />
                <div ref={eyeLRef} style={{ position: "absolute", left: 66, top: 80, width: 24, height: 38, borderRadius: 12, background: ACCENT, boxShadow: "0 0 16px rgba(126,208,192,.9)" }} />
                <div ref={eyeRRef} style={{ position: "absolute", left: 110, top: 80, width: 24, height: 38, borderRadius: 12, background: ACCENT, boxShadow: "0 0 16px rgba(126,208,192,.9)" }} />
                <div ref={mouthRef} style={{ position: "absolute", left: 86, top: 126, width: 28, height: 14, borderRadius: "0 0 20px 20px", background: ACCENT, boxShadow: "0 0 12px rgba(126,208,192,.75)" }} />
              </div>
            </div>

            {/* 로봇을 누르면 데모 화면(`/demo`)으로 간다.
                ⚠️ 예전에는 여기서 채팅 모달이 열렸다. 그런데 방문자가 이 봇이 무슨 문서를
                   가졌는지 모르는 채로 답을 받으면 <맞는지 틀리는지 판단할 수가 없다.>
                   그래서 문서를 전부 펼쳐놓고 대조할 수 있는 별도 화면으로 옮겼고,
                   모달과 전송 로직은 이 파일에서 걷어냈다.
                ⚠️ 그림 위에 투명한 링크를 얹는다. 그림 자체에 onClick 을 달면
                   키보드로 닿을 수도, 스크린리더가 읽을 수도 없다. */}
            <Link
              ref={robotHitRef}
              href="/demo"
              /* 이 화면은 문을 열고 들어온 곳이다. 나갈 때도 문이 열리며 도착해야
                 앞뒤가 이어진다. 이름표만 붙이고 <모양은 globals.css 가> 정한다. */
              transitionTypes={["door"]}
              aria-label="데모 페이지에서 직접 테스트해보기 — 이 봇이 학습한 문서를 전부 볼 수 있습니다"
              className="alldap-robot-hit"
              style={{ position: "absolute", left: 528, top: 272, width: 344, height: 396, cursor: "pointer", pointerEvents: "none", visibility: "hidden" }}
            />

            {/* 안내 데스크 + 소품 */}
            {/* 🐛 pointerEvents: "none" 이 <반드시> 필요하다.
                이 레이어는 씬 전체를 덮는 <div> 이고 위 로봇 링크보다 나중에 그려진다.
                그림이 투명해도 <상자는 마우스를 먹는다> — 없으면 로봇에 마우스를 올려도
                이 레이어가 가로채서 "테스트해보시겠어요?" 가 영영 안 뜬다(실제로 그랬다).
                디오라마는 전부 장식이라 마우스를 받을 이유가 없다. */}
            <div ref={deskRef} style={{ position: "absolute", left: 0, top: 0, width: "100%", height: "100%", pointerEvents: "none" }}>
              <div style={{ position: "absolute", left: "50%", top: 604, width: 720, height: 200, marginLeft: -360, borderRadius: "20px 20px 10px 10px", background: "linear-gradient(180deg,#F3DEDB 0%,#EFD6D3 40%,#E3C6C3 100%)", boxShadow: "0 26px 50px rgba(140,102,96,.22)" }} />
              <div style={{ position: "absolute", left: "50%", top: 576, width: 812, height: 34, marginLeft: -406, borderRadius: 12, background: "linear-gradient(180deg,#FFFFFF 0%,#F6EEEC 100%)", boxShadow: "0 10px 22px rgba(140,102,96,.18)" }} />
              <div style={{ position: "absolute", left: "50%", top: 648, width: 250, height: 60, marginLeft: -125, borderRadius: 14, background: "#FFFFFF", boxShadow: "0 8px 18px rgba(140,102,96,.14)" }} />
              <div style={{ position: "absolute", left: "50%", top: 670, width: 150, height: 15, marginLeft: -75, borderRadius: 8, background: "#7A6C69" }} />
              <div style={{ position: "absolute", left: 906, top: 452, width: 150, height: 104, borderRadius: 12, background: "#F7F1EE", boxShadow: "0 12px 24px rgba(140,102,96,.18)", transform: "rotate(-6deg)" }}>
                <div style={{ position: "absolute", inset: 9, borderRadius: 7, background: "linear-gradient(160deg,#DCEDE9,#C3E0D9)" }} />
              </div>
              <div style={{ position: "absolute", left: 952, top: 552, width: 58, height: 26, borderRadius: 6, background: "#EFE6E1" }} />
              <div style={{ position: "absolute", left: 352, top: 512, width: 62, height: 66, borderRadius: "8px 8px 20px 20px", background: "linear-gradient(160deg,#FFFFFF,#F1E9E6)", boxShadow: "0 10px 20px rgba(140,102,96,.16)" }} />
              <div style={{ position: "absolute", left: 408, top: 528, width: 30, height: 30, borderRadius: "50%", border: "7px solid #FFFFFF" }} />
              <div style={{ position: "absolute", left: 240, top: 504, width: 74, height: 74, borderRadius: "10px 10px 24px 24px", background: "linear-gradient(160deg,#E0AB94,#D79B84)", boxShadow: "0 10px 20px rgba(140,102,96,.16)" }} />
              <div style={{ position: "absolute", left: 252, top: 462, width: 58, height: 58, borderRadius: "50%", background: "#93C2A0" }} />
              <div style={{ position: "absolute", left: 288, top: 482, width: 44, height: 44, borderRadius: "50%", background: "#A3CFAE" }} />
              <div style={{ position: "absolute", left: 228, top: 486, width: 40, height: 40, borderRadius: "50%", background: "#87B694" }} />
              <div style={{ position: "absolute", left: 800, top: 528, width: 66, height: 34, borderRadius: "34px 34px 5px 5px", background: "linear-gradient(170deg,#9EDDD0,#7ED0C0)", boxShadow: "0 8px 16px rgba(140,102,96,.16)" }} />
              <div style={{ position: "absolute", left: 826, top: 516, width: 14, height: 14, borderRadius: "50%", background: "#F7F1EE" }} />
            </div>

            {/* 전경(러그·의자) — 가장 많이 움직여서 깊이를 만든다 */}
            <div ref={frontRef} style={{ position: "absolute", inset: 0, pointerEvents: "none" }}>
              <div style={{ position: "absolute", left: 1046, top: 734, width: 400, height: 140, borderRadius: "50%", background: "#EBD7DA" }} />
              <div style={{ position: "absolute", left: 1136, top: 640, width: 170, height: 56, borderRadius: 16, background: "#E7C3C0", boxShadow: "0 14px 26px rgba(140,102,96,.2)" }} />
              <div style={{ position: "absolute", left: 1136, top: 566, width: 170, height: 86, borderRadius: "18px 18px 6px 6px", background: "#EFCFCC" }} />
              <div style={{ position: "absolute", left: 1156, top: 692, width: 14, height: 62, borderRadius: 7, background: "#F0E7E3" }} />
              <div style={{ position: "absolute", left: 1272, top: 692, width: 14, height: 62, borderRadius: 7, background: "#F0E7E3" }} />
            </div>
          </div>

          {/* ── 문 ──────────────────────────────────────────────────────────
              씬 <위>, 히어로 문구 <아래>. 문이 다 열릴 때까지 로봇을 가리는 것이
              이 레이어의 유일한 일이다. 그래서 문짝은 반투명이 아니라 불투명이다 —
              간유리처럼 보이게 하되 <실제로 비치게 하지는 않는다.> 비치면 마지막에
              드러날 것이 처음부터 보여서 연출이 성립하지 않는다. */}
          <div style={{ position: "absolute", inset: 0, zIndex: 3, overflow: "hidden", pointerEvents: "none" }}>
            {Array.from({ length: DOOR_COUNT }, (_, i) => (
              <div
                key={i}
                /* ⚠️ 중괄호로 감싼다 — React 19 는 ref 콜백의 <반환값을 정리 함수로>
                   취급한다. `ref={(n) => (arr[i] = n)}` 는 노드를 함수로 오해해 터진다. */
                ref={(n) => { doorRefs.current[i] = n; }}
                style={{
                  position: "absolute",
                  inset: 0,
                  // 먼저 열리는 문이 위에 온다
                  zIndex: DOOR_COUNT - i,
                  /* ⚠️ 실제로는 <먼저 열리는 문(위, i 가 작은 쪽)이 더 어둡고>, 나중에
                     열리는 문(로봇에 가까운 쪽)은 brightness 가 1 로 그대로다 — "뒤로
                     갈수록 어둡다"는 depth 의도와는 반대 방향이다. 굳이 바로잡지 않는
                     이유: 문짝은 불투명해 한 번에 <하나만> 화면에 보이고(다음 문은
                     이전 문이 완전히 열려야 드러난다), DOOR_COUNT=2 라 밝기 차이도
                     최대 5.5%(0.945 vs 1.0)뿐이라 눈에 띄지 않는다. 보이지도 않는
                     차이를 고치겠다고 굳이 손대 새 버그를 만들 이유가 없다. */
                  filter: `brightness(${1 - (DOOR_COUNT - 1 - i) * 0.055})`,
                  transformOrigin: "50% 50%",
                  willChange: "transform,opacity",
                }}
              >
{(["left", "right"] as const).map((side) => {
                  const dir = side === "left" ? -1 : 1;
                  return (
                    <div
                      key={side}
                      style={{
                        position: "absolute",
                        top: 0,
                        bottom: 0,
                        left: side === "left" ? 0 : "auto",
                        right: side === "right" ? 0 : "auto",
                        // 50% 가 아니라 50.3% 인 이유: 딱 절반이면 소수점 반올림 때문에
                        // 가운데에 배경이 비치는 1px 실선이 생긴다(문이 닫혔는데 틈이 보인다).
                        width: "50.3%",
                        transform: `translateX(calc(var(--open, 0) * ${dir * 100}%))`,
                        background:
                          side === "left"
                            ? "linear-gradient(100deg,#FCF6F4 0%,#F2E5E1 56%,#E7D5D1 100%)"
                            : "linear-gradient(260deg,#FCF6F4 0%,#F2E5E1 56%,#E7D5D1 100%)",
                        boxShadow: `inset ${dir * -20}px 0 40px rgba(150,116,110,.16)`,
                        overflow: "hidden",
                        willChange: "transform",
                      }}
                    >
                      {/* 간유리 시트지 — 사무실 유리문의 그 가로 띠다. 이 한 줄이
                          "밋밋한 판"을 "유리문"으로 읽히게 하는 거의 전부다. */}
                      <div style={{ position: "absolute", left: 0, right: 0, top: "42%", height: 132, background: "rgba(255,255,255,.5)", borderTop: "1px solid rgba(255,255,255,.75)", borderBottom: "1px solid rgba(199,178,173,.45)" }} />
                      {/* 유리에 비친 빛 한 줄기 */}
                      <div style={{ position: "absolute", top: "-30%", bottom: "-30%", left: side === "left" ? "18%" : "auto", right: side === "right" ? "18%" : "auto", width: 90, transform: `rotate(${dir * 9}deg)`, background: "linear-gradient(90deg, rgba(255,255,255,0), rgba(255,255,255,.5), rgba(255,255,255,0))" }} />
                      {/* 금속 새시 — 위·아래 가로대와 문틈 쪽 세로 기둥.
                          이게 없으면 <문>이 아니라 그냥 밝은 판으로 읽힌다(실제로 그랬다).
                          닫혀 있을 때 세로 기둥 두 개가 가운데서 맞물리는 것이
                          "여기가 열린다" 를 말해주는 유일한 신호다. */}
                      <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: 30, background: "linear-gradient(180deg,#DFCEC9,#C9B2AD)" }} />
                      <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 46, background: "linear-gradient(0deg,#D5C0BB,#C9B2AD)" }} />
                      <div style={{ position: "absolute", top: 0, bottom: 0, left: side === "left" ? "auto" : 0, right: side === "left" ? 0 : "auto", width: 14, background: "linear-gradient(90deg,#DDCBC6,#C4ABA6)" }} />
                      {/* 레버 — 마지막 문의 오른쪽 문짝에만.
                          ⚠️ "기능 보기" 같은 라벨 버튼이 아니라 <이 세계의 물건>이다.
                             여기는 안내 데스크고 눈앞에 문이 있다. 당기면 안쪽에서 응답이 온다.
                          ⚠️ 문짝 안에 넣었으므로 문이 열리면 레버도 함께 밀려나간다.
                             레이어에 따로 띄우면 문은 열리는데 레버만 허공에 남는다.
                          ⚠️ 안내 문구를 <달지 않는다.> 레버는 생김새로 이미 "당기는 것"이라
                             말하고, 글자를 붙이면 방금 지운 라벨 버튼으로 되돌아간다. */}
                      {side === "right" && i === DOOR_COUNT - 1 && (
                        <div
                          ref={leverRef}
                          style={{ position: "absolute", left: "13%", top: "38%", opacity: 0, visibility: "hidden", pointerEvents: "none" }}
                        >
                          <button
                            type="button"
                            onClick={() => setArmsOpen((v) => !v)}
                            aria-expanded={armsOpen}
                            /* 그림만 있어서 이름을 손으로 달아준다. 없으면 스크린리더에
                               "버튼" 이라고만 읽혀 무엇을 하는지 알 수 없다. */
                            aria-label={armsOpen ? "기능 목록 닫기" : "기능 목록 보기"}
                            className={`alldap-lever${armsOpen ? " is-on" : ""}`}
                          >
                            <span className="alldap-lever-slot" aria-hidden />
                            <span className="alldap-lever-grip" aria-hidden />
                          </button>
                        </div>
                      )}
                      {/* 손잡이 — 문틈 쪽 세로 바 */}
                      <div style={{ position: "absolute", top: "50%", marginTop: -54, left: side === "left" ? "auto" : 34, right: side === "left" ? 34 : "auto", width: 9, height: 108, borderRadius: 5, background: "linear-gradient(180deg,#EFE3DF,#BCA6A1)", boxShadow: "0 6px 14px rgba(120,88,82,.28)" }} />
                    </div>
                  );
                })}
                {/* 문틈으로 새는 빛 — 문짝 <위>에 얹는다.
                    뒤에 깔면 닫혀 있는 동안 완전히 가려져서, 정작 보여주고 싶은
                    "닫힌 문틈으로 새어 나오는 실선"이 안 보인다(실제로 그렇게 나왔다).
                    색은 로봇의 눈·전구와 같은 민트(ACCENT)다 — 처음에는 실선 한 줄이지만
                    마지막 문이 열리면 그 빛의 정체가 로봇이었음이 밝혀진다.
                    이 화면에서 크게 건 <한 가지>이고 나머지는 조용히 뒀다. */}
                <div
                  style={{
                    position: "absolute",
                    left: "50%",
                    top: 0,
                    bottom: 0,
                    // --open(0~1)은 루프가 문 레이어에 써준다. 자식은 calc 로 받아 쓴다.
                    // 닫혔을 때 12px. 7px 로 뒀더니 blur 를 먹고 <아예 안 보였다> —
                    // 닫힌 문틈의 실선이 이 연출의 첫인상이라 보이지 않으면 의미가 없다.
                    /* ⚠️ 폭을 <실제 틈>에서 계산한다. 예전에는 "10px + 최대 150px" 로
                       따로 굴렸는데, 문짝은 자기 폭(화면의 50.3%)의 비율로 벌어지므로
                       활짝 열리면 틈이 1400px 인데 빛은 160px 이었다 —
                       <문이 열리는 속도와 빛이 퍼지는 속도가 어긋나 보이던 원인이다.>
                       틈 = 양쪽 문짝이 물러난 거리의 합 = open × 50.3vw × 2.
                       닫혔을 때의 11px 은 실선으로 남기는 몫이다. */
                    width: "calc(11px + var(--open, 0) * 100.6vw)",
                    opacity: "var(--glow, 1)",
                    transform: "translateX(-50%)",
                    // 가로로는 가운데가 밝고, 세로로는 <가운데가 가장 밝다.>
                    // 균일하게 채우면 빛이 아니라 칠해놓은 띠로 보인다(실제로 그랬다).
                    background:
                      "radial-gradient(70% 55% at 50% 50%, rgba(232,252,246,1) 0%, rgba(126,208,192,.8) 40%, rgba(126,208,192,0) 100%)",
                    filter: "blur(7px)",
                    boxShadow: "0 0 52px rgba(126,208,192,.55)",
                    pointerEvents: "none",
                  }}
                />
              </div>
            ))}
          </div>

          {/* ── 로봇 팔 ──────────────────────────────────────────────────────
              "기능 보기" 를 누르면 <위에서> 팔이 내려와 기능 목록을 들고 있고,
              다시 누르면 올라간다.

              ── 왜 rAF 루프가 아니라 CSS 전환인가 ──────────────────────────
              이 화면의 다른 움직임은 전부 스크롤 진행도(p)에 묶여 있어서 매 프레임
              계산해야 하지만, 팔은 <눌렀나 안 눌렀나> 두 상태뿐이다. 두 상태 사이를
              오가는 것은 CSS transition 이 이미 하는 일이라 직접 그릴 이유가 없다.
              계단식으로 내려오는 것도 transitionDelay 한 줄이면 된다.

              ── 왜 팔마다 길이가 다른가 ────────────────────────────────────
              같은 길이로 내려오면 팔이 아니라 <표>로 보인다. 길이를 흩어야
              천장에서 기계 팔이 내려온 것으로 읽힌다. */}
          <div
            className="alldap-arms"
            data-open={armsOpen}
            /* ⚠️ aria-hidden 이 아니라 inert 다. aria-hidden 은 <스크린리더에서만> 숨긴다 —
               키보드 포커스는 막지 못해서, 카드에 tabIndex={0} 이 있으면 접혀 화면 밖에
               있는 카드 5개를 Tab 이 그대로 지나간다(스크린리더는 아무것도 안 읽는데
               포커스 링만 빈 화면에서 움직인다). inert 는 포커스·스크린리더·클릭을
               한 번에 막는 네이티브 속성이라 이 한 줄로 둘 다 해결된다. */
            inert={!armsOpen}
            style={{ position: "absolute", inset: 0, zIndex: 7, overflow: "hidden", pointerEvents: "none" }}
          >
            {FEATURES.map((f) => (
              <div
                key={f.label}
                className="alldap-arm"
                /* 가운데(50%)부터 바깥으로 퍼지듯 내려오게 한다. 왼쪽부터 차례로
                   내려오면 순서가 있는 목록처럼 읽히는데, 이건 순서가 없다. */
                style={{ left: `${f.x}%`, transitionDelay: `${Math.abs(f.x - 50) * 3.4}ms` }}
              >
                {/* 팔 — 위 끝은 화면 밖이라 둥글릴 필요가 없다 */}
                <div className="alldap-arm-bar" style={{ height: f.len }} />
                {/* 관절 하나. 이게 없으면 그냥 막대기다 */}
                <div className="alldap-arm-joint" style={{ top: f.len * 0.52 }} />
                {/* 집게 — 판을 물고 있는 부분 */}
                <div className="alldap-arm-grip" />
                {/* tabIndex 를 주는 이유: 상세를 <마우스를 올렸을 때만> 보여주면
                    키보드만 쓰는 사람은 영영 못 본다. 포커스로도 열리게 한다
                    (CSS 의 :focus-within). */}
                <div className="alldap-arm-card" tabIndex={0}>
                  <span className="alldap-arm-label">{f.label}</span>
                  {/* ⚠️ 상세를 <한 겹 더> 감싼다. 0fr 접기는 자식이 요소여야 하는데
                      글자만 두면 익명 항목이 되어 overflow: hidden 이 안 걸리고,
                      접힌 판의 높이가 안 줄어든다(실제로 빈 상자처럼 나왔다). */}
                  <span className="alldap-arm-detail">
                    <span>{f.detail}</span>
                  </span>
                </div>
              </div>
            ))}
          </div>

          {/* 비네트 — 가장자리를 살짝 눌러 시선을 가운데로 모은다 */}
          <div style={{ position: "absolute", inset: 0, pointerEvents: "none", background: "radial-gradient(75% 60% at 50% 45%, rgba(0,0,0,0) 40%, rgba(90,66,62,0.16) 100%)" }} />
          <header style={{ position: "absolute", top: 0, left: 0, right: 0, display: "flex", alignItems: "center", justifyContent: "space-between", padding: "26px 34px", zIndex: 5 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
              <span style={{ fontSize: 19, fontWeight: 700, letterSpacing: "0.22em" }}>ALLDAP</span>
              <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: 26, height: 22, border: "1.6px solid #171514", borderRadius: 4, fontSize: 11, fontWeight: 700, letterSpacing: "0.02em" }}>AI</span>
            </div>

            {/* 문을 다 열고 로봇을 만난 뒤에야 나타나는 메뉴. 초기값이 숨김인 것은
                rAF 루프가 첫 프레임을 그리기 전에도 안 보여야 하기 때문이다 —
                CTA 가 같은 이유로 같은 초기값을 갖고 있다. */}
            <nav
              ref={navRef}
              style={{ display: "flex", alignItems: "center", gap: 4, opacity: 0, pointerEvents: "none", visibility: "hidden" }}
            >
              {SCENE_NAV.map(({ label, href }) => (
                <Link
                  key={href}
                  href={href}
                  /* 랜딩에서 나가는 링크는 전부 문 열림 전환을 쓴다(로봇·고용하기와 같다). */
                  transitionTypes={["door"]}
                  style={{ padding: "8px 14px", borderRadius: 8, color: "#171514", fontSize: 15, fontWeight: 500, textDecoration: "none" }}
                >
                  {label}
                </Link>
              ))}
            </nav>
          </header>

          {/* ── 인사 팻말 ────────────────────────────────────────────────────
              🔴 예전에는 화면 위쪽에 큰 글자 두 덩어리(제목 + 부제)가 떠 있었다.
                 위로 몰려 보였고, 무엇보다 <이 장면과 무관한 웹페이지 문구>였다.
                 지금은 문 뒤의 로봇이 팔을 넘겨 팻말을 들고 있다 — 기능 팻말과 같은
                 언어라, 처음 보는 사람도 "저 팔이 뭔가 보여주는구나" 를 한 번에 익힌다.
              ⚠️ 부제("문서를 읽고 출처까지…")는 <지웠다.> 팻말에 두 문장을 넣으면
                 들고 있기엔 무거워지고, 그 설명은 팔이 내려와 보여주는 기능 목록과 겹친다.
                 SEO 용 설명은 app/page.tsx 의 metadata 가 이미 갖고 있다.
              ⚠️ h1 은 <여기 살아 있다.> 이 화면의 유일한 제목이라 없애면 문서 구조가
                 사라진다(그림만 남고 기계는 아무것도 못 읽는다). */}
          <div ref={greetRef} className="alldap-greet" data-open="true">
            <span className="alldap-greet-bar" style={{ left: "14%" }} aria-hidden />
            <span className="alldap-greet-bar" style={{ right: "14%" }} aria-hidden />
            <div className="alldap-greet-card">
              <h1>
                안녕하세요, 올답입니다.
                <span className="alldap-caret" aria-hidden />
              </h1>
            </div>
          </div>

          <div ref={ctaRef} style={{ position: "absolute", left: "50%", top: "64%", transform: "translateX(-50%)", zIndex: 6, opacity: 0, pointerEvents: "none", visibility: "hidden", willChange: "transform,opacity" }}>
            <div style={{ position: "relative", padding: 18 }}>
              <div style={{ position: "absolute", top: 0, left: 0, width: 28, height: 28, borderTop: "1.6px solid rgba(23,21,20,.4)", borderLeft: "1.6px solid rgba(23,21,20,.4)" }} />
              <div style={{ position: "absolute", top: 0, right: 0, width: 28, height: 28, borderTop: "1.6px solid rgba(23,21,20,.4)", borderRight: "1.6px solid rgba(23,21,20,.4)" }} />
              <div style={{ position: "absolute", bottom: 0, left: 0, width: 28, height: 28, borderBottom: "1.6px solid rgba(23,21,20,.4)", borderLeft: "1.6px solid rgba(23,21,20,.4)" }} />
              <div style={{ position: "absolute", bottom: 0, right: 0, width: 28, height: 28, borderBottom: "1.6px solid rgba(23,21,20,.4)", borderRight: "1.6px solid rgba(23,21,20,.4)" }} />
              {/* 이 화면의 유일한 목적지다. 원본 스펙(17px / 20·34 패딩)보다 키웠다 —
                  줌인이 끝난 뒤 화면 전체에서 눌러야 할 곳이 여기 하나뿐인데 작으면 안 보인다. */}
              {/* 이 화면의 유일한 목적지다.
                  ⚠️ 문구가 "챗봇 시작하기" 가 아니라 <고용하기> 인 이유: 이 제품은 도구를
                     켜는 것이 아니라 <안내 데스크 직원을 들이는 것>으로 팔린다. 여기까지
                     오는 동안 방문자는 문을 열고 들어와 직원을 만났다. 그 다음 행동은
                     "시작"이 아니라 "고용"이다.
                  ⚠️ button 이 아니라 Link 다 — 실제로 하는 일이 <이동>(로그인/가입)이라서다.
                     button 으로 두면 새 탭으로 열기·주소 복사가 안 되고 링크로 안 읽힌다. */}
              <Link
                href="/auth"
                /* 위 로봇 링크·우상단 메뉴와 같은 이유다. 랜딩에서 나가는 링크는 전부 문이다. */
                transitionTypes={["door"]}
                className="alldap-cta"
                style={{ display: "flex", alignItems: "center", gap: 14, cursor: "pointer", padding: "26px 48px", borderRadius: 14, background: "#171514", color: "#FFFFFF", fontSize: 21, fontWeight: 600, letterSpacing: "-0.015em", textDecoration: "none", boxShadow: "0 22px 54px rgba(74,50,46,.32)" }}
              >
                <span style={{ display: "inline-block", width: 11, height: 11, borderRadius: "50%", background: ACCENT }} />
                고용하기
              </Link>
            </div>
          </div>

          {/* 이 화면을 어떻게 진행시키는지 알려주는 유일한 안내다. 스펙(21×33 / 13px)으로는
              구석에서 안 읽혀서, 마우스 아이콘과 글자를 함께 키웠다.
              ⚠️ div 가 아니라 button 이다 — 화면을 진행시키는 유일한 <눈에 보이는> 안내인데
                 div+onClick 은 마우스로만 눌린다. 시각 스타일은 그대로 두고 button 의
                 기본 테두리·배경·폰트·정렬만 지워 겉모습을 이전과 같게 만든다. */}
          <button
            type="button"
            ref={hintRef}
            onClick={() => stepBy(1)}
            style={{ position: "absolute", left: 34, bottom: 34, display: "flex", alignItems: "center", gap: 16, zIndex: 5, cursor: "pointer", border: "none", background: "transparent", font: "inherit", padding: 0, textAlign: "left" }}
          >
            <div style={{ position: "relative", width: 27, height: 42, border: "2px solid rgba(23,21,20,.55)", borderRadius: 14, display: "flex", justifyContent: "center", paddingTop: 8, flex: "none" }}>
              <span className="alldap-wheel" style={{ display: "block", width: 3, height: 8, borderRadius: 2, background: "#171514" }} />
            </div>
            <p style={{ margin: 0, fontSize: 16, lineHeight: 1.4, fontWeight: 600, color: "#3A3230" }}>스크롤해서<br />안내 데스크로 들어가 보세요</p>
          </button>
        </div>
      </div>

    </div>
  );
}

