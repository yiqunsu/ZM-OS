"use client";

import { useEffect, useState, useCallback } from "react";
import {
  DndContext, DragOverlay, PointerSensor, KeyboardSensor,
  useSensor, useSensors, closestCenter,
  type DragStartEvent, type DragEndEvent,
} from "@dnd-kit/core";
import {
  sortableKeyboardCoordinates, arrayMove,
} from "@dnd-kit/sortable";
import MachineColumn from "./MachineColumn";
import PendingColumn from "./PendingColumn";
import OrderCard     from "./OrderCard";
import TaskCard      from "./TaskCard";
import { api } from "@/lib/api";
import type { KanbanMachine, KanbanOrder, KanbanTask, TaskStatus } from "./types";

type ActiveItem =
  | { kind: "order";      order: KanbanOrder }
  | { kind: "task";       task:  KanbanTask  }
  | { kind: "task-order"; order: KanbanOrder };

export default function KanbanBoard() {
  const [machines,      setMachines]      = useState<KanbanMachine[]>([]);
  const [pendingOrders, setPendingOrders] = useState<KanbanOrder[]>([]);
  const [loading,       setLoading]       = useState(true);
  const [activeItem,    setActiveItem]    = useState<ActiveItem | null>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const load = useCallback(async () => {
    setLoading(true);
    const data = await api.get<{ machines: KanbanMachine[]; pending_orders: KanbanOrder[] }>("/kanban");
    setMachines(data.machines);
    setPendingOrders(data.pending_orders);
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  function findTaskById(taskId: string): KanbanTask | undefined {
    for (const m of machines) {
      const t = m.tasks.find((t) => t.id === taskId);
      if (t) return t;
    }
  }

  function findMachineByTaskId(taskId: string): KanbanMachine | undefined {
    return machines.find((m) => m.tasks.some((t) => t.id === taskId));
  }

  /* ── Create task (pending order → machine column) ── */
  async function createTask(machineId: string, orderId: string) {
    const order = pendingOrders.find((o) => o.id === orderId);
    if (!order) return;
    setPendingOrders((prev) => prev.filter((o) => o.id !== orderId));
    try {
      const task = await api.post<KanbanTask>("/production-tasks", { machine_id: machineId, order_ids: [orderId] });
      setMachines((prev) =>
        prev.map((m) =>
          m.id === machineId
            ? { ...m, tasks: [...m.tasks, task].sort((a, b) => a.position - b.position) }
            : m
        )
      );
    } catch {
      setPendingOrders((prev) => [...prev, order]);
    }
  }

  /* ── Add pending order to existing task (merge) ── */
  async function addOrderToTask(taskId: string, orderId: string) {
    const order = pendingOrders.find((o) => o.id === orderId);
    const task  = findTaskById(taskId);
    if (!order || !task) return;
    setPendingOrders((prev) => prev.filter((o) => o.id !== orderId));
    setMachines((prev) =>
      prev.map((m) => ({
        ...m,
        tasks: m.tasks.map((t) =>
          t.id === taskId ? { ...t, orders: [...t.orders, order] } : t
        ),
      }))
    );
    const newOrderIds = [...task.orders.map((o) => o.id), orderId];
    try {
      await api.put(`/production-tasks/${taskId}`, { order_ids: newOrderIds });
    } catch {
      load();
    }
  }

  /* ── Remove one order from a task (send back to pending) ── */
  async function removeOrderFromTask(orderId: string, fromTaskId: string) {
    const task = findTaskById(fromTaskId);
    if (!task) return;
    const order = task.orders.find((o) => o.id === orderId);
    if (!order) return;

    if (task.orders.length === 1) {
      await deleteTask(fromTaskId);
    } else {
      setMachines((prev) =>
        prev.map((m) => ({
          ...m,
          tasks: m.tasks.map((t) =>
            t.id === fromTaskId ? { ...t, orders: t.orders.filter((o) => o.id !== orderId) } : t
          ),
        }))
      );
      setPendingOrders((prev) =>
        [...prev, { ...order, status: "PENDING" }]
          .sort((a, b) => a.order_no.localeCompare(b.order_no))
      );
      const newOrderIds = task.orders.filter((o) => o.id !== orderId).map((o) => o.id);
      try {
        await api.put(`/production-tasks/${fromTaskId}`, { order_ids: newOrderIds });
      } catch {
        load();
      }
    }
  }

  /* ── Move an order from a task to a new task on a machine ── */
  async function moveOrderToNewTask(orderId: string, fromTaskId: string, machineId: string) {
    const fromTask = findTaskById(fromTaskId);
    const order    = fromTask?.orders.find((o) => o.id === orderId);
    if (!fromTask || !order) return;

    // Optimistic: strip from old task
    if (fromTask.orders.length === 1) {
      setMachines((prev) =>
        prev.map((m) => ({ ...m, tasks: m.tasks.filter((t) => t.id !== fromTaskId) }))
      );
    } else {
      setMachines((prev) =>
        prev.map((m) => ({
          ...m,
          tasks: m.tasks.map((t) =>
            t.id === fromTaskId ? { ...t, orders: t.orders.filter((o) => o.id !== orderId) } : t
          ),
        }))
      );
    }

    // Remove from old task
    if (fromTask.orders.length === 1) {
      await api.delete(`/production-tasks/${fromTaskId}`);
    } else {
      await api.put(`/production-tasks/${fromTaskId}`, {
        order_ids: fromTask.orders.filter((o) => o.id !== orderId).map((o) => o.id),
      });
    }

    // Create new task on target machine
    try {
      const newTask = await api.post<KanbanTask>("/production-tasks", { machine_id: machineId, order_ids: [orderId] });
      setMachines((prev) =>
        prev.map((m) =>
          m.id === machineId
            ? { ...m, tasks: [...m.tasks, newTask].sort((a, b) => a.position - b.position) }
            : m
        )
      );
    } catch {
      load();
    }
  }

  /* ── Move an order from one task into another task (merge across tasks) ── */
  async function moveOrderBetweenTasks(orderId: string, fromTaskId: string, toTaskId: string) {
    const fromTask = findTaskById(fromTaskId);
    const toTask   = findTaskById(toTaskId);
    const order    = fromTask?.orders.find((o) => o.id === orderId);
    if (!fromTask || !toTask || !order) return;

    const isLastOrder = fromTask.orders.length === 1;

    setMachines((prev) =>
      prev.map((m) => ({
        ...m,
        tasks: m.tasks
          .map((t) => {
            if (t.id === fromTaskId) return { ...t, orders: t.orders.filter((o) => o.id !== orderId) };
            if (t.id === toTaskId)   return { ...t, orders: [...t.orders, order] };
            return t;
          })
          .filter((t) => !(t.id === fromTaskId && isLastOrder)),
      }))
    );

    const toOrderIds = [...toTask.orders.map((o) => o.id), orderId];
    await Promise.all([
      api.put(`/production-tasks/${toTaskId}`, { order_ids: toOrderIds }),
      isLastOrder
        ? api.delete(`/production-tasks/${fromTaskId}`)
        : api.put(`/production-tasks/${fromTaskId}`, {
            order_ids: fromTask.orders.filter((o) => o.id !== orderId).map((o) => o.id),
          }),
    ]);
  }

  /* ── Update task status (DONE removes task from board) ── */
  async function updateTaskStatus(taskId: string, status: TaskStatus) {
    if (status === "DONE") {
      setMachines((prev) =>
        prev.map((m) => ({ ...m, tasks: m.tasks.filter((t) => t.id !== taskId) }))
      );
    } else {
      setMachines((prev) =>
        prev.map((m) => ({
          ...m,
          tasks: m.tasks.map((t) => t.id === taskId ? { ...t, status } : t),
        }))
      );
    }
    await api.put(`/production-tasks/${taskId}`, { status });
  }

  /* ── Delete task (unlinks all orders → back to pending) ── */
  async function deleteTask(taskId: string) {
    const task = findTaskById(taskId);
    if (!task) return;
    setMachines((prev) =>
      prev.map((m) => ({ ...m, tasks: m.tasks.filter((t) => t.id !== taskId) }))
    );
    setPendingOrders((prev) =>
      [...prev, ...task.orders.map((o) => ({ ...o, status: "PENDING" }))]
        .sort((a, b) => a.order_no.localeCompare(b.order_no))
    );
    await api.delete(`/production-tasks/${taskId}`);
  }

  /* ── Reorder tasks within the same machine column ── */
  async function reorderTasks(machineId: string, activeTaskId: string, overTaskId: string) {
    const machine = machines.find((m) => m.id === machineId);
    if (!machine) return;
    const oldIndex = machine.tasks.findIndex((t) => t.id === activeTaskId);
    const newIndex = machine.tasks.findIndex((t) => t.id === overTaskId);
    if (oldIndex === -1 || newIndex === -1 || oldIndex === newIndex) return;

    const reordered = arrayMove(machine.tasks, oldIndex, newIndex);
    setMachines((prev) =>
      prev.map((m) => m.id === machineId ? { ...m, tasks: reordered } : m)
    );
    await Promise.all(
      reordered.map((task, idx) => api.put(`/production-tasks/${task.id}`, { position: idx }))
    );
  }

  /* ── Move a task to a different machine column ── */
  async function moveTaskToMachine(taskId: string, fromMachineId: string, toMachineId: string, position?: number) {
    const fromMachine = machines.find((m) => m.id === fromMachineId);
    const toMachine   = machines.find((m) => m.id === toMachineId);
    if (!fromMachine || !toMachine) return;
    const task = fromMachine.tasks.find((t) => t.id === taskId);
    if (!task) return;

    const newPosition = position ?? (Math.max(0, ...toMachine.tasks.map((t) => t.position)) + 1);

    setMachines((prev) =>
      prev.map((m) => {
        if (m.id === fromMachineId) return { ...m, tasks: m.tasks.filter((t) => t.id !== taskId) };
        if (m.id === toMachineId)   return { ...m, tasks: [...m.tasks, { ...task, machine_id: toMachineId, position: newPosition }].sort((a, b) => a.position - b.position) };
        return m;
      })
    );

    await api.put(`/production-tasks/${taskId}`, { machine_id: toMachineId, position: newPosition });
  }

  /* ── DnD handlers ── */
  function onDragStart({ active }: DragStartEvent) {
    const type = active.data.current?.type;
    if (type === "order") {
      const order = pendingOrders.find((o) => o.id === active.id);
      if (order) setActiveItem({ kind: "order", order });
    } else if (type === "task") {
      const task = findTaskById(active.id as string);
      if (task) setActiveItem({ kind: "task", task });
    } else if (type === "task-order") {
      const fromTaskId = active.data.current?.fromTaskId as string;
      const task  = findTaskById(fromTaskId);
      const order = task?.orders.find((o) => o.id === active.id);
      if (order) setActiveItem({ kind: "task-order", order });
    }
  }

  function onDragEnd({ active, over }: DragEndEvent) {
    setActiveItem(null);
    if (!over) return;

    const activeType = active.data.current?.type as string | undefined;
    const overId     = over.id as string;

    /* Pending order dragged */
    if (activeType === "order") {
      const orderId = active.id as string;
      if (overId === "pending-column") return;
      if (overId.startsWith("col-")) {
        createTask(overId.replace("col-", ""), orderId);
      } else {
        const task = findTaskById(overId);
        if (task) addOrderToTask(task.id, orderId);
      }
      return;
    }

    /* Order row within a task dragged (split/move) */
    if (activeType === "task-order") {
      const orderId    = active.id as string;
      const fromTaskId = active.data.current?.fromTaskId as string;
      if (overId === "pending-column") {
        removeOrderFromTask(orderId, fromTaskId);
      } else if (overId.startsWith("col-")) {
        moveOrderToNewTask(orderId, fromTaskId, overId.replace("col-", ""));
      } else {
        const toTask = findTaskById(overId);
        if (toTask && toTask.id !== fromTaskId) {
          moveOrderBetweenTasks(orderId, fromTaskId, toTask.id);
        }
      }
      return;
    }

    /* Task card dragged (reorder or cross-machine) */
    if (activeType === "task") {
      const activeTaskId  = active.id as string;
      const activeMachine = findMachineByTaskId(activeTaskId);
      if (!activeMachine) return;

      if (overId === "pending-column") return;

      if (overId.startsWith("col-")) {
        const targetMachineId = overId.replace("col-", "");
        if (activeMachine.id !== targetMachineId) {
          moveTaskToMachine(activeTaskId, activeMachine.id, targetMachineId);
        }
      } else {
        const overMachine = findMachineByTaskId(overId);
        if (!overMachine) return;
        if (activeMachine.id === overMachine.id) {
          reorderTasks(activeMachine.id, activeTaskId, overId);
        } else {
          const overTask = findTaskById(overId);
          moveTaskToMachine(activeTaskId, activeMachine.id, overMachine.id, overTask?.position);
        }
      }
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <p className="text-slate-400 text-sm">加载中…</p>
      </div>
    );
  }

  if (machines.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3">
        <p className="text-slate-400 text-sm">暂无可用机器</p>
        <a href="/settings" className="text-sm text-blue-600 hover:text-blue-700 font-medium">
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
      <div className="flex gap-4 p-4 h-full overflow-x-auto">
        {/* Pending column on the LEFT, hugging the sidebar */}
        <PendingColumn orders={pendingOrders} />

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
