export interface ChatSessionSummary {
  id: string;
  title: string;
  created_at: string;
  message_count: number;
}

export interface ToolCall {
  id?: string;
  name?: string;
  args?: Record<string, unknown>;
  function?: { name: string; arguments: string };
  display?: Record<string, unknown>;
}

export type ChatAttachmentMime = "image/jpeg" | "image/png";

export interface ChatAttachment {
  id: string;
  mime_type: ChatAttachmentMime;
  byte_size: number;
}

export interface ChatMessage {
  id: string;
  session_id?: string | null;
  role: string;
  content: string | null;
  tool_calls: ToolCall[] | Record<string, unknown> | null;
  tool_call_id: string | null;
  tool_name: string | null;
  is_pending: boolean;
  created_at: string;
  attachments: ChatAttachment[];
  /**
   * Browser-only preview owned by an optimistic message until the backend sends
   * user_message_committed. It must never enter request bodies or history.
   */
  optimistic_image_preview_data_url?: string;
}

export interface UserMessageCommittedEvent {
  type: "user_message_committed";
  user_message_id: string;
  attachments: ChatAttachment[];
}

function isChatAttachment(value: unknown): value is ChatAttachment {
  if (!value || typeof value !== "object") return false;
  const attachment = value as Record<string, unknown>;
  return (
    typeof attachment.id === "string"
    && attachment.id.trim().length > 0
    && (attachment.mime_type === "image/jpeg" || attachment.mime_type === "image/png")
    && typeof attachment.byte_size === "number"
    && Number.isInteger(attachment.byte_size)
    && attachment.byte_size > 0
  );
}

export function isUserMessageCommittedEvent(value: unknown): value is UserMessageCommittedEvent {
  if (!value || typeof value !== "object") return false;
  const event = value as Record<string, unknown>;
  return (
    event.type === "user_message_committed"
    && typeof event.user_message_id === "string"
    && event.user_message_id.trim().length > 0
    && Array.isArray(event.attachments)
    && event.attachments.every(isChatAttachment)
  );
}

export interface ScheduleTask {
  machine_id: string;
  machine_name: string;
  order_ids: string[];
  order_nos: string[];
  total_width: number;
  reason: string;
}

export interface UnassignedOrder {
  order_id: string;
  order_no: string;
  reason: string;
}

export interface SchedulePlan {
  id: string;
  status: "DRAFT" | "APPLIED";
  tasks: ScheduleTask[];
  unassigned: UnassignedOrder[];
  created_at: string;
}
