"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useSession } from "next-auth/react";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { api, ApiError } from "@/lib/api";
import { federatedSignOut } from "@/lib/auth-client";
import type { ChatSessionSummary } from "@/components/chat/types";

const RECENT_SESSION_LIMIT = 6;

const navItems = [
  {
    href: "/",
    label: "AI 助手",
    hint: "智能录单 · 排产",
    // exact match — home only
    match: (p: string) => p === "/",
    icon: (
      <svg className="w-[18px] h-[18px]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.7}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09ZM18.259 8.715 18 9.75l-.259-1.035a3.375 3.375 0 0 0-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 0 0 2.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 0 0 2.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 0 0-2.456 2.456Z" />
      </svg>
    ),
  },
  {
    href: "/kanban",
    label: "排单看板",
    hint: "生产排程",
    match: (p: string) => p.startsWith("/kanban"),
    icon: (
      <svg className="w-[18px] h-[18px]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.7}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6A2.25 2.25 0 0 1 6 3.75h2.25A2.25 2.25 0 0 1 10.5 6v2.25a2.25 2.25 0 0 1-2.25 2.25H6a2.25 2.25 0 0 1-2.25-2.25V6ZM3.75 15.75A2.25 2.25 0 0 1 6 13.5h2.25a2.25 2.25 0 0 1 2.25 2.25V18a2.25 2.25 0 0 1-2.25 2.25H6A2.25 2.25 0 0 1 3.75 18v-2.25ZM13.5 6a2.25 2.25 0 0 1 2.25-2.25H18A2.25 2.25 0 0 1 20.25 6v2.25A2.25 2.25 0 0 1 18 10.5h-2.25a2.25 2.25 0 0 1-2.25-2.25V6ZM13.5 15.75a2.25 2.25 0 0 1 2.25-2.25H18a2.25 2.25 0 0 1 2.25 2.25V18A2.25 2.25 0 0 1 18 20.25h-2.25a2.25 2.25 0 0 1-2.25-2.25v-2.25Z" />
      </svg>
    ),
  },
  {
    href: "/orders",
    label: "订单列表",
    hint: "全部订单",
    match: (p: string) => p.startsWith("/orders"),
    icon: (
      <svg className="w-[18px] h-[18px]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.7}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 0 0 2.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 0 0-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 0 0 .75-.75 2.25 2.25 0 0 0-.1-.664m-5.8 0A2.251 2.251 0 0 1 13.5 2.25H15c1.012 0 1.867.668 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m0 0H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V9.375c0-.621-.504-1.125-1.125-1.125H8.25Z" />
      </svg>
    ),
  },
  {
    href: "/settings",
    label: "基础数据",
    hint: "客户 · 产品 · 配方",
    ownerOnly: true,
    match: (p: string) => p.startsWith("/settings"),
    icon: (
      <svg className="w-[18px] h-[18px]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.7}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 0v3.75m-16.5-3.75v3.75m16.5 0v3.75C20.25 16.153 16.556 18 12 18s-8.25-1.847-8.25-4.125v-3.75m16.5 0c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125" />
      </svg>
    ),
  },
];

function BrandMark({ className = "w-7 h-[15px]" }: { className?: string }) {
  return (
    <svg viewBox="-4 -1 40 21" fill="none" xmlns="http://www.w3.org/2000/svg" className={className}>
      <g transform="skewX(-12)" fill="white">
        <path d="M 2,0 L 14,0 L 14,19 L 9,19 L 9,4 L 2,4 Z" />
        <rect x="17" y="0" width="5" height="19" />
        <path d="M 23,0 L 28,0 L 28,14 L 32,14 L 32,19 L 23,19 Z" />
      </g>
    </svg>
  );
}

function SessionListFallback() {
  return (
    <div className="space-y-1 px-1" aria-label="正在加载最近会话">
      {[0, 1, 2].map((item) => (
        <div key={item} className="h-8 rounded-lg bg-slate-100 animate-pulse" />
      ))}
    </div>
  );
}

