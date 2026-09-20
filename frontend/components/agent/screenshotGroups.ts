import type { WorkItem } from "./types";

export interface ScreenshotGroup {
  id: string;
  archived?: boolean;
  revision?: number;
  busy?: boolean;
  runningId?: string | null;
  day: string;
  position: number;
  uploadedAt?: string;
  items: WorkItem[];
}

export function screenshotLabel(group?: ScreenshotGroup) {
  return group ? `${group.day} · 第 ${group.position} 张截图` : "订单截图";
}

export function screenshotGroups(items: WorkItem[]): ScreenshotGroup[] {
  const grouped = new Map<string, WorkItem[]>();
  for (const item of items) {
    if (item.status === "CLOSED") continue;
    grouped.set(item.source_attachment_id, [...(grouped.get(item.source_attachment_id) ?? []), item]);
  }
  const groups = [...grouped].map(([id, rows]) => {
    rows.sort((a, b) => (a.source_order_index ?? 1) - (b.source_order_index ?? 1));
    const source = rows.find(i => i.source_uploaded_at) ?? rows[0];
    const uploadedAt = source.source_uploaded_at ?? source.created_at;
    return {
      id, items: rows, uploadedAt,
      day: source.source_day ?? (uploadedAt ? new Date(uploadedAt).toLocaleDateString("sv-SE", {timeZone:"Asia/Shanghai"}) : "上传日期未知"),
      position: source.source_day_position ?? 0,
    };
  }).sort((a, b) => b.day.localeCompare(a.day) ||
    (a.position && b.position ? a.position - b.position : 0) ||
    (a.uploadedAt ?? "").localeCompare(b.uploadedAt ?? "") ||
    a.items[0].queue_position - b.items[0].queue_position || a.id.localeCompare(b.id));
  // Legacy/mocked responses may lack metadata; never expose the durable queue position as a title.
  const dailyCounts = new Map<string, number>();
  return groups.map(group => {
    const next = (dailyCounts.get(group.day) ?? 0) + 1;
    dailyCounts.set(group.day, next);
    return {...group, position: group.position || next};
  });
}
