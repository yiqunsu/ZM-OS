"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ClipboardList, Layers3, Plus } from "lucide-react";
import { agentApi } from "./api";
import type { Session } from "./types";

export default function AgentSessionNav() {
  const activeId = useSearchParams().get("session");
  const [items, setItems] = useState<Session[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [pageCount, setPageCount] = useState(1);
  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const result = await agentApi.get<{
        items: Session[];
        next_cursor: string | null;
      }>("/sessions?limit=50", signal);
      if (signal?.aborted) return;
      setItems(result.items);
      setCursor(result.next_cursor);
      setPageCount(1);
      setError("");
    } catch (e) {
      if (!signal?.aborted)
        setError(e instanceof Error ? e.message : "会话加载失败");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => void load(controller.signal), 0);
    const refresh = () => {
      if (document.visibilityState === "visible") void load(controller.signal);
    };
    window.addEventListener("agent:sessions-changed", refresh);
    return () => {
      clearTimeout(timer);
      controller.abort();
      window.removeEventListener("agent:sessions-changed", refresh);
    };
  }, [activeId, load]);
  async function more() {
    setLoading(true);
    try {
      const result = await agentApi.get<{
        items: Session[];
        next_cursor: string | null;
      }>(`/sessions?limit=50&cursor=${encodeURIComponent(cursor!)}`);
      setItems((old) => [
        ...new Map([...old, ...result.items].map((s) => [s.id, s])).values(),
      ]);
      setCursor(result.next_cursor);
      setPageCount((n) => n + 1);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "会话加载失败");
    } finally {
      setLoading(false);
    }
  }
  return (
    <section
      aria-label="助手会话列表"
      className="mt-6 border-t border-slate-100 pt-5"
    >
      <div className="mb-3 flex items-center justify-between px-3">
        <h2 className="text-xs font-medium text-slate-500">我的会话</h2>
        <Link
          href="/"
          aria-label="新建助手会话"
          className="rounded-md p-1 text-slate-500 hover:bg-slate-100"
        >
          <Plus className="h-4 w-4" />
        </Link>
      </div>
      {error && (
        <p role="alert" className="px-3 py-2 text-xs text-red-700">
          {error}
          <button className="ml-2 underline" onClick={() => void load()}>
            重试
          </button>
        </p>
      )}
      {loading && !items.length && (
        <p className="px-3 py-2 text-xs text-slate-400">正在加载…</p>
      )}
      {!loading && !error && !items.length && (
        <p className="px-3 py-2 text-xs leading-6 text-slate-400">
          开始一个任务，会话会保存在这里。
        </p>
      )}
      <div className="space-y-1">
        {items
          .filter((s) => s.status !== "DELETING" && s.agent_type === "SCHEDULING")
          .map((s) => {
            const Icon =
              s.agent_type === "ORDER_INTAKE" ? ClipboardList : Layers3;
            return (
              <Link
                key={s.id}
                href={`/?session=${encodeURIComponent(s.id)}`}
                aria-current={activeId === s.id ? "page" : undefined}
                className={`flex items-start gap-2.5 rounded-lg px-3 py-2.5 transition-colors ${activeId === s.id ? "bg-[#C8331F]/[0.06] text-[#AC2C1B]" : "text-slate-600 hover:bg-slate-50"}`}
              >
                <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 opacity-60" />
                <span className="min-w-0">
                  <span className="block truncate text-xs font-medium">
                    {s.title ||
                      (s.agent_type === "ORDER_INTAKE" ? "创建订单" : "排单")}
                  </span>
                  <span className="mt-1 block text-[10px] text-slate-400">
                    {s.agent_type === "ORDER_INTAKE" ? "订单录入" : "生产排单"}
                    {s.status === "ARCHIVED" ? " · 已归档" : ""}
                  </span>
                </span>
              </Link>
            );
          })}
      </div>
      {cursor && (
        <button
          disabled={loading}
          onClick={() => void more()}
          className="w-full py-3 text-xs text-slate-500 disabled:opacity-40"
        >
          {loading ? "加载中…" : "更多会话"}
          {pageCount > 1 ? ` · 已加载 ${items.length} 条` : ""}
        </button>
      )}
    </section>
  );
}
