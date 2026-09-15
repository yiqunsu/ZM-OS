"use client";
import { useRouter } from "next/navigation";
import { useAgentOperation } from "./useAgentOperation";
import { useAgentWorkspace } from "./useAgentWorkspace";
import { useAgentSession } from "./useAgentSession";
import OrderWorkbench from "./OrderWorkbench";
import SchedulingWorkbench from "./SchedulingWorkbench";
import AgentHome from "./AgentHome";

export default function AgentShell({ requestedSessionId }: { requestedSessionId: string | null }) {
  const router = useRouter();
  const { error, working, act } = useAgentOperation();
  const openWorkspace = useAgentWorkspace(act);
  const { snapshot, error: loadError, refresh } = useAgentSession(requestedSessionId);
  const message = error || loadError;
  const notice = message ? (
    <p role="alert" className="rounded-xl bg-red-50 p-4 text-sm text-red-700">
      {message}
      {requestedSessionId && (
        <button className="ml-3 underline" onClick={() => void act(refresh)}>刷新</button>
      )}
    </p>
  ) : null;
  if (!requestedSessionId) return <AgentHome working={working} notice={notice} create={openWorkspace} />;
  if (!snapshot) return <main className="p-8">{notice || <p role="status">正在恢复工作区…</p>}
    <button className="mt-4 underline" onClick={() => router.push("/")}>返回助手首页</button></main>;
  return snapshot.session.agent_type === "ORDER_INTAKE"
    ? <OrderWorkbench key={snapshot.session.id} snapshot={snapshot} refresh={refresh} loadError={loadError} />
    : <SchedulingWorkbench key={snapshot.session.id} snapshot={snapshot} refresh={refresh} loadError={loadError} />;
}
