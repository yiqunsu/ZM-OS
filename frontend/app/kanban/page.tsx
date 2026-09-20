import KanbanBoard from "@/components/kanban/KanbanBoard";
import StartSchedulingButton from "@/components/agent/StartSchedulingButton";

export default function KanbanPage() {
  return (
    <div className="flex flex-col h-screen">
      <header className="sticky top-0 z-40 bg-white border-b border-slate-200 shadow-sm shrink-0">
        <div className="px-8 flex items-center h-14 gap-4">
          <h1 className="text-base font-semibold text-slate-800 shrink-0">排单看板</h1>
          <span className="flex-1" />
          <StartSchedulingButton />
        </div>
      </header>

      <main className="flex-1 overflow-hidden bg-slate-50">
        <KanbanBoard />
      </main>
    </div>
  );
}
