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
 * 반대로 chatOpen·msgs 는 <구조가 바뀌는> 상태라 state 가 맞다.
 *
 * ── 왜 인라인 style 인가 (프로젝트는 Tailwind 인데) ─────────────────────────
 * 디오라마는 1440×900 좌표계 위에 픽셀 단위로 배치된 오브젝트 60여 개다.
 * 디자인 스펙이 이미 raw CSS 수치로 확정돼 있어서, Tailwind 클래스로 옮기면
 * `left-[594px] top-[472px]` 같은 임의값 클래스가 될 뿐 읽기만 나빠진다.
 * UI 레이어(헤더·CTA·모달)도 원본 수치를 그대로 유지하려고 같은 방식으로 뒀다.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "@/lib/api";

/**
 * 랜딩 데모가 물어보는 봇의 publicKey.
 *
 * 위젯 공개 API 를 그대로 쓴다(`POST /api/w/{publicKey}/chat`) — 로그인 없이 열려 있는
 * 유일한 채팅 경로이고, 랜딩 방문자는 로그인이 없기 때문이다.
 * 채팅은 Origin 검증 대상이 아니라(WidgetController 주석 참고) 여기서 불러도 막히지 않는다.
 * 실질 방어는 서버의 rate limit 이다.
 */
const DEMO_PUBLIC_KEY = process.env.NEXT_PUBLIC_DEMO_PUBLIC_KEY ?? "pk_local_dev";

/** 씬의 기준 좌표계. 모든 오브젝트 위치가 이 크기 안의 절대 좌표다. */
const SCENE_W = 1440;
const SCENE_H = 900;

/* ── 진행 방식 ─────────────────────────────────────────────────────────────
 * 스크롤 <한 번>이 방아쇠다. 그 뒤로는 입력과 무관하게 정해진 시간 동안
 * 0 → 1(먼 뷰 → 로봇 얼굴)까지 알아서 흘러간다. 다 가면 CTA 가 떠 있다.
 *
 * 입력량에 비례해 쌓는 방식(굴린 만큼 들어감)도 만들어봤지만, 사용자가
 * <계속 굴려야> 장면이 진행돼서 구경이 아니라 작업이 됐다. 방아쇠 방식이면
 * 한 번 굴리고 손을 떼도 연출이 끝까지 재생된다.
 */

/** 0 → 1 까지 가는 데 걸리는 시간(ms). <키우면 더 느긋해진다.> */
const ZOOM_DURATION_MS = 2600;

const ACCENT = "#7ED0C0";

type Msg = { role: "bot" | "me"; text: string; source?: string };

/** 0~1 로 자른 뒤 부드럽게 만드는 보간. 스크롤 매핑은 전부 이걸 쓴다. */
function smoothstep(a: number, b: number, x: number) {
  const k = Math.min(1, Math.max(0, (x - a) / (b - a)));
  return k * k * (3 - 2 * k);
}
const mix = (a: number, b: number, k: number) => a + (b - a) * k;

