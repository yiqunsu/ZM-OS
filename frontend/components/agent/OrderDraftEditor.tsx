"use client";
import { useConfirmation } from "@/components/ConfirmationProvider";
import { useEffect, useState, useImperativeHandle, type Ref } from "react";
import Link from "next/link";
import { ImagePreview } from "./ImagePreview";
import OrderForm from "@/components/orders/form/OrderForm";
import type { OrderDraft as FormDraft } from "@/components/orders/form/model";
import { AgentError, agentApi, attachmentUrl } from "./api";
import type { OrderDraft, WorkItem } from "./types";

export type OrderEditorHandle = { saveForNavigation: () => Promise<boolean> };

export default function OrderDraftEditor({
  item,
  busy,
  readOnly,
  onChanged,
  workbench = false,
  editorRef,
  onCompleted,
  sourceLabel = "订单截图",
}: {
  item: WorkItem;
  busy: boolean;
  readOnly: boolean;
  onChanged: () => Promise<unknown>;
  workbench?: boolean;
  editorRef?: Ref<OrderEditorHandle>;
  sourceLabel?: string;
  onCompleted?: (message: string) => void;
}) {
  const confirm = useConfirmation();
  const [draft, setDraft] = useState<OrderDraft>(item.draft);
  const [revision, setRevision] = useState(item.revision);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [formReady, setFormReady] = useState(false);
  useEffect(() => {
    if (dirty || item.revision < revision) return;
    const timer = setTimeout(() => {
      setDraft(item.draft);
      setRevision(item.revision);
    }, 0);
    return () => clearTimeout(timer);
  }, [item.draft, item.revision, dirty, revision]);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (dirty) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  function edit(value: FormDraft) {
    setDraft((old) => ({
      ...old,
      customer_id: value.customer_id || null,
      product_id: value.product_id || null,
      spec_params: value.spec_params ?? {},
      quantity: value.quantity == null ? null : String(value.quantity),
      unit: value.unit === "m" || value.unit === "kg" ? value.unit : null,
      formula_id: value.formula_id || null,
      formula_mode: value.formula_mode === "existing" ? "existing" : "none",
      extra_notes: value.extra_notes ?? "",
    }));
    setDirty(true);
  }
  async function save(): Promise<WorkItem | null> {
    if (!dirty) return { ...item, draft, revision };
    setSaving(true);
    setError("");
    try {
      const { schema_version: _version, ...patch } = draft;
      void _version;
      const next = await agentApi.patch<WorkItem>(`/items/${item.id}/draft`, {
        expected_revision: revision,
        patch,
      });
      setDraft(next.draft);
      setRevision(next.revision);
      setDirty(false);
      await onChanged();
      return next;
    } catch (e) {
      setError(e instanceof Error ? e.message : "草稿保存失败");
      if (e instanceof AgentError && e.status === 409)
        await onChanged().catch(() => undefined);
      return null;
    } finally {
      setSaving(false);
    }
  }
  useImperativeHandle(editorRef, () => ({
    saveForNavigation: async () => !dirty || !!(await save()),
  }));

  async function command(action: "confirm" | "defer" | "close") {
    if (
      action === "close" &&
      !(await confirm({ title: "放弃这笔订单？", description: `将放弃${sourceLabel}中的第 ${item.source_order_index ?? 1} 笔订单草稿，不会创建正式订单。同图的其他订单继续保留。`, confirmLabel: "确认放弃", cancelLabel: "继续核对" }))
    )
      return;
    const saved = dirty ? await save() : { revision };
    if (!saved) return;
    setSaving(true);
    setError("");
    try {
      const result = await agentApi.command<{ order?: { order_no: string } }>(
        `/items/${item.id}/${action}`,
        {
          expected_revision: saved.revision,
          ...(workbench ? { advance: true } : {}),
          ...(action === "close" ? { confirmed: true } : {}),
        },
      );
      onCompleted?.(
        action === "confirm"
          ? `订单 ${result.order?.order_no ?? ""} 创建成功`
          : action === "defer"
            ? "已保存，稍后可继续处理"
            : "已放弃这笔订单",
      );
      try {
        await onChanged();
      } catch {
        setError("操作已成功，列表刷新失败，请刷新页面继续。");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败，请重试");
    } finally {
      setSaving(false);
    }
  }
  const conflict = dirty && item.revision !== revision;
  const locked = readOnly || item.status !== "ACTIVE";
  return (
    <section
      className="m-3 space-y-2.5"
      aria-label="订单核对工作区"
      data-unsaved-draft={dirty}
    >
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">
          核对订单 {item.source_order_index ?? 1}
        </h2>
        <div className="flex items-center gap-3">
          {!workbench && (
            <ImagePreview
              src={attachmentUrl(item.source_attachment_id)}
              alt={sourceLabel}
              label="原始截图"
            />
          )}
          <span className="text-xs text-slate-400">
            {dirty ? "未保存" : "已保存"}
          </span>
        </div>
      </div>
      {item.status === "CREATED" && (
        <p className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">
          {item.order_id ? "订单已创建。" : "正式订单已删除，识别记录保留。"}
          {item.order_id && <Link className="ml-2 underline" href={`/orders/${item.order_id}`}>
            查看正式订单
          </Link>}
        </p>
      )}
      {error && (
        <p
          role="alert"
          className="rounded-lg bg-red-50 p-3 text-sm text-red-700"
        >
          {error}
        </p>
      )}
      {conflict && (
        <div className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
          草稿有更新，你的未保存内容仍保留。
          <button
            className="ml-2 underline"
            onClick={async () => {
              if (await confirm({title: "加载最新草稿？", description: "当前未保存的修改将被替换为已保存的最新草稿。", confirmLabel: "放弃修改并加载", cancelLabel: "继续编辑"})) {
                setDraft(item.draft);
                setRevision(item.revision);
                setDirty(false);
                setError("");
              }
            }}
          >
            加载最新草稿
          </button>
        </div>
      )}
      <OrderForm
        key={`${item.id}:${revision}`}
        workspace={{
          draft,
          issues: workbench ? item.issues : undefined,
          onDraftChange: edit,
          disabled: saving || busy || locked,
          onReadyChange: setFormReady,
        }}
      />
      {item.issues.length > 0 && !workbench && (
        <details className="group relative rounded-lg border border-amber-200/60 bg-amber-50 text-xs text-amber-900">
          <summary className="flex cursor-pointer items-center gap-2 px-3 py-2">
            <span className="shrink-0">{item.issues.length} 项待核对</span>
            <span className="min-w-0 flex-1 truncate">
              {item.issues[0].message}
            </span>
            <span className="shrink-0 underline">查看</span>
          </summary>
          <ul className="absolute bottom-full left-0 right-0 z-20 mb-1 max-h-48 space-y-2 overflow-y-auto rounded-lg border border-amber-200 bg-white p-3 shadow-lg">
            {item.issues.map((issue, index) => (
              <li key={`${issue.field}:${index}`}>{issue.message}</li>
            ))}
          </ul>
        </details>
      )}
      {workbench && item.issues.filter((i) => i.field === "source").map((i, index) => (
        <p className="text-xs text-amber-700" key={index}>{i.message}</p>
      ))}
      {!locked && (
        <div className="flex flex-wrap gap-2 border-t border-slate-200/70 pt-2">
          <button
            disabled={!dirty || saving || conflict}
            onClick={() => void save()}
            className="rounded-lg border bg-white px-4 py-2 text-sm disabled:opacity-40"
          >
            保存草稿
          </button>
          <button
            disabled={
              busy ||
              saving ||
              (!workbench && dirty) ||
              conflict ||
              !formReady ||
              (!dirty && item.issues.some((i) => i.severity === "blocking"))
            }
            onClick={() => void command("confirm")}
            className="rounded-lg bg-[#C8331F] px-4 py-2 text-sm text-white disabled:opacity-40"
          >
            {workbench ? "确认创建订单" : "创建订单"}
          </button>
          <button
            disabled={busy || saving || (!workbench && dirty) || conflict}
            onClick={() => void command("defer")}
            className="px-3 py-2 text-sm disabled:opacity-40"
          >
            {workbench ? "稍后处理" : "暂放"}
          </button>
          <button
            disabled={busy || saving || (!workbench && dirty) || conflict}
            onClick={() => void command("close")}
            className="px-3 py-2 text-sm text-slate-500 disabled:opacity-40"
          >
            放弃
          </button>
        </div>
      )}
      <p className="text-[11px] leading-4 text-slate-400">
        {workbench
          ? "核对无误后确认创建，订单将进入待排单。"
          : "先保存修改，再创建订单。"}
      </p>
    </section>
  );
}
