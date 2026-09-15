"use client";
import type { ReactNode } from "react";
import { ClipboardList, Layers3, ArrowUpRight } from "lucide-react";
import type { AgentType } from "./types";
export default function AgentHome({
  working,
  notice,
  create,
}: {
  working: boolean;
  notice: ReactNode;
  create: (type: AgentType) => Promise<void>;
}) {
  return (
    <main className="agent-home mx-auto w-full max-w-5xl px-5 py-12 md:px-12 md:py-20">
      <p className="mb-3 text-xs font-medium tracking-widest text-[#C8331F]">
        FILMOS · AI 助手
      </p>
      <h1 className="text-3xl font-semibold tracking-tight text-slate-900 md:text-4xl">
        今天，先处理哪件事？
      </h1>
      <p className="mt-3 text-sm leading-7 text-slate-500">
        选择要处理的事情，最后由你核对并确认。
      </p>
      <div className="my-10 grid gap-5 sm:grid-cols-2">
        <button
          disabled={working}
          onClick={() => void create("ORDER_INTAKE")}
          className="group relative flex flex-col items-start overflow-hidden rounded-2xl border border-slate-200/80 bg-white p-7 text-left transition duration-200 hover:-translate-y-0.5 hover:border-[#C8331F]/30 hover:shadow-lg hover:shadow-slate-200/40 disabled:opacity-40 motion-reduce:transform-none md:p-8"
        >
          <ClipboardList className="mb-7 h-11 w-11 rounded-xl bg-[#C8331F]/[0.07] p-2.5 text-[#C8331F]" />
          <h2 className="text-lg font-semibold">创建订单</h2>
          <p className="mt-2 flex-1 text-sm leading-6 text-slate-500">
            上传订单截图，对照原图核对，一键创建订单。
          </p>
          <span className="mt-6 block text-sm text-[#C8331F]">
            开始录单{" "}
            <ArrowUpRight className="ml-2 inline h-4 w-4 transition-transform group-hover:translate-x-0.5" />
          </span>
        </button>
        <button
          disabled={working}
          onClick={() => void create("SCHEDULING")}
          className="group relative flex flex-col items-start overflow-hidden rounded-2xl border border-slate-200/80 bg-white p-7 text-left transition duration-200 hover:-translate-y-0.5 hover:border-[#C8331F]/30 hover:shadow-lg hover:shadow-slate-200/40 disabled:opacity-40 motion-reduce:transform-none md:p-8"
        >
          <Layers3 className="mb-7 h-11 w-11 rounded-xl bg-[#C8331F]/[0.07] p-2.5 text-[#C8331F]" />
          <h2 className="text-lg font-semibold">排单</h2>
          <p className="mt-2 flex-1 text-sm leading-6 text-slate-500">
            结合待排订单、设备能力和生产队列，拟定可调整的排单建议。
          </p>
          <span className="mt-6 block text-sm text-[#C8331F]">
            开始排单{" "}
            <ArrowUpRight className="ml-2 inline h-4 w-4 transition-transform group-hover:translate-x-0.5" />
          </span>
        </button>
      </div>
      {notice}
    </main>
  );
}
