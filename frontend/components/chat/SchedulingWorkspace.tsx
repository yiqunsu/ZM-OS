"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { DndContext, DragOverlay, useDraggable, useDroppable, type DragEndEvent } from "@dnd-kit/core"
import { api, ApiError } from "@/lib/api"
import type { KanbanSnapshot, KanbanOrder } from "@/components/kanban/types"
import type { SchedulePlan } from "./types"

type Draft = SchedulePlan & { revision: string; stale?: boolean }
type Assignment = { machine_id: string; order_ids: string[] }

function DropZone({ id, children }: { id: string; children: React.ReactNode }) {
  const { setNodeRef, isOver } = useDroppable({ id })
  return <div ref={setNodeRef} className={`min-h-10 rounded-xl border border-dashed p-2 transition-colors ${isOver ? "border-blue-500 bg-blue-50 ring-2 ring-blue-200" : "border-transparent"}`}>{children}</div>
}

function OrderChip({ id, label, order, disabled, destinations, move }: {
  id: string; label: string; disabled: boolean;
  order?: KanbanOrder;
  destinations: { id: string; label: string }[]; move: (id: string, target: string) => void;
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id, disabled })
  return <div className="my-2 rounded-xl border border-slate-200/80 bg-white p-3 text-xs shadow-sm">
    <button type="button" ref={setNodeRef} {...attributes} {...listeners} disabled={disabled}
      style={{ opacity: isDragging ? 0.35 : 1, touchAction: "none" }}
      className="relative z-10 flex w-full cursor-grab items-start gap-2 text-left active:cursor-grabbing disabled:cursor-default"><span className="pt-1 text-slate-300">⠿</span><span className="min-w-0 flex-1"><span className="flex items-start justify-between gap-3"><span className="text-sm font-semibold text-slate-800">{order?.customer.company ?? label}</span><span className="shrink-0 font-semibold text-slate-700">{order ? `${order.quantity} ${order.unit}` : ""}</span></span><span className="mt-1 block text-slate-600">{order?.product.name ?? "订单详情待刷新"}</span><span className="mt-1 block text-[11px] leading-relaxed text-slate-400">{order && Object.entries(order.spec_params).map(([key, value]) => `${key} ${value}`).join(" · ")}</span></span></button>
    <div className="mt-2 flex items-center justify-between gap-2 border-t border-slate-100 pt-2"><span className="truncate text-[10px] text-slate-400">{label}</span><select aria-label={`移动订单 ${label}`} disabled={disabled} value="" onChange={e => move(id, e.target.value)} className="max-w-32 rounded bg-transparent py-1 text-[11px] text-slate-500 disabled:opacity-40">
      <option value="">移动到…</option>
      {destinations.map(d => <option key={d.id} value={d.id}>{d.label}</option>)}
    </select></div>
  </div>
}

