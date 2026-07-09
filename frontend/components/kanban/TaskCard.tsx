"use client";

import { useState } from "react";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useDndContext, useDraggable } from "@dnd-kit/core";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { KanbanOrder, KanbanTask, TaskStatus } from "./types";
import { TASK_STATUS_LABEL, TASK_STATUS_STYLE, TASK_STATUS_CYCLE } from "./types";

/* ── Full order detail type (fetched on demand) ── */
interface FullOrder {
  id: string; order_no: string; status: string;
  quantity: number; unit: string; spec_params: Record<string, string>;
  extra_notes: string | null; formula_snapshot: { name?: string; materials?: string } | null; created_at: string;
  customer: { company: string; contact: string };
  product:  { name: string; category: { name: string } };
  formula:  { id: string; name: string; materials: string } | null;
}

const STATUS_LABEL: Record<string, string> = { PENDING: "待排单", PRODUCING: "生产中", DONE: "已完成" };
const STATUS_STYLE: Record<string, string> = {
  PENDING:   "bg-amber-50 text-amber-600 border-amber-200",
  PRODUCING: "bg-blue-50 text-blue-600 border-blue-200",
  DONE:      "bg-green-50 text-green-600 border-green-200",
};

function getMaterials(order: FullOrder): string | null {
  if (order.formula_snapshot?.materials?.trim()) return order.formula_snapshot.materials.trim();
  if (order.formula?.materials?.trim()) return order.formula.materials.trim();
  return null;
}

function fmtDate(iso: string) {
  return new Date(iso).toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-2 text-sm">
      <span className="text-slate-400 shrink-0 w-16">{label}</span>
      <span className="text-slate-700">{value}</span>
    </div>
  );
}

