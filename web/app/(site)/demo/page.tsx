import type { Metadata } from "next";
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";

import { DemoConsole } from "@/components/DemoConsole";
import { PageIntro } from "@/components/Evidence";

/**
 * `/demo` — 데모 봇이 <무엇을 학습했는지 전부 보여주고> 그 위에서 답을 시험해보는 화면.
 *
 * ── 왜 이 페이지가 따로 필요한가 ─────────────────────────────────────────
 * 랜딩에 있던 데모는 "무엇이든 물어보세요" 였는데, 방문자는 이 봇이 무슨 문서를 갖고
 * 있는지 모르니 답이 맞는지 틀린지 판단할 수가 없었다. 남의 회사 인사규정에 대해
 * 그럴듯한 답이 나와도 그건 <아무것도 증명하지 않는다.>
 *
 * 문서를 옆에 펼쳐두면 이야기가 달라진다:
 *   - 문서에 있는 것을 물으면 → 출처가 붙은 답이 나오고, 그 출처를 열어 대조할 수 있다
 *   - 문서에 없는 것을 물으면 → 지어내지 않고 거절한다
 * 두 번째가 이 제품이 파는 유일한 주장이고, <그건 남의 문서로도 증명된다.>
 *
 * ── 왜 API 가 아니라 파일을 읽는가 ───────────────────────────────────────
 * 문서 목록·본문을 공개로 내려주는 엔드포인트를 만들면, 그 순간부터 <모든 봇의 문서를
 * 인증 없이 읽을 수 있는 문>이 하나 생긴다. 실제 고객 문서를 받는 제품에서 그건
 * 만들면 안 되는 문이다. 이 데모의 코퍼스는 우리가 만든 테스트 문서라 저장소에 그대로
 * 있고(`ai-service/testdata/corpus/`), 그걸 읽으면 새 공개 API 없이 같은 화면이 나온다.
 *
 * ⚠️ 대신 <파일과 DB 가 어긋날 수 있다.> 이 페이지는 "봇이 실제로 가진 문서"가 아니라
 *    "봇에 넣었던 원본 파일"을 보여준다. 둘은 같아야 하지만 자동으로 보장되지는 않는다.
 *    (그 원본이 DB 청크와 일치한다는 것은 2026-08-17 에 재청킹으로 대조해 확인했다 —
 *     `AGENTS.md` 의 "코퍼스 확장" 절 참고)
 *
 * ── 이 파일이 서버 컴포넌트인 이유 ───────────────────────────────────────
 * 파일시스템은 서버에만 있다. 그리고 `export const metadata` 도 서버 컴포넌트 전용이다.
 * 브라우저가 필요한 부분(문서 고르기·채팅)만 `<DemoConsole />` 로 떼어 클라이언트로 보낸다.
 *
 * 호출하는 API: 없음(이 파일은). 채팅은 DemoConsole 이 위젯 공개 API 로 직접 부른다.
 */
export const metadata: Metadata = {
  title: "데모 — AllDap",
  description:
    "데모 봇이 학습한 문서를 전부 공개합니다. 문서에 있는 것은 출처와 함께 답하고, 없는 것은 답하지 않는다는 것을 직접 확인해 보세요.",
};

/**
 * 코퍼스 원본 위치. `web/` 에서 한 단계 올라가 `ai-service/` 로 간다.
 *
 * ⚠️ `process.cwd()` 는 개발·빌드 모두 `web/` 이다. 저장소를 통째로 두고 쓰는 지금은
 *    맞지만, `web/` 만 컨테이너에 복사해 배포하면 이 경로가 사라진다. 그때는 빌드 시점에
 *    JSON 으로 굽거나 `public/` 으로 복사하는 단계가 필요하다. 지금은 배포 전이라 남겨둔다.
 */
const CORPUS_DIR = path.join(process.cwd(), "..", "ai-service", "testdata", "corpus");

export interface CorpusDoc {
  /** 파일명. 답변의 `sources[].filename` 과 맞춰보는 열쇠다. */
  filename: string;
  /** 문서 첫 줄의 `# 제목`. 없으면 파일명을 쓴다. */
  title: string;
  body: string;
}

async function loadCorpus(): Promise<CorpusDoc[]> {
  try {
    const names = (await readdir(CORPUS_DIR)).filter((n) => n.endsWith(".md")).sort();
    return await Promise.all(
      names.map(async (filename) => {
        const body = await readFile(path.join(CORPUS_DIR, filename), "utf-8");
        // `# 제목` 한 줄을 뽑는다. m 플래그가 있어야 첫 줄이 아니어도 잡힌다.
        const title = body.match(/^#\s+(.+)$/m)?.[1]?.trim() ?? filename.replace(/\.md$/, "");
        return { filename, title, body };
      }),
    );
  } catch {
    // 코퍼스를 못 읽어도 화면은 떠야 한다. 채팅은 문서 목록과 무관하게 동작한다.
    return [];
  }
}

export default async function DemoPage() {
  const docs = await loadCorpus();

  return (
    <div className="mx-auto w-full max-w-5xl px-6 py-12">
      <PageIntro
        eyebrow="데모"
        title="이 봇이 아는 것 전부입니다"
        lead={
          docs.length > 0
            ? `문서 ${docs.length}개를 학습했습니다. 여기 있는 내용은 출처와 함께 답하고, 없는 내용은 지어내지 않고 거절합니다. 왼쪽에서 문서를 열어 답과 대조해 보세요.`
            : "코퍼스 파일을 읽지 못했습니다. 채팅은 그대로 동작하지만 문서 목록은 비어 있습니다."
        }
      />
      <DemoConsole docs={docs} />
    </div>
  );
}