export default function SchedulingWorkspace({ planId, disabled = false, onApplied }: {
  planId?: string; disabled?: boolean; onApplied?: () => void;
}) {
  const [board, setBoard] = useState<KanbanSnapshot | null>(null)
  const [plan, setPlan] = useState<Draft | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [draggedId, setDraggedId] = useState<string | null>(null)
  const [confirmRevision, setConfirmRevision] = useState<string | null>(null)
  const mutation = useRef(false)
  const generation = useRef(0)
  const load = useCallback(async () => {
    const token = generation.current
    try {
      const [nextBoard, nextPlan] = await Promise.all([
        api.get<KanbanSnapshot>("/kanban"),
        planId ? api.get<Draft>(`/schedule-plans/${planId}`) : Promise.resolve(null),
      ])
      if (token !== generation.current || mutation.current) return
      setBoard(nextBoard)
      setPlan(nextPlan)
      setConfirmRevision(previous => previous && previous !== nextPlan?.revision ? null : previous)
      setError(null)
    } catch (e) {
      if (token === generation.current) setError(e instanceof Error ? e.message : "看板加载失败")
    }
  }, [planId])

  useEffect(() => {
    const currentGeneration = generation
    currentGeneration.current++
    const initial = setTimeout(() => { void load() }, 0)
    const timer = setInterval(() => { if (!mutation.current) void load() }, 5000)
    return () => { currentGeneration.current++; clearTimeout(initial); clearInterval(timer) }
  }, [load])

  const active = plan?.status === "DRAFT" && plan.id === planId
  const locked = disabled || busy || !active || Boolean(plan?.stale) || Boolean(error) || confirmRevision !== null
  const destinations = [
    { id: "pending", label: "暂不安排" },
    ...(board?.machines ?? []).map(m => ({ id: `machine:${m.id}`, label: `${m.name} · 新任务` })),
    ...(active ? plan.tasks : []).map((t, i) => ({ id: `task:${i}`, label: `${t.machine_name} · 草案任务 ${i + 1}` })),
  ]

  async function save(tasks: Assignment[]) {
    if (!plan || mutation.current) return
    mutation.current = true; generation.current++; setBusy(true)
    try {
      const saved = await api.put<Draft>(`/schedule-plans/${plan.id}`, { revision: plan.revision, tasks })
      setPlan(saved); setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : "草案保存失败")
      if (e instanceof ApiError && e.status === 409) setConfirmRevision(null)
    } finally { mutation.current = false; setBusy(false) }
  }

  function move(id: string, target: string) {
    if (locked || !plan || !target) return
    const tasks = plan.tasks.map(t => ({ machine_id: t.machine_id, order_ids: t.order_ids.filter(key => key !== id) }))
    if (target.startsWith("task:")) tasks[Number(target.slice(5))].order_ids.push(id)
    else if (target.startsWith("machine:")) tasks.push({ machine_id: target.slice(8), order_ids: [id] })
    void save(tasks.filter(t => t.order_ids.length))
  }

  function reorder(index: number, direction: number) {
    if (!plan || locked) return
    const tasks = plan.tasks.map(t => ({ machine_id: t.machine_id, order_ids: [...t.order_ids] }))
    const same = tasks.map((t, i) => t.machine_id === tasks[index].machine_id ? i : -1).filter(i => i >= 0)
    const target = same[same.indexOf(index) + direction]
    if (target === undefined) return
    ;[tasks[index], tasks[target]] = [tasks[target], tasks[index]]
    void save(tasks)
  }

  async function apply() {
    if (!plan || !confirmRevision || mutation.current) return
    mutation.current = true; generation.current++; setBusy(true)
    try {
      await api.post(`/schedule-plans/${plan.id}/apply`, { revision: confirmRevision })
      setPlan({ ...plan, status: "APPLIED" }); setConfirmRevision(null); onApplied?.()
    } catch (e) { setError(e instanceof Error ? e.message : "执行失败"); setConfirmRevision(null) }
    finally { mutation.current = false; setBusy(false) }
  }

  function dragEnd(event: DragEndEvent) {
    setDraggedId(null)
    if (event.over) move(String(event.active.id), String(event.over.id))
  }

  const orders = new Map(board?.pending_orders.map(order => [order.id, order]))
  const assignedCount = plan?.tasks.reduce((n, task) => n + task.order_ids.length, 0) ?? 0

  return <div className="flex min-h-0 flex-1 flex-col bg-[#F5F6F8]">
    <div className="border-b border-slate-200/70 bg-white px-5 py-4">
      <div className="flex items-center justify-between gap-2"><h2 className="text-base font-semibold text-slate-900">{active ? "先调整，再下发" : "生产进度"}</h2><span className="flex items-center gap-1.5 text-[10px] text-slate-400"><span className={`h-1.5 w-1.5 rounded-full ${error ? "bg-amber-400" : "bg-emerald-500"}`} />每 5 秒同步</span></div>
      <p className="mt-1.5 text-xs leading-relaxed text-slate-500">{active ? "拖动订单调整机器或合并任务，确认前不会影响实际生产。" : "按机器查看当前生产与等待队列。"}</p>
      {active && <div className="mt-4 flex gap-6 text-xs text-slate-500"><span><strong className="mr-1 text-xl font-semibold text-slate-800">{plan.tasks.length}</strong>新任务</span><span><strong className="mr-1 text-xl font-semibold text-slate-800">{assignedCount}</strong>张已安排</span><span><strong className={`mr-1 text-xl font-semibold ${plan.unassigned.length ? "text-amber-600" : "text-slate-800"}`}>{plan.unassigned.length}</strong>张待处理</span></div>}
      {plan?.stale && active && <p role="alert" className="mt-2 text-sm text-amber-700">生产数据已变化，请让助手重新生成方案。</p>}
      {error && <div role="alert" className="mt-2 text-sm text-red-600">{error} <button onClick={() => void load()} className="underline">重新加载</button></div>}
    </div>
    <DndContext onDragStart={event => setDraggedId(String(event.active.id))} onDragCancel={() => setDraggedId(null)} onDragEnd={dragEnd}>
      <div className="flex-1 space-y-4 overflow-y-auto p-4 md:p-5">
        {!board && <p>正在加载生产看板…</p>}
        <details className="rounded-2xl border border-slate-200/70 bg-white px-4 py-3">
          <summary className="cursor-pointer text-xs font-medium text-slate-600">{active ? "暂未安排" : "待排订单"}<span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5">{active ? plan.unassigned.length : board?.pending_orders.length ?? 0}</span><span className="ml-2 font-normal text-slate-400">展开查看</span></summary>
          <DropZone id="pending">
            {active ? plan.unassigned.map(item => <div key={item.order_id}>
              <OrderChip id={item.order_id} label={item.order_no} order={orders.get(item.order_id)} disabled={locked} destinations={destinations} move={move} />
              <p className="px-2 text-xs text-amber-700">{item.reason}</p>
            </div>) : board?.pending_orders.map(order => <p key={order.id} className="py-2 text-xs text-slate-600">{order.customer.company} · {order.product.name} · {order.quantity}{order.unit}</p>)}
            {active && <p className="py-2 text-center text-[11px] text-slate-400">拖到这里，暂不安排生产</p>}
          </DropZone>
        </details>
        {board?.machines.map(machine => <section key={machine.id} className="overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-sm">
          <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-3.5"><div><h3 className="text-sm font-semibold text-slate-900">{machine.name}</h3><p className="mt-1 text-[11px] text-slate-400">幅宽 {machine.min_width}–{machine.max_width} mm</p></div><span className={`rounded-full px-2.5 py-1 text-[10px] font-medium ${machine.tasks.some(t => t.status === "PRODUCING") ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>{machine.tasks.some(t => t.status === "PRODUCING") ? "生产中" : machine.tasks.length ? "等待生产" : "空闲"}</span></div>
          <div className="p-3">
          {machine.tasks.length > 0 && <details className="mb-3 rounded-lg bg-slate-50 px-3 py-2.5"><summary className="cursor-pointer text-[11px] text-slate-500">已下发队列 · {machine.tasks.length} 个任务<span className="ml-2 text-slate-400">只读</span></summary>{machine.tasks.map(task => <div key={task.id} className="mt-2 border-t border-slate-200/60 pt-2 text-xs text-slate-600"><span className="text-[10px] text-slate-400">{task.status === "PRODUCING" ? "生产中" : "等待生产"}</span>{task.orders.map(o => <p key={o.id} className="mt-1">{o.customer.company} · {o.product.name} · {o.quantity}{o.unit}</p>)}</div>)}</details>}
          {active && plan.tasks.map((task, index) => task.machine_id === machine.id && <div key={index} className="mb-3 rounded-xl bg-blue-50/60 p-2">
            <div className="flex items-center justify-between px-2 pt-1 text-xs"><span className="font-medium text-blue-800">待下发 {plan.tasks.slice(0, index + 1).filter(t => t.machine_id === machine.id).length}<span className="ml-2 font-normal text-blue-600/70">{task.total_width} mm · {task.order_ids.length} 张订单</span></span><div>
              <button aria-label={`任务 ${index + 1} 上移`} disabled={locked} onClick={() => reorder(index, -1)} className="px-2 py-1">↑</button>
              <button aria-label={`任务 ${index + 1} 下移`} disabled={locked} onClick={() => reorder(index, 1)} className="px-2 py-1">↓</button>
            </div></div>
            <DropZone id={`task:${index}`}>
              {task.order_ids.map((id, i) => <OrderChip key={id} id={id} label={task.order_nos[i]} order={orders.get(id)} disabled={locked} destinations={destinations} move={move} />)}
              <p className="text-center text-[10px] text-blue-500/80">拖入此处，合并到该任务</p>
            </DropZone>
            <details className="px-2 pb-1 text-[10px] text-slate-400"><summary className="cursor-pointer">安排依据</summary><p className="mt-1 leading-relaxed">{task.reason}</p></details>
          </div>)}
          {active && <DropZone id={`machine:${machine.id}`}><div className="rounded-lg border border-dashed border-slate-200 py-3 text-center text-[11px] text-slate-400">＋ 拖入订单，在此机器新建任务</div></DropZone>}
          {!machine.tasks.length && !active && <p className="text-xs text-slate-400">暂无任务</p>}
          </div>
        </section>)}
      </div>
      <DragOverlay>{draggedId && <div className="rounded-xl border border-blue-300 bg-white p-4 text-sm font-medium text-slate-700 shadow-xl">{orders.get(draggedId)?.customer.company ?? "移动订单"}<p className="mt-1 text-xs font-normal text-slate-400">{orders.get(draggedId)?.product.name} · 松开以放入高亮区域</p></div>}</DragOverlay>
    </DndContext>
    {active && <div className="shrink-0 border-t border-slate-200 bg-white px-5 py-4 shadow-[0_-4px_16px_rgba(15,23,42,0.03)]">
      <p aria-live="polite" className="mb-3 text-xs text-slate-500">{busy ? "正在保存，请稍候…" : `确认后将下发 ${plan.tasks.length} 个任务，涉及 ${assignedCount} 张订单。`}</p>
      {confirmRevision ? <div role="group" aria-label="确认当前草案">
        <p className="mb-2 text-sm">确认将刚才核对的草案下发生产？</p>
        <button disabled={busy || disabled || plan.stale || !!error} onClick={() => void apply()} className="rounded bg-red-700 px-3 py-2 text-white disabled:opacity-40">确认执行</button>
        <button disabled={busy} onClick={() => setConfirmRevision(null)} className="ml-2 px-3 py-2">取消</button>
      </div> : <button disabled={locked || !plan.tasks.length} onClick={() => setConfirmRevision(plan.revision)} className="w-full rounded-xl bg-[#C8331F] py-3 text-sm font-medium text-white shadow-sm transition-colors hover:bg-[#AD2B1A] disabled:opacity-40">核对方案并下发生产 →</button>}
    </div>}
  </div>
}
