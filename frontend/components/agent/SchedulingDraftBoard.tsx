"use client";
import { DndContext, PointerSensor, useSensor, useSensors, useDraggable, type DragEndEvent } from "@dnd-kit/core";
import { CSS } from "@dnd-kit/utilities";
import { ArrowUp, ArrowDown, GripVertical } from "lucide-react";
import MachineColumn from "@/components/kanban/MachineColumn";
import OrderCard from "@/components/kanban/OrderCard";
import type { KanbanSnapshot } from "@/components/kanban/types";
import type { Plan, PlanTask } from "./types";

interface Props { board: KanbanSnapshot; plan: Plan | null; selected: string[]; disabled: boolean;
  toggle: (id: string) => void; save: (tasks: PlanTask[]) => Promise<void>; }
export default function SchedulingDraftBoard({ board, plan, selected, disabled, toggle, save }: Props) {
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }));
  const assigned = new Set(plan?.tasks.flatMap(task => task.order_ids));
  const pending = board.pending_orders.filter(order => !assigned.has(order.id));
  function move(index: number, machine: string) {
    if (plan) void save([...plan.tasks.filter((_, i) => i !== index), { ...plan.tasks[index], machine_id: machine }]);
  }
  function reorder(index: number, delta: number) {
    if (!plan) return;
    const tasks = [...plan.tasks];
    const same = tasks.map((task, i) => task.machine_id === tasks[index].machine_id ? i : -1).filter(i => i >= 0);
    const target = same[same.indexOf(index) + delta];
    if (target === undefined) return;
    [tasks[index], tasks[target]] = [tasks[target], tasks[index]];
    void save(tasks);
  }
  function relocate(orderId: string, destination: string) {
    if (!plan) return;
    let tasks = plan.tasks.map(task => ({ ...task, order_ids: task.order_ids.filter(id => id !== orderId) }));
    if (destination.startsWith("task:")) {
      const index = Number(destination.slice(5));
      tasks[index] = { ...tasks[index], order_ids: [...tasks[index].order_ids, orderId] };
    } else if (destination) {
      tasks.push({ machine_id: destination, order_ids: [orderId], machine_name: "", order_nos: [], total_width: 0, reason: "" });
    }
    tasks = tasks.filter(task => task.order_ids.length);
    void save(tasks);
  }
  function drop(event: DragEndEvent) {
    if (!plan || disabled || !event.over) return;
    const index = event.active.data.current?.draftIndex;
    const machine = event.over.data.current?.machineId;
    if (typeof index === "number" && typeof machine === "string") move(index, machine);
  }
  function destination(orderId: string, index?: number) {
    const meterOrder = board.pending_orders.find(order => order.id === orderId)?.unit === "m";
    return <select aria-label={`安排订单 ${orderId}`} disabled={disabled} value="" onChange={e => { if (e.target.value) relocate(orderId, e.target.value === "unassigned" ? "" : e.target.value); }}
      className="mt-2 w-full rounded-lg border border-slate-200 bg-white px-2 py-2 text-xs">
      <option value="">{index === undefined ? "选择机器或加入已有草稿任务" : "调整订单分组"}</option>
      {index !== undefined && <option value="unassigned">移回未安排</option>}
      {board.machines.map(machine => <option key={machine.id} value={machine.id}>{machine.name} · 单独生产</option>)}
      {plan?.tasks.map((task, i) => i !== index && task.order_ids.every(id => (board.pending_orders.find(order => order.id === id)?.unit === "m") === meterOrder) && <option key={task.draft_task_id ?? i} value={`task:${i}`}>{task.machine_name} · 合入草稿任务 {i + 1}</option>)}
    </select>;
  }
  return <DndContext sensors={sensors} onDragEnd={drop}>
    <div className="flex min-h-0 flex-1 gap-4 overflow-x-auto px-4 pb-4 pt-3 sm:px-6" aria-label="排单草稿看板">
      <section className="flex h-full w-72 shrink-0 flex-col rounded-xl border border-slate-200 bg-white" aria-label="待排订单">
        <div className="border-b border-slate-100 p-4"><h2 className="text-sm font-semibold">待排订单 <span className="ml-1 text-slate-400">{pending.length}</span></h2>
          <p className="mt-1 text-xs text-slate-400">{plan ? "未安排的选中订单保留在这里" : "勾选本次需要安排的订单"}</p></div>
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
          {pending.map(order => { const chosen = plan ? plan.input_order_ids.includes(order.id) : selected.includes(order.id);
            return <div key={order.id} data-selected={chosen} className={`rounded-xl p-1 transition-colors ${chosen ? "bg-orange-50 ring-2 ring-[#C8331F]/40" : "bg-slate-50"}`}>
              {!plan && <label className="flex cursor-pointer items-center gap-2 px-2 py-2 text-xs text-slate-600"><input type="checkbox" checked={chosen} disabled={disabled} onChange={() => toggle(order.id)} aria-label={`选择订单 ${order.order_no}`} className="h-4 w-4 accent-[#C8331F]" />{chosen ? "已选择" : "选择此订单"}</label>}
              <OrderCard order={order} dragDisabled />
              {plan && chosen && <div className="px-2 pb-2"><p className="mt-2 text-xs leading-5 text-amber-700">{plan.stale ? "请重新生成草稿，查看最新安排结果。" : plan.unassigned.find(row => row.order_id === order.id)?.reason ?? "待安排"}</p>{destination(order.id)}</div>}
              {plan && !chosen && <p className="p-2 text-xs text-slate-400">未参与本次排单</p>}
            </div>;
          })}
          {!pending.length && <p className="py-12 text-center text-sm text-slate-400">{plan ? "本次订单已全部安排到右侧" : "当前没有待排单的订单"}</p>}
        </div>
      </section>
      {board.machines.map(machine => <MachineColumn key={machine.id} machine={machine} pendingOrders={[]} readOnly
        onTaskStatusChange={() => {}} onTaskDelete={async () => {}} onAddOrderToTask={() => {}}
        draftContent={<div className="mt-3 space-y-3 border-t border-dashed border-slate-300 pt-3">
          <p className="text-xs font-medium text-slate-500">{plan ? "本次草稿 · 确认后下发" : "本次排单将显示在这里"}</p>
          {plan?.tasks.map((task, index) => task.machine_id === machine.id && <DraftTask key={task.draft_task_id ?? index} task={task} index={index} disabled={disabled}>
            <div className="flex items-center gap-1"><span className="flex-1 text-xs font-semibold text-[#C8331F]">草稿任务 · {task.order_ids.length} 笔</span>
              <button aria-label={`上移草稿任务 ${index + 1}`} disabled={disabled || !plan.tasks.slice(0,index).some(t => t.machine_id === machine.id)} onClick={() => reorder(index,-1)} className="rounded p-1 disabled:opacity-25"><ArrowUp size={15}/></button>
              <button aria-label={`下移草稿任务 ${index + 1}`} disabled={disabled || !plan.tasks.slice(index+1).some(t => t.machine_id === machine.id)} onClick={() => reorder(index,1)} className="rounded p-1 disabled:opacity-25"><ArrowDown size={15}/></button></div>
            <select aria-label={`草稿任务 ${index + 1} 的机器`} value={task.machine_id} disabled={disabled} onChange={e => move(index,e.target.value)} className="my-2 w-full rounded-lg border border-orange-200 bg-white px-2 py-2 text-xs">
              {board.machines.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}</select>
            <div className="space-y-2">{task.order_ids.map(id => { const order = board.pending_orders.find(o => o.id === id); return <div key={id}>
              {order ? <OrderCard order={order} dragDisabled /> : <p className="text-xs text-red-700">订单状态已变化，请重新生成草稿。</p>}{destination(id,index)}</div>; })}</div>
            <details className="mt-2 text-xs leading-5 text-slate-500"><summary className="cursor-pointer">安排依据</summary><p className="pt-1">{task.reason}</p></details>
          </DraftTask>)}
          {!plan?.tasks.some(task => task.machine_id === machine.id) && <p className="rounded-lg border border-dashed border-slate-200 py-6 text-center text-xs text-slate-400">暂无新增任务</p>}
        </div>} />)}
    </div>
  </DndContext>;
}
function DraftTask({ task, index, disabled, children }: { task: PlanTask; index: number; disabled: boolean; children: React.ReactNode }) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({ id: `draft-${task.draft_task_id ?? index}`, data: { draftIndex: index }, disabled });
  return <article ref={setNodeRef} aria-label={`草稿任务 ${index+1}`} style={{ transform: CSS.Translate.toString(transform), opacity: isDragging ? .5 : 1 }}
    className="rounded-xl border border-orange-200 bg-orange-50/70 p-3 shadow-sm">
    <button {...attributes} {...listeners} disabled={disabled} aria-label={`拖动草稿任务 ${index+1}`} className="mb-1 flex w-full cursor-grab items-center justify-center text-orange-300"><GripVertical size={16}/></button>
    {children}
  </article>;
}
