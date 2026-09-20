"use client";
import Link from "next/link";
import { Check, Loader2, Sparkles } from "lucide-react";
import { useConfirmation } from "@/components/ConfirmationProvider";
import { Button } from "@/components/ui/button";
import { agentApi } from "./api";
import { useSchedulingWorkbench } from "./useSchedulingWorkbench";
import SchedulingDraftBoard from "./SchedulingDraftBoard";
import BackToAssistantButton from "./BackToAssistantButton";
import type { Snapshot } from "./types";

export default function SchedulingWorkbench({ snapshot, refresh, loadError }: {
  snapshot: Snapshot; refresh: () => Promise<unknown>; loadError: string;
}) {
  const work = useSchedulingWorkbench(snapshot, refresh);
  const confirm = useConfirmation();
  const { session, active_run } = snapshot;
  const { board, plan } = work;
  const archived = session.status !== "ACTIVE";
  const busy = work.working || !!active_run || archived || (!!session.active_plan_id && !plan);
  const issue = work.error || work.loadError || loadError;
  const assigned = plan?.tasks.reduce((n, task) => n + task.order_ids.length, 0) ?? 0;
  const selectionInvalid = work.selected.some(id => !board?.pending_orders.some(order => order.id === id));
  const explanation = plan?.revision === 1 ? snapshot.messages.find(message => message.role === "assistant" && message.run_id === plan.created_by_run_id)?.content : null;
  const result = snapshot.recent_run_results[0];
  const failed = !active_run && result?.status === "FAILED";
  const lastMessage = [...snapshot.messages].reverse().find(message => message.role === "assistant");
  // Business confirmations use the transient notice; only runtime replies survive a reload.
  const lastReply = !plan && !active_run && lastMessage?.run_id ? lastMessage.content : null;
  async function command(action: "apply" | "replace" | "close") {
    if (!plan) return;
    const options = action === "apply"
      ? { title: "确认下发本次排单？", description: `将 ${assigned} 笔订单下发为 ${plan.tasks.length} 个生产任务。${plan.unassigned.length ? `另有 ${plan.unassigned.length} 笔仍保留为待排单。` : ""}下发后会更新正式排单看板。`, confirmLabel: "确认排单", destructive: false }
      : action === "replace"
        ? { title: "重新生成排单草稿？", description: "将按本次选中的订单重新分析，成功后替换当前草稿和手动调整；失败时保留原草稿。", confirmLabel: "重新生成", destructive: false }
        : { title: "放弃本次排单草稿？", description: "草稿中的调整将清除。订单和已有生产任务会保留，可重新选择订单排单。", confirmLabel: "放弃草稿" };
    if (await confirm(options)) await work.command(action);
  }
  return <main className="flex h-[calc(100dvh-4rem)] min-w-0 flex-col bg-[#F7F8FA] md:h-dvh">
    <header className="shrink-0 border-b border-slate-200 bg-white px-4 py-4 sm:px-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <BackToAssistantButton disabled={work.working} />
          <div><h1 className="text-lg font-semibold text-slate-800">智能排单</h1><p className="mt-1 text-xs text-slate-400">选择订单 → 查看与调整草稿 → 确认排单</p></div>
        </div>
        <Link href="/kanban" className="text-sm text-slate-500 hover:text-slate-900">查看正式看板 →</Link>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        {plan ? <><span className="mr-auto text-sm text-slate-600">本次 {plan.input_order_ids.length} 笔 · 已安排 <b className="text-[#C8331F]">{assigned}</b> 笔{plan.unassigned.length > 0 && ` · 未安排 ${plan.unassigned.length} 笔`}</span>
          <Button variant="ghost" disabled={busy} onClick={() => void command("close")}>放弃草稿</Button>
          <Button variant="outline" disabled={busy} onClick={() => void command("replace")}>重新生成</Button>
          <Button className="bg-[#C8331F] text-white hover:bg-[#A92919]" disabled={busy || !!issue || plan.stale || !assigned} onClick={() => void command("apply")}><Check size={16}/>确认排单</Button></>
          : <><span className="text-sm text-slate-600">已选择 <b className="text-[#C8331F]">{work.selected.length}</b> 笔</span>
            <Button variant="ghost" disabled={busy || !board?.pending_orders.length} onClick={() => work.setSelected(board?.pending_orders.map(order => order.id) ?? [])}>全选</Button>
            <Button variant="ghost" disabled={busy || !work.selected.length} onClick={() => work.setSelected([])}>清空</Button>
            <span className="flex-1"/>
            <Button className="bg-[#C8331F] text-white hover:bg-[#A92919]" disabled={busy || !!issue || !work.selected.length || selectionInvalid} onClick={() => void work.start()}>
              {active_run ? <Loader2 size={16} className="animate-spin"/> : <Sparkles size={16}/>}{active_run ? "正在生成草稿…" : "开始排单"}</Button></>}
      </div>
    </header>
    <div className="shrink-0 space-y-2 px-4 pt-3 sm:px-6">
      {archived && <div className="rounded-xl bg-amber-50 p-3 text-sm text-amber-800">本次记录已归档，当前为只读。<button className="ml-3 underline" disabled={work.working} onClick={() => void work.mutate(() => agentApi.command(`/sessions/${session.id}/restore`))}>恢复记录</button></div>}
      {issue && <div role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-700">{issue}<button className="ml-3 underline" onClick={() => void work.reload()}>刷新看板</button></div>}
      {!plan && selectionInvalid && <p role="alert" className="text-sm text-amber-700">部分已选订单的状态发生变化，请清空后重新选择。</p>}
      {plan?.stale && <p role="alert" className="rounded-xl bg-amber-50 p-3 text-sm text-amber-800">排单规则或生产数据已变化，请重新生成草稿后再确认。</p>}
      {plan?.load_basis === "TASK_COUNT" && <p className="rounded-lg bg-slate-100 px-3 py-2 text-xs leading-5 text-slate-600">同等条件下按任务数粗略比较负载，不代表生产时长。</p>}
      {active_run ? <div role="status" className="flex items-center gap-2 rounded-xl border border-orange-100 bg-orange-50 p-3 text-sm text-[#C8331F]"><Loader2 size={16} className="animate-spin"/>正在核对订单和设备，生成本次排单建议…</div>
        : plan ? <div className="rounded-xl border border-slate-200 bg-white p-3 text-sm leading-6 text-slate-600"><span className="mr-2 font-medium text-slate-800">排单说明</span>{plan.revision > 1 ? "已按你的调整更新草稿，通过机器能力与合单规则校验。" : explanation || "根据设备能力、规格与配方匹配生成草稿，新增任务排在已有任务之后。"}<span className="ml-2 text-xs text-slate-400">{work.working ? "正在保存…" : "草稿已保存"}</span></div>
        : work.notice ? <p role="status" className="rounded-xl bg-green-50 p-3 text-sm text-green-800">{work.notice}</p>
        : failed ? <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-700">本次排单未完成，已选订单保留，可重新点击开始排单。</p>
        : lastReply && <p className="rounded-xl bg-white p-3 text-sm text-slate-600">{lastReply.slice(0,300)}</p>}
    </div>
    {board ? <SchedulingDraftBoard board={board} plan={plan} selected={work.selected} disabled={busy || !!issue || !!plan?.stale}
      toggle={id => work.setSelected(ids => ids.includes(id) ? ids.filter(value => value !== id) : [...ids,id])} save={work.save}/>
      : <p role="status" className="p-8 text-sm text-slate-400">正在加载订单和机器…</p>}
  </main>;
}
