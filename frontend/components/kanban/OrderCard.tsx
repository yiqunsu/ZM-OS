"use client";

import { useState, useRef } from "react";
import { useDraggable } from "@dnd-kit/core";
import { CSS } from "@dnd-kit/utilities";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { api } from "@/lib/api";
import type { KanbanOrder } from "./types";

interface FullOrder {
  id:               string;
  order_no:         string;
  status:           string;
  quantity:         number;
  unit:             string;
  spec_params:      Record<string, string>;
  extra_notes:      string | null;
  formula_snapshot: { name?: string; materials?: string } | null;
  created_at:       string;
  customer: { company: string; contact: string };
  product:  { name: string; category: { name: string } };
  formula:  { id: string; name: string; materials: string } | null;
}

const STATUS_LABEL: Record<string, string> = {
  PENDING:   "待排单",
  PRODUCING: "生产中",
  DONE:      "已完成",
};
const STATUS_STYLE: Record<string, string> = {
  PENDING:   "bg-amber-50 text-amber-600 border-amber-200",
  PRODUCING: "bg-blue-50 text-blue-600 border-blue-200",
  DONE:      "bg-green-50 text-green-600 border-green-200",
};

interface Props {
  order: KanbanOrder;
  overlay?: boolean;
}

export default function OrderCard({ order, overlay = false }: Props) {
  const [detailOpen,    setDetailOpen]    = useState(false);
  const [fullOrder,     setFullOrder]     = useState<FullOrder | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  /* Track pointer movement to distinguish click vs drag */
  const pointerStartPos = useRef<{ x: number; y: number } | null>(null);
  const didDrag = useRef(false);

  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id:   order.id,
    data: { type: "order" },
    disabled: overlay,
  });

  const style = {
    transform: CSS.Translate.toString(transform),
    opacity:   isDragging ? 0.4 : 1,
  };

  const specs = Object.entries(order.spec_params ?? {});

  async function openDetail() {
    setDetailOpen(true);
    if (!fullOrder) {
      setDetailLoading(true);
      setFullOrder(await api.get<FullOrder>(`/orders/${order.id}`));
      setDetailLoading(false);
    }
  }

  /* Wrap DnD's onPointerDown so we can track movement without breaking drag */
  function handlePointerDown(e: React.PointerEvent<HTMLDivElement>) {
    pointerStartPos.current = { x: e.clientX, y: e.clientY };
    didDrag.current = false;
    listeners?.onPointerDown?.(e); // must forward to DnD or drag breaks
  }

  function handlePointerMove(e: React.PointerEvent) {
    if (!pointerStartPos.current) return;
    const dx = Math.abs(e.clientX - pointerStartPos.current.x);
    const dy = Math.abs(e.clientY - pointerStartPos.current.y);
    if (dx > 6 || dy > 6) didDrag.current = true;
  }

  function handleClick() {
    if (overlay || didDrag.current) return;
    openDetail();
  }

  /* Formatted date helper */
  function fmtDate(iso: string) {
    return new Date(iso).toLocaleDateString("zh-CN", {
      year: "numeric", month: "2-digit", day: "2-digit",
    });
  }

  function getMaterials(): string | null {
    if (fullOrder?.formula_snapshot?.materials?.trim()) return fullOrder.formula_snapshot.materials.trim();
    if (fullOrder?.formula?.materials?.trim()) return fullOrder.formula.materials.trim();
    return null;
  }

  return (
    <>
      <div
        ref={setNodeRef}
        style={style}
        {...attributes}
        {...listeners}
        onPointerDown={handlePointerDown}  /* overrides listeners.onPointerDown — we forward it manually */
        onPointerMove={handlePointerMove}
        onClick={handleClick}
        className={`bg-white rounded-xl border border-slate-200 p-3.5 select-none ${
          overlay
            ? "shadow-xl rotate-1 cursor-grabbing"
            : "cursor-grab hover:border-slate-300 hover:shadow-sm transition-all"
        }`}
      >
        {/* Row 1: order number + badge */}
        <div className="flex items-center justify-between gap-2 mb-2.5">
          <span className="font-mono text-[11px] text-slate-400 tracking-tight leading-none">
            {order.order_no}
          </span>
          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-50 text-amber-600 border border-amber-200 font-semibold shrink-0 leading-none">
            待排单
          </span>
        </div>

        {/* Row 2: company name */}
        <p className="text-sm font-semibold text-slate-800 truncate leading-tight mb-1">
          {order.customer.company}
        </p>

        {/* Row 3: category · product */}
        <p className="text-xs text-slate-400 truncate leading-tight mb-3">
          {order.product.category.name}
          <span className="mx-1.5 text-slate-300">·</span>
          {order.product.name}
        </p>

        {/* Row 4: spec chips + quantity */}
        <div className="flex items-end justify-between gap-2">
          <div className="flex flex-wrap gap-1 min-w-0">
            {specs.map(([k, v]) => (
              <span
                key={k}
                className="inline-flex items-center px-2 py-0.5 rounded-full bg-slate-100 text-slate-500 text-[11px] leading-none font-medium"
              >
                {k}: {v}
              </span>
            ))}
            {specs.length === 0 && (
              <span className="text-xs text-slate-300 italic">暂无规格</span>
            )}
          </div>
          <span className="text-xs font-bold text-slate-700 shrink-0 leading-none">
            {order.quantity}
            <span className="font-normal text-slate-400 ml-0.5">{order.unit}</span>
          </span>
        </div>
      </div>

      {/* Detail dialog */}
      <Dialog open={detailOpen} onOpenChange={(o) => !o && setDetailOpen(false)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-3">
              <span className="font-mono text-sm font-semibold text-slate-700">
                {order.order_no}
              </span>
              {fullOrder && (
                <span className={`text-[11px] px-2 py-0.5 rounded-full border font-semibold ${STATUS_STYLE[fullOrder.status]}`}>
                  {STATUS_LABEL[fullOrder.status]}
                </span>
              )}
            </DialogTitle>
          </DialogHeader>

          {detailLoading || !fullOrder ? (
            <div className="py-10 flex items-center justify-center">
              <p className="text-sm text-slate-400">加载中…</p>
            </div>
          ) : (
            <div className="space-y-5 pt-1">

              {/* Customer + product */}
              <section>
                <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">基本信息</h4>
                <div className="space-y-1.5">
                  <Row label="客户" value={fullOrder.customer.company} />
                  <Row label="产品" value={`${fullOrder.product.category.name} · ${fullOrder.product.name}`} />
                  <Row label="数量" value={`${fullOrder.quantity} ${fullOrder.unit}`} />
                  <Row label="创建日期" value={fmtDate(fullOrder.created_at)} />
                </div>
              </section>

              {/* Spec params */}
              {Object.keys(fullOrder.spec_params ?? {}).length > 0 && (
                <section>
                  <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">规格参数</h4>
                  <div className="flex flex-wrap gap-1.5">
                    {Object.entries(fullOrder.spec_params).map(([k, v]) => (
                      <span key={k} className="px-2.5 py-1 rounded-lg bg-slate-100 text-slate-600 text-xs font-medium">
                        {k}: {v}
                      </span>
                    ))}
                  </div>
                </section>
              )}

              {/* Formula */}
              {(fullOrder.formula || fullOrder.formula_snapshot) && (() => {
                const materials = getMaterials();
                return (
                  <section>
                    <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">配方</h4>
                    {fullOrder.formula && (
                      <p className="text-sm text-slate-700 font-semibold mb-2">{fullOrder.formula.name}</p>
                    )}
                    {materials ? (
                      <pre className="text-xs text-slate-600 whitespace-pre-wrap leading-relaxed bg-slate-50 rounded-lg px-3 py-2.5 border border-slate-200 font-sans">
                        {materials}
                      </pre>
                    ) : (
                      <p className="text-xs text-slate-400 italic">暂无原材料明细</p>
                    )}
                  </section>
                );
              })()}

              {/* Extra notes */}
              {fullOrder.extra_notes && (
                <section>
                  <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">额外要求</h4>
                  <p className="text-sm text-slate-600 whitespace-pre-wrap leading-relaxed bg-slate-50 rounded-lg px-3 py-2">
                    {fullOrder.extra_notes}
                  </p>
                </section>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-2 text-sm">
      <span className="text-slate-400 shrink-0 w-16">{label}</span>
      <span className="text-slate-700">{value}</span>
    </div>
  );
}
