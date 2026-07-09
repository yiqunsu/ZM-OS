"use client";

import { useEffect, useState } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { api, ApiError } from "@/lib/api";

/* ─── 类型 ─── */
interface Category { id: string; name: string; desc: string | null }
interface Product  { id: string; name: string; category_id: string; category: Category }

const AVATAR_COLORS = [
  "bg-violet-100 text-violet-700", "bg-pink-100 text-pink-700",
  "bg-amber-100 text-amber-700",   "bg-teal-100 text-teal-700",
  "bg-indigo-100 text-indigo-700", "bg-rose-100 text-rose-700",
];
function avatarColor(id: string) {
  return AVATAR_COLORS[(id.charCodeAt(0) + id.charCodeAt(id.length - 1)) % AVATAR_COLORS.length];
}

/* ─── 通用小型 Dialog ─── */
function ConfirmDeleteDialog({
  open, name, extra, onCancel, onConfirm,
}: { open: boolean; name: string; extra?: string; onCancel: () => void; onConfirm: () => void }) {
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onCancel()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader><DialogTitle className="text-slate-800">确认删除</DialogTitle></DialogHeader>
        <p className="text-sm text-slate-500 py-2">
          确定删除「<span className="font-medium text-slate-700">{name}</span>」吗？
          {extra && <span className="block mt-1 text-xs text-slate-400">{extra}</span>}
        </p>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel} className="border-slate-200 text-slate-600">取消</Button>
          <Button onClick={onConfirm} className="bg-red-500 hover:bg-red-600 text-white border-0">删除</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/* ══════════════════════════════
   产品大类区块
══════════════════════════════ */
function CategorySection({
  categories, onReload,
}: { categories: Category[]; onReload: () => void }) {
  const [dialogOpen, setDialogOpen]       = useState(false);
  const [deleteTarget, setDeleteTarget]   = useState<Category | null>(null);
  const [editing, setEditing]             = useState<Category | null>(null);
  const [form, setForm]                   = useState({ name: "", desc: "" });
  const [saving, setSaving]               = useState(false);
  const [error, setError]                 = useState("");

  function openCreate() { setEditing(null); setForm({ name: "", desc: "" }); setError(""); setDialogOpen(true); }
  function openEdit(c: Category) { setEditing(c); setForm({ name: c.name, desc: c.desc ?? "" }); setError(""); setDialogOpen(true); }

  async function handleSave() {
    if (!form.name.trim()) { setError("大类名称为必填项"); return; }
    setSaving(true); setError("");
    try {
      if (editing) await api.put(`/product-categories/${editing.id}`, form);
      else await api.post("/product-categories", form);
      setDialogOpen(false); onReload();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "保存失败");
    } finally { setSaving(false); }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    try {
      await api.delete(`/product-categories/${deleteTarget.id}`);
      setDeleteTarget(null); onReload();
    } catch (e) {
      alert(e instanceof ApiError ? e.message : "删除失败");
    }
  }

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
      <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-slate-800">产品大类</h2>
          <p className="text-sm text-slate-500 mt-0.5">
            共 <span className="text-blue-600 font-semibold">{categories.length}</span> 个大类
          </p>
        </div>
        <button
          onClick={openCreate}
          className="inline-flex items-center gap-1.5 bg-blue-600 hover:bg-blue-700 active:scale-95 text-white text-sm font-medium px-4 py-2 rounded-lg transition-all shadow-sm shadow-blue-200"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
          </svg>
          新增大类
        </button>
      </div>

      {categories.length === 0 ? (
        <div className="px-6 py-10 text-center">
          <p className="text-slate-400 text-sm">暂无产品大类，点击右上角新增</p>
        </div>
      ) : (
        <div className="flex flex-wrap gap-3 px-6 py-4">
          {categories.map((c) => (
            <div key={c.id} className="group flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-200 bg-slate-50 hover:border-blue-200 hover:bg-blue-50/50 transition-colors">
              <div className={`w-7 h-7 rounded-md flex items-center justify-center text-xs font-bold shrink-0 ${avatarColor(c.id)}`}>
                {c.name.charAt(0)}
              </div>
              <div className="min-w-0">
                <p className="text-sm font-medium text-slate-800 leading-tight">{c.name}</p>
                {c.desc && <p className="text-xs text-slate-400 truncate max-w-[120px]">{c.desc}</p>}
              </div>
              <div className="flex gap-1 ml-1 opacity-0 group-hover:opacity-100 transition-opacity">
                <button
                  onClick={() => openEdit(c)}
                  className="p-1 rounded text-slate-400 hover:text-blue-600 hover:bg-blue-100 transition-colors"
                  title="编辑"
                >
                  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L6.832 19.82a4.5 4.5 0 0 1-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 0 1 1.13-1.897L16.863 4.487Z" />
                  </svg>
                </button>
                <button
                  onClick={() => setDeleteTarget(c)}
                  className="p-1 rounded text-slate-400 hover:text-red-500 hover:bg-red-50 transition-colors"
                  title="删除"
                >
                  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
                  </svg>
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 新增/编辑 */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader><DialogTitle className="text-slate-800">{editing ? "编辑大类" : "新增产品大类"}</DialogTitle></DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-1.5">
              <Label className="text-slate-700 text-sm font-medium">名称 <span className="text-red-400">*</span></Label>
              <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="如：PE膜" className="border-slate-200 focus:border-blue-400 focus:ring-blue-400" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-slate-700 text-sm font-medium">描述</Label>
              <Input value={form.desc} onChange={(e) => setForm({ ...form, desc: e.target.value })} placeholder="可选" className="border-slate-200 focus:border-blue-400 focus:ring-blue-400" />
            </div>
            {error && <p className="text-sm text-red-500 bg-red-50 border border-red-100 rounded-md px-3 py-2">{error}</p>}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)} className="border-slate-200 text-slate-600">取消</Button>
            <Button onClick={handleSave} disabled={saving} className="bg-blue-600 hover:bg-blue-700 text-white">{saving ? "保存中…" : "保存"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDeleteDialog
        open={deleteTarget !== null}
        name={deleteTarget?.name ?? ""}
        extra="若该大类下存在产品，则无法删除"
        onCancel={() => setDeleteTarget(null)}
        onConfirm={handleDelete}
      />
    </div>
  );
}

/* ══════════════════════════════
   产品列表区块
══════════════════════════════ */
function ProductSection({
  products, categories, onReload,
}: { products: Product[]; categories: Category[]; onReload: () => void }) {
  const [dialogOpen, setDialogOpen]         = useState(false);
  const [deleteTarget, setDeleteTarget]     = useState<Product | null>(null);
  const [editing, setEditing]               = useState<Product | null>(null);
  const [form, setForm]                     = useState({ name: "", category_id: "" });
  const [saving, setSaving]                 = useState(false);
  const [error, setError]                   = useState("");
  const [selected, setSelected]             = useState<Set<string>>(new Set());
  const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false);
  const [bulkDeleting, setBulkDeleting]     = useState(false);
  const [filterCategoryId, setFilterCategoryId] = useState("");

  const filtered = filterCategoryId ? products.filter((p) => p.category_id === filterCategoryId) : products;
  const allChecked = filtered.length > 0 && filtered.every((p) => selected.has(p.id));
  const indeterminate = filtered.some((p) => selected.has(p.id)) && !allChecked;

  function toggleAll() {
    if (allChecked) {
      setSelected((prev) => { const next = new Set(prev); filtered.forEach((p) => next.delete(p.id)); return next; });
    } else {
      setSelected((prev) => new Set([...prev, ...filtered.map((p) => p.id)]));
    }
  }
  function toggleOne(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function openCreate() { setEditing(null); setForm({ name: "", category_id: categories[0]?.id ?? "" }); setError(""); setDialogOpen(true); }
  function openEdit(p: Product) { setEditing(p); setForm({ name: p.name, category_id: p.category_id }); setError(""); setDialogOpen(true); }

  async function handleSave() {
    if (!form.name.trim() || !form.category_id) { setError("产品名称和所属大类为必填项"); return; }
    setSaving(true); setError("");
    try {
      if (editing) await api.put(`/products/${editing.id}`, form);
      else await api.post("/products", form);
      setDialogOpen(false); onReload();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "保存失败");
    } finally { setSaving(false); }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    try {
      await api.delete(`/products/${deleteTarget.id}`);
      setDeleteTarget(null); onReload();
    } catch (e) {
      alert(e instanceof ApiError ? e.message : "删除失败");
    }
  }

  async function handleBulkDelete() {
    setBulkDeleting(true);
    const ids = [...selected];
    const errors: string[] = [];
    for (const id of ids) {
      try {
        await api.delete(`/products/${id}`);
      } catch {
        const p = products.find((x) => x.id === id);
        errors.push(p?.name ?? id);
      }
    }
    setBulkDeleting(false);
    setBulkDeleteOpen(false);
    setSelected(new Set());
    onReload();
    if (errors.length > 0) alert(`以下产品删除失败（存在关联订单或配方）：\n${errors.join("、")}`);
  }

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
      <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3 flex-1 flex-wrap">
          <div>
            <h2 className="text-base font-semibold text-slate-800">产品</h2>
            <p className="text-sm text-slate-500 mt-0.5">
              显示 <span className="text-blue-600 font-semibold">{filtered.length}</span> / {products.length} 个产品
            </p>
          </div>
          <select
            value={filterCategoryId}
            onChange={(e) => setFilterCategoryId(e.target.value)}
            className="h-8 rounded-md border border-slate-200 bg-white px-2.5 text-sm text-slate-700 focus:border-blue-400 focus:outline-none focus:ring-1 focus:ring-blue-400"
          >
            <option value="">全部大类</option>
            {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
        <div className="flex items-center gap-2">
          {selected.size > 0 && (
            <button
              onClick={() => setBulkDeleteOpen(true)}
              className="inline-flex items-center gap-1.5 bg-red-500 hover:bg-red-600 active:scale-95 text-white text-sm font-medium px-4 py-2 rounded-lg transition-all"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
              </svg>
              删除所选 ({selected.size})
            </button>
          )}
          <button
            onClick={openCreate}
            disabled={categories.length === 0}
            className="inline-flex items-center gap-1.5 bg-blue-600 hover:bg-blue-700 active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium px-4 py-2 rounded-lg transition-all shadow-sm shadow-blue-200"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
            </svg>
            新增产品
          </button>
        </div>
      </div>

      {filtered.length === 0 ? (
        <div className="px-6 py-10 text-center">
          <p className="text-slate-400 text-sm">
            {categories.length === 0 ? "请先添加产品大类" : filterCategoryId ? "该大类下暂无产品" : "暂无产品"}
          </p>
        </div>
      ) : (
        <>
          {/* 手机端：卡片列表 */}
          <div className="md:hidden divide-y divide-slate-100">
            {filtered.map((p) => (
              <div key={p.id} className={`px-4 py-3.5 flex items-center gap-3 ${selected.has(p.id) ? "bg-blue-50/60" : ""}`}>
                <input
                  type="checkbox"
                  checked={selected.has(p.id)}
                  onChange={() => toggleOne(p.id)}
                  className="w-4 h-4 rounded border-slate-300 text-blue-600 cursor-pointer accent-blue-600 shrink-0"
                />
                <div className={`w-9 h-9 rounded-lg flex items-center justify-center font-bold text-sm shrink-0 ${avatarColor(p.id)}`}>
                  {p.name.charAt(0)}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="font-medium text-slate-800">{p.name}</p>
                  <span className="inline-flex items-center mt-0.5 px-2 py-0.5 rounded-md bg-blue-50 text-blue-700 text-xs font-medium">{p.category.name}</span>
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                  <button onClick={() => openEdit(p)} className="p-2 rounded-lg border border-slate-200 text-slate-500 hover:text-blue-600 hover:border-blue-300 transition-colors">
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L6.832 19.82a4.5 4.5 0 0 1-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 0 1 1.13-1.897L16.863 4.487Z" /></svg>
                  </button>
                  <button onClick={() => setDeleteTarget(p)} className="p-2 rounded-lg border border-slate-200 text-slate-400 hover:text-red-500 hover:border-red-200 transition-colors">
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" /></svg>
                  </button>
                </div>
              </div>
            ))}
          </div>

          {/* 桌面端：表格 */}
          <table className="hidden md:table w-full text-sm table-fixed">
            <colgroup><col className="w-12" /><col /><col className="w-36" /><col className="w-36" /></colgroup>
            <thead>
              <tr className="bg-slate-50 border-b border-slate-100">
                <th className="px-4 py-3.5">
                  <input type="checkbox" checked={allChecked} ref={(el) => { if (el) el.indeterminate = indeterminate; }} onChange={toggleAll} className="w-4 h-4 rounded border-slate-300 text-blue-600 cursor-pointer accent-blue-600" />
                </th>
                {["产品名称", "所属大类", ""].map((h) => (
                  <th key={h} className="text-left px-6 py-3.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {filtered.map((p) => (
                <tr key={p.id} className={`transition-colors group ${selected.has(p.id) ? "bg-blue-50/60" : "hover:bg-blue-50/30"}`}>
                  <td className="px-4 py-4">
                    <input type="checkbox" checked={selected.has(p.id)} onChange={() => toggleOne(p.id)} className="w-4 h-4 rounded border-slate-300 text-blue-600 cursor-pointer accent-blue-600" />
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-3">
                      <div className={`w-8 h-8 rounded-lg flex items-center justify-center font-bold text-xs shrink-0 ${avatarColor(p.id)}`}>{p.name.charAt(0)}</div>
                      <span className="font-medium text-slate-800 truncate">{p.name}</span>
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <span className="inline-flex items-center px-2 py-0.5 rounded-md bg-blue-50 text-blue-700 text-xs font-medium">{p.category.name}</span>
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex items-center justify-end gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button onClick={() => openEdit(p)} className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-md border border-slate-200 bg-white text-slate-600 hover:text-blue-600 hover:border-blue-300 text-xs font-medium transition-colors">
                        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L6.832 19.82a4.5 4.5 0 0 1-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 0 1 1.13-1.897L16.863 4.487Z" /></svg>
                        编辑
                      </button>
                      <button onClick={() => setDeleteTarget(p)} className="p-1.5 rounded-md border border-slate-200 bg-white text-slate-400 hover:text-red-500 hover:border-red-200 transition-colors">
                        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" /></svg>
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="px-6 py-3.5 bg-slate-50 border-t border-slate-100 flex items-center justify-between">
            <span className="text-xs text-slate-400">显示 {filtered.length} / {products.length} 个产品</span>
            {selected.size > 0 && <span className="text-xs text-blue-600 font-medium">已选 {selected.size} 项</span>}
          </div>
        </>
      )}

      {/* 新增/编辑 */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader><DialogTitle className="text-slate-800">{editing ? "编辑产品" : "新增产品"}</DialogTitle></DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-1.5">
              <Label className="text-slate-700 text-sm font-medium">产品名称 <span className="text-red-400">*</span></Label>
              <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="如：透明 PE 拉伸膜" className="border-slate-200 focus:border-blue-400 focus:ring-blue-400" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-slate-700 text-sm font-medium">所属大类 <span className="text-red-400">*</span></Label>
              <select
                value={form.category_id}
                onChange={(e) => setForm({ ...form, category_id: e.target.value })}
                className="w-full h-9 rounded-md border border-slate-200 bg-white px-3 text-sm text-slate-800 focus:border-blue-400 focus:outline-none focus:ring-1 focus:ring-blue-400"
              >
                <option value="">请选择</option>
                {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
            {error && <p className="text-sm text-red-500 bg-red-50 border border-red-100 rounded-md px-3 py-2">{error}</p>}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)} className="border-slate-200 text-slate-600">取消</Button>
            <Button onClick={handleSave} disabled={saving} className="bg-blue-600 hover:bg-blue-700 text-white">{saving ? "保存中…" : "保存"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 单条删除 */}
      <ConfirmDeleteDialog
        open={deleteTarget !== null}
        name={deleteTarget?.name ?? ""}
        extra="若该产品存在关联订单或配方，则无法删除"
        onCancel={() => setDeleteTarget(null)}
        onConfirm={handleDelete}
      />

      {/* 批量删除 */}
      <Dialog open={bulkDeleteOpen} onOpenChange={(o) => !o && setBulkDeleteOpen(false)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader><DialogTitle className="text-slate-800">批量删除</DialogTitle></DialogHeader>
          <p className="text-sm text-slate-500 py-2">
            确定删除选中的 <span className="font-semibold text-slate-700">{selected.size}</span> 个产品吗？
            <span className="block mt-1 text-xs text-slate-400">存在关联订单或配方的产品将跳过并提示。</span>
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setBulkDeleteOpen(false)} className="border-slate-200 text-slate-600">取消</Button>
            <Button onClick={handleBulkDelete} disabled={bulkDeleting} className="bg-red-500 hover:bg-red-600 text-white border-0">
              {bulkDeleting ? "删除中…" : "确认删除"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

/* ══════════════════════════════
   主组件
══════════════════════════════ */
export default function ProductTab() {
  const [categories, setCategories] = useState<Category[]>([]);
  const [products, setProducts]     = useState<Product[]>([]);
  const [loading, setLoading]       = useState(true);

  async function load() {
    setLoading(true);
    const [c, p] = await Promise.all([
      api.get<Category[]>("/product-categories"),
      api.get<Product[]>("/products"),
    ]);
    setCategories(c);
    setProducts(p);
    setLoading(false);
  }

  useEffect(() => { load(); }, []);

  if (loading) {
    return <div className="py-16 text-center text-sm text-slate-400">加载中…</div>;
  }

  return (
    <div className="space-y-6">
      <CategorySection categories={categories} onReload={load} />
      <ProductSection   products={products} categories={categories} onReload={load} />
    </div>
  );
}
