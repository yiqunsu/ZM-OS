"use client";

import { useEffect, useState } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { api, ApiError } from "@/lib/api";

/* ─── 类型 ─── */
interface Category   { id: string; name: string }
interface Product    { id: string; name: string; category: Category }
interface FormulaRef { id: string; name: string }

interface Formula {
  id: string;
  name: string;
  product_id: string;
  product: Product;
  spec_params: Record<string, string>;
  materials: string;   // 纯文本
  source_id: string | null;
  source: FormulaRef | null;
  notes: string | null;
}

interface SpecParam { key: string; value: string; [k: string]: string }

interface FormState {
  name: string;
  product_id: string;
  specParams: SpecParam[];
  materials: string;   // 纯文本
  source_id: string;
  notes: string;
}

const emptyForm: FormState = {
  name: "", product_id: "",
  specParams: [{ key: "", value: "" }],
  materials: "", source_id: "", notes: "",
};

function objToSpecParamRows(obj: Record<string, string>): SpecParam[] {
  const entries = Object.entries(obj ?? {});
  return entries.length
    ? entries.map(([key, value]) => ({ key, value: String(value) }))
    : [{ key: "", value: "" }];
}

function specParamsToObj(rows: SpecParam[]): Record<string, string> {
  const obj: Record<string, string> = {};
  rows.forEach(({ key, value }) => { if (key.trim()) obj[key.trim()] = value.trim(); });
  return obj;
}

