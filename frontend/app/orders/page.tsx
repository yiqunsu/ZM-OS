"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { api, ApiError } from "@/lib/api";

/* ─── Types ─── */
type OrderStatus = "PENDING" | "PRODUCING" | "DONE";

interface Category { id: string; name: string }
interface Product  { id: string; name: string; category: Category }
interface Customer { id: string; company: string; contact: string }
interface Formula  { id: string; name: string; materials: string }

interface Order {
  id:          string;
  order_no:    string;
  customer:    Customer;
  product:     Product;
  spec_params: Record<string, string>;
  quantity:    number;
  unit:        string;
  formula:     Formula | null;
  status:      OrderStatus;
  created_at:  string;
}

interface FullOrder extends Order {
  formula_snapshot: { name?: string; materials?: string } | null;
  extra_notes:      string | null;
}

const STATUS_LABEL: Record<OrderStatus, string> = {
  PENDING:   "待排单",
  PRODUCING: "生产中",
  DONE:      "已完成",
};

const STATUS_STYLE: Record<OrderStatus, string> = {
  PENDING:   "bg-amber-50 text-amber-700 border border-amber-200",
  PRODUCING: "bg-blue-50 text-blue-700 border border-blue-200",
  DONE:      "bg-green-50 text-green-700 border border-green-200",
};

const STATUS_CYCLE: Record<OrderStatus, OrderStatus> = {
  PENDING:   "PRODUCING",
  PRODUCING: "DONE",
  DONE:      "PENDING",
};

const FILTER_TABS: { key: OrderStatus | "ALL"; label: string }[] = [
  { key: "ALL",       label: "全部" },
  { key: "PENDING",   label: "待排单" },
  { key: "PRODUCING", label: "生产中" },
  { key: "DONE",      label: "已完成" },
];

function getMaterials(order: FullOrder): string | null {
  if (order.formula_snapshot?.materials?.trim()) return order.formula_snapshot.materials.trim();
  if (order.formula?.materials?.trim()) return order.formula.materials.trim();
  return null;
}

function fmtDate(iso: string) {
  return new Date(iso).toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });
}

