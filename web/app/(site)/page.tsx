import Link from "next/link";
import { Placeholder } from "@/components/Placeholder";

/**
 * `/` 랜딩 페이지 — PRD §8 "가치 제안, 데모, CTA / SEO, 반응형"
 *
 * 호출하는 API: 없음. 로그인 없이 보는 정적 화면이다.
 * (데모 챗봇을 붙인다면 그때 POST /api/w/{publicKey}/chat 을 쓰게 된다.)
 */
export default function LandingPage() {
  return (
    <div className="mx-auto w-full max-w-5xl px-6 py-16">
      {/* ── 가치 제안 (PRD §1.1) ───────────────────────────── */}
      <section className="max-w-2xl">
        <h1 className="text-3xl font-semibold leading-snug sm:text-4xl">
          문서를 올리면, 출처까지 보여주는 챗봇이 됩니다.
        </h1>
        <p className="mt-4 text-muted">
          AllDap 은 업로드한 문서에 근거가 없으면 답을 지어내지 않습니다.
          모르면 모른다고 답하고, 그 미답변 기록을 모아 무엇을 보강해야 하는지 알려줍니다.
        </p>
        <div className="mt-8 flex gap-3">
          <Link
            href="/auth"
            className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white"
          >
            무료로 시작하기
          </Link>
          <Link
            href="/dashboard"
            className="rounded-md border border-subtle px-4 py-2 text-sm"
          >
            대시보드 보기
          </Link>
        </div>
      </section>

      {/* ── 아직 안 만든 영역들 ────────────────────────────── */}
      <div className="mt-16 space-y-4">
        <Placeholder title="핵심 가치 3단 소개">
          <p>① 출처가 붙는 답변 ② 근거 없으면 거절(환각 억제) ③ 답변 품질 자동 평가.</p>
          <p>TODO(W2 이후): 카피와 스크린샷을 채운다. 지금은 자리만 잡아둔 상태.</p>
        </Placeholder>

        <Placeholder
          title="라이브 데모 위젯"
          api="POST /api/w/{publicKey}/chat (공개 · rate limit)"
        >
          <p>
            방문자가 가입 없이 바로 질문해볼 수 있는 데모. 시드 봇(public_key =
            pk_local_dev)을 붙이면 된다.
          </p>
          <p>TODO(W2): 위젯 컴포넌트를 /w/[publicKey] 와 공유하도록 만들 것.</p>
        </Placeholder>

        <Placeholder title="SEO 메타데이터 · Open Graph">
          <p>
            PRD §8 은 랜딩에 SEO 를 요구한다. Next.js 는 각 page 에서 `metadata` 를
            export 하면 된다.
          </p>
          <p>TODO(W4): og:image, 구조화 데이터(JSON-LD)를 넣을 것.</p>
        </Placeholder>
      </div>
    </div>
  );
}
