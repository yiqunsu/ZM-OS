"use client";

import { useState } from "react";
import { Popover } from "@base-ui/react/popover";
import ConfirmDialog from "@/components/ConfirmDialog";
import { api } from "@/lib/api";
import type { KanbanTask, TaskStatus } from "@/components/kanban/types";

import { orderDisplayStatus, ORDER_STATUS_LABEL, type OrderStatus } from "@/lib/order-status";
type StatusOrder = {
  id: string;
  order_no: string;
  status: OrderStatus;
  task?: { id: string; status: TaskStatus; updated_at?: string } | null;
};

export default function OrderStatusButton({ order, orders, className, onUpdated }: {
  order: StatusOrder;
  orders: StatusOrder[];
  className: string;
  onUpdated: (task: KanbanTask) => void;
}) {
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState<TaskStatus | null>(null);
  const task = order.task;
  const related = orders.filter(item => item.task?.id === task?.id);
  const label = ORDER_STATUS_LABEL[orderDisplayStatus(order)];
  const withdrawing = target === "WAITING";
  const recovering = task?.status === "DONE";
  const choose = (status: TaskStatus) => { setOpen(false); setTarget(status); };

  if (order.status === "PENDING" || !task) return (
    <span className={`${className} whitespace-nowrap shrink-0`} title="请先通过排单看板安排生产，不能直接修改状态">{label}</span>
  );

  return <>
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger className={`${className} whitespace-nowrap shrink-0`} aria-label={`修改订单 ${order.order_no} 的状态`}
        onClick={event => event.stopPropagation()}>{label}</Popover.Trigger>
      <Popover.Portal>
        <Popover.Positioner side="bottom" align="start" sideOffset={6} collisionPadding={12} className="z-[80]">
          <Popover.Popup aria-label="选择订单状态" onClick={event => event.stopPropagation()}
            className="w-60 rounded-xl border border-slate-200 bg-white p-2 text-sm text-slate-700 shadow-lg outline-none">
            <p className="px-3 py-2 text-xs text-slate-400">选择状态，确认后生效</p>
            <button disabled className="w-full rounded-lg px-3 py-2 text-left text-slate-300">待排单 · 需在看板撤回</button>
            <button disabled={task.status !== "PRODUCING"} onClick={() => choose("WAITING")}
              className="w-full rounded-lg px-3 py-2 text-left hover:bg-slate-50 disabled:text-slate-300">
              {task.status === "WAITING" ? "待生产 · 当前状态" : "撤回到待生产"}
            </button>
            <button disabled={task.status === "PRODUCING"} onClick={() => choose("PRODUCING")}
              className="w-full rounded-lg px-3 py-2 text-left hover:bg-slate-50 disabled:text-slate-300">
              {recovering ? "恢复生产中" : task.status === "WAITING" ? "开始生产" : "生产中 · 当前状态"}
            </button>
            <button disabled={task.status !== "PRODUCING"} onClick={() => choose("DONE")}
              className="w-full rounded-lg px-3 py-2 text-left hover:bg-slate-50 disabled:text-slate-300">已完成</button>
            {task.status === "WAITING" && <p className="px-3 py-2 text-xs leading-5 text-slate-400">订单已排单，需先开始生产再标记完成。</p>}
          </Popover.Popup>
        </Popover.Positioner>
      </Popover.Portal>
    </Popover.Root>
    <div onClick={event => event.stopPropagation()}>
      <ConfirmDialog open={target !== null} destructive={false}
        title={withdrawing ? "确认撤回到待生产？" : target === "DONE" ? "确认完成生产？" : recovering ? "确认恢复生产？" : "确认开始生产？"}
        description={`同一生产任务的 ${related.length} 笔订单将一起${withdrawing ? "撤回到待生产，保留原机器与排队位置，不会取消排单" : target === "DONE" ? "标记为已完成" : recovering ? "恢复为生产中，并返回原机器队列" : "开始生产"}。\n${related.map(item => item.order_no).join("、")}`}
        confirmLabel={withdrawing ? "确认撤回" : target === "DONE" ? "确认完成" : recovering ? "确认恢复" : "确认开始"}
        onCancel={() => setTarget(null)}
        onConfirm={async () => {
          const result = await api.put<KanbanTask>(`/production-tasks/${task.id}`, {
            status: target, expected_status: task.status, expected_updated_at: task.updated_at,
            expected_order_ids: related.map(item => item.id),
          });
          onUpdated(result);
          setTarget(null);
        }} />
    </div>
  </>;
}
