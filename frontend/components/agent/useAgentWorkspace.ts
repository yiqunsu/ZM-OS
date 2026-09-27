"use client";
import { useRouter } from "next/navigation";
import { agentApi } from "./api";
import type { Session, AgentType } from "./types";
import type { AgentOperation } from "./useAgentOperation";

export function useAgentWorkspace(act: AgentOperation) {
  const router = useRouter();
  return async function openWorkspace(type: AgentType) {
    await act(async () => {
      const created = await agentApi.command<{ session: Session }>(
        type === "ORDER_INTAKE" ? "/intake/workspace" : "/scheduling/workspace",
        {},
      );
      router.push(`/?session=${encodeURIComponent(created.session.id)}`);
    });
  };
}
