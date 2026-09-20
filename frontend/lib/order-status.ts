export type OrderStatus = "PENDING" | "PRODUCING" | "DONE";
export type OrderDisplayStatus = OrderStatus | "WAITING";

// Order.PRODUCING means assigned; the linked task tells us whether work has started.
export function orderDisplayStatus(order: {
  status: OrderStatus;
  task?: { status: "WAITING" | "PRODUCING" | "DONE" } | null;
}): OrderDisplayStatus {
  return order.task?.status ?? order.status;
}

export const ORDER_STATUS_LABEL: Record<OrderDisplayStatus, string> = {
  PENDING: "待排单",
  WAITING: "待生产",
  PRODUCING: "生产中",
  DONE: "已完成",
};

export const ORDER_STATUS_STYLE: Record<OrderDisplayStatus, string> = {
  PENDING: "bg-amber-50 text-amber-700 border border-amber-200",
  WAITING: "bg-slate-100 text-slate-600 border border-slate-200",
  PRODUCING: "bg-blue-50 text-blue-700 border border-blue-200",
  DONE: "bg-green-50 text-green-700 border border-green-200",
};
