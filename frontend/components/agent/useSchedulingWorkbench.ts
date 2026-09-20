"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { agentApi } from "./api";
import { useAgentOperation } from "./useAgentOperation";
import type { KanbanSnapshot } from "@/components/kanban/types";
import type { Plan, PlanTask, Snapshot } from "./types";

export function useSchedulingWorkbench(snapshot: Snapshot, refresh: () => Promise<unknown>) {
  const { session } = snapshot;
  const [board, setBoard] = useState<KanbanSnapshot | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [selected, setSelected] = useState<string[]>(session.state?.scheduling_order_ids ?? []);
  const [loadError, setLoadError] = useState("");
  const [notice, setNotice] = useState("");
  const operation = useAgentOperation();
  const generation = useRef(0);
  const mutating = useRef(false);
  const reload = useCallback(async () => {
    const version = ++generation.current;
    try {
      const [nextBoard, nextPlan] = await Promise.all([
        api.get<KanbanSnapshot>("/kanban"),
        session.active_plan_id ? agentApi.get<Plan>(`/plans/${session.active_plan_id}`) : Promise.resolve(null),
      ]);
      if (version !== generation.current || mutating.current) return;
      setBoard(nextBoard);
      setPlan(nextPlan);
      setLoadError("");
    } catch (error) {
      if (version === generation.current) setLoadError(error instanceof Error ? error.message : "看板加载失败");
    }
  }, [session.active_plan_id]);
  useEffect(() => {
    const initial = setTimeout(() => void reload(), 0);
    const interval = setInterval(() => void reload(), 15000);
    return () => { clearTimeout(initial); clearInterval(interval); };
  }, [reload, snapshot.event_cursor]);
  async function mutate(action: () => Promise<unknown>) {
    await operation.act(async () => {
      mutating.current = true;
      generation.current++;
      try { await action(); }
      finally { mutating.current = false; await refresh(); await reload(); }
    });
  }
  async function start() {
    await mutate(async () => {
      await agentApi.command(`/sessions/${session.id}/schedule`, {
        expected_state_revision: session.state_revision, order_ids: [...selected].sort(),
      });
      setNotice("");
    });
  }
  async function save(tasks: PlanTask[]) {
    if (!plan) return;
    await mutate(async () => {
      const saved = await agentApi.put<Plan>(`/plans/${plan.id}/draft`, {
        expected_revision: plan.revision, tasks: tasks.map(({ draft_task_id, machine_id, order_ids }) => ({ draft_task_id, machine_id, order_ids })),
      });
      setPlan(saved);
      setNotice("调整已保存");
    });
  }
  async function command(action: "apply" | "replace" | "close") {
    if (!plan) return;
    await mutate(async () => {
      await agentApi.command(`/plans/${plan.id}/${action}`, {
        expected_revision: plan.revision,
        ...(action === "close" ? { confirmed: true } : {}),
      });
      if (action !== "replace") setPlan(null);
      if (action === "apply") {
        setSelected(plan.unassigned.map(row => row.order_id));
        setNotice(`排单成功，已下发 ${plan.tasks.reduce((n, task) => n + task.order_ids.length, 0)} 笔订单。`);
      }
      if (action === "close") { setSelected(plan.input_order_ids); setNotice("草稿已放弃，订单仍在待排列表。"); }
    });
  }
  return { board, plan: plan?.id === session.active_plan_id ? plan : null, selected, setSelected, loadError, notice, reload: async () => { operation.setError(""); await reload(); },
    error: operation.error, working: operation.working, start, save, command, mutate };
}
