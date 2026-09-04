"use client";

import { useCallback, useEffect, useState } from "react";
import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { arrayMove, sortableKeyboardCoordinates } from "@dnd-kit/sortable";
import MachineColumn from "./MachineColumn";
import OrderCard from "./OrderCard";
import PendingColumn from "./PendingColumn";
import TaskCard from "./TaskCard";
import { api } from "@/lib/api";
import type {
  KanbanMachine,
  KanbanOrder,
  KanbanSnapshot,
  KanbanTask,
  TaskStatus,
} from "./types";

type ActiveItem =
  | { kind: "order"; order: KanbanOrder }
  | { kind: "task"; task: KanbanTask }
  | { kind: "task-order"; order: KanbanOrder };

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "操作失败，请重试";
}

export default function KanbanBoard() {
  const [machines, setMachines] = useState<KanbanMachine[]>([]);
  const [pendingOrders, setPendingOrders] = useState<KanbanOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeItem, setActiveItem] = useState<ActiveItem | null>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const applySnapshot = useCallback((snapshot: KanbanSnapshot) => {
    setMachines(snapshot.machines);
    setPendingOrders(snapshot.pending_orders);
  }, []);

  const load = useCallback(async (showLoading = true) => {
    if (showLoading) setLoading(true);
    try {
      applySnapshot(await api.get<KanbanSnapshot>("/kanban"));
      setError(null);
    } catch (loadError) {
      setError(errorMessage(loadError));
    } finally {
      if (showLoading) setLoading(false);
    }
  }, [applySnapshot]);

  useEffect(() => {
    let cancelled = false;
    api.get<KanbanSnapshot>("/kanban")
      .then((snapshot) => {
        if (!cancelled) {
          applySnapshot(snapshot);
          setError(null);
        }
      })
      .catch((loadError: unknown) => {
        if (!cancelled) setError(errorMessage(loadError));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [applySnapshot]);

  function findTaskById(taskId: string): KanbanTask | undefined {
    for (const machine of machines) {
      const task = machine.tasks.find((item) => item.id === taskId);
      if (task) return task;
    }
  }

  function findMachineByTaskId(taskId: string): KanbanMachine | undefined {
    return machines.find((machine) => machine.tasks.some((task) => task.id === taskId));
  }

  async function runBoardMutation(path: string, body: unknown) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      applySnapshot(await api.post<KanbanSnapshot>(path, body));
    } catch (mutationError) {
      setError(errorMessage(mutationError));
      await load(false);
    } finally {
      setBusy(false);
    }
  }

  async function runMutation(action: () => Promise<unknown>) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await action();
      await load(false);
    } catch (mutationError) {
      setError(errorMessage(mutationError));
      await load(false);
    } finally {
      setBusy(false);
    }
  }

  function createTask(machineId: string, orderId: string) {
    return runBoardMutation("/production-tasks/actions/move-order", {
      order_id: orderId,
      target_machine_id: machineId,
    });
  }

  function addOrderToTask(taskId: string, orderId: string) {
    return runBoardMutation("/production-tasks/actions/move-order", {
      order_id: orderId,
      target_task_id: taskId,
    });
  }

  function removeOrderFromTask(orderId: string, sourceTaskId: string) {
    return runBoardMutation("/production-tasks/actions/move-order", {
      order_id: orderId,
      source_task_id: sourceTaskId,
    });
  }

  function moveOrderToNewTask(orderId: string, sourceTaskId: string, machineId: string) {
    return runBoardMutation("/production-tasks/actions/move-order", {
      order_id: orderId,
      source_task_id: sourceTaskId,
      target_machine_id: machineId,
    });
  }

  function moveOrderBetweenTasks(orderId: string, sourceTaskId: string, targetTaskId: string) {
    return runBoardMutation("/production-tasks/actions/move-order", {
      order_id: orderId,
      source_task_id: sourceTaskId,
      target_task_id: targetTaskId,
    });
  }

  function updateTaskStatus(taskId: string, status: TaskStatus) {
    return runMutation(() => api.put(`/production-tasks/${taskId}`, { status }));
  }

  function deleteTask(taskId: string) {
    return runMutation(() => api.delete(`/production-tasks/${taskId}`));
  }

  function reorderTasks(machineId: string, activeTaskId: string, overTaskId: string) {
    const machine = machines.find((item) => item.id === machineId);
    if (!machine) return;
    const oldIndex = machine.tasks.findIndex((task) => task.id === activeTaskId);
    const newIndex = machine.tasks.findIndex((task) => task.id === overTaskId);
    if (oldIndex === -1 || newIndex === -1 || oldIndex === newIndex) return;
    const orderedTaskIds = arrayMove(machine.tasks, oldIndex, newIndex).map((task) => task.id);
    return runBoardMutation("/production-tasks/actions/reorder", {
      machine_id: machineId,
      ordered_task_ids: orderedTaskIds,
    });
  }

  function moveTaskToMachine(taskId: string, targetMachineId: string, targetIndex: number) {
    return runBoardMutation("/production-tasks/actions/move-task", {
      task_id: taskId,
      target_machine_id: targetMachineId,
      target_index: targetIndex,
    });
  }

  function onDragStart({ active }: DragStartEvent) {
    if (busy) return;
    const type = active.data.current?.type;
    if (type === "order") {
      const order = pendingOrders.find((item) => item.id === active.id);
      if (order) setActiveItem({ kind: "order", order });
    } else if (type === "task") {
      const task = findTaskById(active.id as string);
      if (task) setActiveItem({ kind: "task", task });
    } else if (type === "task-order") {
      const sourceTaskId = active.data.current?.fromTaskId as string;
      const order = findTaskById(sourceTaskId)?.orders.find((item) => item.id === active.id);
      if (order) setActiveItem({ kind: "task-order", order });
    }
  }

  function onDragEnd({ active, over }: DragEndEvent) {
    setActiveItem(null);
    if (!over || busy) return;

    const activeType = active.data.current?.type as string | undefined;
    const overId = over.id as string;

    if (activeType === "order") {
      const orderId = active.id as string;
      if (overId === "pending-column") return;
      if (overId.startsWith("col-")) {
        void createTask(overId.replace("col-", ""), orderId);
      } else {
        const task = findTaskById(overId);
        if (task) void addOrderToTask(task.id, orderId);
      }
      return;
    }

    if (activeType === "task-order") {
      const orderId = active.id as string;
      const sourceTaskId = active.data.current?.fromTaskId as string;
      if (overId === "pending-column") {
        void removeOrderFromTask(orderId, sourceTaskId);
      } else if (overId.startsWith("col-")) {
        void moveOrderToNewTask(orderId, sourceTaskId, overId.replace("col-", ""));
      } else {
        const targetTask = findTaskById(overId);
        if (targetTask && targetTask.id !== sourceTaskId) {
          void moveOrderBetweenTasks(orderId, sourceTaskId, targetTask.id);
        }
      }
      return;
    }

    if (activeType !== "task" || overId === "pending-column") return;
    const activeTaskId = active.id as string;
    const activeMachine = findMachineByTaskId(activeTaskId);
    if (!activeMachine) return;

    if (overId.startsWith("col-")) {
      const targetMachineId = overId.replace("col-", "");
      if (activeMachine.id !== targetMachineId) {
        const target = machines.find((machine) => machine.id === targetMachineId);
        if (target) void moveTaskToMachine(activeTaskId, targetMachineId, target.tasks.length);
      }
      return;
    }

    const overMachine = findMachineByTaskId(overId);
    if (!overMachine) return;
    if (activeMachine.id === overMachine.id) {
      void reorderTasks(activeMachine.id, activeTaskId, overId);
    } else {
      const targetIndex = overMachine.tasks.findIndex((task) => task.id === overId);
      void moveTaskToMachine(activeTaskId, overMachine.id, Math.max(0, targetIndex));
    }
  }

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-slate-400">加载中…</p>
      </div>
    );
  }

  if (machines.length === 0 && !error) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3">
        <p className="text-sm text-slate-400">暂无可用机器</p>
        <a href="/settings" className="text-sm font-medium text-blue-600 hover:text-blue-700">
          前往「基础数据」添加机器 →
        </a>
      </div>
    );
  }

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
    >
      <div className="relative h-full">
        {(error || busy) && (
          <div className="absolute left-1/2 top-3 z-[60] -translate-x-1/2">
            {error ? (
              <div className="flex items-center gap-3 rounded-lg border border-red-200 bg-white px-4 py-2 text-sm text-red-600 shadow-lg">
                <span>{error}</span>
                <button className="font-medium text-red-700 hover:underline" onClick={() => void load(false)}>
                  重试
                </button>
              </div>
            ) : (
              <div className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm text-slate-600 shadow-lg">
                正在保存…
              </div>
            )}
          </div>
        )}

        <div className="flex h-full gap-4 overflow-x-auto p-4">
          <PendingColumn
            orders={pendingOrders}
            machines={machines}
            onCreateTask={(machineId, orderId) => void createTask(machineId, orderId)}
          />
          {machines.map((machine) => (
            <MachineColumn
              key={machine.id}
              machine={machine}
              pendingOrders={pendingOrders}
              onTaskStatusChange={updateTaskStatus}
              onTaskDelete={deleteTask}
              onAddOrderToTask={addOrderToTask}
            />
          ))}
        </div>
      </div>

      <DragOverlay>
        {(activeItem?.kind === "order" || activeItem?.kind === "task-order") && (
          <OrderCard order={activeItem.order} overlay />
        )}
        {activeItem?.kind === "task" && (
          <TaskCard
            task={activeItem.task}
            pendingOrders={[]}
            onStatusChange={() => {}}
            onDelete={() => {}}
            onAddOrder={() => {}}
            overlay
          />
        )}
      </DragOverlay>
    </DndContext>
  );
}
