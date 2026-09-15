"use client";
import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";

export default function BackToAssistantButton({ disabled = false, onClick }: {
  disabled?: boolean;
  onClick?: () => void;
}) {
  const router = useRouter();
  return (
    <button
      type="button"
      aria-label="返回助手首页"
      title="返回助手首页"
      disabled={disabled}
      onClick={onClick ?? (() => router.push("/"))}
      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-slate-700 hover:bg-slate-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-500 disabled:opacity-40"
    >
      <ArrowLeft size={19} />
    </button>
  );
}