function RecentSessions() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const activeSessionId = searchParams.get("session");
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [retryKey, setRetryKey] = useState(0);
  const [deleteTarget, setDeleteTarget] = useState<ChatSessionSummary | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    api.get<ChatSessionSummary[]>("/agent/sessions")
      .then((items) => {
        if (!cancelled) setSessions(items.slice(0, RECENT_SESSION_LIMIT));
      })
      .catch(() => {
        if (!cancelled) setLoadError(true);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [activeSessionId, retryKey]);

  async function deleteSession() {
    if (!deleteTarget || isDeleting) return;

    const sessionToDelete = deleteTarget;
    setIsDeleting(true);
    setDeleteError(null);

    try {
      await api.delete(`/agent/sessions/${encodeURIComponent(sessionToDelete.id)}`);
      setSessions((items) => items.filter((item) => item.id !== sessionToDelete.id));
      setDeleteTarget(null);
      if (activeSessionId === sessionToDelete.id) {
        router.replace("/", { scroll: false });
      }
    } catch (error) {
      setDeleteError(error instanceof ApiError ? error.message : "删除会话失败，请重试");
    } finally {
      setIsDeleting(false);
    }
  }

  return (
    <div className="mt-3 border-t border-slate-100 pt-3">
      <div className="flex items-center justify-between px-3 pb-1.5">
        <p className="text-[11px] font-medium uppercase tracking-wider text-slate-300">最近会话</p>
        <Link
          href="/"
          scroll={false}
          title="开启新对话"
          className="flex h-5 w-5 items-center justify-center rounded-md text-slate-300 transition-colors hover:bg-slate-100 hover:text-slate-600"
        >
          <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
          </svg>
        </Link>
      </div>

      {isLoading && sessions.length === 0 ? (
        <SessionListFallback />
      ) : loadError ? (
        <button
          type="button"
          onClick={() => {
            setLoadError(false);
            setIsLoading(true);
            setRetryKey((value) => value + 1);
          }}
          className="w-full rounded-lg px-3 py-2 text-left text-xs text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
        >
          加载失败，点击重试
        </button>
      ) : sessions.length === 0 ? (
        <p className="px-3 py-2 text-xs text-slate-400">还没有历史会话</p>
      ) : (
        <div className="space-y-0.5">
          {sessions.map((chatSession) => {
            const active = pathname === "/" && activeSessionId === chatSession.id;
            return (
              <div key={chatSession.id} className="group relative">
                <Link
                  href={{ pathname: "/", query: { session: chatSession.id } }}
                  scroll={false}
                  title={chatSession.title}
                  className={`flex items-center gap-2 rounded-lg py-2 pl-3 pr-9 text-xs transition-colors ${
                    active
                      ? "bg-slate-100 text-slate-800"
                      : "text-slate-500 hover:bg-slate-100 hover:text-slate-800"
                  }`}
                >
                  <svg className="h-3.5 w-3.5 shrink-0 text-slate-300 group-hover:text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M8.625 12h.008v.008h-.008V12Zm3.375 0h.008v.008H12V12Zm3.375 0h.008v.008h-.008V12ZM21 12c0 4.142-4.03 7.5-9 7.5a10.2 10.2 0 0 1-3.17-.5L3 20.25l1.58-4.2A6.9 6.9 0 0 1 3 12c0-4.142 4.03-7.5 9-7.5s9 3.358 9 7.5Z" />
                  </svg>
                  <span className="truncate">{chatSession.title}</span>
                </Link>
                <button
                  type="button"
                  onClick={() => {
                    setDeleteError(null);
                    setDeleteTarget(chatSession);
                  }}
                  aria-label={`删除会话 ${chatSession.title}`}
                  title="删除会话"
                  className={`absolute right-1.5 top-1/2 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-md text-slate-300 transition-all hover:bg-red-50 hover:text-red-500 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-200 ${
                    active ? "opacity-100" : "opacity-0 group-hover:opacity-100"
                  }`}
                >
                  <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166M19.228 5.79 18.16 19.673A2.25 2.25 0 0 1 15.916 21H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0V4.477c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
                  </svg>
                </button>
              </div>
            );
          })}
        </div>
      )}

      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open && !isDeleting) {
            setDeleteTarget(null);
            setDeleteError(null);
          }
        }}
      >
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle className="text-slate-800">删除会话</DialogTitle>
          </DialogHeader>
          <p className="py-2 text-sm text-slate-500">
            确定删除会话「<span className="font-medium text-slate-700">{deleteTarget?.title}</span>」吗？聊天记录也会被删除，此操作不可撤销。
          </p>
          {deleteError && (
            <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">
              {deleteError}
            </p>
          )}
          <DialogFooter>
            <Button
              variant="outline"
              disabled={isDeleting}
              onClick={() => {
                setDeleteTarget(null);
                setDeleteError(null);
              }}
              className="border-slate-200 text-slate-600"
            >
              取消
            </Button>
            <Button
              disabled={isDeleting}
              onClick={deleteSession}
              className="border-0 bg-red-500 text-white hover:bg-red-600"
            >
              {isDeleting ? "删除中…" : "确认删除"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function Sidebar() {
  const pathname = usePathname();
  const { data: session, status } = useSession();

  if (pathname.startsWith("/login")) return null;

  const email = session?.user?.email ?? "";
  const initial = email ? email[0]!.toUpperCase() : "F";
  const visibleNavItems = navItems.filter(
    (item) => !("ownerOnly" in item && item.ownerOnly) || session?.user?.role === "OWNER",
  );

  return (
    <>
      {/* 桌面端：左侧宽导航栏 */}
      <aside className="hidden md:flex fixed left-0 top-0 h-full w-60 flex-col bg-white border-r border-slate-200 z-50">
        {/* 品牌 */}
        <div className="flex items-center gap-2.5 px-4 h-16 shrink-0">
          <div className="w-9 h-9 rounded-xl bg-[#C8331F] flex items-center justify-center shrink-0 shadow-sm shadow-red-200/60">
            <BrandMark />
          </div>
          <div className="min-w-0">
            <div className="text-[15px] font-semibold text-slate-800 leading-tight tracking-tight">FilmOS</div>
            <div className="flex items-center gap-1.5 leading-tight">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
              <span className="text-[11px] text-slate-400">已就绪</span>
            </div>
          </div>
        </div>

        {/* 导航 */}
        <nav className="flex-1 px-3 pt-2 space-y-0.5 overflow-y-auto">
          <p className="px-3 pb-1.5 pt-2 text-[11px] font-medium uppercase tracking-wider text-slate-300">工作台</p>
          {visibleNavItems.map((item) => {
            const active = item.match(pathname);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`group flex items-center gap-3 px-3 py-2 rounded-xl transition-colors ${
                  active
                    ? "bg-[#C8331F]/[0.07] text-[#C8331F]"
                    : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                }`}
              >
                <span className={active ? "text-[#C8331F]" : "text-slate-400 group-hover:text-slate-600"}>
                  {item.icon}
                </span>
                <span className="flex-1 min-w-0">
                  <span className="block text-sm font-medium leading-tight truncate">{item.label}</span>
                  <span className={`block text-[11px] leading-tight truncate ${active ? "text-[#C8331F]/60" : "text-slate-400"}`}>
                    {item.hint}
                  </span>
                </span>
              </Link>
            );
          })}
          <Suspense fallback={<SessionListFallback />}>
            {status === "authenticated" ? <RecentSessions /> : null}
          </Suspense>
        </nav>

        {/* 用户 */}
        <div className="shrink-0 border-t border-slate-100 p-3">
          <div className="flex items-center gap-2.5 px-1.5 py-1.5">
            <div className="w-8 h-8 rounded-lg bg-[#C8331F]/10 text-[#C8331F] flex items-center justify-center text-xs font-semibold shrink-0">
              {initial}
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-xs font-medium text-slate-700 truncate">{email || "未登录"}</div>
              <div className="text-[11px] text-slate-400 leading-tight">工作区</div>
            </div>
            <button
              onClick={() => void federatedSignOut()}
              title="退出登录"
              className="w-7 h-7 flex items-center justify-center rounded-lg text-slate-400 hover:text-red-500 hover:bg-red-50 transition-colors shrink-0"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 9V5.25A2.25 2.25 0 0 1 10.5 3h6a2.25 2.25 0 0 1 2.25 2.25v13.5A2.25 2.25 0 0 1 16.5 21h-6a2.25 2.25 0 0 1-2.25-2.25V15M12 9l-3 3m0 0 3 3m-3-3h12.75" />
              </svg>
            </button>
          </div>
        </div>
      </aside>

      {/* 手机端：底部导航栏 */}
      <nav
        className="md:hidden fixed bottom-0 left-0 right-0 z-50 bg-white border-t border-slate-200"
        style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
      >
        <div className="flex items-stretch h-16">
          {visibleNavItems.map((item) => {
            const active = item.match(pathname);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex-1 flex flex-col items-center justify-center gap-0.5 transition-colors ${
                  active ? "text-[#C8331F]" : "text-slate-400"
                }`}
              >
                {item.icon}
                <span className="text-[10px] font-medium">{item.label}</span>
              </Link>
            );
          })}
        </div>
      </nav>
    </>
  );
}
