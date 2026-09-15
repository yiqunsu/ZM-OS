"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { agentApi } from "./api";
import type { WorkItem } from "./types";
import type { ScreenshotGroup } from "./screenshotGroups";

export type ScreenshotTab = "pending" | "created" | "archived";
interface ScreenshotRow {
  id: string;
  source_day: string;
  source_day_position: number;
  source_uploaded_at: string;
  source_archived: boolean;
  screenshot_revision: number;
  busy: boolean;
  running_item_id: string | null;
  items: WorkItem[];
}
interface ScreenshotPage {
  screenshots: ScreenshotRow[];
  counts: Record<string, number>;
  next_cursor: string | null;
}
export function useScreenshotList(tab: ScreenshotTab, version: string) {
  const [page, setPage] = useState<{ tab: ScreenshotTab; data: ScreenshotPage } | null>(null);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const loadedPages = useRef({tab, count: 1});
  const reload = useCallback(async () => {
    const seq = ++generation.current;
    if (loadedPages.current.tab !== tab) loadedPages.current = {tab, count: 1};
    const data = await agentApi.get<ScreenshotPage>(`/intake/screenshots?tab=${tab}`);
    for (let n = 1; n < loadedPages.current.count && data.next_cursor; n++) {
      const next = await agentApi.get<ScreenshotPage>(`/intake/screenshots?tab=${tab}&cursor=${encodeURIComponent(data.next_cursor)}`);
      data.screenshots.push(...next.screenshots);
      data.next_cursor = next.next_cursor;
      data.counts = next.counts;
    }
    if (seq === generation.current) { setPage({tab, data}); setError(""); }
  }, [tab]);
  useEffect(() => {
    const counter = generation;
    let disposed = false;
    const update = () => { void reload().catch(() => { if (!disposed) setError("截图列表加载失败，请重试"); }); };
    update();
    const timer = setInterval(update, 15000);
    return () => { disposed = true; clearInterval(timer); counter.current++; };
  }, [reload, version]);
  async function more() {
    if (page?.tab !== tab || !page.data.next_cursor) return;
    const seq = ++generation.current;
    const data = await agentApi.get<ScreenshotPage>(`/intake/screenshots?tab=${tab}&cursor=${encodeURIComponent(page.data.next_cursor)}`);
    if (seq === generation.current) {
      loadedPages.current.count++;
      setPage({tab, data: {...data, screenshots: [...page.data.screenshots, ...data.screenshots]}});
    }
  }
  const data = page?.tab === tab ? page.data : null;
  const screenshots: ScreenshotGroup[] = (data?.screenshots ?? []).map(row => ({
    id: row.id, day: row.source_day, position: row.source_day_position,
    uploadedAt: row.source_uploaded_at, items: row.items,
    archived: row.source_archived, revision: row.screenshot_revision,
    busy: row.busy, runningId: row.running_item_id,
  }));
  return {screenshots, counts: data?.counts, hasMore: !!data?.next_cursor, loading: !data && !error, error, reload, more};
}
