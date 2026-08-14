import ChatInterface from "@/components/chat/ChatInterface";

export default async function Home({
  searchParams,
}: {
  searchParams: Promise<{ session?: string | string[] }>;
}) {
  const params = await searchParams;
  const requestedSessionId = typeof params.session === "string" ? params.session : null;

  return (
    <ChatInterface
      key={requestedSessionId ?? "new-conversation"}
      requestedSessionId={requestedSessionId}
    />
  );
}
