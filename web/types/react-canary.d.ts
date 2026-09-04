/// <reference types="react/canary" />

// `ViewTransition` 은 React 가 실제로 export 하는데(Next 이 품은 react 에서 확인),
// 타입은 `@types/react/index.d.ts` 가 아니라 `canary.d.ts` 에 들어 있다.
// 이 한 줄이 없으면 `import { ViewTransition } from "react"` 가 타입 에러가 난다.
// tsconfig 의 include 가 `**/*.ts` 라 이 파일은 자동으로 잡힌다.
// (주석을 /* */ 블록으로 쓰면 위 include 패턴 안의 `*/` 가 블록을 조기 종료시켜
//  타입 에러가 난다 — 그래서 이 설명은 줄 주석(//)으로 쓴다.)
export {};
