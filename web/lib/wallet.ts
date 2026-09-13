import type { BillingCard, Id } from "./types";

/**
 * 계정당 카드 상한. 서버(`BillingService.MAX_METHODS`)와 같은 값이다.
 * 화면(`app/(dashboard)/account/page.tsx`)에서 여기로 옮겼다. 판단이 이 파일로 왔기 때문이다.
 * 여기 두는 이유는 <버튼을 미리 감추기> 위해서일 뿐, 판단은 서버가 한다(넘으면 409).
 * 두 값이 어긋나면 화면이 허용한 등록을 서버가 거부하는 것으로 드러난다. 조용히 틀리진 않는다.
 */
export const MAX_METHODS = 5;

/** 카드 상태에서 화면이 무엇을 그릴지. 마크업이 아니라 <판단>만 담는다. */
export interface WalletView {
  /** 청구에 쓰이는 카드. 없을 수 있다 */
  billed: BillingCard | undefined;
  /** 서랍에 들어갈 카드. 청구 카드는 빠진다 (두 번 그리면 혼동이 돌아온다) */
  others: BillingCard[];
  /** 카드는 있는데 기본이 없다. 서버 불변식이 깨진 상태다 */
  warnNoDefault: boolean;
  /** 서랍을 그리는가. 아니면 등록 자리만 그린다 */
  showDrawer: boolean;
  /** 서랍을 열어둘 것인가 */
  drawerOpen: boolean;
  /** 상한에 닿았는가 */
  full: boolean;
}

export function walletView(methods: BillingCard[], justAddedId: Id | null): WalletView {
  const billed = methods.find((m) => m.isDefault);
  /* 청구 카드는 서랍에 <다시> 넣지 않는다. 두 번 그리면 "왜 같은 카드가 두 개지" 가 되고,
     지갑 구조가 없애려던 혼동이 그대로 돌아온다. */
  const others = methods.filter((m) => m.id !== billed?.id);
  /* 🔴 카드는 있는데 기본이 없는 상태. V7 부분 유니크 인덱스는 "기본 1장 이하" 만 보장하고
     "1장 이상" 은 앱 코드가 지킨다(BillingService.register 에 TOCTOU 경합이 있다).
     전에는 이때 목록을 통째로 안 그려서, 사용자가 자기 카드를 보지도 지우지도 못하는데
     토스에는 빌링키가 남았다. 어느 카드로 청구되는지는 우리도 모른다. 그렇게 말하고
     지정할 수 있게 열어준다. 아무 카드나 청구 카드로 그리는 것은 모르는 것을 아는 척하는 것이다. */
  const warnNoDefault = billed === undefined && methods.length > 0;
  return {
    billed,
    others,
    warnNoDefault,
    /* 서랍의 조건은 <카드가 있는가> 다. billed 가 아니다. 이 한 줄이 B-3 의 전부다. */
    showDrawer: methods.length > 0,
    /* 방금 추가했으면 연다(안 열면 2번째부터 등록한 카드가 닫힌 서랍 안으로 사라진다).
       기본이 없을 때도 연다(거기서 지정해야 한다). */
    drawerOpen: (justAddedId !== null && others.some((c) => c.id === justAddedId)) || warnNoDefault,
    full: methods.length >= MAX_METHODS,
  };
}
