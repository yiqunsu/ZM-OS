"use client";

import { useEffect, useState } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { api, ApiError } from "@/lib/api";

/* ─── 类型 ─── */
interface Category { id: string; name: string }
interface Pattern  { id: string; name: string }

interface Machine {
  id: string;
  name: string;
  is_active: boolean;
  min_width: number;
  max_width: number;
  notes: string | null;
  categories: Category[];
  patterns: Pattern[];
}

interface FormState {
  name: string;
  is_active: boolean;
  min_width: string;
  max_width: string;
  notes: string;
  category_ids: string[];
  pattern_ids: string[];
}

const emptyForm: FormState = {
  name: "", is_active: true,
  min_width: "", max_width: "",
  notes: "", category_ids: [], pattern_ids: [],
};

/* ─── Avatar 颜色 ─── */
const AVATAR_COLORS = [
  "bg-blue-100 text-blue-700",
  "bg-indigo-100 text-indigo-700",
  "bg-sky-100 text-sky-700",
  "bg-violet-100 text-violet-700",
  "bg-teal-100 text-teal-700",
];
function avatarColor(id: string) {
  return AVATAR_COLORS[(id.charCodeAt(0) + id.charCodeAt(id.length - 1)) % AVATAR_COLORS.length];
}

/* ─── 多选复选框组 ─── */
function CheckboxGroup({
  label, items, selected, onChange,
}: {
  label: string;
  items: { id: string; name: string }[];
  selected: string[];
  onChange: (ids: string[]) => void;
}) {
  function toggle(id: string) {
    onChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);
  }
  return (
    <div className="space-y-1.5">
      <Label className="text-slate-700 text-sm font-medium">{label}</Label>
      {items.length === 0 ? (
        <p className="text-xs text-slate-400 py-1">暂无数据，可在对应 Tab 中先添加</p>
      ) : (
        <div className="flex flex-wrap gap-2 pt-1">
          {items.map((item) => {
            const checked = selected.includes(item.id);
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => toggle(item.id)}
                className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                  checked
                    ? "bg-blue-600 text-white border-blue-600"
                    : "bg-white text-slate-600 border-slate-200 hover:border-blue-300 hover:text-blue-600"
                }`}
              >
                {item.name}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

/* ─── 主组件 ─── */
export default function MachineTab() {
  const [machines, setMachines]     = useState<Machine[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [patterns, setPatterns]     = useState<Pattern[]>([]);
  const [loading, setLoading]       = useState(true);

  const [dialogOpen, setDialogOpen]           = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [editing, setEditing]   = useState<Machine | null>(null);
  const [deleting, setDeleting] = useState<Machine | null>(null);
  const [form, setForm]         = useState<FormState>(emptyForm);
  const [saving, setSaving]     = useState(false);
  const [error, setError]       = useState("");
  const [viewingNotes, setViewingNotes] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    const [m, c, p] = await Promise.all([
      api.get<Machine[]>("/machines"),
      api.get<Category[]>("/product-categories"),
      api.get<Pattern[]>("/patterns"),
    ]);
    setMachines(m);
    setCategories(c);
    setPatterns(p);
    setLoading(false);
  }

  useEffect(() => { load(); }, []);

  function openCreate() {
    setEditing(null);
    setForm(emptyForm);
    setError("");
    setDialogOpen(true);
  }

  function openEdit(m: Machine) {
    setEditing(m);
    setForm({
      name: m.name,
      is_active: m.is_active,
      min_width: String(m.min_width),
      max_width: String(m.max_width),
      notes: m.notes ?? "",
      category_ids: m.categories.map((c) => c.id),
      pattern_ids:  m.patterns.map((p) => p.id),
    });
    setError("");
    setDialogOpen(true);
  }

  async function handleSave() {
    if (!form.name.trim()) { setError("机器名称为必填项"); return; }
    const min = parseFloat(form.min_width);
    const max = parseFloat(form.max_width);
    if (isNaN(min) || isNaN(max) || min >= max) {
      setError("宽度范围不合法（最小值须小于最大值）");
      return;
    }
    setSaving(true); setError("");
    try {
      const payload = { ...form, min_width: min, max_width: max };
      if (editing) await api.put(`/machines/${editing.id}`, payload);
      else await api.post("/machines", payload);
      setDialogOpen(false);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "保存失败");
    } finally { setSaving(false); }
  }

  async function handleDelete() {
    if (!deleting) return;
    try {
      await api.delete(`/machines/${deleting.id}`);
      setDeleteDialogOpen(false);
      setDeleting(null);
      await load();
    } catch (e) {
      alert(e instanceof ApiError ? e.message : "删除失败");
    }
  }

  async function toggleActive(m: Machine) {
    await api.put(`/machines/${m.id}`, {
      name: m.name, is_active: !m.is_active,
      min_width: m.min_width, max_width: m.max_width,
      notes: m.notes,
      category_ids: m.categories.map((c) => c.id),
      pattern_ids:  m.patterns.map((p) => p.id),
    });
    await load();
  }

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
      {/* Header */}
      <div className="px-6 py-5 border-b border-slate-100 flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-slate-800">机器列表</h2>
          {!loading && (
            <p className="text-sm text-slate-500 mt-0.5">
              共 <span className="text-blue-600 font-semibold">{machines.length}</span> 台机器
            </p>
          )}
        </div>
        <button
          onClick={openCreate}
          className="inline-flex items-center gap-1.5 bg-blue-600 hover:bg-blue-700 active:scale-95 text-white text-sm font-medium px-4 py-2 rounded-lg transition-all shadow-sm shadow-blue-200"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
          </svg>
          新增机器
        </button>
      </div>

      {/* Table */}
      {loading ? (
        <div className="px-6 py-16 text-center text-sm text-slate-400">加载中…</div>
      ) : machines.length === 0 ? (
        <div className="px-6 py-16 text-center">
          <p className="text-slate-400 text-sm">暂无机器</p>
          <button onClick={openCreate} className="mt-3 text-sm text-blue-600 hover:text-blue-700 font-medium">
            + 新增第一台机器
          </button>
        </div>
      ) : (
        <>
          {/* 手机端：卡片列表 */}
          <div className="md:hidden divide-y divide-slate-100">
            {machines.map((m) => (
              <div key={m.id} className="px-4 py-3.5">
                <div className="flex items-center gap-3">
                  <div className={`w-9 h-9 rounded-lg flex items-center justify-center font-bold text-sm shrink-0 ${avatarColor(m.id)}`}>
                    {m.name.charAt(0)}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-slate-800">{m.name}</span>
                      <button
                        onClick={() => toggleActive(m)}
                        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${
                          m.is_active ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"
                        }`}
                      >
                        <span className={`w-1.5 h-1.5 rounded-full ${m.is_active ? "bg-emerald-500" : "bg-slate-400"}`} />
                        {m.is_active ? "在用" : "停用"}
                      </button>
                    </div>
                    <p className="text-sm text-slate-500 mt-0.5 tabular-nums">{m.min_width}–{m.max_width} mm</p>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    <button onClick={() => openEdit(m)} className="p-2 rounded-lg border border-slate-200 text-slate-500 hover:text-blue-600 hover:border-blue-300 transition-colors">
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L6.832 19.82a4.5 4.5 0 0 1-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 0 1 1.13-1.897L16.863 4.487Z" /></svg>
                    </button>
                    <button onClick={() => { setDeleting(m); setDeleteDialogOpen(true); }} className="p-2 rounded-lg border border-slate-200 text-slate-400 hover:text-red-500 hover:border-red-200 transition-colors">
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" /></svg>
                    </button>
                  </div>
                </div>
                {m.categories.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1 ml-12">
                    {m.categories.map((category) => (
                      <span key={category.id} className="px-2 py-0.5 rounded-md bg-blue-50 text-blue-700 text-xs font-medium">
                        {category.name}
                      </span>
                    ))}
                  </div>
                )}
                {m.notes && (
                  <button onClick={() => setViewingNotes(m.notes)} className="mt-1.5 ml-12 text-xs text-slate-400 hover:text-blue-600 text-left truncate max-w-full">
                    备注：{m.notes}
                  </button>
                )}
              </div>
            ))}
          </div>

          {/* 桌面端：表格 */}
          <table className="hidden md:table w-full text-sm table-fixed">
            <colgroup>
              <col className="w-36" />
              <col className="w-24" />
              <col className="w-36" />
              <col />
              <col className="w-44" />
              <col className="w-36" />
            </colgroup>
            <thead>
              <tr className="bg-slate-50 border-b border-slate-100">
                {["机器名称", "状态", "宽度范围", "可生产大类", "备注", ""].map((h) => (
                  <th key={h} className="text-left px-6 py-3.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {machines.map((m) => (
                <tr key={m.id} className="hover:bg-blue-50/30 transition-colors group">
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-3">
                      <div className={`w-8 h-8 rounded-lg flex items-center justify-center font-bold text-xs shrink-0 ${avatarColor(m.id)}`}>{m.name.charAt(0)}</div>
                      <span className="font-medium text-slate-800 truncate">{m.name}</span>
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <button onClick={() => toggleActive(m)} title="点击切换状态" className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium transition-colors ${m.is_active ? "bg-emerald-50 text-emerald-700 hover:bg-emerald-100" : "bg-slate-100 text-slate-500 hover:bg-slate-200"}`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${m.is_active ? "bg-emerald-500" : "bg-slate-400"}`} />
                      {m.is_active ? "在用" : "停用"}
                    </button>
                  </td>
                  <td className="px-6 py-4 text-slate-600 tabular-nums">{m.min_width}–{m.max_width} mm</td>
                  <td className="px-6 py-4">
                    <div className="flex flex-wrap gap-1">
                      {m.categories.length === 0 ? <span className="text-slate-300">—</span> : m.categories.slice(0, 3).map((category) => (
                        <span key={category.id} className="px-2 py-0.5 rounded-md bg-blue-50 text-blue-700 text-xs font-medium">{category.name}</span>
                      ))}
                      {m.categories.length > 3 && <span className="px-2 py-0.5 rounded-md bg-slate-100 text-slate-500 text-xs">+{m.categories.length - 3}</span>}
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    {m.notes ? (
                      <button onClick={() => setViewingNotes(m.notes)} className="inline-flex items-center max-w-full px-2 py-0.5 rounded-md bg-slate-100 hover:bg-slate-200 text-slate-600 text-xs transition-colors">
                        <span className="truncate">{m.notes}</span>
                      </button>
                    ) : <span className="text-slate-300">—</span>}
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex items-center justify-end gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button onClick={() => openEdit(m)} className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-md border border-slate-200 bg-white text-slate-600 hover:text-blue-600 hover:border-blue-300 text-xs font-medium transition-colors">
                        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L6.832 19.82a4.5 4.5 0 0 1-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 0 1 1.13-1.897L16.863 4.487Z" /></svg>
                        编辑
                      </button>
                      <button onClick={() => { setDeleting(m); setDeleteDialogOpen(true); }} className="p-1.5 rounded-md border border-slate-200 bg-white text-slate-400 hover:text-red-500 hover:border-red-200 transition-colors">
                        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" /></svg>
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="px-6 py-3.5 bg-slate-50 border-t border-slate-100">
            <span className="text-xs text-slate-400">显示全部 {machines.length} 台机器</span>
          </div>
        </>
      )}

      {/* ── 新增/编辑 Dialog ── */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="text-slate-800">
              {editing ? "编辑机器" : "新增机器"}
            </DialogTitle>
          </DialogHeader>

          <div className="space-y-4 py-2">
            {/* 名称 + 状态 */}
            <div className="flex gap-4">
              <div className="flex-1 space-y-1.5">
                <Label className="text-slate-700 text-sm font-medium">
                  机器名称 <span className="text-red-400">*</span>
                </Label>
                <Input
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="如：1号机"
                  className="border-slate-200 focus:border-blue-400 focus:ring-blue-400"
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-slate-700 text-sm font-medium">状态</Label>
                <button
                  type="button"
                  onClick={() => setForm({ ...form, is_active: !form.is_active })}
                  className={`mt-0.5 w-full h-9 px-4 rounded-lg border text-sm font-medium transition-colors ${
                    form.is_active
                      ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                      : "bg-slate-50 text-slate-500 border-slate-200"
                  }`}
                >
                  {form.is_active ? "在用" : "停用"}
                </button>
              </div>
            </div>

            {/* 宽度范围 */}
            <div className="space-y-1.5">
              <Label className="text-slate-700 text-sm font-medium">
                宽度范围 (mm) <span className="text-red-400">*</span>
              </Label>
              <div className="flex items-center gap-3">
                <Input
                  type="number"
                  value={form.min_width}
                  onChange={(e) => setForm({ ...form, min_width: e.target.value })}
                  placeholder="最小"
                  className="border-slate-200 focus:border-blue-400 focus:ring-blue-400"
                />
                <span className="text-slate-400 shrink-0">—</span>
                <Input
                  type="number"
                  value={form.max_width}
                  onChange={(e) => setForm({ ...form, max_width: e.target.value })}
                  placeholder="最大"
                  className="border-slate-200 focus:border-blue-400 focus:ring-blue-400"
                />
              </div>
            </div>

            {/* 可生产产品大类 */}
            <CheckboxGroup
              label="可生产产品大类"
              items={categories}
              selected={form.category_ids}
              onChange={(ids) => setForm({ ...form, category_ids: ids })}
            />

            {/* 可用花纹 */}
            <CheckboxGroup
              label="可用花纹"
              items={patterns}
              selected={form.pattern_ids}
              onChange={(ids) => setForm({ ...form, pattern_ids: ids })}
            />

            {/* 备注 */}
            <div className="space-y-1.5">
              <Label className="text-slate-700 text-sm font-medium">备注</Label>
              <Textarea
                value={form.notes}
                onChange={(e) => setForm({ ...form, notes: e.target.value })}
                placeholder="其他限制说明（供 AI 排单参考）"
                rows={3}
                className="border-slate-200 focus:border-blue-400 focus:ring-blue-400 resize-none"
              />
            </div>

            {error && (
              <p className="text-sm text-red-500 bg-red-50 border border-red-100 rounded-md px-3 py-2">
                {error}
              </p>
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)} className="border-slate-200 text-slate-600">
              取消
            </Button>
            <Button onClick={handleSave} disabled={saving} className="bg-blue-600 hover:bg-blue-700 text-white">
              {saving ? "保存中…" : "保存"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── 备注查看 Dialog ── */}
      <Dialog open={viewingNotes !== null} onOpenChange={(o) => !o && setViewingNotes(null)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle className="text-slate-800">备注</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-slate-600 py-2 whitespace-pre-wrap leading-relaxed">{viewingNotes}</p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setViewingNotes(null)} className="border-slate-200 text-slate-600">
              关闭
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── 删除确认 Dialog ── */}
      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle className="text-slate-800">确认删除</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-slate-500 py-2">
            确定删除机器「<span className="font-medium text-slate-700">{deleting?.name}</span>」吗？若该机器存在关联生产任务则无法删除。
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteDialogOpen(false)} className="border-slate-200 text-slate-600">
              取消
            </Button>
            <Button onClick={handleDelete} className="bg-red-500 hover:bg-red-600 text-white border-0">
              删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
