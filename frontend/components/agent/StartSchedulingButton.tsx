"use client";
import { Sparkles } from "lucide-react";
import { useAgentOperation } from "./useAgentOperation";
import { useAgentWorkspace } from "./useAgentWorkspace";
export default function StartSchedulingButton() {
  const { act, working, error } = useAgentOperation();
  const openWorkspace = useAgentWorkspace(act);
  return <><button type="button" disabled={working} onClick={() => void openWorkspace("SCHEDULING")}
    className="inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm shadow-blue-200 transition-all hover:bg-blue-700 active:scale-95 disabled:opacity-50">
      <Sparkles size={16} />智能排单
    </button>
    {error && <span role="alert" className="text-xs text-red-700">{error}</span>}</>;
}
