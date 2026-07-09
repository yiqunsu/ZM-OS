"use client";

import { useDroppable } from "@dnd-kit/core";
import { useDndContext } from "@dnd-kit/core";
import OrderCard from "./OrderCard";
import type { KanbanOrder } from "./types";

interface Props {
  orders: KanbanOrder[];
}

export default function PendingColumn({ orders }: Props) {
  const { setNodeRef, isOver } = useDroppable({
    id:   "pending-column",
    data: { type: "pending-column" },
  });

  const { active } = useDndContext();
  const activeType = active?.data.current?.type as string | undefined;
  const isTaskOrderOver = isOver && activeType === "task-order";

  return (
    <div className="w-80 shrink-0 flex flex-col h-full border-r border-slate-200 bg-slate-50">
      {/* Header */}
      <div className="px-5 py-4 border-b border-slate-200 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-slate-800">待排单</h2>
          <span className="bg-blue-50 text-blue-600 px-2 py-0.5 rounded-full text-[10px] font-bold tabular-nums">
            {orders.length}
          </span>
        </div>
        {/* Filter icon placeholder */}
        <button className="p-1 rounded-md text-slate-400 hover:text-slate-600 hover:bg-slate-200 transition-colors" title="筛选">
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M3 4.5h14.25M3 9h9.75M3 13.5h5.25" />
          </svg>
        </button>
      </div>

      {/* Scroll body */}
      <div
        ref={setNodeRef}
        className={`flex-1 overflow-y-auto px-4 py-4 flex flex-col gap-3 transition-colors ${
          isTaskOrderOver ? "bg-orange-50/60" : ""
        }`}
      >
        {/* Helper text */}
        <p className="text-xs text-slate-400 select-none">
          {isTaskOrderOver ? "松开可拆分回待排单" : "拖拽到右侧机器列排单"}
        </p>

        {orders.length === 0 ? (
          <div className="flex flex-col items-center justify-center flex-1 py-16 text-center">
            <div className="w-10 h-10 rounded-full bg-slate-200 flex items-center justify-center mb-3">
              <svg className="w-5 h-5 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
              </svg>
            </div>
            <p className="text-slate-400 text-xs">暂无待排单订单</p>
          </div>
        ) : (
          <>
            {orders.map((order) => <OrderCard key={order.id} order={order} />)}
            {isTaskOrderOver && (
              <div className="py-3 rounded-xl border-2 border-dashed border-orange-300 bg-orange-50 text-center">
                <p className="text-xs text-orange-500 font-medium">松开拆分回待排单</p>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
