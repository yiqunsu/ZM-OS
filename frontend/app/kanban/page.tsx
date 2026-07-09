import KanbanBoard from "@/components/kanban/KanbanBoard";
import Link from "next/link";

export default function KanbanPage() {
  return (
    <div className="flex flex-col h-screen">
      <header className="sticky top-0 z-40 bg-white border-b border-slate-200 shadow-sm shrink-0">
        <div className="px-8 flex items-center h-14 gap-4">
          <h1 className="text-base font-semibold text-slate-800 shrink-0">排单看板</h1>
          <span className="flex-1" />
          <Link
            href="/orders/new"
            className="inline-flex items-center gap-1.5 bg-blue-600 hover:bg-blue-700 active:scale-95 text-white text-sm font-medium px-4 py-2 rounded-lg transition-all shadow-sm shadow-blue-200"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
            </svg>
            新建订单
          </Link>
        </div>
      </header>

      <main className="flex-1 overflow-hidden bg-slate-50">
        <KanbanBoard />
      </main>
    </div>
  );
}