export function ReceptionHero() {
  /* 구조가 바뀌는 것만 state. 나머지는 전부 ref다(위 주석 참고). */
  const [chatOpen, setChatOpen] = useState(false);
  const [msgs, setMsgs] = useState<Msg[]>([]);

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
  const heroRef = useRef<HTMLDivElement>(null);
  const ctaRef = useRef<HTMLDivElement>(null);
  const hintRef = useRef<HTMLDivElement>(null);
  const navRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  /* 모달 안 로봇 얼굴(표정이 따로 논다) */
  const cHeadRef = useRef<HTMLDivElement>(null);
  const cEyeLRef = useRef<HTMLDivElement>(null);
  const cEyeRRef = useRef<HTMLDivElement>(null);
  const cMouthRef = useRef<HTMLDivElement>(null);
  const cDocRef = useRef<HTMLDivElement>(null);
  const cScanRef = useRef<HTMLDivElement>(null);
  const cBulbRef = useRef<HTMLDivElement>(null);

  /* 매 프레임 읽고 쓰는 값들. state 로 두면 리렌더가 폭주한다. */
  const anim = useRef({
    p: 0,          // 현재 진행도(관성 적용된 값)
    target: 0,     // 스크롤이 알려준 목표 진행도
    mx: 0, my: 0,  // 커서 현재값
    mtx: 0, mty: 0,// 커서 목표값
    fit: 1,        // 씬(1440×900)을 화면에 채우는 배율
    blurK: 0,      // 모달 열림 정도(뒤 흐림)
    happyK: 0,     // 로봇이 웃는 정도
    docK: 0,       // 모달 얼굴이 "문서"로 바뀐 정도
    typeK: 0,      // 모달 얼굴이 아래(입력창)를 보는 정도
    typing: false,
    thinking: false,
    greetUntil: 0,
    open: false,   // chatOpen 을 루프에서 읽기 위한 사본
    shake: 1,      // prefers-reduced-motion 이면 0
    touchY: 0,     // 터치 시작 y
    transFrom: 0,  // 이번 전환의 출발 진행도
    transStart: 0, // 전환 시작 시각(ms). 0 이면 전환 중이 아니다
    cloudBase: [] as { own: number; slot: number }[],
    cloudSpan: 2800,
  });

  /* 루프는 chatOpen 을 state 로 못 읽는다(클로저가 낡는다). ref 로 흘려준다. */
  useEffect(() => {
    anim.current.open = chatOpen;
  }, [chatOpen]);

  const scrollList = useCallback(() => {
    const l = listRef.current;
    if (l) l.scrollTop = l.scrollHeight;
  }, []);

  /* 같은 대화를 묶는 키. 서버가 conversations 행을 이걸로 이어 붙인다.
     모달을 처음 열 때 한 번만 만들고 새로고침 전까지 유지한다. */
  const sessionRef = useRef<string | null>(null);
  const sessionId = () => (sessionRef.current ??= crypto.randomUUID());

  const send = useCallback((preset?: string) => {
    const i = inputRef.current;
    const v = (preset ?? i?.value ?? "").trim();
    // 답변을 기다리는 중이면 무시한다. 없으면 Enter 연타로 요청이 겹쳐
    // 답변 순서가 뒤섞이고 rate limit 만 깎인다.
    if (!v || anim.current.thinking) return;
    if (i) i.value = "";
    anim.current.typing = false;
    anim.current.thinking = true;
    setMsgs((s) => [...s, { role: "me", text: v }]);

    api.widget
      .chat(DEMO_PUBLIC_KEY, { message: v, sessionId: sessionId() })
      .then((res) => {
        setMsgs((s) => [
          ...s,
          {
            role: "bot",
            text: res.answer,
            /* 같은 문서에서 청크를 여러 개 가져오면 파일명이 중복된다. Set 으로 접는다.
               근거가 없으면(fallback) sources 가 비므로 출처 줄 자체를 안 그린다 —
               "출처: (없음)" 이 뜨면 근거가 있는데 못 찾은 것처럼 읽힌다. */
            source: res.sources.length
              ? [...new Set(res.sources.map((x) => x.filename))].join(", ")
              : undefined,
          },
        ]);
      })
      .catch((e) => {
        /* 서버가 "무엇을 어떻게 하면 되는지"까지 담은 한국어를 준다. 그대로 보여준다.
           ⚠️ 실패를 조용히 삼키면 안 된다. 답이 안 오는 것과 "모른다"는 답은 다른 상태인데,
              화면에 아무것도 안 뜨면 방문자는 챗봇이 고장난 줄 안다. */
        setMsgs((s) => [
          ...s,
          {
            role: "bot",
            text:
              e instanceof ApiError
                ? e.message
                : "지금은 답변을 가져오지 못했습니다. 잠시 후 다시 시도해 주세요.",
          },
        ]);
      })
      .finally(() => {
        anim.current.thinking = false;
      });
  }, []);

  useEffect(() => {
    scrollList();
  }, [msgs, scrollList]);

  /**
   * to(0 또는 1)까지 가는 전환을 <시작>시킨다. 여기서는 목적지와 시작 시각만 정하고,
   * 실제 재생은 rAF 루프가 시간을 보며 한다.
   * 휠·스와이프·키·힌트 클릭이 전부 이 한 곳으로 모인다.
   */
  const glideTo = useCallback((to: number) => {
    const a = anim.current;
    if (a.open) return; // 모달이 열려 있으면 뒤 장면을 움직이지 않는다
    if (a.target === to) return; // 이미 그리로 가는 중이면 다시 시작하지 않는다
    // <현재 위치>에서 출발한다. 전환 도중에 방향을 바꿔도 튀지 않는다.
    a.transFrom = a.p;
    a.target = to;
    a.transStart = performance.now();
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    const stage = stageRef.current;
    if (!el || !stage) return;

    // 흔들림을 싫어하는 사용자 설정을 존중한다. 진폭 0 이면 화면이 완전히 정지한다.
    anim.current.shake = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 1;

    /* ── 입력: 굴린 만큼 진행도에 쌓는다 ──────────────────────────────────
     * passive:false 로 걸고 preventDefault 한다. 페이지가 실제로 스크롤되면
     * 화면이 밀려버려서, 이 히어로는 "스크롤"이 아니라 <스크롤 제스처>만 받는다. */
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      if (Math.abs(e.deltaY) < 4) return; // 손 떨림 수준의 미세 입력 무시
      // 방향만 본다. 얼마나 세게 굴렸는지는 안 본다 — 연출 길이는 항상 같아야 한다.
      glideTo(e.deltaY > 0 ? 1 : 0);
    };
    const onTouchStart = (e: TouchEvent) => {
      anim.current.touchY = e.touches[0].clientY;
    };
    const onTouchEnd = (e: TouchEvent) => {
      const dy = anim.current.touchY - e.changedTouches[0].clientY;
      if (Math.abs(dy) < 40) return; // 탭이나 손 떨림은 스와이프가 아니다
      glideTo(dy > 0 ? 1 : 0);
    };
    /* 네이티브 스크롤을 없앴으므로 키보드 이동도 우리가 직접 붙여야 한다.
       안 붙이면 마우스 없는 사용자는 이 화면을 진행시킬 방법이 없다. */
    const onKey = (e: KeyboardEvent) => {
      // 모달이 열려 있거나 입력창에 포커스가 있으면 키는 <글자>다. 가로채면 안 된다.
      if (anim.current.open) return;
      if (document.activeElement instanceof HTMLInputElement) return;
      const down = e.key === "ArrowDown" || e.key === "PageDown" || e.key === " ";
      const up = e.key === "ArrowUp" || e.key === "PageUp";
      if (!down && !up) return;
      e.preventDefault();
      glideTo(down ? 1 : 0);
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
          const k = Math.min(1, (now - a.transStart) / ZOOM_DURATION_MS);
          a.p = a.transFrom + (a.target - a.transFrom) * (k * k * (3 - 2 * k));
          if (k >= 1) a.transStart = 0;
        }
      }
      const p = a.p;
      const t = now / 1000;

      /* ── UI 레이어: 스크롤에 따라 사라지고 나타난다 ── */
      const hero = heroRef.current;
      if (hero) {
        const f = 1 - smoothstep(0.02, 0.24, p);
        hero.style.opacity = String(f);
        hero.style.transform = `translateY(${-p * 90}px) scale(${1 + p * 0.16})`;
      }
      const nav = navRef.current;
      if (nav) {
        const f = (1 - smoothstep(0.04, 0.34, p)) * (1 - a.blurK);
        nav.style.opacity = String(f);
        nav.style.pointerEvents = f < 0.1 ? "none" : "auto";
        nav.style.transform = `translateY(${-p * 14}px)`;
      }
      const hint = hintRef.current;
      if (hint) {
        const f = (1 - smoothstep(0.01, 0.12, p)) * (1 - a.blurK);
        hint.style.opacity = String(f);
        hint.style.pointerEvents = f < 0.1 ? "none" : "auto";
      }
      const cta = ctaRef.current;
      if (cta) {
        const f = smoothstep(0.6, 0.78, p);
        cta.style.opacity = String(f * (1 - a.blurK));
        cta.style.pointerEvents = f > 0.6 ? "auto" : "none";
        cta.style.transform = `translateX(-50%) translateY(${26 - f * 26}px)`;
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

      /* ── 줌: 2단계. 멀리서 데스크 전체 → 카운터 → 로봇 얼굴 ──
         원본 3D 는 카메라를 z 로 밀어넣었는데, 여기서는 scale + transform-origin
         이동으로 같은 인상을 만든다. origin 이 함께 움직여야 "다가간다"가 되고,
         고정하면 그냥 "커진다"로 보인다. */
      const seg = p < 0.55 ? p / 0.55 : (p - 0.55) / 0.45;
      const e = seg * seg * (3 - 2 * seg);
      const zoom = p < 0.55 ? mix(0.72, 1.42, e) : mix(1.42, 2.15, e);
      const ox = mix(50, 48.6, smoothstep(0, 1, p));
      const oy = mix(58, 38, smoothstep(0, 1, p));
      const panY = mix(9, -1, smoothstep(0, 0.7, p));

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
        if (n) n.style.transform = `translate(${-shX * k * 0.5}px,${-panY * k * 2.2}px) scale(${1 - k * 0.06 + p * k * 0.05})`;
      };
      const near = (ref: React.RefObject<HTMLDivElement | null>, k: number) => {
        const n = ref.current;
        if (n) n.style.transform = `translate(${shX * k * 0.35}px,0) scale(${1 + p * k * 0.045})`;
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

      /* ── 모달이 열릴 때의 감쇠 ──
       * ⚠️ 어둡게 덮는 것(dim)·흐림·로봇 페이드는 <여기서 하지 않는다.> 아래 JSX 에서
       *    chatOpen 에 따라 CSS transition 으로 처리한다.
       *    이유: 모달의 글자가 밝은 색이라 <배경이 어두워지지 않으면 안 읽힌다.>
       *    가독성을 rAF 루프에 의존하게 두면, 루프가 안 도는 상황(백그라운드 탭,
       *    저사양 기기에서의 프레임 누락)에서 흰 글자가 밝은 배경 위에 남는다.
       *    실제로 hidden 탭에서 그 상태를 확인했다. 장식은 루프에, <읽히는 것은 CSS 에.>
       * blurK 는 이제 nav·hint·CTA 를 함께 숨기는 용도로만 쓴다(전부 장식). */
      a.blurK += ((a.open ? 1 : 0) - a.blurK) * 0.13;
      a.happyK += ((a.open ? 1 : 0) - a.happyK) * 0.11;

      /* ── 로봇: 몸은 고정, 시선만 커서를 따라간다 ──
         gaze 를 곱하는 이유: 멀리서(p 작을 때) 눈알이 굴러가면 소름끼친다.
         가까이 왔을 때만 반응하게 해야 "쳐다본다"가 애교로 읽힌다. */
      a.mx += (a.mtx - a.mx) * 0.09;
      a.my += (a.mty - a.my) * 0.09;
      const gaze = smoothstep(0.3, 0.75, p);
      const bob = a.happyK * Math.sin(t * 4.4) * 5;
      if (headRef.current) {
        headRef.current.style.transform =
          `translate(${a.mx * 7 * gaze}px,${a.my * 4 * gaze}px) ` +
          `translateY(${bob - a.happyK * 6}px) rotate(${a.mx * 1.6 * gaze * (1 - a.happyK)}deg)`;
      }
      const cyc = t % 4.6;
      const blink = cyc < 0.14 ? Math.max(0.08, Math.abs(cyc - 0.07) / 0.07) : 1;
      const ex = a.mx * 7 * gaze;
      const ey = a.my * 5 * gaze;
      const hk = a.happyK;
      [eyeLRef, eyeRRef].forEach((r) => {
        const n = r.current;
        if (!n) return;
        n.style.transform = `translate(${ex * (1 - hk)}px,${ey * (1 - hk) + hk * 4}px) scaleY(${blink * (1 - hk * 0.58)})`;
        n.style.borderRadius = hk > 0.15 ? `12px 12px ${12 - hk * 9}px ${12 - hk * 9}px` : "12px";
      });
      if (mouthRef.current) {
        mouthRef.current.style.transform =
          `translate(${ex * 0.5 * (1 - hk)}px,${ey * 0.4 + hk * 5}px) scale(${1 + hk * 1.35},${1 + hk * 1.7})`;
      }
      if (bulbRef.current) {
        const g = 0.72 + Math.sin(t * 2.2) * 0.28;
        bulbRef.current.style.opacity = String(g);
        bulbRef.current.style.boxShadow = `0 0 ${18 + g * 20}px rgba(126,208,192,.85)`;
      }

      /* ── 모달 안 얼굴: 기본 → 입력 중(아래를 봄) → 생각 중(얼굴이 문서로 바뀜) ──
         "생각 중"에 스피너 대신 문서를 스캔하게 한 이유: 이 제품이 하는 일이
         <문서를 찾아 읽는 것>이라서다. 로딩 표시가 곧 기능 설명이 된다. */
      const greeting = a.open && performance.now() < a.greetUntil;
      a.docK += ((a.thinking ? 1 : 0) - a.docK) * 0.14;
      a.typeK += ((a.typing && !a.thinking ? 1 : 0) - a.typeK) * 0.12;
      const dk = a.docK;
      const tk = a.typeK;
      const gk = greeting ? 1 : 0;
      /* ⚠️ "입력창을 내려다보는" 수치를 원본 스펙보다 <키웠다>.
       *    스펙값(머리 1.6° · 눈 7px)으로는 실사용에서 <움직이는지 알아볼 수 없었다.>
       *    입력창이 머리에서 한참 아래에 있어서, 그 정도로는 시선이 갔다고 안 읽힌다.
       *    머리 5° + 4px 아래로, 눈 13px 아래로, 눈꺼풀도 더 내린다.
       *    (원본은 three.js 3D 를 전제로 잡힌 값이라 2D 로 옮기면 체감이 다르다) */
      /* 두둥실 — 모달이 열려 있는 <내내> 떠 있게 한다.
       * 원래는 인사하는 1.7초 동안만 돌고 뚝 멈춰서, 그 뒤로는 로봇이 굳은 사진처럼 보였다.
       * 대화가 이어지는 동안 계속 살아 있어야 "안내 데스크에 앉아 있는 사람"으로 읽힌다.
       * ⚠️ shake 를 곱한다 — prefers-reduced-motion 이면 완전히 멈춘다.
       *    끝없이 흔들리는 요소는 그 설정을 켠 사용자가 가장 피하고 싶은 것이다. */
      const cBob = Math.sin(t * 5.2) * 3 * a.shake;
      if (cHeadRef.current) {
        cHeadRef.current.style.transform =
          `translateY(${dk * -2 + tk * 4 + cBob}px) ` +
          `rotate(${tk * 5 + dk * Math.sin(t * 1.1) * 1.2}deg)`;
      }
      const faceOn = 1 - dk;
      [cEyeLRef, cEyeRRef].forEach((r) => {
        const n = r.current;
        if (!n) return;
        n.style.opacity = String(faceOn);
        n.style.transform = `translate(${tk * 1.5}px,${tk * 13}px) scaleY(${blink * (1 - gk * 0.5) * (1 - tk * 0.45)})`;
        n.style.borderRadius = gk ? "7px 7px 2px 2px" : "7px";
      });
      if (cMouthRef.current) {
        cMouthRef.current.style.opacity = String(faceOn);
        cMouthRef.current.style.transform = `translateY(${tk * 9}px) scale(${1 + gk * 0.9 - tk * 0.35},${1 + gk * 1.2 - tk * 0.5})`;
      }
      if (cDocRef.current) {
        cDocRef.current.style.opacity = String(dk);
        cDocRef.current.style.transform = `translateY(${(1 - dk) * 8}px) rotate(${Math.sin(t * 1.6) * 3}deg)`;
      }
      if (cScanRef.current) {
        cScanRef.current.style.transform = `translateY(${(Math.sin(t * 2.4) * 0.5 + 0.5) * 30}px)`;
      }
      if (cBulbRef.current) {
        cBulbRef.current.style.opacity = String(0.6 + Math.sin(t * (a.thinking ? 6.2 : 2.2)) * 0.4);
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
    // glideTo 는 useCallback([]) 이라 <절대 안 바뀌므로> 넣어도 재실행되지 않는다.
    // (경고를 억누르는 대신 넣는다 — 억누르면 나중에 진짜 의존성이 빠져도 안 보인다)
  }, [glideTo]);

  const openChat = () => {
    anim.current.greetUntil = performance.now() + 1700;
    setChatOpen(true);
    /* ⚠️ 입력창에 <자동 포커스를 주지 않는다.>
     * 열자마자 커서가 깜빡이면 인사말과 제안 칩을 읽기 전에 "뭔가 쳐야 한다"는
     * 압박이 생기고, 모바일에서는 키보드가 즉시 올라와 화면 절반을 먹는다.
     * 방문자가 입력창을 누르거나 제안 칩을 고르는 순간부터 시작하게 둔다. */
  };

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
              // transform 은 매 프레임 rAF 가 덮어쓰지만 filter 는 별개 속성이라
              // 여기서 React 가 관리해도 서로 안 싸운다.
              filter: chatOpen ? "blur(13px) saturate(0.82)" : "none",
              transition: "filter 0.32s ease",
            }}
          >
            {/* 구름 — box-shadow 를 여러 겹 써서 덩어리 하나로 뭉게구름을 만든다 */}
            <div ref={cloudsRef} style={{ position: "absolute", left: -600, right: -600, top: 0, bottom: 0 }}>
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
            <div ref={wallRef} style={{ position: "absolute", inset: 0 }}>
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
            <div style={{ position: "absolute", left: 0, top: 0, width: "100%", height: "100%", opacity: chatOpen ? 0 : 1, transition: "opacity 0.32s ease" }}>
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

            {/* 안내 데스크 + 소품 */}
            <div ref={deskRef} style={{ position: "absolute", left: 0, top: 0, width: "100%", height: "100%" }}>
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
            <div ref={frontRef} style={{ position: "absolute", inset: 0 }}>
              <div style={{ position: "absolute", left: 1046, top: 734, width: 400, height: 140, borderRadius: "50%", background: "#EBD7DA" }} />
              <div style={{ position: "absolute", left: 1136, top: 640, width: 170, height: 56, borderRadius: 16, background: "#E7C3C0", boxShadow: "0 14px 26px rgba(140,102,96,.2)" }} />
              <div style={{ position: "absolute", left: 1136, top: 566, width: 170, height: 86, borderRadius: "18px 18px 6px 6px", background: "#EFCFCC" }} />
              <div style={{ position: "absolute", left: 1156, top: 692, width: 14, height: 62, borderRadius: 7, background: "#F0E7E3" }} />
              <div style={{ position: "absolute", left: 1272, top: 692, width: 14, height: 62, borderRadius: 7, background: "#F0E7E3" }} />
            </div>
          </div>

          {/* 비네트 — 가장자리를 살짝 눌러 시선을 가운데로 모은다 */}
          <div style={{ position: "absolute", inset: 0, pointerEvents: "none", background: "radial-gradient(75% 60% at 50% 45%, rgba(0,0,0,0) 40%, rgba(90,66,62,0.16) 100%)" }} />
          {/* 모달 뒤를 덮는 어두운 막. 모달 글자가 밝은 색이라 <이게 없으면 안 읽힌다> —
              그래서 rAF 가 아니라 chatOpen 에 직접 물려 CSS 로 전환한다. */}
          <div style={{ position: "absolute", inset: 0, zIndex: 8, pointerEvents: "none", opacity: chatOpen ? 1 : 0, transition: "opacity 0.32s ease", background: "radial-gradient(90% 70% at 50% 50%, rgba(28,20,19,.42) 0%, rgba(28,20,19,.68) 100%)" }} />

          <header style={{ position: "absolute", top: 0, left: 0, right: 0, display: "flex", alignItems: "center", justifyContent: "space-between", padding: "26px 34px", zIndex: 5 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
              <span style={{ fontSize: 19, fontWeight: 700, letterSpacing: "0.22em" }}>ALLDAP</span>
              <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: 26, height: 22, border: "1.6px solid #171514", borderRadius: 4, fontSize: 11, fontWeight: 700, letterSpacing: "0.02em" }}>AI</span>
            </div>
            <div ref={navRef} style={{ position: "relative", padding: 11, willChange: "opacity" }}>
              {/* 네 모서리 브래킷 — 카메라 뷰파인더 느낌 */}
              <div style={{ position: "absolute", top: 0, left: 0, width: 20, height: 20, borderTop: "1.5px solid rgba(23,21,20,.35)", borderLeft: "1.5px solid rgba(23,21,20,.35)" }} />
              <div style={{ position: "absolute", top: 0, right: 0, width: 20, height: 20, borderTop: "1.5px solid rgba(23,21,20,.35)", borderRight: "1.5px solid rgba(23,21,20,.35)" }} />
              <div style={{ position: "absolute", bottom: 0, left: 0, width: 20, height: 20, borderBottom: "1.5px solid rgba(23,21,20,.35)", borderLeft: "1.5px solid rgba(23,21,20,.35)" }} />
              <div style={{ position: "absolute", bottom: 0, right: 0, width: 20, height: 20, borderBottom: "1.5px solid rgba(23,21,20,.35)", borderRight: "1.5px solid rgba(23,21,20,.35)" }} />
              {/* 원본 스펙(14px / 5·12 패딩)보다 한 단계 키웠다. 히어로가 전체 화면을
                  쓰는 큰 무대라 스펙 크기로는 구석에서 눈에 안 들어온다. */}
              <nav className="alldap-nav" style={{ display: "flex", alignItems: "center", gap: 5, background: "rgba(255,255,255,.42)", backdropFilter: "blur(10px)", borderRadius: 10, padding: "6px 6px 6px 16px" }}>
                {["홈", "기능", "요금제", "고객사례", "FAQ"].map((label) => (
                  <a key={label} href="#" style={{ padding: "12px 18px", fontSize: 17, fontWeight: 500 }}>{label}</a>
                ))}
                <a href="/auth" className="alldap-nav-cta" style={{ marginLeft: 7, padding: "15px 30px", borderRadius: 9, background: "#171514", color: "#FFFFFF", fontSize: 17, fontWeight: 600 }}>도입 문의</a>
              </nav>
            </div>
          </header>

          <div ref={heroRef} style={{ position: "absolute", top: 0, left: 0, right: 0, height: "100%", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "flex-start", paddingTop: "14vh", gap: 26, zIndex: 4, pointerEvents: "none", willChange: "transform,opacity" }}>
            <h1 style={{ margin: 0, fontSize: "clamp(52px,7.4vw,116px)", lineHeight: 1.0, fontWeight: 800, letterSpacing: "-0.035em", display: "flex", alignItems: "center", gap: 4 }}>
              안녕하세요, 올답입니다.
              <span className="alldap-caret" style={{ display: "inline-block", width: 6, height: "0.86em", background: "#171514" }} />
            </h1>
            <p style={{ margin: 0, textAlign: "center", fontSize: "clamp(19px,2vw,29px)", lineHeight: 1.45, fontWeight: 500, color: "#3A3230" }}>
              문서를 읽고 출처까지 알려주는<br />한국어 AI 안내 데스크
            </p>
          </div>

          <div ref={ctaRef} style={{ position: "absolute", left: "50%", top: "64%", transform: "translateX(-50%)", zIndex: 6, opacity: 0, pointerEvents: "none", willChange: "transform,opacity" }}>
            <div style={{ position: "relative", padding: 18 }}>
              <div style={{ position: "absolute", top: 0, left: 0, width: 28, height: 28, borderTop: "1.6px solid rgba(23,21,20,.4)", borderLeft: "1.6px solid rgba(23,21,20,.4)" }} />
              <div style={{ position: "absolute", top: 0, right: 0, width: 28, height: 28, borderTop: "1.6px solid rgba(23,21,20,.4)", borderRight: "1.6px solid rgba(23,21,20,.4)" }} />
              <div style={{ position: "absolute", bottom: 0, left: 0, width: 28, height: 28, borderBottom: "1.6px solid rgba(23,21,20,.4)", borderLeft: "1.6px solid rgba(23,21,20,.4)" }} />
              <div style={{ position: "absolute", bottom: 0, right: 0, width: 28, height: 28, borderBottom: "1.6px solid rgba(23,21,20,.4)", borderRight: "1.6px solid rgba(23,21,20,.4)" }} />
              {/* 이 화면의 유일한 목적지다. 원본 스펙(17px / 20·34 패딩)보다 키웠다 —
                  줌인이 끝난 뒤 화면 전체에서 눌러야 할 곳이 여기 하나뿐인데 작으면 안 보인다. */}
              <button type="button" onClick={openChat} className="alldap-cta" style={{ display: "flex", alignItems: "center", gap: 14, border: "none", cursor: "pointer", padding: "26px 48px", borderRadius: 14, background: "#171514", color: "#FFFFFF", fontSize: 21, fontWeight: 600, fontFamily: "inherit", letterSpacing: "-0.015em", boxShadow: "0 22px 54px rgba(74,50,46,.32)" }}>
                <span style={{ display: "inline-block", width: 11, height: 11, borderRadius: "50%", background: ACCENT }} />
                챗봇 시작하기
              </button>
            </div>
          </div>

          {/* 이 화면을 어떻게 진행시키는지 알려주는 유일한 안내다. 스펙(21×33 / 13px)으로는
              구석에서 안 읽혀서, 마우스 아이콘과 글자를 함께 키웠다. */}
          <div ref={hintRef} onClick={() => glideTo(1)} style={{ position: "absolute", left: 34, bottom: 34, display: "flex", alignItems: "center", gap: 16, zIndex: 5, cursor: "pointer" }}>
            <div style={{ position: "relative", width: 27, height: 42, border: "2px solid rgba(23,21,20,.55)", borderRadius: 14, display: "flex", justifyContent: "center", paddingTop: 8, flex: "none" }}>
              <span className="alldap-wheel" style={{ display: "block", width: 3, height: 8, borderRadius: 2, background: "#171514" }} />
            </div>
            <p style={{ margin: 0, fontSize: 16, lineHeight: 1.4, fontWeight: 600, color: "#3A3230" }}>스크롤해서<br />안내 데스크로 들어가 보세요</p>
          </div>
        </div>
      </div>

      {/* ── 챗 모달 ── 흰 패널이 아니라 화면 전체를 덮고 뒤 씬을 흐린다.
          로봇 얼굴이 모달 위로 올라와 표정으로 상태를 말한다. */}
      {chatOpen && (
        <div style={{ position: "fixed", inset: 0, zIndex: 30, display: "flex", alignItems: "center", justifyContent: "center", padding: 28 }}>
          <div className="alldap-rise" style={{ width: "min(94vw,760px)", display: "flex", flexDirection: "column", alignItems: "center", gap: 18 }}>
            <button type="button" onClick={() => setChatOpen(false)} aria-label="닫기" style={{ position: "absolute", top: 26, right: 28, border: "none", cursor: "pointer", width: 38, height: 38, borderRadius: 10, background: "rgba(255,255,255,.12)", color: "#F5F0EE", fontSize: 15, fontFamily: "inherit" }}>✕</button>

            <div ref={cHeadRef} style={{ position: "relative", width: 104, height: 102, marginBottom: 2 }}>
              <div style={{ position: "absolute", left: 50, top: -22, width: 5, height: 24, borderRadius: 3, background: "#E4DAD5" }} />
              <div ref={cBulbRef} style={{ position: "absolute", left: 44, top: -38, width: 17, height: 17, borderRadius: "50%", background: ACCENT, boxShadow: "0 0 18px rgba(126,208,192,.8)" }} />
              <div style={{ position: "absolute", left: -15, top: 38, width: 19, height: 29, borderRadius: 10, background: "linear-gradient(160deg,#F4EDEA,#DED3CE)" }} />
              <div style={{ position: "absolute", left: 100, top: 38, width: 19, height: 29, borderRadius: 10, background: "linear-gradient(200deg,#F4EDEA,#DED3CE)" }} />
              <div style={{ position: "absolute", inset: 0, borderRadius: 34, background: "linear-gradient(165deg,#FFFCFB 0%,#F5EEEB 52%,#E4D9D4 100%)", boxShadow: "0 16px 34px rgba(10,6,6,.4)" }} />
              <div style={{ position: "absolute", left: 11, top: 23, width: 82, height: 58, borderRadius: 20, background: "linear-gradient(170deg,#3A322F,#1C1817)", overflow: "hidden" }}>
                <div ref={cEyeLRef} style={{ position: "absolute", left: 23, top: 19, width: 13, height: 20, borderRadius: 7, background: ACCENT, boxShadow: "0 0 12px rgba(126,208,192,.9)" }} />
                <div ref={cEyeRRef} style={{ position: "absolute", left: 46, top: 19, width: 13, height: 20, borderRadius: 7, background: ACCENT, boxShadow: "0 0 12px rgba(126,208,192,.9)" }} />
                <div ref={cMouthRef} style={{ position: "absolute", left: 34, top: 42, width: 14, height: 7, borderRadius: "0 0 10px 10px", background: ACCENT, boxShadow: "0 0 9px rgba(126,208,192,.7)" }} />
                {/* "생각 중" 표시 = 얼굴이 문서가 되고 스캔 라인이 훑는다 */}
                <div ref={cDocRef} style={{ position: "absolute", left: 26, top: 10, width: 30, height: 38, borderRadius: 3, background: "#FBF7F6", opacity: 0, boxShadow: "0 3px 10px rgba(0,0,0,.4)" }}>
                  <div style={{ position: "absolute", left: 5, top: 7, width: 20, height: 2.5, borderRadius: 2, background: "#C9BFBC" }} />
                  <div style={{ position: "absolute", left: 5, top: 14, width: 14, height: 2.5, borderRadius: 2, background: "#D6CDCA" }} />
                  <div style={{ position: "absolute", left: 5, top: 21, width: 18, height: 2.5, borderRadius: 2, background: "#C9BFBC" }} />
                  <div style={{ position: "absolute", left: 5, top: 28, width: 11, height: 2.5, borderRadius: 2, background: "#D6CDCA" }} />
                  <div ref={cScanRef} style={{ position: "absolute", left: 0, top: 0, width: "100%", height: 9, background: "linear-gradient(180deg,rgba(126,208,192,0),rgba(126,208,192,.55),rgba(126,208,192,0))" }} />
                </div>
              </div>
            </div>

            <h2 style={{ margin: 0, fontSize: 29, fontWeight: 700, letterSpacing: "-0.03em", color: "#FBF7F6", textAlign: "center" }}>올답 안내 데스크</h2>
            <p style={{ margin: "-6px 0 0", maxWidth: 520, textAlign: "center", fontSize: 15.5, lineHeight: 1.62, color: "#B8ADAA" }}>
              사내 문서 42건을 학습했어요. 규정·절차·복리후생 무엇이든 물어보시면 근거 문서와 조항까지 함께 알려드릴게요.
            </p>

            {msgs.length > 0 && (
              <div ref={listRef} style={{ width: "100%", maxHeight: "34vh", overflowY: "auto", display: "flex", flexDirection: "column", gap: 10, padding: "4px 2px" }}>
                {msgs.map((m, i) => (
                  <div key={i} style={{ display: "flex", justifyContent: m.role === "me" ? "flex-end" : "flex-start" }}>
                    <div style={{ maxWidth: "76%", padding: "13px 16px", borderRadius: m.role === "me" ? "16px 16px 5px 16px" : "16px 16px 16px 5px", background: m.role === "me" ? "rgba(126,208,192,.16)" : "rgba(255,255,255,.07)", color: m.role === "me" ? "#EAF6F3" : "#F1EAE8", fontSize: 14.5, lineHeight: 1.6 }}>
                      {m.text}
                      {m.source && (
                        <span style={{ display: "block", marginTop: 10, paddingTop: 10, borderTop: "1px solid rgba(255,255,255,.12)", fontSize: 12, fontWeight: 600, color: "#9C918D" }}>
                          출처 · {m.source}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}

            <div style={{ width: "100%", display: "flex", flexDirection: "column", gap: 14, padding: "18px 18px 14px", borderRadius: 22, background: "rgba(32,27,26,.92)", border: "1px solid rgba(255,255,255,.1)", boxShadow: "0 30px 70px rgba(20,12,11,.5)" }}>
              <input
                ref={inputRef}
                onKeyDown={(e) => {
                  if (e.key !== "Enter") return;
                  /*
                   * 🐛 한글 입력에서 <반드시> 필요한 검사다.
                   *
                   * 한글은 자모를 모아 한 글자를 만든다. "알려줘"를 치면 마지막 "줘"는
                   * 아직 <조합 중(composing)> 상태로 입력창에 떠 있다. 이때 Enter 를 누르면
                   *   keydown(Enter) → send() 가 값을 읽고 입력창을 비움
                   *   → 그 <뒤에> IME 가 "줘"를 확정해 빈 입력창에 다시 넣는다
                   * 결과: 마지막 글자가 입력창에 남아 <다음 전송에 딸려 간다.>
                   *
                   * isComposing 이 true 면 이 Enter 는 "조합을 확정하라"는 뜻이지
                   * "전송하라"가 아니다. 그냥 넘겨서 IME 가 처리하게 둔다.
                   * (영문만 쓰면 조합 단계가 없어서 이 버그가 안 보인다 — 한국어 제품이라 필수)
                   */
                  if (e.nativeEvent.isComposing) return;
                  e.preventDefault();
                  send();
                }}
                onInput={() => { anim.current.typing = true; }}
                onFocus={() => { anim.current.typing = true; }}
                onBlur={() => { anim.current.typing = false; }}
                placeholder="무엇이든 물어보세요"
                style={{ width: "100%", border: "none", outline: "none", background: "transparent", color: "#FBF7F6", fontSize: 16, fontFamily: "inherit", padding: "6px 4px" }}
              />
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                {["연차 규정 알려줘", "출장비 정산 절차", "복리후생 요약"].map((label) => (
                  <button key={label} type="button" onClick={() => send(label)} className="alldap-chip" style={{ border: "1px solid rgba(255,255,255,.14)", cursor: "pointer", padding: "9px 15px", borderRadius: 20, background: "rgba(255,255,255,.05)", color: "#CFC5C2", fontSize: 13.5, fontWeight: 500, fontFamily: "inherit", whiteSpace: "nowrap" }}>
                    {label}
                  </button>
                ))}
                <button type="button" onClick={() => send()} aria-label="보내기" className="alldap-send" style={{ marginLeft: "auto", border: "none", cursor: "pointer", width: 40, height: 40, borderRadius: "50%", background: ACCENT, color: "#11201D", fontSize: 17, fontWeight: 700, fontFamily: "inherit", flex: "none" }}>↑</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

