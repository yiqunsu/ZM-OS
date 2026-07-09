"use client";

import { useDroppable } from "@dnd-kit/core";
import { useDndContext } from "@dnd-kit/core";
import { SortableContext, verticalListSortingStrategy } from "@dnd-kit/sortable";
import TaskCard from "./TaskCard";
import type { KanbanMachine, KanbanOrder, KanbanTask, TaskStatus } from "./types";

interface Props {
  machine:        KanbanMachine;
  pendingOrders:  KanbanOrder[];
  onTaskStatusChange: (taskId: string, status: TaskStatus) => void;
  onTaskDelete:       (taskId: string) => void;
  onAddOrderToTask:   (taskId: string, orderId: string) => void;
}

export default function MachineColumn({
  machine, pendingOrders, onTaskStatusChange, onTaskDelete, onAddOrderToTask,
}: Props) {
  const droppableId = `col-${machine.id}`;

  const { setNodeRef, isOver } = useDroppable({
    id:   droppableId,
    data: { type: "machine-column", machineId: machine.id },
  });

  const { active, over } = useDndContext();
  const activeType = active?.data.current?.type as string | undefined;
  const isOrderType = activeType === "order" || activeType === "task-order";
  const isTaskType  = activeType === "task";

  /* Column droppable is "over" when the dragged center is closest to it (vs any task card) */
  const isColOver = over?.id === droppableId;

  const categoryNames = machine.categories.map((c) => c.name).join("、");
  const taskIds = machine.tasks.map((t) => t.id);

  const inProgress  = machine.tasks.filter((t) => t.status === "PRODUCING").length;
  const totalOrders = machine.tasks.reduce((sum, t) => sum + t.orders.length, 0);

  return (
    <div className="w-72 shrink-0 flex flex-col h-full">
      {/* Column header */}
      <div className={`px-4 py-3 rounded-t-xl border border-b-0 bg-white transition-colors ${
        isColOver && isOrderType ? "border-blue-300" : "border-slate-200"
      }`}>
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-slate-800 truncate">{machine.name}</h3>
          <div className="flex items-center gap-1.5 shrink-0">
            {inProgress > 0 && (
              <span className="text-xs px-1.5 py-0.5 rounded-full bg-blue-100 text-blue-700 font-semibold">
                生产中
              </span>
            )}
            {totalOrders > 0 && (
              <span className="text-xs px-1.5 py-0.5 rounded-full bg-slate-100 text-slate-600 font-semibold">
                {totalOrders}单
              </span>
            )}
          </div>
        </div>
        <p className="text-xs text-slate-400 mt-0.5 truncate">
          {machine.min_width}–{machine.max_width} mm
          {categoryNames && <span className="ml-1.5">· {categoryNames}</span>}
        </p>
      </div>

      {/* Column body — droppable */}
      <div
        ref={setNodeRef}
        className={`flex-1 overflow-y-auto rounded-b-xl border p-3 transition-colors ${
          isColOver && isOrderType
            ? "bg-blue-50/60 border-blue-300"
            : isColOver && isTaskType
            ? "bg-amber-50/60 border-amber-300"
            : isOver
            ? "bg-blue-50/40 border-blue-200"
            : "bg-slate-50/60 border-slate-200"
        }`}
      >
        <SortableContext items={taskIds} strategy={verticalListSortingStrategy}>
          <div className="space-y-3">
            {machine.tasks.map((task: KanbanTask) => (
              <TaskCard
                key={task.id}
                task={task}
                pendingOrders={pendingOrders}
                onStatusChange={(status) => onTaskStatusChange(task.id, status)}
                onDelete={() => onTaskDelete(task.id)}
                onAddOrder={(orderId) => onAddOrderToTask(task.id, orderId)}
              />
            ))}
          </div>
        </SortableContext>

        {/* Empty state / new-task drop zone */}
        {machine.tasks.length === 0 ? (
          <div className={`flex flex-col items-center justify-center h-full py-12 text-center rounded-lg border-2 border-dashed transition-colors ${
            isColOver && isOrderType ? "border-blue-400 bg-blue-50" :
            isColOver && isTaskType  ? "border-amber-400 bg-amber-50" :
            "border-slate-200"
          }`}>
            <svg className={`w-6 h-6 mb-2 transition-colors ${
              isColOver ? "text-blue-400" : "text-slate-300"
            }`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 16.5m0 0L7.5 12m4.5 4.5V3" />
            </svg>
            <p className={`text-xs transition-colors ${
              isColOver && isOrderType ? "text-blue-500 font-medium" :
              isColOver && isTaskType  ? "text-amber-500 font-medium" :
              "text-slate-400"
            }`}>
              {isColOver && isOrderType ? "松开创建新任务" :
               isColOver && isTaskType  ? "松开移入此机器" :
               "拖入订单排单"}
            </p>
          </div>
        ) : (
          /* When tasks exist, show a faint "new task" indicator at the bottom when an order is over the column */
          isColOver && isOrderType && (
            <div className="mt-3 py-3 rounded-lg border-2 border-dashed border-blue-300 bg-blue-50 text-center">
              <p className="text-xs text-blue-500 font-medium">松开创建新任务</p>
            </div>
          )
        )}
      </div>
    </div>
  );
}
