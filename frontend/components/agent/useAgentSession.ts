"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { AgentError, agentApi } from "./api";
import type { Event, Snapshot } from "./types";

import { EVENT_KINDS } from "./contracts.generated";

export function useAgentSession(sid: string | null) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState("");
  const [connected, setConnected] = useState(false);
  const [partial, setPartial] = useState<Record<string, string>>({});
  const [progress, setProgress] = useState<Event[]>([]);
  const cursor = useRef(0);
  const generation = useRef(0);
  const onSnapshot = useRef<((value: Snapshot) => void) | null>(null);
  const refresh = useCallback(async () => {
    if (!sid) return null;
    const version = generation.current;
    const next = await agentApi.get<Snapshot>(`/sessions/${sid}/snapshot`);
    if (version === generation.current) {
      setSnapshot((old) =>
        !old || next.event_cursor >= old.event_cursor ? next : old,
      );
      setError("");
      onSnapshot.current?.(next);
    }
    return next;
  }, [sid]);

  useEffect(() => {
    generation.current++;
    const version = generation.current;
    let source: EventSource | null = null;
    let update: ReturnType<typeof setTimeout> | null = null;
    let disposed = false;
    cursor.current = 0;
    const reload = () => {
      if (disposed) return;
      void refresh().catch((e) => {
        if (!disposed) {
          setError(e instanceof Error ? e.message : "加载失败");
          if (e instanceof AgentError && [401, 404, 410].includes(e.status)) {
            source?.close();
            source = null;
            setConnected(false);
          }
        }
      });
    };
    const connect = (initial: Snapshot) => {
      if (disposed || source || version !== generation.current) return;
      cursor.current = initial.event_cursor;
      source = new EventSource(
        `/api/agent/v2/sessions/${sid}/events?stream=true&after=${initial.event_cursor}`,
      );
      source.onopen = () => {
        if (!disposed) setConnected(true);
      };
      source.onerror = () => {
        if (!disposed) {
          setConnected(false);
          reload();
        }
      };
      const receive = (raw: MessageEvent<string>) => {
        if (disposed) return;
        try {
          const event: Event = JSON.parse(raw.data);
          if (event.seq <= cursor.current) return;
          cursor.current = event.seq;
          if (
            event.kind === "run.progress" ||
            event.kind.startsWith("tool.") ||
            event.kind === "recognition.completed"
          ) {
            setProgress((old) => [...old, event].slice(-80));
          }
          if (event.kind === "assistant.delta" && event.run_id) {
            const rid = event.run_id;
            setPartial((old) => ({
              ...old,
              [rid]: (old[rid] ?? "") + (event.payload.text ?? ""),
            }));
          } else {
            if (
              event.run_id &&
              ["message.completed", "run.failed", "run.cancelled"].includes(
                event.kind,
              )
            ) {
              const rid = event.run_id;
              setPartial((old) => {
                const next = { ...old };
                delete next[rid];
                return next;
              });
            }
            if (!update)
              update = setTimeout(() => {
                update = null;
                reload();
              }, 100);
          }
        } catch {
          reload();
        }
      };
      for (const kind of EVENT_KINDS)
        source.addEventListener(kind, receive as EventListener);
    };
    onSnapshot.current = connect;
    const timer = setTimeout(async () => {
      setSnapshot(null);
      setPartial({});
      setProgress([]);
      setError("");
      setConnected(false);
      if (!sid) return;
      try {
        await refresh();
      } catch (e) {
        if (!disposed) setError(e instanceof Error ? e.message : "加载失败");
      }
    }, 0);
    const polling = setInterval(reload, 10000);
    return () => {
      disposed = true;
      if (onSnapshot.current === connect) onSnapshot.current = null;
      generation.current = version + 1;
      clearTimeout(timer);
      clearInterval(polling);
      if (update) clearTimeout(update);
      source?.close();
    };
  }, [sid, refresh]);
  return { snapshot, error, connected, partial, progress, refresh };
}
