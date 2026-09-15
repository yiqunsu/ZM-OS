import AgentShell from "@/components/agent/AgentShell";

export const dynamic = "force-dynamic";

export default async function Home({
  searchParams,
}: {
  searchParams: Promise<{ session?: string | string[] }>;
}) {
  const params = await searchParams;
  const requestedSessionId = typeof params.session === "string" ? params.session : null;

  return <AgentShell key={requestedSessionId ?? "agent-home"} requestedSessionId={requestedSessionId} />;
}