/* ─── 规格参数动态行编辑器 ─── */
function SpecParamRows({
  rows, onChange,
}: { rows: SpecParam[]; onChange: (rows: SpecParam[]) => void }) {
  function update(i: number, field: "key" | "value", val: string) {
    onChange(rows.map((r, idx) => (idx === i ? { ...r, [field]: val } : r)));
  }
  function remove(i: number) { onChange(rows.filter((_, idx) => idx !== i)); }
  function add() { onChange([...rows, { key: "", value: "" }]); }

  return (
    <div className="space-y-2">
      {rows.map((row, i) => (
        <div key={i} className="flex items-center gap-2">
          <Input
            value={row.key}
            onChange={(e) => update(i, "key", e.target.value)}
            placeholder="参数名（如：厚度）"
            className="w-36 shrink-0 border-slate-200 focus:border-blue-400 focus:ring-blue-400 h-8 text-sm"
          />
          <Input
            value={row.value}
            onChange={(e) => update(i, "value", e.target.value)}
            placeholder="数值（如：50μm）"
            className="flex-1 border-slate-200 focus:border-blue-400 focus:ring-blue-400 h-8 text-sm"
          />
          <button
            type="button"
            onClick={() => remove(i)}
            disabled={rows.length === 1}
            className="p-1.5 rounded text-slate-300 hover:text-red-400 disabled:opacity-30 transition-colors shrink-0"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={add}
        className="text-xs text-blue-600 hover:text-blue-700 font-medium flex items-center gap-1 mt-1"
      >
        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
        </svg>
        添加规格参数
      </button>
    </div>
  );
}

/* ─── 主组件 ─── */
export default function FormulaTab() {
  const [formulas, setFormulas] = useState<Formula[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading]   = useState(true);

  const [dialogOpen, setDialogOpen]             = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [editing, setEditing]   = useState<Formula | null>(null);
  const [deleting, setDeleting] = useState<Formula | null>(null);
  const [form, setForm]         = useState<FormState>(emptyForm);
  const [saving, setSaving]     = useState(false);
  const [error, setError]       = useState("");
  const [viewingNotes, setViewingNotes]         = useState<string | null>(null);
  const [viewingMaterials, setViewingMaterials] = useState<string | null>(null);

  /* ── Filters ── */
  const [filterCategoryId, setFilterCategoryId] = useState("");
  const [filterProductId,  setFilterProductId]  = useState("");

  const categories = Array.from(new Map(products.map((p) => [p.category.id, p.category])).values())
    .sort((a, b) => a.name.localeCompare(b.name));

  const productsInCategory = filterCategoryId
    ? products.filter((p) => p.category.id === filterCategoryId)
    : products;

  const filteredFormulas = formulas.filter((f) => {
    if (filterCategoryId && f.product.category.id !== filterCategoryId) return false;
    if (filterProductId  && f.product_id !== filterProductId)            return false;
    return true;
  });

  function handleCategoryChange(catId: string) {
    setFilterCategoryId(catId);
    setFilterProductId(""); // reset product when category changes
  }

  async function load() {
    setLoading(true);
    const [f, p] = await Promise.all([
      api.get<Formula[]>("/formulas"),
      api.get<Product[]>("/products"),
    ]);
    setFormulas(f);
    setProducts(p);
    setLoading(false);
  }
  useEffect(() => { load(); }, []);

  function openCreate() {
    setEditing(null);
    setForm({ ...emptyForm, product_id: products[0]?.id ?? "" });
    setError(""); setDialogOpen(true);
  }

  function openEdit(f: Formula) {
    setEditing(f);
    setForm({
      name:        f.name,
      product_id:  f.product_id,
      specParams:  objToSpecParamRows(f.spec_params),
      materials:   f.materials,
      source_id:   f.source_id ?? "",
      notes:       f.notes ?? "",
    });
    setError(""); setDialogOpen(true);
  }

  async function handleSave() {
    if (!form.name.trim() || !form.product_id) { setError("配方名称和关联产品为必填项"); return; }
    setSaving(true); setError("");
    try {
      const payload = {
        name:        form.name.trim(),
        product_id:  form.product_id,
        spec_params: specParamsToObj(form.specParams),
        materials:   form.materials.trim(),
        source_id:   form.source_id || null,
        notes:       form.notes.trim() || null,
      };
      if (editing) await api.put(`/formulas/${editing.id}`, payload);
      else await api.post("/formulas", payload);
      setDialogOpen(false); await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "保存失败");
    } finally { setSaving(false); }
  }

  async function handleDelete() {
    if (!deleting) return;
    try {
      await api.delete(`/formulas/${deleting.id}`);
      setDeleteDialogOpen(false); setDeleting(null); await load();
    } catch (e) {
      alert(e instanceof ApiError ? e.message : "删除失败");
    }
  }

  const sourceOptions = formulas.filter((f) => f.id !== editing?.id);

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
      {/* Header */}
      <div className="px-4 md:px-6 py-4 md:py-5 border-b border-slate-100">
        {/* 手机端：标题+按钮一行，筛选另起一行 */}
        <div className="flex items-center justify-between gap-3 mb-3 md:mb-0">
          <div>
            <h2 className="text-base font-semibold text-slate-800">配方库</h2>
            {!loading && (
              <p className="text-sm text-slate-500 mt-0.5">
                显示 <span className="text-blue-600 font-semibold">{filteredFormulas.length}</span> / {formulas.length} 个配方
              </p>
            )}
          </div>
          <button
            onClick={openCreate}
            disabled={products.length === 0}
            className="inline-flex items-center gap-1.5 bg-blue-600 hover:bg-blue-700 active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium px-3 md:px-4 py-2 rounded-lg transition-all shadow-sm shadow-blue-200 shrink-0"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
            </svg>
            新增配方
          </button>
        </div>
        {!loading && products.length > 0 && (
          <div className="flex gap-2 flex-wrap">
            <select
              value={filterCategoryId}
              onChange={(e) => handleCategoryChange(e.target.value)}
              className="flex-1 min-w-0 h-8 rounded-md border border-slate-200 bg-white px-2.5 text-sm text-slate-700 focus:border-blue-400 focus:outline-none focus:ring-1 focus:ring-blue-400"
            >
              <option value="">全部大类</option>
              {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            <select
              value={filterProductId}
              onChange={(e) => setFilterProductId(e.target.value)}
              className="flex-1 min-w-0 h-8 rounded-md border border-slate-200 bg-white px-2.5 text-sm text-slate-700 focus:border-blue-400 focus:outline-none focus:ring-1 focus:ring-blue-400"
            >
              <option value="">全部产品</option>
              {productsInCategory.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>
        )}
      </div>

      {/* Table */}
      {loading ? (
        <div className="px-6 py-16 text-center text-sm text-slate-400">加载中…</div>
      ) : filteredFormulas.length === 0 ? (
        <div className="px-6 py-16 text-center">
          <p className="text-slate-400 text-sm">
            {products.length === 0
              ? "请先在「产品」Tab 中添加产品"
              : filterCategoryId || filterProductId
                ? "当前筛选条件下暂无配方"
                : "暂无配方"}
          </p>
          {products.length > 0 && !filterCategoryId && !filterProductId && (
            <button onClick={openCreate} className="mt-3 text-sm text-blue-600 hover:text-blue-700 font-medium">
              + 新增第一个配方
            </button>
          )}
        </div>
      ) : (
        <>
          {/* 手机端：卡片列表 */}
          <div className="md:hidden divide-y divide-slate-100">
            {filteredFormulas.map((f) => {
              const specEntries = Object.entries(f.spec_params ?? {});
              return (
                <div key={f.id} className="px-4 py-3.5">
                  <div className="flex items-start justify-between gap-2 mb-1.5">
                    <div className="min-w-0">
                      <p className="font-semibold text-slate-800">{f.name}</p>
                      {f.source && <p className="text-xs text-slate-400 mt-0.5">衍生自：{f.source.name}</p>}
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <button onClick={() => openEdit(f)} className="p-2 rounded-lg border border-slate-200 text-slate-500 hover:text-blue-600 hover:border-blue-300 transition-colors">
                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L6.832 19.82a4.5 4.5 0 0 1-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 0 1 1.13-1.897L16.863 4.487Z" /></svg>
                      </button>
                      <button onClick={() => { setDeleting(f); setDeleteDialogOpen(true); }} className="p-2 rounded-lg border border-slate-200 text-slate-400 hover:text-red-500 hover:border-red-200 transition-colors">
                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" /></svg>
                      </button>
                    </div>
                  </div>
                  <p className="text-xs text-slate-400">{f.product.category.name}</p>
                  <p className="text-sm text-slate-700 font-medium">{f.product.name}</p>
                  {specEntries.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-1.5">
                      {specEntries.map(([k, v]) => (
                        <span key={k} className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 text-xs whitespace-nowrap">
                          <span className="text-slate-400">{k}</span><span className="mx-0.5 text-slate-300">·</span><span className="font-medium">{v}</span>
                        </span>
                      ))}
                    </div>
                  )}
                  {f.materials?.trim() && (
                    <button onClick={() => setViewingMaterials(f.materials)} className="mt-2 text-left w-full">
                      <span className="text-xs text-slate-500 line-clamp-2 leading-relaxed">{f.materials}</span>
                      <span className="text-xs text-blue-500 mt-0.5 block">查看配方 →</span>
                    </button>
                  )}
                </div>
              );
            })}
          </div>

          {/* 桌面端：表格 */}
          <table className="hidden md:table w-full text-sm table-fixed">
            <colgroup>
              <col className="w-44" /><col className="w-52" /><col className="w-48" /><col /><col className="w-44" /><col className="w-32" />
            </colgroup>
            <thead>
              <tr className="bg-slate-50 border-b border-slate-100">
                {["配方名称", "关联产品", "规格参数", "原材料及比例", "备注", ""].map((h) => (
                  <th key={h} className="text-left px-5 py-3.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {filteredFormulas.map((f) => {
                const specEntries = Object.entries(f.spec_params ?? {});
                return (
                  <tr key={f.id} className="hover:bg-blue-50/30 transition-colors group">
                    <td className="px-5 py-4">
                      <span className="font-semibold text-slate-800 truncate block">{f.name}</span>
                      {f.source && <span className="text-xs text-slate-400 mt-0.5 block truncate">衍生自：{f.source.name}</span>}
                    </td>
                    <td className="px-5 py-4">
                      <p className="text-xs font-medium text-slate-400 uppercase tracking-wide leading-tight truncate">{f.product.category.name}</p>
                      <p className="text-sm font-medium text-slate-800 mt-0.5 truncate">{f.product.name}</p>
                    </td>
                    <td className="px-5 py-4">
                      {specEntries.length === 0 ? <span className="text-slate-300">—</span> : (
                        <div className="flex flex-wrap gap-1">
                          {specEntries.map(([k, v]) => (
                            <span key={k} className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 text-xs whitespace-nowrap">
                              <span className="text-slate-400">{k}</span><span className="mx-0.5 text-slate-300">·</span><span className="font-medium">{v}</span>
                            </span>
                          ))}
                        </div>
                      )}
                    </td>
                    <td className="px-5 py-4">
                      {f.materials?.trim() ? (
                        <button onClick={() => setViewingMaterials(f.materials)} className="w-full text-left group/mat">
                          <span className="block text-xs text-slate-600 leading-relaxed line-clamp-2 group-hover/mat:text-blue-600 transition-colors">{f.materials}</span>
                          <span className="text-xs text-slate-400 group-hover/mat:text-blue-500 mt-0.5 block">点击查看全部 →</span>
                        </button>
                      ) : <span className="text-slate-300">—</span>}
                    </td>
                    <td className="px-5 py-4">
                      {f.notes ? (
                        <button onClick={() => setViewingNotes(f.notes)} className="inline-flex items-center max-w-full px-2 py-0.5 rounded-md bg-slate-100 hover:bg-slate-200 text-slate-600 text-xs transition-colors">
                          <span className="truncate">{f.notes}</span>
                        </button>
                      ) : <span className="text-slate-300">—</span>}
                    </td>
                    <td className="px-5 py-4">
                      <div className="flex items-center justify-end gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button onClick={() => openEdit(f)} className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-md border border-slate-200 bg-white text-slate-600 hover:text-blue-600 hover:border-blue-300 text-xs font-medium transition-colors">
                          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L6.832 19.82a4.5 4.5 0 0 1-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 0 1 1.13-1.897L16.863 4.487Z" /></svg>
                          编辑
                        </button>
                        <button onClick={() => { setDeleting(f); setDeleteDialogOpen(true); }} className="p-1.5 rounded-md border border-slate-200 bg-white text-slate-400 hover:text-red-500 hover:border-red-200 transition-colors">
                          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" /></svg>
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="px-5 py-3.5 bg-slate-50 border-t border-slate-100">
            <span className="text-xs text-slate-400">显示 {filteredFormulas.length} / {formulas.length} 个配方</span>
          </div>
        </>
      )}

      {/* ── 新增/编辑 Dialog ── */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="text-slate-800">{editing ? "编辑配方" : "新增配方"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-5 py-2">
            {/* 配方名称 + 关联产品 */}
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label className="text-slate-700 text-sm font-medium">配方名称 <span className="text-red-400">*</span></Label>
                <Input
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="如：PE-50μm-透明"
                  className="border-slate-200 focus:border-blue-400 focus:ring-blue-400"
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-slate-700 text-sm font-medium">关联产品 <span className="text-red-400">*</span></Label>
                <select
                  value={form.product_id}
                  onChange={(e) => setForm({ ...form, product_id: e.target.value })}
                  className="w-full h-9 rounded-md border border-slate-200 bg-white px-3 text-sm text-slate-800 focus:border-blue-400 focus:outline-none focus:ring-1 focus:ring-blue-400"
                >
                  <option value="">请选择</option>
                  {products.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}（{p.category.name}）</option>
                  ))}
                </select>
              </div>
            </div>

            {/* 规格参数 */}
            <div className="space-y-2">
              <Label className="text-slate-700 text-sm font-medium">规格参数</Label>
              <p className="text-xs text-slate-400 -mt-1">左侧填参数名，右侧填数值</p>
              <SpecParamRows
                rows={form.specParams}
                onChange={(rows) => setForm({ ...form, specParams: rows })}
              />
            </div>

            {/* 原材料及比例 */}
            <div className="space-y-1.5">
              <Label className="text-slate-700 text-sm font-medium">原材料及比例</Label>
              <Textarea
                value={form.materials}
                onChange={(e) => setForm({ ...form, materials: e.target.value })}
                placeholder={"例：\nXX树脂 60%\nYY添加剂 30%\nZZ助剂 10%"}
                rows={4}
                className="border-slate-200 focus:border-blue-400 focus:ring-blue-400 resize-none text-sm"
              />
            </div>

            {/* 来源配方 */}
            <div className="space-y-1.5">
              <Label className="text-slate-700 text-sm font-medium">来源配方（可选）</Label>
              <select
                value={form.source_id}
                onChange={(e) => setForm({ ...form, source_id: e.target.value })}
                className="w-full h-9 rounded-md border border-slate-200 bg-white px-3 text-sm text-slate-800 focus:border-blue-400 focus:outline-none focus:ring-1 focus:ring-blue-400"
              >
                <option value="">无（原创配方）</option>
                {sourceOptions.map((f) => (
                  <option key={f.id} value={f.id}>{f.name}</option>
                ))}
              </select>
            </div>

            {/* 备注 */}
            <div className="space-y-1.5">
              <Label className="text-slate-700 text-sm font-medium">备注</Label>
              <Textarea
                value={form.notes}
                onChange={(e) => setForm({ ...form, notes: e.target.value })}
                placeholder="可选"
                rows={2}
                className="border-slate-200 focus:border-blue-400 focus:ring-blue-400 resize-none"
              />
            </div>

            {error && (
              <p className="text-sm text-red-500 bg-red-50 border border-red-100 rounded-md px-3 py-2">{error}</p>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)} className="border-slate-200 text-slate-600">取消</Button>
            <Button onClick={handleSave} disabled={saving} className="bg-blue-600 hover:bg-blue-700 text-white">{saving ? "保存中…" : "保存"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── 原材料查看 ── */}
      <Dialog open={viewingMaterials !== null} onOpenChange={(o) => !o && setViewingMaterials(null)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader><DialogTitle className="text-slate-800">原材料及比例</DialogTitle></DialogHeader>
          <p className="text-sm text-slate-600 py-2 whitespace-pre-wrap leading-relaxed">{viewingMaterials}</p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setViewingMaterials(null)} className="border-slate-200 text-slate-600">关闭</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── 备注查看 ── */}
      <Dialog open={viewingNotes !== null} onOpenChange={(o) => !o && setViewingNotes(null)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader><DialogTitle className="text-slate-800">备注</DialogTitle></DialogHeader>
          <p className="text-sm text-slate-600 py-2 whitespace-pre-wrap leading-relaxed">{viewingNotes}</p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setViewingNotes(null)} className="border-slate-200 text-slate-600">关闭</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── 删除确认 ── */}
      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader><DialogTitle className="text-slate-800">确认删除</DialogTitle></DialogHeader>
          <p className="text-sm text-slate-500 py-2">
            确定删除配方「<span className="font-medium text-slate-700">{deleting?.name}</span>」吗？若已被订单引用则无法删除。
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteDialogOpen(false)} className="border-slate-200 text-slate-600">取消</Button>
            <Button onClick={handleDelete} className="bg-red-500 hover:bg-red-600 text-white border-0">删除</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