/* ── Draggable row for a single order inside a task ── */
function OrderRow({ order, fromTaskId }: { order: KanbanOrder; fromTaskId: string }) {
  const [detailOpen,    setDetailOpen]    = useState(false);
  const [fullOrder,     setFullOrder]     = useState<FullOrder | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id:   order.id,
    data: { type: "task-order", orderId: order.id, fromTaskId },
  });

  async function openDetail(e: React.MouseEvent) {
    e.stopPropagation();
    setDetailOpen(true);
    if (!fullOrder) {
      setDetailLoading(true);
      setFullOrder(await api.get<FullOrder>(`/orders/${order.id}`));
      setDetailLoading(false);
    }
  }

  const specs = Object.entries(order.spec_params ?? {});

  return (
    <>
      <div
        ref={setNodeRef}
        className={`px-3 py-2.5 flex gap-2 items-start transition-opacity ${isDragging ? "opacity-40" : ""}`}
      >
        {/* Per-order drag handle */}
        <div
          {...attributes}
          {...listeners}
          className="mt-1 p-0.5 shrink-0 cursor-grab text-slate-300 hover:text-slate-500 transition-colors"
          title="拖出可拆分"
        >
          <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 16 16">
            <circle cx="5"  cy="3.5" r="1.3" />
            <circle cx="11" cy="3.5" r="1.3" />
            <circle cx="5"  cy="8"   r="1.3" />
            <circle cx="11" cy="8"   r="1.3" />
            <circle cx="5"  cy="12.5" r="1.3" />
            <circle cx="11" cy="12.5" r="1.3" />
          </svg>
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2 mb-0.5">
            <span className="font-mono text-xs text-slate-500">
              <span className="text-slate-400">ORD-</span>
              <span className="font-semibold text-slate-700">{order.order_no.replace("ORD-", "")}</span>
            </span>
            <span className="text-xs text-slate-500 font-medium">
              {order.quantity}<span className="text-slate-400 ml-0.5">{order.unit}</span>
            </span>
          </div>
          <p className="text-sm font-medium text-slate-800 truncate">{order.customer.company}</p>
          <p className="text-xs text-slate-400 truncate">{order.product.category.name} · {order.product.name}</p>
          {specs.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-1">
              {specs.map(([k, v]) => (
                <span key={k} className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 text-xs">
                  {k}:{v}
                </span>
              ))}
            </div>
          )}
        </div>
        {/* View detail button */}
        <button
          onClick={openDetail}
          className="mt-0.5 p-1 shrink-0 rounded text-slate-300 hover:text-blue-500 hover:bg-blue-50 transition-colors"
          title="查看订单详情"
        >
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M2.036 12.322a1.012 1.012 0 0 1 0-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.964-7.178Z" />
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
          </svg>
        </button>
      </div>

      {/* Order detail dialog */}
      <Dialog open={detailOpen} onOpenChange={(o) => !o && setDetailOpen(false)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-3">
              <span className="font-mono text-sm font-semibold text-slate-700">{order.order_no}</span>
              {fullOrder && (
                <span className={`text-[11px] px-2 py-0.5 rounded-full border font-semibold ${STATUS_STYLE[fullOrder.status]}`}>
                  {STATUS_LABEL[fullOrder.status]}
                </span>
              )}
            </DialogTitle>
          </DialogHeader>
          {detailLoading || !fullOrder ? (
            <div className="py-10 flex items-center justify-center">
              <p className="text-sm text-slate-400">加载中…</p>
            </div>
          ) : (
            <div className="space-y-5 pt-1">
              <section>
                <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">基本信息</h4>
                <div className="space-y-1.5">
                  <DetailRow label="客户" value={fullOrder.customer.company} />
                  <DetailRow label="联系人" value={fullOrder.customer.contact} />
                  <DetailRow label="产品" value={`${fullOrder.product.category.name} · ${fullOrder.product.name}`} />
                  <DetailRow label="数量" value={`${fullOrder.quantity} ${fullOrder.unit}`} />
                  <DetailRow label="创建日期" value={fmtDate(fullOrder.created_at)} />
                </div>
              </section>
              {Object.keys(fullOrder.spec_params ?? {}).length > 0 && (
                <section>
                  <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">规格参数</h4>
                  <div className="flex flex-wrap gap-1.5">
                    {Object.entries(fullOrder.spec_params).map(([k, v]) => (
                      <span key={k} className="px-2.5 py-1 rounded-lg bg-slate-100 text-slate-600 text-xs font-medium">{k}: {v}</span>
                    ))}
                  </div>
                </section>
              )}
              {(fullOrder.formula || fullOrder.formula_snapshot) && (() => {
                const materials = getMaterials(fullOrder);
                return (
                  <section>
                    <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">配方</h4>
                    {fullOrder.formula && <p className="text-sm text-slate-700 font-semibold mb-2">{fullOrder.formula.name}</p>}
                    {materials ? (
                      <pre className="text-xs text-slate-600 whitespace-pre-wrap leading-relaxed bg-slate-50 rounded-lg px-3 py-2.5 border border-slate-200 font-sans">{materials}</pre>
                    ) : (
                      <p className="text-xs text-slate-400 italic">暂无原材料明细</p>
                    )}
                  </section>
                );
              })()}
              {fullOrder.extra_notes && (
                <section>
                  <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">额外要求</h4>
                  <p className="text-sm text-slate-600 whitespace-pre-wrap leading-relaxed bg-slate-50 rounded-lg px-3 py-2">{fullOrder.extra_notes}</p>
                </section>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}

interface Props {
  task:          KanbanTask;
  pendingOrders: KanbanOrder[];
  onStatusChange: (status: TaskStatus) => void;
  onDelete:       () => void;
  onAddOrder:     (orderId: string) => void;
  overlay?:       boolean;
}

export default function TaskCard({
  task, pendingOrders, onStatusChange, onDelete, onAddOrder, overlay = false,
}: Props) {
  const [deleteOpen,   setDeleteOpen]   = useState(false);
  const [addOrderOpen, setAddOrderOpen] = useState(false);

  const {
    attributes, listeners, setNodeRef, transform, transition, isDragging,
  } = useSortable({
    id:   task.id,
    data: { type: "task", machineId: task.machine_id },
    disabled: overlay,
  });

  /* Detect when a pending-order or task-order is being dragged over this card */
  const { active, over } = useDndContext();
  const isOrderOverMe = !overlay &&
    over?.id === task.id &&
    (active?.data.current?.type === "order" ||
     (active?.data.current?.type === "task-order" && active?.data.current?.fromTaskId !== task.id));

  const style = {
    transform:  CSS.Transform.toString(transform),
    transition,
    opacity:    isDragging ? 0.4 : 1,
    zIndex:     isDragging ? 50 : undefined,
  };

  const nextStatus = TASK_STATUS_CYCLE[task.status];

  return (
    <>
      <div
        ref={setNodeRef}
        style={style}
        className={`bg-white rounded-lg border shadow-sm overflow-hidden relative ${
          overlay ? "shadow-xl rotate-1" : "hover:shadow-md transition-shadow"
        } ${isOrderOverMe ? "border-blue-400 ring-2 ring-blue-200" : "border-slate-200"}`}
      >
        {/* Merge-drop visual overlay */}
        {isOrderOverMe && (
          <div className="absolute inset-0 bg-blue-50/85 flex items-center justify-center z-10 rounded-lg pointer-events-none">
            <span className="text-sm font-semibold text-blue-600 bg-white px-3 py-1.5 rounded-full border border-blue-200 shadow-sm">
              合并到此任务
            </span>
          </div>
        )}

        {/* Card header */}
        <div className="flex items-center gap-2 px-3 py-2 border-b border-slate-100 bg-slate-50/70">
          {/* Task drag handle */}
          <div
            {...attributes}
            {...listeners}
            className={`p-1 rounded text-slate-300 hover:text-slate-500 transition-colors shrink-0 ${overlay ? "cursor-grabbing" : "cursor-grab"}`}
            title="拖拽整个任务"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 5h16.5M3.75 12h16.5M3.75 19h16.5" />
            </svg>
          </div>

          {/* Status badge — click to advance */}
          <button
            onClick={() => onStatusChange(nextStatus)}
            className={`px-2 py-0.5 rounded-full text-xs font-semibold transition-opacity hover:opacity-75 ${TASK_STATUS_STYLE[task.status]}`}
            title={`点击标记「${TASK_STATUS_LABEL[nextStatus]}」`}
          >
            {TASK_STATUS_LABEL[task.status]}
          </button>

          <span className="flex-1" />

          {/* Add order button */}
          <button
            onClick={() => setAddOrderOpen(true)}
            disabled={pendingOrders.length === 0}
            className="p-1 rounded text-slate-400 hover:text-blue-600 hover:bg-blue-50 disabled:opacity-30 transition-colors"
            title="添加订单（合并生产）"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
            </svg>
          </button>

          {/* Delete button */}
          <button
            onClick={() => setDeleteOpen(true)}
            className="p-1 rounded text-slate-400 hover:text-red-500 hover:bg-red-50 transition-colors"
            title="删除任务（订单退回待排单）"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Orders list — each row is independently draggable */}
        <div className="divide-y divide-slate-50">
          {task.orders.map((order) => (
            <OrderRow key={order.id} order={order} fromTaskId={task.id} />
          ))}
        </div>

        {/* Merge indicator */}
        {task.orders.length > 1 && (
          <div className="px-3 py-1.5 bg-blue-50 border-t border-blue-100">
            <span className="text-xs text-blue-600 font-medium">合并生产 · {task.orders.length} 张订单</span>
          </div>
        )}
      </div>

      {/* Delete confirm dialog */}
      <Dialog open={deleteOpen} onOpenChange={(o) => !o && setDeleteOpen(false)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader><DialogTitle className="text-slate-800">删除生产任务</DialogTitle></DialogHeader>
          <p className="text-sm text-slate-500 py-2">
            确认删除该任务？任务内 <span className="font-medium text-slate-700">{task.orders.length}</span> 张订单将退回「待排单」。
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteOpen(false)} className="border-slate-200 text-slate-600">取消</Button>
            <Button onClick={() => { setDeleteOpen(false); onDelete(); }} className="bg-red-500 hover:bg-red-600 text-white border-0">确认删除</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Add order dialog */}
      <Dialog open={addOrderOpen} onOpenChange={(o) => !o && setAddOrderOpen(false)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader><DialogTitle className="text-slate-800">添加订单（合并生产）</DialogTitle></DialogHeader>
          <div className="py-2 space-y-2 max-h-72 overflow-y-auto">
            {pendingOrders.length === 0 ? (
              <p className="text-sm text-slate-400 text-center py-4">暂无待排单订单</p>
            ) : (
              pendingOrders.map((order) => (
                <button
                  key={order.id}
                  onClick={() => { onAddOrder(order.id); setAddOrderOpen(false); }}
                  className="w-full text-left p-3 rounded-lg border border-slate-200 hover:border-blue-300 hover:bg-blue-50/50 transition-colors"
                >
                  <div className="flex items-center justify-between mb-0.5">
                    <span className="font-mono text-xs text-slate-500">{order.order_no}</span>
                    <span className="text-xs text-slate-500">{order.quantity}{order.unit}</span>
                  </div>
                  <p className="text-sm font-medium text-slate-800">{order.customer.company}</p>
                  <p className="text-xs text-slate-400">{order.product.category.name} · {order.product.name}</p>
                </button>
              ))
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAddOrderOpen(false)} className="border-slate-200 text-slate-600">取消</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
