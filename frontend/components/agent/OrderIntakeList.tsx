import { useState } from "react";
import { Archive, ArchiveRestore, Check, ChevronDown, FileImage, LoaderCircle } from "lucide-react";
import type { ScreenshotTab } from "./useScreenshotList";
import type { WorkItem } from "./types";
import type { ScreenshotGroup } from "./screenshotGroups";
import { attachmentUrl } from "./api";

export function itemTitle(item: WorkItem) {
  const date = item.created_at
    ? new Date(item.created_at).toLocaleDateString("sv-SE")
    : "";
  return `${item.customer_name || "客户"}-${item.product_name || "产品"}${date ? `-${date}` : ""}`;
}
export default function OrderIntakeList({
  screenshots,
  tab, onTab, onArchive,
  counts,
  selectedId,
  runningId,
  disabled,
  readOnly = false,
  onSelect,
  onRetry,
  more,
}: {
  screenshots: ScreenshotGroup[];
  tab: ScreenshotTab;
  onTab: (tab: ScreenshotTab) => void;
  onArchive: (group: ScreenshotGroup) => void;
  counts?: Record<string, number>;
  selectedId?: string;
  runningId?: string | null;
  disabled: boolean;
  readOnly?: boolean;
  onSelect: (item: WorkItem) => void;
  onRetry: (item: WorkItem) => void;
  more?: React.ReactNode;
}) {
  const items = screenshots.flatMap(group => group.items);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const pending = counts
    ? (counts.PENDING || 0) + (counts.ACTIVE || 0) + (counts.DEFERRED || 0)
    : items.filter((i) => !["CREATED", "CLOSED"].includes(i.status)).length;
  const created =
    counts?.CREATED ?? items.filter((i) => i.status === "CREATED").length;
  const filtered = items.filter((i) =>
    tab === "archived" ? i.status !== "CLOSED" : tab === "created"
      ? i.status === "CREATED"
      : !["CREATED", "CLOSED"].includes(i.status),
  );
  const days = new Map<string, ScreenshotGroup[]>();
  for (const screenshot of screenshots) {
    const shown = screenshot.items.filter(i => filtered.includes(i));
    if (shown.length) days.set(screenshot.day, [...(days.get(screenshot.day) ?? []), {...screenshot, items: shown}]);
  }
  return (
    <section className="intake-list" aria-label="订单列表">
      <header>
        <h2>订单列表</h2>
        <span>{tab === "archived" ? counts?.ARCHIVED ?? items.length : pending + created} 笔</span>
      </header>
      <div className="intake-tabs">
        {(
          [
            ["pending", "待处理", pending],
            ["created", "已下发", created],
            ["archived", "已归档", counts?.ARCHIVED ?? 0],
          ] as const
        ).map(([key, label, count]) => (
          <button
            key={key}
            aria-pressed={tab === key}
            onClick={() => onTab(key)}
          >
            {label} <span>{count}</span>
          </button>
        ))}
      </div>
      <div className="intake-list-scroll">
        {[...days].map(([day, screenshots]) => <section key={day} aria-label={`${day}上传的截图`} className="screenshot-day">
          <h3 className="flex items-center justify-between px-3 pb-2 pt-4 text-xs font-semibold text-slate-500"><span>{day}</span><span>{screenshots.length} 张截图</span></h3>
          {screenshots.map((screenshot) => {
            const {id, items: group, position, uploadedAt} = screenshot;
            const groupRunningId = screenshot.runningId ?? runningId;
            return (
          <div key={id} className="screenshot-group">
            <button
              className="screenshot-heading"
              aria-expanded={!collapsed.has(id)}
              onClick={() =>
                setCollapsed((old) => {
                  const next = new Set(old);
                  if (next.has(id)) next.delete(id);
                  else next.add(id);
                  return next;
                })
              }
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={attachmentUrl(id)}
                alt={`第 ${position} 张截图缩略图`}
              />
              <span>
                第 {position} 张截图
                <small>
                  {uploadedAt && `${new Date(uploadedAt).toLocaleTimeString("zh-CN", {timeZone:"Asia/Shanghai",hour:"2-digit",minute:"2-digit",hour12:false})} 上传 · `}
                  {group.some(i => i.recognition_status === "SUCCEEDED")
                    ? `${group.filter(i => i.recognition_status === "SUCCEEDED").length} 笔订单`
                    : group.some(i => i.id === groupRunningId) ? "正在识别" : group.some(i => i.recognition_status === "FAILED") ? "识别失败" : "等待识别"}
                </small>
              </span>
              <ChevronDown
                size={14}
                className={collapsed.has(id) ? "-rotate-90" : ""}
              />
            </button>
            <div className="screenshot-management">
              <button disabled={disabled || screenshot.busy} onClick={() => onArchive(screenshot)}
                aria-label={`${screenshot.archived ? "恢复" : "归档"} ${screenshot.day} 第 ${position} 张截图`}>
                {screenshot.archived ? <ArchiveRestore size={13} /> : <Archive size={13} />}
                {screenshot.archived ? "恢复截图" : "归档截图"}
              </button>
            </div>
            {!collapsed.has(id) &&
              group.map((i) =>
                i.recognition_status !== "SUCCEEDED" ? (
                  <div className="recognition-row" key={i.id}>
                    {groupRunningId === i.id ? (
                      <LoaderCircle size={15} className="animate-spin" />
                    ) : (
                      <FileImage size={15} />
                    )}
                    <span>
                      {groupRunningId === i.id
                        ? "正在识别…"
                        : i.recognition_status === "FAILED"
                          ? "识别失败"
                          : "等待识别"}
                    </span>
                    <button disabled={disabled || readOnly || screenshot.busy} onClick={() => onRetry(i)}>
                      {i.recognition_status === "FAILED" ? "重试" : "识别"}
                    </button>
                  </div>
                ) : (
                  <button
                    key={i.id}
                    className={`intake-item ${selectedId === i.id ? "selected" : ""}`}
                    disabled={disabled || screenshot.busy}
                    aria-current={selectedId === i.id ? "true" : undefined}
                    onClick={() => onSelect(i)}
                  >
                    <span className="intake-title">{itemTitle(i)}</span>
                    <span className="intake-item-meta">
                      <span
                        className={`status-badge ${i.status === "CREATED" ? "created" : ""}`}
                      >
                        {i.status === "CREATED" ? (
                          <>
                            <Check size={11} />
                            已下发
                          </>
                        ) : (
                          "待处理"
                        )}
                      </span>
                      <span>
                        {i.status === "DEFERRED" ? "已暂存 · " : ""}第{" "}
                        {i.source_order_index ?? 1} 笔
                      </span>
                    </span>
                  </button>
                ),
              )}
          </div>
          ); })}
        </section>)}
        {!filtered.length && (
          <p className="list-empty">
            {tab === "archived" ? "暂无归档截图" : tab === "created" ? "还没有已创建订单" : "暂无待处理订单"}
          </p>
        )}
        {more}
      </div>
    </section>
  );
}
