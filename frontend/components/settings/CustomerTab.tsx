"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { api, ApiError } from "@/lib/api";

interface Customer {
  id: string;
  company: string;
  contact: string;
  notes: string | null;
}

interface FormState {
  company: string;
  contact: string;
  notes: string;
}

const emptyForm: FormState = { company: "", contact: "", notes: "" };

const AVATAR_COLORS = [
  "bg-blue-100 text-blue-700",
  "bg-violet-100 text-violet-700",
  "bg-emerald-100 text-emerald-700",
  "bg-orange-100 text-orange-700",
  "bg-rose-100 text-rose-700",
  "bg-cyan-100 text-cyan-700",
];

function getAvatarColor(id: string) {
  const code = id.charCodeAt(0) + id.charCodeAt(id.length - 1);
  return AVATAR_COLORS[code % AVATAR_COLORS.length];
}

export default function CustomerTab() {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [editing, setEditing] = useState<Customer | null>(null);
  const [deleting, setDeleting] = useState<Customer | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [viewingNotes, setViewingNotes] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setCustomers(await api.get<Customer[]>("/customers"));
    setLoading(false);
  }

  useEffect(() => {
    load();
  }, []);

  function openCreate() {
    setEditing(null);
    setForm(emptyForm);
    setError("");
    setDialogOpen(true);
  }

  function openEdit(c: Customer) {
    setEditing(c);
    setForm({ company: c.company, contact: c.contact, notes: c.notes ?? "" });
    setError("");
    setDialogOpen(true);
  }

  function openDelete(c: Customer) {
    setDeleting(c);
    setDeleteDialogOpen(true);
  }

  async function handleSave() {
    if (!form.company.trim() || !form.contact.trim()) {
      setError("公司名称和联系人为必填项");
      return;
    }
    setSaving(true);
    setError("");
    try {
      if (editing) {
        await api.put(`/customers/${editing.id}`, form);
      } else {
        await api.post("/customers", form);
      }
      setDialogOpen(false);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!deleting) return;
    try {
      await api.delete(`/customers/${deleting.id}`);
      setDeleteDialogOpen(false);
      setDeleting(null);
      await load();
    } catch (e) {
      alert(e instanceof ApiError ? e.message : "删除失败");
    }
  }

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
      {/* Section header */}
      <div className="px-6 py-5 border-b border-slate-100 flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-slate-800">客户列表</h2>
          {!loading && (
            <p className="text-sm text-slate-500 mt-0.5">
              共{" "}
              <span className="text-blue-600 font-semibold">{customers.length}</span>{" "}
              个客户
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
          新增客户
        </button>
      </div>

      {/* Table */}
      {loading ? (
        <div className="px-6 py-16 text-center text-sm text-slate-400">加载中…</div>
      ) : customers.length === 0 ? (
        <div className="px-6 py-16 text-center">
          <p className="text-slate-400 text-sm">暂无客户</p>
          <button
            onClick={openCreate}
            className="mt-3 text-sm text-blue-600 hover:text-blue-700 font-medium"
          >
            + 新增第一个客户
          </button>
        </div>
      ) : (
        <>
          {/* 手机端：卡片列表 */}
          <div className="md:hidden divide-y divide-slate-100">
            {customers.map((c) => (
              <div key={c.id} className="px-4 py-3.5 flex items-center gap-3">
                <div className={`w-9 h-9 rounded-lg flex items-center justify-center font-bold text-sm shrink-0 ${getAvatarColor(c.id)}`}>
                  {c.company.charAt(0)}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="font-medium text-slate-800">{c.company}</p>
                  <p className="text-sm text-slate-500 mt-0.5">{c.contact}</p>
                  {c.notes && (
                    <button
                      onClick={() => setViewingNotes(c.notes)}
                      className="mt-1 text-xs text-slate-400 hover:text-blue-600 truncate max-w-full text-left"
                    >
                      备注：{c.notes}
                    </button>
                  )}
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                  <button
                    onClick={() => openEdit(c)}
                    className="p-2 rounded-lg border border-slate-200 text-slate-500 hover:text-blue-600 hover:border-blue-300 transition-colors"
                  >
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L6.832 19.82a4.5 4.5 0 0 1-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 0 1 1.13-1.897L16.863 4.487Z" />
                    </svg>
                  </button>
                  <button
                    onClick={() => openDelete(c)}
                    className="p-2 rounded-lg border border-slate-200 text-slate-400 hover:text-red-500 hover:border-red-200 transition-colors"
                  >
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
                    </svg>
                  </button>
                </div>
              </div>
            ))}
          </div>

          {/* 桌面端：表格 */}
          <table className="hidden md:table w-full text-sm table-fixed">
            <colgroup>
              <col />
              <col className="w-32" />
              <col className="w-44" />
              <col className="w-36" />
            </colgroup>
            <thead>
              <tr className="bg-slate-50 border-b border-slate-100">
                <th className="text-left px-6 py-3.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">公司名称</th>
                <th className="text-left px-6 py-3.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">联系人</th>
                <th className="text-left px-6 py-3.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">备注</th>
                <th className="px-6 py-3.5" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {customers.map((c) => (
                <tr key={c.id} className="hover:bg-blue-50/30 transition-colors group">
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-3">
                      <div className={`w-8 h-8 rounded-lg flex items-center justify-center font-bold text-xs shrink-0 ${getAvatarColor(c.id)}`}>
                        {c.company.charAt(0)}
                      </div>
                      <span className="font-medium text-slate-800">{c.company}</span>
                    </div>
                  </td>
                  <td className="px-6 py-4 text-slate-600">{c.contact}</td>
                  <td className="px-6 py-4">
                    {c.notes ? (
                      <button onClick={() => setViewingNotes(c.notes)} className="inline-flex items-center max-w-full px-2 py-0.5 rounded-md bg-slate-100 hover:bg-slate-200 text-slate-600 text-xs transition-colors cursor-pointer">
                        <span className="truncate">{c.notes}</span>
                      </button>
                    ) : (
                      <span className="text-slate-300">—</span>
                    )}
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex items-center justify-end gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button onClick={() => openEdit(c)} className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-md border border-slate-200 bg-white text-slate-600 hover:text-blue-600 hover:border-blue-300 text-xs font-medium transition-colors">
                        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L6.832 19.82a4.5 4.5 0 0 1-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 0 1 1.13-1.897L16.863 4.487Z" /></svg>
                        编辑
                      </button>
                      <button onClick={() => openDelete(c)} className="p-1.5 rounded-md border border-slate-200 bg-white text-slate-400 hover:text-red-500 hover:border-red-200 transition-colors">
                        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" /></svg>
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="px-6 py-3.5 bg-slate-50 border-t border-slate-100">
            <span className="text-xs text-slate-400">显示全部 {customers.length} 个客户</span>
          </div>
        </>
      )}

      {/* 新增/编辑 Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-slate-800">
              {editing ? "编辑客户" : "新增客户"}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-1.5">
              <Label htmlFor="company" className="text-slate-700 text-sm font-medium">
                公司名称 <span className="text-red-400">*</span>
              </Label>
              <Input
                id="company"
                value={form.company}
                onChange={(e) => setForm({ ...form, company: e.target.value })}
                placeholder="如：华兴包装"
                className="border-slate-200 focus:border-blue-400 focus:ring-blue-400"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="contact" className="text-slate-700 text-sm font-medium">
                联系人 <span className="text-red-400">*</span>
              </Label>
              <Input
                id="contact"
                value={form.contact}
                onChange={(e) => setForm({ ...form, contact: e.target.value })}
                placeholder="姓名"
                className="border-slate-200 focus:border-blue-400 focus:ring-blue-400"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="notes" className="text-slate-700 text-sm font-medium">
                备注
              </Label>
              <Textarea
                id="notes"
                value={form.notes}
                onChange={(e) => setForm({ ...form, notes: e.target.value })}
                placeholder="可选，如账期、特殊要求等"
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
            <Button
              variant="outline"
              onClick={() => setDialogOpen(false)}
              className="border-slate-200 text-slate-600"
            >
              取消
            </Button>
            <Button
              onClick={handleSave}
              disabled={saving}
              className="bg-blue-600 hover:bg-blue-700 text-white"
            >
              {saving ? "保存中…" : "保存"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 备注查看 Dialog */}
      <Dialog open={viewingNotes !== null} onOpenChange={(o) => !o && setViewingNotes(null)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle className="text-slate-800">备注</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-slate-600 py-2 whitespace-pre-wrap leading-relaxed">
            {viewingNotes}
          </p>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setViewingNotes(null)}
              className="border-slate-200 text-slate-600"
            >
              关闭
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 删除确认 Dialog */}
      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle className="text-slate-800">确认删除</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-slate-500 py-2">
            确定删除客户「<span className="font-medium text-slate-700">{deleting?.company}</span>」吗？若该客户存在关联订单则无法删除。
          </p>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteDialogOpen(false)}
              className="border-slate-200 text-slate-600"
            >
              取消
            </Button>
            <Button
              onClick={handleDelete}
              className="bg-red-500 hover:bg-red-600 text-white border-0"
            >
              删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
