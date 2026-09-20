"use client";
import { useRef, useState } from "react";

export function useAgentOperation() {
  const [error, setError] = useState("");
  const [working, setWorking] = useState(false);
  const processing = useRef(false);
  async function act(operation: () => Promise<unknown>) {
    if (processing.current) return;
    processing.current = true;
    setWorking(true);
    setError("");
    try {
      await operation();
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败，请重试");
    } finally {
      processing.current = false;
      setWorking(false);
    }
  }
  return { error, setError, working, act };
}
export type AgentOperation = ReturnType<typeof useAgentOperation>["act"];
