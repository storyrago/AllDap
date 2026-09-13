import { redirect } from "next/navigation";

import { parseId } from "@/lib/ids";

/**
 * `/bot/[botId]` 자체는 PRD §7 사이트맵에 없는 경로다.
 * 그래도 사용자가 주소창에서 뒤를 지우고 들어올 수 있으므로
 * 404 대신 첫 화면(문서 관리)으로 보낸다.
 *
 * 다만 <말이 안 되는 id>(`/bot/abc`)까지 보내지는 않는다. parseId 가 먼저 404 로 끊는다.
 * 안 끊으면 `/bot/abc/documents` 로 한 번 더 튕긴 뒤 거기서 404 가 나, 주소만 지저분해진다.
 */
export default async function BotIndexPage({
  params,
}: {
  params: Promise<{ botId: string }>;
}) {
  const { botId: rawBotId } = await params;
  const botId = parseId(rawBotId);
  redirect(`/bot/${botId}/documents`);
}
