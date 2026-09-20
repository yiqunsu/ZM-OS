"use client";

import { Check, Loader2 } from "lucide-react";
import type { Event, Run } from "./types";

const stages: Record<string, string> = {
  ADMITTANCE: "确认任务范围",
  EXTRACTION: "识别订单截图",
  RECOGNITION: "识别订单截图",
  MAIN_AGENT: "核对任务信息",
  EXTRACTING: "识别订单截图",
  DRAFTING: "核对订单草稿",
  READING_BOARD: "分析生产安排",
  EXPLAINING: "整理回复",
  COMPOSE: "整理回复",
  COMPOSE_RESPONSE: "整理回复",
};
const tools: Record<string, string> = {
  read_current_draft: "读取订单草稿",
  search_customers: "查找已有客户",
  search_products: "查找已有产品",
  search_formulas: "查找已有配方",
  patch_current_draft: "更新订单草稿",
  read_board: "读取生产队列",
  read_draft: "读取排单草案",
  generate_draft: "生成排单建议",
};
export default function RunProgress({
  run,
  events,
}: {
  run: Run;
  events: Event[];
}) {
  const rows = events
    .filter((e) => e.run_id === run.id)
    .flatMap((e) => {
      let label = "";
      if (e.kind === "run.progress")
        label = stages[e.payload.stage ?? ""] ?? "处理任务信息";
      if (e.kind === "recognition.completed") label = "截图识别完成";
      if (e.kind.startsWith("tool."))
        label = `${tools[e.payload.tool_name ?? ""] ?? "处理任务信息"}${e.kind === "tool.succeeded" ? " · 完成" : e.kind === "tool.failed" ? " · 未完成" : ""}`;
      return label
        ? [
            {
              seq: e.seq,
              label,
              completed:
                e.kind === "tool.succeeded" ||
                e.kind === "recognition.completed",
            },
          ]
        : [];
    })
    .slice(-6);
  return (
    <details className="rounded-xl border border-slate-200/80 bg-slate-50/70 px-4 py-3">
      <summary className="cursor-pointer text-xs text-slate-500">
        <span className="inline-flex items-center gap-2">
          <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" />
          {run.status === "QUEUED"
            ? "已接收，等待处理…"
            : (rows.at(-1)?.label ?? "正在处理…")}
        </span>
      </summary>
      {rows.length > 0 && (
        <ol className="mt-3 space-y-2 border-t border-slate-200/70 pt-3">
          {rows.map((row) => (
            <li
              key={row.seq}
              className="flex items-center gap-2 text-[11px] text-slate-500"
            >
              {!row.completed ? (
                <span className="h-3 w-3 rounded-full border border-slate-300" />
              ) : (
                <Check className="h-3 w-3 text-slate-400" />
              )}
              {row.label}
            </li>
          ))}
        </ol>
      )}
    </details>
  );
}
