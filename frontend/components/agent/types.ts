import type { EventKind } from "./contracts.generated";

export type AgentType = "ORDER_INTAKE" | "SCHEDULING";
export interface Session {
  state?: { scheduling_order_ids?: string[] };
  created_at?: string;
  image_count?: number;
  order_count?: number;
  id: string;
  title: string;
  agent_type: AgentType;
  status: "ACTIVE" | "ARCHIVED" | "DELETING";
  state_revision: number;
  active_work_item_id: string | null;
  active_plan_id: string | null;
}
export interface Run {
  work_item_id?: string | null;
  id: string;
  status: "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED";
  error_code: string | null;
  error_message: string | null;
  output_message_id: string | null;
}
export interface Attachment {
  id: string;
  mime_type: string;
  available: boolean;
}
export interface NextAction {
  kind: "NEXT_ITEM";
  label: string;
  session_id: string;
  expected_state_revision: number;
  expected_next_item_id: string;
}
export interface Message {
  id: string;
  role: string;
  content: string | null;
  event_seq: number;
  run_id: string | null;
  attachments: Attachment[];
  presentation?: { schema_version: number; actions?: NextAction[] } | null;
}
export interface OrderDraft {
  schema_version?: 1;
  customer_id?: string | null;
  product_id?: string | null;
  spec_params: Record<string, string>;
  quantity?: string | null;
  unit?: "m" | "kg" | null;
  formula_mode: "none" | "existing";
  formula_id?: string | null;
  extra_notes: string;
}
export interface WorkItem {
  session_id?: string;
  source_archived?: boolean;
  screenshot_revision?: number;
  source_uploaded_at?: string;
  source_day?: string;
  source_day_position?: number;
  created_at?: string;
  customer_name?: string | null;
  product_name?: string | null;
  last_error_code?: string | null;
  id: string;
  source_attachment_id: string;
  queue_position: number;
  source_order_index?: number;
  order_id?: string | null;
  status: "PENDING" | "ACTIVE" | "DEFERRED" | "CREATED" | "CLOSED";
  revision: number;
  recognition_status: string;
  draft: OrderDraft;
  issues: { field: string; code: string; severity: string; message: string }[];
}
export interface Snapshot {
  work_item_counts?: Record<string, number>;
  session: Session;
  event_cursor: number;
  messages: Message[];
  active_run: Run | null;
  recent_run_results: Run[];
  work_items: WorkItem[];
  active_work_item: WorkItem | null;
  next_work_item: WorkItem | null;
}
export interface Event {
  seq: number;
  kind: EventKind;
  run_id: string | null;
  payload: { text?: string; stage?: string; tool_name?: string };
}
export interface PlanTask {
  draft_task_id?: string;
  machine_id: string;
  machine_name: string;
  order_ids: string[];
  order_nos: string[];
  total_width: number;
  reason: string;
}
export interface Plan {
  load_basis?: "TASK_COUNT" | "WEIGHT_KG";
  input_order_ids: string[];
  created_by_run_id?: string;
  id: string;
  status: string;
  revision: number;
  tasks: PlanTask[];
  unassigned: { order_id: string; order_no: string; reason: string }[];
  stale: boolean;
  stale_reasons: string[];
}
