import { redirect } from "next/navigation";

/**
 * `/bot/[botId]` 자체는 PRD §7 사이트맵에 없는 경로다.
 * 그래도 사용자가 주소창에서 뒤를 지우고 들어올 수 있으므로
 * 404 대신 첫 화면(문서 관리)으로 보낸다.
 */
export default async function BotIndexPage({
  params,
}: {
  params: Promise<{ botId: string }>;
}) {
  const { botId } = await params;
  redirect(`/bot/${botId}/documents`);
}
