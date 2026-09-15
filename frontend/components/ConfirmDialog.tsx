"use client";

import { useRef, useState, type ReactNode } from "react";
import { Dialog } from "@base-ui/react/dialog";
import { AlertTriangle, LoaderCircle } from "lucide-react";

export type ConfirmationOptions = {
  title: string;
  description: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
};

export default function ConfirmDialog({ open, onCancel, onConfirm, ...options }: ConfirmationOptions & {
  open: boolean;
  onCancel: () => void;
  onConfirm: () => void | Promise<unknown>;
}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const inFlight = useRef(false);
  const cancel = useRef<HTMLButtonElement>(null);
  async function submit() {
    if (inFlight.current) return;
    inFlight.current = true;
    setPending(true);
    setError("");
    try {
      await onConfirm();
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败，请重试");
    } finally {
      inFlight.current = false;
      setPending(false);
    }
  }
  return (
    <Dialog.Root open={open} disablePointerDismissal onOpenChange={(next) => {
      if (!next && !inFlight.current) { setError(""); onCancel(); }
    }} onOpenChangeComplete={(next) => { if (!next) setError(""); }}>
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 z-[100] bg-slate-900/30 backdrop-blur-[2px]" />
        <Dialog.Popup role="alertdialog" initialFocus={cancel} aria-busy={pending}
          className="fixed left-1/2 top-1/2 z-[101] w-[calc(100%-32px)] max-w-md -translate-x-1/2 -translate-y-1/2 overflow-hidden rounded-2xl border border-slate-200 bg-white text-slate-800 shadow-2xl outline-none">
          <div className="max-h-[65dvh] overflow-y-auto p-6">
            <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-amber-50 text-amber-600"><AlertTriangle size={23} /></div>
            <Dialog.Title className="text-lg font-semibold tracking-tight">{options.title}</Dialog.Title>
            <Dialog.Description className="mt-3 whitespace-pre-line break-words text-sm leading-7 text-slate-500">{options.description}</Dialog.Description>
            {error && <p role="alert" className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm leading-6 text-red-700">{error}</p>}
          </div>
          <div className="flex justify-end gap-3 border-t border-slate-100 bg-slate-50/70 px-6 py-4">
            <Dialog.Close ref={cancel} disabled={pending} className="min-h-10 rounded-lg border border-slate-200 bg-white px-5 text-sm font-medium hover:bg-slate-50 disabled:opacity-50">{options.cancelLabel ?? "取消"}</Dialog.Close>
            <button disabled={pending} onClick={() => void submit()} className={`flex min-h-10 items-center justify-center gap-2 rounded-lg px-5 text-sm font-medium text-white disabled:opacity-60 ${options.destructive === false ? "bg-slate-800 hover:bg-slate-700" : "bg-[#C8331F] hover:bg-[#ad2c1b]"}`}>
              {pending && <LoaderCircle size={15} className="animate-spin" />}{pending ? "正在处理…" : options.confirmLabel ?? "确认删除"}
            </button>
          </div>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
