/**
 * URL 의 동적 세그먼트(`/bot/[botId]`)를 숫자 id 로 바꾸는 <경계>.
 *
 * 2026-09-13 에 기본키가 UUID v4 에서 BIGINT 순번으로 바뀌면서 생긴 파일이다.
 *
 * ── 왜 URL 파라미터는 언제나 string 인가
 *    URL 은 텍스트다. `/bot/47` 의 "47" 은 주소 문자열의 한 조각일 뿐이고,
 *    Next 의 `params` · `useParams()` 도 그래서 항상 `string` 을 준다
 *    (타입 선언이 그렇게 돼 있는 게 아니라, 원래 가진 정보가 문자열뿐이다).
 *    숫자로 바꾸는 일은 <우리 몫>이고, 그 자리를 한 곳에 모은 것이 이 파일이다.
 *
 * ── 왜 각 페이지에서 Number() 를 부르지 않는가
 *    전에는 id 가 UUID 라 모양이 틀리면 서버가 걸렀다. 이제는 <여기가 첫 관문>이다.
 *    페이지마다 변환하면 검사를 빠뜨리는 곳이 반드시 생기고, 그때 `/api/bots/NaN`
 *    같은 요청이 나간다. 경계를 한 함수로 좁히면 빠뜨릴 자리가 없다.
 */
import { notFound } from "next/navigation";

import type { Id } from "./types";

/**
 * 숫자 id 의 모양. `Number()` 를 바로 쓰지 않는 이유가 전부 여기 들어 있다.
 *
 *   Number("")                 → 0          빈 문자열이 0번 봇이 된다
 *   Number(" 1 ")              → 1          공백이 조용히 먹힌다
 *   Number("1.5")              → 1.5        정수가 아닌데 통과한다
 *   Number("1e3")              → 1000       주소에 없던 숫자가 만들어진다
 *   Number("0x10")             → 16         같은 이유
 *   Number("-1")               → -1         존재할 수 없는 id
 *   Number("abc")              → NaN        이건 눈에 띄지만, 위의 것들은 안 띈다
 *
 * 그래서 <먼저 모양을 막고> 나서 숫자로 바꾼다. `[1-9][0-9]*` 는
 * "0 으로 시작하지 않는 양의 정수" 다 (id 는 IDENTITY 라 1부터 매겨진다).
 */
const ID_PATTERN = /^[1-9][0-9]*$/;

/**
 * 이 문자열이 id 로 쓸 수 있는 모양인가. `parseId` 의 판단만 떼어낸 것이다.
 *
 * 왜 떼어냈나: `parseId` 는 실패할 때 `notFound()` 를 부르는데, 그건 Next 의 렌더
 * 흐름 안에서만 의미가 있어 <자체 점검으로 돌릴 수가 없다>. 이 저장소는 이미
 * "짜둔 검사가 아무 데서도 안 돌아서" 오픈 리다이렉트를 배포까지 보낸 적이 있다
 * (AGENTS.md). 그래서 판단만 순수 함수로 빼 `lib/ids.check.ts` 가 CI 에서 돌린다.
 */
export function isValidId(raw: string): boolean {
  if (!ID_PATTERN.test(raw)) return false;
  return Number.isSafeInteger(Number(raw));
}

/**
 * URL 세그먼트를 {@link Id} 로. 형식이 틀리면 404 화면으로 보낸다.
 *
 * ── 왜 400 이 아니라 404 인가
 *    이 저장소는 이미 "남의 봇은 403 이 아니라 404" 라는 규칙을 갖고 있다
 *    (403 은 "그 봇은 존재한다" 를 알려주는 셈이라, 번호를 훑어 남의 봇 존재 여부를
 *    알아낼 수 있다). 잘못된 id 를 400 으로 따로 구분해 주면 같은 구멍이 다시 열린다.
 *    "없는 봇" · "남의 봇" · "말이 안 되는 id" 가 <전부 같은 404> 여야 훑어도 얻는 것이 없다.
 *
 * ── 왜 값을 돌려주는 대신 예외를 던지는 방식인가
 *    `notFound()` 는 반환하지 않는다(타입이 `never` 다). 그래서 호출부는
 *    `const botId = parseId(raw)` 한 줄로 끝나고, 실패를 처리하는 분기가 필요 없다.
 *    검사를 잊을 자리 자체가 생기지 않는다.
 *
 * ⚠️ 서버 컴포넌트와 클라이언트 컴포넌트 양쪽에서 쓴다. `next/navigation` 의
 *    `notFound()` 는 둘 다 지원한다(클라이언트에서는 가장 가까운 not-found 경계를 그린다).
 */
export function parseId(raw: string): Id {
  /* isValidId 가 두 가지를 본다: 모양(정규식)과 <정확히 담기는가>(Number.isSafeInteger).
     둘째가 필요한 이유 - 정규식을 통과해도 자릿수가 너무 길면 number 로 정확히 담기지 않는다.
     "9007199254740993" 은 9007199254740992 가 되어 <조용히 다른 봇>을 가리킨다. */
  if (!isValidId(raw)) notFound();
  return Number(raw);
}