/* ─── Main ─── */
export default function OrdersPage() {
  const router = useRouter();
  const [orders,       setOrders]       = useState<Order[]>([]);
  const [loading,      setLoading]      = useState(true);
  const [filter,       setFilter]       = useState<OrderStatus | "ALL">("ALL");
  const [deleteTarget, setDeleteTarget] = useState<Order | null>(null);
  const [detailOrder,  setDetailOrder]  = useState<FullOrder | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  /* ── Extra filters ── */
  const [filterCustomer, setFilterCustomer] = useState("");
  const [filterProduct,  setFilterProduct]  = useState("");
  const [filterDateFrom, setFilterDateFrom] = useState("");
  const [filterDateTo,   setFilterDateTo]   = useState("");

  async function load() {
    setLoading(true);
    setOrders(await api.get<Order[]>("/orders"));
    setLoading(false);
  }

  useEffect(() => { load(); }, []);

  async function openDetail(order: Order) {
    setDetailLoading(true);
    setDetailOrder(null);
    setDetailOrder(await api.get<FullOrder>(`/orders/${order.id}`));
    setDetailLoading(false);
  }

  async function cycleStatus(order: Order, e: React.MouseEvent) {
    e.stopPropagation();
    const next = STATUS_CYCLE[order.status];
    await api.put(`/orders/${order.id}`, { status: next });
    setOrders((prev) => prev.map((o) => o.id === order.id ? { ...o, status: next } : o));
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    try {
      await api.delete(`/orders/${deleteTarget.id}`);
      setDeleteTarget(null);
      setOrders((prev) => prev.filter((o) => o.id !== deleteTarget.id));
    } catch (e) {
      alert(e instanceof ApiError ? e.message : "删除失败");
    }
  }

  /* ── Derived filter options ── */
  const uniqueCustomers = Array.from(
    new Map(orders.map((o) => [o.customer.id, o.customer])).values()
  ).sort((a, b) => a.company.localeCompare(b.company));

  const uniqueProducts = Array.from(
    new Map(orders.map((o) => [o.product.id, o.product])).values()
  ).sort((a, b) => a.name.localeCompare(b.name));

  const hasExtraFilter = filterCustomer || filterProduct || filterDateFrom || filterDateTo;

  function clearExtraFilters() {
    setFilterCustomer(""); setFilterProduct("");
    setFilterDateFrom(""); setFilterDateTo("");
  }

  const displayed = orders.filter((o) => {
    if (filter !== "ALL" && o.status !== filter) return false;
    if (filterCustomer && o.customer.id !== filterCustomer) return false;
    if (filterProduct  && o.product.id  !== filterProduct)  return false;
    if (filterDateFrom) {
      const created = o.created_at.slice(0, 10);
      if (created < filterDateFrom) return false;
    }
    if (filterDateTo) {
      const created = o.created_at.slice(0, 10);
      if (created > filterDateTo) return false;
    }
    return true;
  });

  const counts: Record<OrderStatus | "ALL", number> = {
    ALL:       orders.length,
    PENDING:   orders.filter((o) => o.status === "PENDING").length,
    PRODUCING: orders.filter((o) => o.status === "PRODUCING").length,
    DONE:      orders.filter((o) => o.status === "DONE").length,
  };

  return (
    <>
      {/* Sticky header */}
      <header className="sticky top-0 z-40 bg-white border-b border-slate-200 shadow-sm">
        {/* 手机端：两行布局 */}
        <div className="md:hidden">
          <div className="px-4 flex items-center justify-between h-14">
            <h1 className="text-base font-semibold text-slate-800">订单管理</h1>
            <button
              onClick={() => router.push("/orders/new")}
              className="inline-flex items-center gap-1 bg-blue-600 hover:bg-blue-700 active:scale-95 text-white text-sm font-medium px-3 py-1.5 rounded-lg transition-all shadow-sm shadow-blue-200"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
              </svg>
              新建订单
            </button>
          </div>
          <nav className="flex items-center border-t border-slate-100 px-2 overflow-x-auto">
            {FILTER_TABS.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setFilter(tab.key)}
                className={`relative flex-shrink-0 h-10 px-4 text-sm font-medium transition-colors ${
                  filter === tab.key ? "text-blue-600" : "text-slate-500"
                }`}
              >
                {tab.label}
                {counts[tab.key] > 0 && (
                  <span className={`ml-1 text-xs px-1.5 py-0.5 rounded-full font-semibold ${
                    filter === tab.key ? "bg-blue-100 text-blue-600" : "bg-slate-100 text-slate-500"
                  }`}>
                    {counts[tab.key]}
                  </span>
                )}
                {filter === tab.key && (
                  <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-blue-600 rounded-full" />
                )}
              </button>
            ))}
          </nav>
        </div>

        {/* 桌面端：单行布局 */}
        <div className="hidden md:flex px-8 items-center h-14 gap-6">
          <h1 className="text-base font-semibold text-slate-800 shrink-0">订单管理</h1>
          <nav className="flex items-center h-14 gap-1 flex-1">
            {FILTER_TABS.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setFilter(tab.key)}
                className={`relative h-full px-4 text-sm font-medium transition-colors ${
                  filter === tab.key ? "text-blue-600" : "text-slate-500 hover:text-slate-800"
                }`}
              >
                {tab.label}
                {counts[tab.key] > 0 && (
                  <span className={`ml-1.5 text-xs px-1.5 py-0.5 rounded-full font-semibold ${
                    filter === tab.key ? "bg-blue-100 text-blue-600" : "bg-slate-100 text-slate-500"
                  }`}>
                    {counts[tab.key]}
                  </span>
                )}
                {filter === tab.key && (
                  <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-blue-600 rounded-full" />
                )}
              </button>
            ))}
          </nav>
          <button
            onClick={() => router.push("/orders/new")}
            className="inline-flex items-center gap-1.5 bg-blue-600 hover:bg-blue-700 active:scale-95 text-white text-sm font-medium px-4 py-2 rounded-lg transition-all shadow-sm shadow-blue-200 shrink-0"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
            </svg>
            新建订单
          </button>
        </div>
      </header>

      {/* Filter bar */}
      <div className="bg-white border-b border-slate-100 px-4 md:px-8 py-2.5 flex items-center gap-2 md:gap-3 overflow-x-auto">
        <select
          value={filterCustomer}
          onChange={(e) => setFilterCustomer(e.target.value)}
          className="h-8 flex-shrink-0 rounded-md border border-slate-200 bg-white px-2.5 text-sm text-slate-700 focus:border-blue-400 focus:outline-none focus:ring-1 focus:ring-blue-400"
        >
          <option value="">全部客户</option>
          {uniqueCustomers.map((c) => <option key={c.id} value={c.id}>{c.company}</option>)}
        </select>
        <select
          value={filterProduct}
          onChange={(e) => setFilterProduct(e.target.value)}
          className="h-8 flex-shrink-0 rounded-md border border-slate-200 bg-white px-2.5 text-sm text-slate-700 focus:border-blue-400 focus:outline-none focus:ring-1 focus:ring-blue-400"
        >
          <option value="">全部产品</option>
          {uniqueProducts.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <div className="hidden md:flex items-center gap-1.5">
          <span className="text-xs text-slate-400 shrink-0">日期</span>
          <input
            type="date"
            value={filterDateFrom}
            onChange={(e) => setFilterDateFrom(e.target.value)}
            className="h-8 rounded-md border border-slate-200 bg-white px-2 text-sm text-slate-700 focus:border-blue-400 focus:outline-none focus:ring-1 focus:ring-blue-400"
          />
          <span className="text-xs text-slate-300">—</span>
          <input
            type="date"
            value={filterDateTo}
            onChange={(e) => setFilterDateTo(e.target.value)}
            className="h-8 rounded-md border border-slate-200 bg-white px-2 text-sm text-slate-700 focus:border-blue-400 focus:outline-none focus:ring-1 focus:ring-blue-400"
          />
        </div>
        {hasExtraFilter && (
          <button
            onClick={clearExtraFilters}
            className="h-8 flex-shrink-0 px-2.5 rounded-md text-xs text-slate-500 hover:text-red-500 border border-slate-200 hover:border-red-200 transition-colors"
          >
            清除筛选
          </button>
        )}
      </div>

      <main className="flex-1 px-4 md:px-8 py-4 md:py-6">
        {loading ? (
          <div className="py-16 text-center text-sm text-slate-400">加载中…</div>
        ) : displayed.length === 0 ? (
          <div className="py-16 text-center">
            <p className="text-slate-400 text-sm">
              {filter === "ALL" ? "暂无订单" : `暂无「${STATUS_LABEL[filter as OrderStatus]}」订单`}
            </p>
          </div>
        ) : (
          <>
            {/* 手机端：卡片列表 */}
            <div className="md:hidden space-y-3">
              {displayed.map((order) => {
                const specEntries = Object.entries(order.spec_params ?? {});
                return (
                  <div
                    key={order.id}
                    onClick={() => openDetail(order)}
                    className="bg-white rounded-xl border border-slate-200 shadow-sm px-4 py-3.5 cursor-pointer active:bg-slate-50 transition-colors"
                  >
                    <div className="flex items-start justify-between gap-2 mb-2">
                      <span className="font-mono text-xs text-slate-500">
                        <span className="text-slate-300">ORD-</span>
                        <span className="text-slate-700 font-semibold">{order.order_no.replace("ORD-", "")}</span>
                      </span>
                      <button
                        onClick={(e) => cycleStatus(order, e)}
                        className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold flex-shrink-0 ${STATUS_STYLE[order.status]}`}
                      >
                        {STATUS_LABEL[order.status]}
                      </button>
                    </div>
                    <div className="flex items-baseline justify-between gap-2">
                      <div className="min-w-0">
                        <p className="text-[11px] text-slate-400 leading-tight">{order.product.category.name}</p>
                        <p className="text-sm font-semibold text-slate-800 truncate">{order.product.name}</p>
                      </div>
                      <span className="text-sm font-medium text-slate-700 flex-shrink-0">
                        {order.quantity}<span className="text-xs text-slate-400 ml-0.5">{order.unit}</span>
                      </span>
                    </div>
                    <div className="mt-2 flex items-center justify-between gap-2">
                      <span className="text-sm text-slate-600">{order.customer.company}</span>
                      {specEntries.length > 0 && (
                        <div className="flex gap-1 flex-wrap justify-end">
                          {specEntries.slice(0, 3).map(([k, v]) => (
                            <span key={k} className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 text-xs whitespace-nowrap">
                              {k}·{v}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
              <p className="text-xs text-slate-400 text-center pt-1">显示 {displayed.length} / {orders.length} 个订单</p>
            </div>

            {/* 桌面端：表格 */}
            <div className="hidden md:block bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
              <table className="w-full text-sm table-fixed">
                <colgroup>
                  <col className="w-44" />
                  <col className="w-32" />
                  <col className="w-48" />
                  <col />
                  <col className="w-24" />
                  <col className="w-28" />
                  <col className="w-28" />
                </colgroup>
                <thead>
                  <tr className="bg-slate-50 border-b border-slate-100">
                    {["订单号", "客户", "产品", "规格参数", "数量", "状态", ""].map((h) => (
                      <th key={h} className="text-left px-5 py-3.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-50">
                  {displayed.map((order) => {
                    const specEntries = Object.entries(order.spec_params ?? {});
                    return (
                      <tr
                        key={order.id}
                        onClick={() => openDetail(order)}
                        className="hover:bg-blue-50/30 transition-colors cursor-pointer group"
                      >
                        <td className="px-5 py-4">
                          <span className="font-mono text-xs">
                            <span className="text-slate-400">ORD-</span>
                            <span className="text-slate-800 font-semibold">{order.order_no.replace("ORD-", "")}</span>
                          </span>
                        </td>
                        <td className="px-5 py-4">
                          <span className="text-slate-700 font-medium truncate block">{order.customer.company}</span>
                        </td>
                        <td className="px-5 py-4">
                          <p className="text-xs font-medium text-slate-400 uppercase tracking-wide leading-tight truncate">{order.product.category.name}</p>
                          <p className="text-sm font-medium text-slate-800 mt-0.5 truncate">{order.product.name}</p>
                        </td>
                        <td className="px-5 py-4">
                          {specEntries.length === 0 ? (
                            <span className="text-slate-300">—</span>
                          ) : (
                            <div className="flex flex-wrap gap-1">
                              {specEntries.map(([k, v]) => (
                                <span key={k} className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 text-xs whitespace-nowrap">
                                  <span className="text-slate-400">{k}</span>
                                  <span className="mx-0.5 text-slate-300">·</span>
                                  <span className="font-medium">{v}</span>
                                </span>
                              ))}
                            </div>
                          )}
                        </td>
                        <td className="px-5 py-4">
                          <span className="text-slate-700 font-medium">{order.quantity}</span>
                          <span className="text-slate-400 text-xs ml-1">{order.unit}</span>
                        </td>
                        <td className="px-5 py-4" onClick={(e) => e.stopPropagation()}>
                          <button
                            onClick={(e) => cycleStatus(order, e)}
                            className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold transition-opacity hover:opacity-75 ${STATUS_STYLE[order.status]}`}
                          >
                            {STATUS_LABEL[order.status]}
                          </button>
                        </td>
                        <td className="px-5 py-4" onClick={(e) => e.stopPropagation()}>
                          <div className="flex items-center justify-end gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
                            <button
                              onClick={() => router.push(`/orders/${order.id}`)}
                              className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-md border border-slate-200 bg-white text-slate-600 hover:text-blue-600 hover:border-blue-300 text-xs font-medium transition-colors"
                            >
                              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                <path strokeLinecap="round" strokeLinejoin="round" d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L6.832 19.82a4.5 4.5 0 0 1-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 0 1 1.13-1.897L16.863 4.487Z" />
                              </svg>
                              编辑
                            </button>
                            <button
                              onClick={() => setDeleteTarget(order)}
                              className="p-1.5 rounded-md border border-slate-200 bg-white text-slate-400 hover:text-red-500 hover:border-red-200 transition-colors"
                            >
                              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                <path strokeLinecap="round" strokeLinejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
                              </svg>
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <div className="px-5 py-3.5 bg-slate-50 border-t border-slate-100">
                <span className="text-xs text-slate-400">显示 {displayed.length} / {orders.length} 个订单</span>
              </div>
            </div>
          </>
        )}
      </main>

      {/* 订单详情 */}
      <Dialog open={detailLoading || detailOrder !== null} onOpenChange={(o) => { if (!o) { setDetailOrder(null); setDetailLoading(false); } }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-3">
              {detailOrder && (
                <>
                  <span className="font-mono text-sm font-semibold text-slate-700">{detailOrder.order_no}</span>
                  <span className={`text-[11px] px-2 py-0.5 rounded-full border font-semibold ${STATUS_STYLE[detailOrder.status]}`}>
                    {STATUS_LABEL[detailOrder.status]}
                  </span>
                </>
              )}
              {detailLoading && <span className="text-sm text-slate-400">加载中…</span>}
            </DialogTitle>
          </DialogHeader>
          {detailLoading || !detailOrder ? (
            <div className="py-10 flex items-center justify-center">
              <p className="text-sm text-slate-400">加载中…</p>
            </div>
          ) : (
            <div className="space-y-5 pt-1">
              <section>
                <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">基本信息</h4>
                <div className="space-y-1.5">
                  <DetailRow label="客户" value={detailOrder.customer.company} />
                  <DetailRow label="联系人" value={detailOrder.customer.contact} />
                  <DetailRow label="产品" value={`${detailOrder.product.category.name} · ${detailOrder.product.name}`} />
                  <DetailRow label="数量" value={`${detailOrder.quantity} ${detailOrder.unit}`} />
                  <DetailRow label="创建日期" value={fmtDate(detailOrder.created_at)} />
                </div>
              </section>
              {Object.keys(detailOrder.spec_params ?? {}).length > 0 && (
                <section>
                  <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">规格参数</h4>
                  <div className="flex flex-wrap gap-1.5">
                    {Object.entries(detailOrder.spec_params).map(([k, v]) => (
                      <span key={k} className="px-2.5 py-1 rounded-lg bg-slate-100 text-slate-600 text-xs font-medium">{k}: {v}</span>
                    ))}
                  </div>
                </section>
              )}
              {(detailOrder.formula || detailOrder.formula_snapshot) && (() => {
                const materials = getMaterials(detailOrder);
                return (
                  <section>
                    <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">配方</h4>
                    {detailOrder.formula && <p className="text-sm text-slate-700 font-semibold mb-2">{detailOrder.formula.name}</p>}
                    {materials ? (
                      <pre className="text-xs text-slate-600 whitespace-pre-wrap leading-relaxed bg-slate-50 rounded-lg px-3 py-2.5 border border-slate-200 font-sans">{materials}</pre>
                    ) : (
                      <p className="text-xs text-slate-400 italic">暂无原材料明细</p>
                    )}
                  </section>
                );
              })()}
              {detailOrder.extra_notes && (
                <section>
                  <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">额外要求</h4>
                  <p className="text-sm text-slate-600 whitespace-pre-wrap leading-relaxed bg-slate-50 rounded-lg px-3 py-2">{detailOrder.extra_notes}</p>
                </section>
              )}
              <div className="flex justify-end pt-1">
                <Button
                  onClick={() => { setDetailOrder(null); router.push(`/orders/${detailOrder.id}`); }}
                  className="bg-blue-600 hover:bg-blue-700 text-white text-sm"
                >
                  编辑订单
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* 删除确认 */}
      <Dialog open={deleteTarget !== null} onOpenChange={(o) => !o && setDeleteTarget(null)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader><DialogTitle className="text-slate-800">确认删除</DialogTitle></DialogHeader>
          <p className="text-sm text-slate-500 py-2">
            确定删除订单「<span className="font-medium text-slate-700">{deleteTarget?.order_no}</span>」吗？此操作不可撤销。
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)} className="border-slate-200 text-slate-600">取消</Button>
            <Button onClick={handleDelete} className="bg-red-500 hover:bg-red-600 text-white border-0">删除</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-2 text-sm">
      <span className="text-slate-400 shrink-0 w-16">{label}</span>
      <span className="text-slate-700">{value}</span>
    </div>
  );
}
