"use client";

import { useCallback, useEffect, useId, useState } from "react";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
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
import styles from "./OrderForm.module.css";
import OrderFieldHint from "./OrderFieldHint";

/* ─── Types ─── */
interface Category {
  id: string;
  name: string;
}
interface Product {
  id: string;
  name: string;
  category_id: string;
  category: Category;
}
interface Customer {
  id: string;
  company: string;
  contact: string;
}
interface Formula {
  id: string;
  name: string;
  product_id: string;
  spec_params: Record<string, string>;
  materials: string;
  notes: string | null;
}

interface SpecParam {
  key: string;
  value: string;
  [k: string]: string;
}
type FormulaMode = "none" | "existing" | "new";

interface FormState {
  customerId: string;
  productId: string;
  specParams: SpecParam[];
  quantity: string;
  unit: "m" | "g" | "kg" | "t" | "";
  extraNotes: string;
  formulaMode: FormulaMode;
  formulaId: string;
  formulaMaterials: string;
  newFormulaName: string;
  newFormulaMaterials: string;
}

const emptyForm: FormState = {
  customerId: "",
  productId: "",
  specParams: [
    { key: "宽幅", value: "" },
    { key: "厚度", value: "" },
  ],
  quantity: "",
  unit: "kg",
  extraNotes: "",
  formulaMode: "none",
  formulaId: "",
  formulaMaterials: "",
  newFormulaName: "",
  newFormulaMaterials: "",
};

/* ─── Helpers ─── */
function specParamsToObj(rows: SpecParam[]): Record<string, string> {
  const obj: Record<string, string> = {};
  rows.forEach(({ key, value }) => {
    if (key.trim()) obj[key.trim()] = value.trim();
  });
  return obj;
}

function objToSpecParams(obj: Record<string, string>): SpecParam[] {
  const entries = Object.entries(obj ?? {}).map(([key, raw]) => {
    const text = String(raw);
    const match = text.match(/^(\d+(?:\.\d+)?)\s*(cm|mm|丝|c|μm|um)$/i);
    if (!match) return [key, text];
    const width = ["宽幅", "宽度", "幅宽", "width"].includes(key);
    const thickness = ["厚度", "厚", "thickness"].includes(key);
    const unit = match[2].toLowerCase();
    const factor = width
      ? ({ cm: 10, mm: 1 } as Record<string, number>)[unit]
      : thickness
        ? ({ 丝: 10, c: 10, μm: 1, um: 1 } as Record<string, number>)[unit]
        : undefined;
    if (factor === undefined) return [key, text];
    return [
      key,
      String(Number((Number(match[1]) * factor).toPrecision(12))) +
        (width ? "mm" : "μm"),
    ];
  });
  return entries.length
    ? entries.map(([key, value]) => ({ key, value: String(value) }))
    : [{ key: "", value: "" }];
}

/* Build a readable label for formula option: name · spec hints · notes */
function formulaLabel(f: Formula): string {
  const parts: string[] = [f.name];
  const hints = Object.entries(f.spec_params ?? {})
    .slice(0, 2)
    .map(([k, v]) => `${k}:${v}`)
    .join(" ");
  if (hints) parts.push(hints);
  if (f.notes?.trim()) parts.push(`备注:${f.notes.trim()}`);
  return parts.join("  ·  ");
}

/* ─── SpecParamRows ─── */
function SpecParamRows({
  rows,
  onChange,
}: {
  rows: SpecParam[];
  onChange: (r: SpecParam[]) => void;
}) {
  function update(i: number, field: "key" | "value", val: string) {
    onChange(rows.map((r, idx) => (idx === i ? { ...r, [field]: val } : r)));
  }
  function remove(i: number) {
    onChange(rows.filter((_, idx) => idx !== i));
  }
  function add() {
    onChange([...rows, { key: "", value: "" }]);
  }

  return (
    <div className="space-y-2">
      {rows.map((row, i) => (
        <div key={i} className="flex items-center gap-2">
          <Input
            value={row.key}
            onChange={(e) => update(i, "key", e.target.value)}
            placeholder="参数名（如：厚度）"
            className="w-36 shrink-0 border-slate-200 h-8 text-sm"
          />
          <Input
            value={row.value}
            onChange={(e) => update(i, "value", e.target.value)}
            placeholder="数值（如：50μm）"
            className="flex-1 border-slate-200 h-8 text-sm"
          />
          <button
            type="button"
            onClick={() => remove(i)}
            disabled={rows.length === 1}
            className="p-1.5 rounded text-slate-300 hover:text-red-400 disabled:opacity-30 transition-colors shrink-0"
          >
            <svg
              className="w-4 h-4"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M6 18 18 6M6 6l12 12"
              />
            </svg>
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={add}
        className="text-xs text-blue-600 hover:text-blue-700 font-medium flex items-center gap-1"
      >
        <svg
          className="w-3.5 h-3.5"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2.5}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M12 4.5v15m7.5-7.5h-15"
          />
        </svg>
        添加规格参数
      </button>
    </div>
  );
}

/* ─── Section wrapper ─── */
function UnitChoices({
  value,
  fixed = false,
  onChange,
}: {
  value: string;
  fixed?: boolean;
  onChange?: (unit: "m" | "kg") => void;
}) {
  const groupName = useId();
  const choiceStyle =
    "inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors";
  if (fixed)
    return (
      <span
        aria-label={`固定单位 ${value}`}
        className={`${choiceStyle} border-[#C8331F]/15 bg-[#C8331F]/5 text-[#C8331F]`}
      >
        <span
          aria-hidden="true"
          className="h-2.5 w-2.5 rounded-full bg-[#C8331F]"
        />
        {value}
      </span>
    );
  return (
    <div
      role="radiogroup"
      aria-label="数量单位"
      className="flex flex-wrap gap-2"
    >
      {(["m", "kg"] as const).map((unit) => (
        <label key={unit} className="relative cursor-pointer">
          <input
            type="radio"
            name={groupName}
            value={unit}
            checked={value === unit}
            onChange={() => onChange?.(unit)}
            className="peer sr-only"
          />
          <span
            className={`${choiceStyle} border-slate-200 bg-white text-slate-500 hover:border-slate-300 peer-checked:border-[#C8331F]/15 peer-checked:bg-[#C8331F]/5 peer-checked:text-[#C8331F] peer-focus-visible:ring-2 peer-focus-visible:ring-[#C8331F]/40 peer-focus-visible:ring-offset-2`}
          >
            <span
              aria-hidden="true"
              className={`h-2.5 w-2.5 rounded-full ${value === unit ? "bg-[#C8331F]" : "border border-slate-300 bg-white"}`}
            />
            {unit === "m" ? "米数 · m" : "重量 · kg"}
          </span>
        </label>
      ))}
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div
      data-order-section={title}
      className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden"
    >
      <div
        data-section-header
        className="px-6 py-4 border-b border-slate-100 bg-slate-50"
      >
        <h2 className="text-sm font-semibold text-slate-700">{title}</h2>
      </div>
      <div data-section-body className="px-6 py-5">
        {children}
      </div>
    </div>
  );
}

/** Initial values for the shared order form. Workspace submission stays with its owner. */
export interface OrderDraft {
  customer_id?: string | null;
  product_id?: string | null;
  spec_params?: Record<string, string>;
  quantity?: number | string | null;
  unit?: "m" | "g" | "kg" | "t" | "" | null;
  formula_mode?: FormulaMode;
  formula_id?: string | null;
  extra_notes?: string;
}

interface OrderFormProps {
  orderId?: string;
  /** Remount on accepted server revisions; local edits never follow polling updates. */
  workspace?: {
    draft: OrderDraft;
    issues?: { field: string; code: string; message: string }[];
    onDraftChange: (draft: OrderDraft) => void;
    disabled: boolean;
    onReadyChange: (ready: boolean) => void;
  };
}

function initialForm(draft?: OrderDraft): FormState {
  if (!draft) return emptyForm;
  return {
    ...emptyForm,
    customerId: draft.customer_id ?? "",
    productId: draft.product_id ?? "",
    specParams: objToSpecParams(draft.spec_params ?? {}),
    quantity:
      draft.quantity == null
        ? ""
        : String(
            Number(draft.quantity) *
              (draft.unit === "t" ? 1000 : draft.unit === "g" ? 0.001 : 1),
          ),
    unit: !draft.unit ? "" : draft.unit === "m" ? "m" : "kg",
    formulaMode: draft.formula_mode ?? "none",
    formulaId: draft.formula_id ?? "",
    extraNotes: draft.extra_notes ?? "",
  };
}

export default function OrderForm({ orderId, workspace }: OrderFormProps) {
  const router = useRouter();
  const { data: session } = useSession();
  const canManage = session?.user?.role === "OWNER";
  const isEdit = Boolean(orderId);
  const isPanel = Boolean(workspace);
  const formulaGroup = useId();

  /* Reference data */
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [formulas, setFormulas] = useState<Formula[]>([]);

  /* Page state */
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  /* Main form */
  const [form, setFormState] = useState<FormState>(() =>
    initialForm(workspace?.draft),
  );
  function setForm(update: FormState | ((previous: FormState) => FormState)) {
    const next = typeof update === "function" ? update(form) : update;
    setFormState(next);
    workspace?.onDraftChange({
      customer_id: next.customerId || null,
      product_id: next.productId || null,
      spec_params: specParamsToObj(next.specParams),
      quantity: next.quantity || null,
      unit: next.unit || null,
      formula_mode: next.formulaMode,
      formula_id: next.formulaId || null,
      extra_notes: next.extraNotes,
    });
  }

  /* Formula change tracking */
  const [origFormulaSpecParams, setOrigFormulaSpecParams] = useState<
    Record<string, string>
  >({});
  const [origFormulaMaterials, setOrigFormulaMaterials] = useState("");

  /* ── Dialog: new customer ── */
  const [newCustomerOpen, setNewCustomerOpen] = useState(false);
  const [newCustomerCompany, setNewCustomerCompany] = useState("");
  const [newCustomerContact, setNewCustomerContact] = useState("");
  const [newCustomerSaving, setNewCustomerSaving] = useState(false);
  const [newCustomerError, setNewCustomerError] = useState("");

  /* ── Dialog: new product ── */
  const [newProductOpen, setNewProductOpen] = useState(false);
  const [newProductName, setNewProductName] = useState("");
  const [newProductCategoryId, setNewProductCategoryId] = useState("");
  const [newProductSaving, setNewProductSaving] = useState(false);
  const [newProductError, setNewProductError] = useState("");

  /* ── Dialog: save-as-new formula ── */
  const [saveFormulaOpen, setSaveFormulaOpen] = useState(false);
  const [saveFormulaName, setSaveFormulaName] = useState("");
  const [saveFormulaSaving, setSaveFormulaSaving] = useState(false);
  const [saveFormulaError, setSaveFormulaError] = useState("");

  /* ─── Setters ─── */
  function set<K extends keyof FormState>(key: K, val: FormState[K]) {
    setForm((f) => ({ ...f, [key]: val }));
  }

  /* ─── Load ─── */
  const load = useCallback(async () => {
    setLoading(true);
    setLoadFailed(false);
    try {
      const [c, cat, p, f] = await Promise.all([
        api.get<Customer[]>("/customers"),
        api.get<Category[]>("/product-categories"),
        api.get<Product[]>("/products"),
        api.get<Formula[]>("/formulas"),
      ]);
      setCustomers(c);
      setCategories(cat);
      setProducts(p);
      setFormulas(f);

      if (orderId) {
        const order = await api.get<{
          customer_id: string;
          product_id: string;
          spec_params: Record<string, string>;
          quantity: number;
          unit: string;
          extra_notes: string | null;
          formula_id: string | null;
        }>(`/orders/${orderId}`);
        const fId = order.formula_id ?? "";
        const matchedFormula: Formula | undefined = f.find((x) => x.id === fId);
        setFormState({
          customerId: order.customer_id,
          productId: order.product_id,
          specParams: objToSpecParams(order.spec_params),
          quantity: String(
            order.quantity *
              (order.unit === "t" ? 1000 : order.unit === "g" ? 0.001 : 1),
          ),
          unit: order.unit === "m" ? "m" : "kg",
          extraNotes: order.extra_notes ?? "",
          formulaMode: fId ? "existing" : "none",
          formulaId: fId,
          formulaMaterials: matchedFormula?.materials ?? "",
          newFormulaName: "",
          newFormulaMaterials: "",
        });
        if (matchedFormula) {
          setOrigFormulaSpecParams(matchedFormula.spec_params);
          setOrigFormulaMaterials(matchedFormula.materials);
        }
      }
      setError("");
    } catch (loadError) {
      setLoadFailed(true);
      setError(
        loadError instanceof Error
          ? loadError.message
          : "表单数据加载失败，请重试",
      );
    } finally {
      setLoading(false);
    }
  }, [orderId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const onReadyChange = workspace?.onReadyChange;
  useEffect(() => {
    onReadyChange?.(!loading && !loadFailed);
    return () => onReadyChange?.(false);
  }, [loading, loadFailed, onReadyChange]);

  /* ─── Formula select ─── */
  function handleFormulaSelect(fId: string) {
    const f = formulas.find((x) => x.id === fId);
    if (!f) {
      set("formulaId", "");
      return;
    }
    setForm((prev) => ({
      ...prev,
      formulaId: fId,
      specParams: isPanel ? prev.specParams : objToSpecParams(f.spec_params),
      formulaMaterials: f.materials,
    }));
    setOrigFormulaSpecParams(f.spec_params);
    setOrigFormulaMaterials(f.materials);
  }

  const formulaModified =
    form.formulaMode === "existing" &&
    form.formulaId &&
    (JSON.stringify(specParamsToObj(form.specParams)) !==
      JSON.stringify(origFormulaSpecParams) ||
      form.formulaMaterials !== origFormulaMaterials);

  /* ─── Update existing formula ─── */
  async function handleUpdateFormula() {
    if (!form.formulaId) return;
    try {
      const updated = await api.put<Formula>(`/formulas/${form.formulaId}`, {
        name: formulas.find((x) => x.id === form.formulaId)?.name ?? "",
        product_id: form.productId,
        spec_params: specParamsToObj(form.specParams),
        materials: form.formulaMaterials,
      });
      setOrigFormulaSpecParams(updated.spec_params);
      setOrigFormulaMaterials(updated.materials);
      setFormulas((prev) =>
        prev.map((x) => (x.id === updated.id ? updated : x)),
      );
    } catch {
      setError("配方更新失败");
    }
  }

  /* ─── Save as new formula (via dialog) ─── */
  async function handleSaveAsNewFormula() {
    if (!saveFormulaName.trim()) {
      setSaveFormulaError("请填写配方名称");
      return;
    }
    setSaveFormulaSaving(true);
    setSaveFormulaError("");
    try {
      const created = await api.post<Formula>("/formulas", {
        name: saveFormulaName.trim(),
        product_id: form.productId,
        spec_params: specParamsToObj(form.specParams),
        materials: form.formulaMaterials,
        source_id: form.formulaId || null,
      });
      setFormulas((prev) => [...prev, created]);
      setForm((f) => ({ ...f, formulaId: created.id }));
      setOrigFormulaSpecParams(created.spec_params);
      setOrigFormulaMaterials(created.materials);
      setSaveFormulaOpen(false);
      setSaveFormulaName("");
    } catch {
      setSaveFormulaError("保存失败，请重试");
    } finally {
      setSaveFormulaSaving(false);
    }
  }

  /* ─── Create new customer (via dialog) ─── */
  async function handleCreateCustomer() {
    if (workspace?.disabled || !canManage || newCustomerSaving) return;
    if (!newCustomerCompany.trim()) {
      setNewCustomerError("请填写公司名称");
      return;
    }
    if (!newCustomerContact.trim()) {
      setNewCustomerError("请填写联系人姓名");
      return;
    }
    setNewCustomerSaving(true);
    setNewCustomerError("");
    try {
      const created = await api.post<Customer>("/customers", {
        company: newCustomerCompany.trim(),
        contact: newCustomerContact.trim(),
      });
      setCustomers((prev) =>
        [...prev, created].sort((a, b) => a.company.localeCompare(b.company)),
      );
      setForm((f) => ({ ...f, customerId: created.id }));
      setNewCustomerOpen(false);
      setNewCustomerCompany("");
      setNewCustomerContact("");
    } catch (e) {
      setNewCustomerError(e instanceof ApiError ? e.message : "创建失败");
    } finally {
      setNewCustomerSaving(false);
    }
  }

  /* ─── Create new product (via dialog) ─── */
  async function handleCreateProduct() {
    if (workspace?.disabled || !canManage || newProductSaving) return;
    if (!newProductName.trim()) {
      setNewProductError("请填写产品名称");
      return;
    }
    if (!newProductCategoryId) {
      setNewProductError("请选择产品大类");
      return;
    }
    setNewProductSaving(true);
    setNewProductError("");
    try {
      const created = await api.post<Product>("/products", {
        name: newProductName.trim(),
        category_id: newProductCategoryId,
      });
      setProducts((prev) =>
        [...prev, created].sort(
          (a, b) =>
            a.category.name.localeCompare(b.category.name) ||
            a.name.localeCompare(b.name),
        ),
      );
      setForm((f) => ({
        ...f,
        productId: created.id,
        formulaId: "",
        formulaMaterials: "",
      }));
      setNewProductOpen(false);
      setNewProductName("");
      setNewProductCategoryId("");
    } catch (e) {
      setNewProductError(e instanceof ApiError ? e.message : "创建失败");
    } finally {
      setNewProductSaving(false);
    }
  }

  /* ─── Submit order ─── */
  async function handleSave(): Promise<boolean> {
    if (saving || isPanel) return false;
    if (!form.customerId) {
      setError("请选择客户");
      return false;
    }
    if (!form.productId) {
      setError("请选择产品");
      return false;
    }
    const requiredSpecs = specParamsToObj(form.specParams);
    for (const [name, aliases, units] of [
      ["宽幅", ["宽幅", "宽度", "幅宽", "width"], ["mm"]],
      ["厚度", ["厚度", "厚", "thickness"], ["μm"]],
    ] as [string, string[], string[]][]) {
      const raw = aliases.map((key) => requiredSpecs[key]).find(Boolean) ?? "";
      const match = raw.match(/^(\d+(?:\.\d+)?)(.*)$/);
      if (
        !match ||
        !Number.isFinite(Number(match[1])) ||
        Number(match[1]) <= 0 ||
        !units.includes(match[2])
      ) {
        setError("请填写" + name + "的正数数值并选择单位");
        return false;
      }
    }
    if (
      !form.quantity ||
      !Number.isFinite(Number(form.quantity)) ||
      Number(form.quantity) <= 0
    ) {
      setError("请填写有效的数量");
      return false;
    }

    setSaving(true);
    setError("");
    try {
      let result: { order_no?: string; id?: string };
      if (isEdit) {
        let formulaId: string | null = null;
        if (form.formulaMode === "new") {
          if (!form.newFormulaName.trim()) {
            setError("请填写配方名称");
            return false;
          }
          const created = await api.post<Formula>("/formulas", {
            name: form.newFormulaName.trim(),
            product_id: form.productId,
            spec_params: specParamsToObj(form.specParams),
            materials: form.newFormulaMaterials,
          });
          formulaId = created.id;
        } else if (form.formulaMode === "existing" && form.formulaId) {
          formulaId = form.formulaId;
        }
        result = await api.put<{ order_no?: string; id?: string }>(
          `/orders/${orderId}`,
          {
            customer_id: form.customerId,
            product_id: form.productId,
            spec_params: specParamsToObj(form.specParams),
            quantity: Number(form.quantity),
            unit: form.unit,
            formula_id: formulaId,
            extra_notes: form.extraNotes,
          },
        );
      } else {
        result = await api.post<{ order_no?: string; id?: string }>(
          "/orders/from-draft",
          {
            customer_id: form.customerId,
            product_id: form.productId,
            spec_params: specParamsToObj(form.specParams),
            quantity: form.quantity,
            unit: form.unit,
            formula_mode: form.formulaMode,
            formula_id: form.formulaId,
            formula_materials: form.formulaMaterials,
            new_formula_name: form.newFormulaName,
            new_formula_materials: form.newFormulaMaterials,
            extra_notes: form.extraNotes,
          },
        );
      }
      void result;
      router.push("/orders");
      return true;
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "保存失败");
      return false;
    } finally {
      setSaving(false);
    }
  }

  const selectedProduct = products.find((p) => p.id === form.productId);
  const selectedCategoryId = selectedProduct?.category_id;
  const filteredFormulas = formulas.filter((f) => {
    if (f.product_id === form.productId) return true;
    if (isPanel) return false;
    if (!selectedCategoryId) return false;
    const fp = products.find((p) => p.id === f.product_id);
    return fp?.category_id === selectedCategoryId;
  });

  if (loading) {
    return (
      <div className="py-16 text-center text-sm text-slate-400">加载中…</div>
    );
  }

  const submitLabel = saving ? "保存中…" : isEdit ? "保存修改" : "创建订单";
  const handleCancel = () => router.back();

  function fieldHint(...fields: string[]) {
    const issues = workspace?.issues?.filter((issue) => fields.includes(issue.field)) ?? [];
    if (!issues.length) return null;
    const names: Record<string, string> = {customer_id: "客户", product_id: "产品", quantity: "数量", formula_id: "配方"};
    return <OrderFieldHint issues={issues} label={names[fields[0]] ?? fields[0].replace("spec_params.", "")} />;
  }

  const sections = (
    <>
      {/* ── Section 1: 基本信息 ── */}
      <Section title="基本信息">
        <div className={`grid grid-cols-1 @min-[480px]:grid-cols-2 gap-5`}>
          {/* 客户 */}
          <div className="space-y-1.5">
            <Label className="text-slate-700 text-sm font-medium">
              客户 <span className="text-red-400">*</span>
            </Label>
            <div className="flex gap-2">
              <select
                aria-label="客户"
                value={form.customerId}
                onChange={(e) => {
                  set("customerId", e.target.value);
                }}
                className="flex-1 min-w-0 h-9 rounded-md border border-slate-200 bg-white px-3 text-sm text-slate-800 focus:border-blue-400 focus:outline-none focus:ring-1 focus:ring-blue-400"
              >
                <option value="">请选择客户</option>
                {customers.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.company}
                  </option>
                ))}
              </select>
              {canManage && (
                <button
                  type="button"
                  onClick={() => {
                    setNewCustomerOpen(true);
                    setNewCustomerError("");
                  }}
                  title="新建客户"
                  className="h-9 w-9 shrink-0 flex items-center justify-center rounded-md border border-slate-200 bg-white text-slate-500 hover:text-blue-600 hover:border-blue-300 transition-colors"
                >
                  <svg
                    className="w-4 h-4"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2.5}
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M12 4.5v15m7.5-7.5h-15"
                    />
                  </svg>
                </button>
              )}
            </div>
            {fieldHint("customer_id")}
          </div>

          {/* 产品 + 新建按钮 */}
          <div className="space-y-1.5">
            <Label className="text-slate-700 text-sm font-medium">
              产品 <span className="text-red-400">*</span>
            </Label>
            <div className="flex gap-2">
              <select
                aria-label="产品"
                value={form.productId}
                onChange={(e) => {
                  setForm((f) => ({
                    ...f,
                    productId: e.target.value,
                    formulaId: "",
                    formulaMaterials: "",
                  }));
                }}
                className="flex-1 min-w-0 h-9 rounded-md border border-slate-200 bg-white px-3 text-sm text-slate-800 focus:border-blue-400 focus:outline-none focus:ring-1 focus:ring-blue-400"
              >
                <option value="">请选择产品</option>
                {products.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.category?.name ? `${p.category.name} / ` : ""}
                    {p.name}
                  </option>
                ))}
              </select>
              {canManage && (
                <button
                  type="button"
                  onClick={() => {
                    setNewProductOpen(true);
                    setNewProductCategoryId(categories[0]?.id ?? "");
                    setNewProductError("");
                  }}
                  title="新建产品"
                  className="h-9 w-9 shrink-0 flex items-center justify-center rounded-md border border-slate-200 bg-white text-slate-500 hover:text-blue-600 hover:border-blue-300 transition-colors"
                >
                  <svg
                    className="w-4 h-4"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2.5}
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M12 4.5v15m7.5-7.5h-15"
                    />
                  </svg>
                </button>
              )}
            </div>
            {fieldHint("product_id")}
          </div>
        </div>
      </Section>

      {/* ── Section 2: 规格参数 ── */}
      <Section title="规格参数">
        <div data-order-specs className="space-y-4">
          {(["宽幅", "厚度"] as const).map((name) => {
            const aliases =
              name === "宽幅"
                ? ["宽幅", "宽度", "幅宽", "width"]
                : ["厚度", "厚", "thickness"];
            const raw =
              form.specParams.find((row) => aliases.includes(row.key))?.value ??
              "";
            const match = raw.match(/^\s*(\d*(?:\.\d*)?)\s*(.*)$/);
            const standardUnit = name === "宽幅" ? "mm" : "μm";
            const compatible = !raw || match?.[2] === standardUnit;
            const value = compatible ? (match?.[1] ?? "") : "";
            const unit = standardUnit;
            function change(value: string, unit: string) {
              set("specParams", [
                ...form.specParams.filter((row) => !aliases.includes(row.key)),
                { key: name, value: value + unit },
              ]);
            }
            return (
              <div key={name} className="space-y-2.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <Label className="text-sm text-slate-700">
                    {name} <span className="text-[#C8331F]">*</span>
                  </Label>
                  <UnitChoices value={unit} fixed />
                </div>
                <Input
                  aria-label={name}
                  type="number"
                  min="0"
                  step="any"
                  required
                  value={value}
                  onChange={(e) => change(e.target.value, unit)}
                  placeholder={`输入${name}数值`}
                  className="h-11 rounded-xl border-slate-200 bg-slate-50/50 shadow-none focus-visible:border-[#C8331F]/40 focus-visible:ring-[#C8331F]/10"
                />
                {fieldHint(`spec_params.${name}`, "spec_params")}
                {raw && !compatible && (
                  <p className="mt-1 text-xs text-amber-700">
                    原始规格：{raw}，请确认数值及单位
                  </p>
                )}
              </div>
            );
          })}
          <div className="space-y-2.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Label className="text-sm text-slate-700">
                数量 <span className="text-[#C8331F]">*</span>
              </Label>
              <UnitChoices
                value={form.unit}
                onChange={(unit) => {
                  set("unit", unit);
                }}
              />
            </div>
            <Input
              aria-label="数量"
              type="number"
              min="0"
              step="any"
              required
              value={form.quantity}
              onChange={(e) => {
                set("quantity", e.target.value);
              }}
              placeholder="输入数量"
              className="h-11 rounded-xl border-slate-200 bg-slate-50/50 shadow-none focus-visible:border-[#C8331F]/40 focus-visible:ring-[#C8331F]/10"
            />
            {fieldHint("quantity", "unit")}
          </div>
          <p className="text-xs text-slate-400">
            宽幅统一 mm，厚度统一 μm；1 丝/c = 10 μm。长度与重量不互相换算。
          </p>
          <details>
            <summary className="cursor-pointer text-xs text-slate-500">
              其他规格（如花纹）
            </summary>
            <div className="mt-3">
              <SpecParamRows
                rows={form.specParams.filter(
                  (row) =>
                    ![
                      "宽幅",
                      "宽度",
                      "幅宽",
                      "width",
                      "厚度",
                      "厚",
                      "thickness",
                    ].includes(row.key),
                )}
                onChange={(rows) => {
                  set("specParams", [
                    ...form.specParams.filter((row) =>
                      [
                        "宽幅",
                        "宽度",
                        "幅宽",
                        "width",
                        "厚度",
                        "厚",
                        "thickness",
                      ].includes(row.key),
                    ),
                    ...rows,
                  ]);
                }}
              />
            </div>
          </details>
        </div>
      </Section>

      {/* ── Section 3: 配方 ── */}
      <Section title="配方">
        {fieldHint("formula_id")}
        <div className="flex flex-wrap gap-5 mb-5">
          {(
            [
              ["none", "不选配方"],
              ["existing", "选择已有配方"],
              ["new", "新建配方"],
            ] as [FormulaMode, string][]
          )
            .filter(([mode]) => mode !== "new" || (!isPanel && canManage))
            .map(([mode, label]) => (
              <label
                key={mode}
                className="flex items-center gap-2 cursor-pointer"
              >
                <input
                  type="radio"
                  name={formulaGroup}
                  value={mode}
                  checked={form.formulaMode === mode}
                  onChange={() => {
                    setForm((f) => ({
                      ...f,
                      formulaMode: mode,
                      formulaId: "",
                      formulaMaterials: "",
                    }));
                  }}
                  className="accent-blue-600"
                />
                <span className="text-sm text-slate-700">{label}</span>
              </label>
            ))}
        </div>

        {/* Path A: 选择已有配方 */}
        {form.formulaMode === "existing" && (
          <div data-formula-selection className="space-y-4">
            <div className="space-y-1.5">
              <Label className="text-slate-700 text-sm font-medium">
                选择配方
              </Label>
              {filteredFormulas.length === 0 ? (
                <p className="text-sm text-slate-400 py-1">
                  {form.productId ? "暂无可选配方" : "请先选择产品"}
                </p>
              ) : (
                <select
                  aria-label="配方"
                  value={form.formulaId}
                  onChange={(e) => {
                    handleFormulaSelect(e.target.value);
                  }}
                  className="w-full h-9 rounded-md border border-slate-200 bg-white px-3 text-sm text-slate-800 focus:border-blue-400 focus:outline-none focus:ring-1 focus:ring-blue-400"
                >
                  <option value="">请选择配方</option>
                  {filteredFormulas.map((f) => {
                    const fp = products.find((p) => p.id === f.product_id);
                    const prefix =
                      fp && fp.id !== form.productId ? `[${fp.name}] ` : "";
                    return (
                      <option key={f.id} value={f.id}>
                        {prefix}
                        {formulaLabel(f)}
                      </option>
                    );
                  })}
                </select>
              )}
            </div>

            {form.formulaId && (
              <>
                <div className="space-y-1.5">
                  <Label className="text-slate-700 text-sm font-medium">
                    原材料及比例
                  </Label>
                  <Textarea
                    value={
                      isPanel
                        ? (formulas.find((f) => f.id === form.formulaId)
                            ?.materials ?? "")
                        : form.formulaMaterials
                    }
                    readOnly={isPanel || !canManage}
                    onChange={(e) => {
                      set("formulaMaterials", e.target.value);
                    }}
                    rows={4}
                    placeholder={"例：\nXX树脂 60%\nYY添加剂 30%"}
                    className="border-slate-200 focus:border-blue-400 focus:ring-blue-400 resize-none text-sm"
                  />
                </div>

                {formulaModified && !isPanel && canManage && (
                  <div className="flex gap-2 pt-1">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={handleUpdateFormula}
                      className="text-sm border-slate-200 text-slate-700 hover:border-blue-300 hover:text-blue-600"
                    >
                      更新此配方
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => {
                        setSaveFormulaName("");
                        setSaveFormulaError("");
                        setSaveFormulaOpen(true);
                      }}
                      className="text-sm border-slate-200 text-slate-700 hover:border-green-300 hover:text-green-600"
                    >
                      另存为新配方
                    </Button>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* Path B: 新建配方 */}
        {form.formulaMode === "new" && (
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label className="text-slate-700 text-sm font-medium">
                配方名称 <span className="text-red-400">*</span>
              </Label>
              <Input
                value={form.newFormulaName}
                onChange={(e) => {
                  set("newFormulaName", e.target.value);
                }}
                placeholder="如：PE-50μm-透明-001"
                className="border-slate-200 focus:border-blue-400 focus:ring-blue-400"
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-slate-700 text-sm font-medium">
                原材料及比例
              </Label>
              <Textarea
                value={form.newFormulaMaterials}
                onChange={(e) => {
                  set("newFormulaMaterials", e.target.value);
                }}
                rows={4}
                placeholder={"例：\nXX树脂 60%\nYY添加剂 30%\nZZ助剂 10%"}
                className="border-slate-200 focus:border-blue-400 focus:ring-blue-400 resize-none text-sm"
              />
            </div>
            <p className="text-xs text-slate-400">
              保存订单时将自动创建该配方并关联。
            </p>
          </div>
        )}

        {form.formulaMode === "none" && (
          <p className="text-sm text-slate-400">
            不关联配方，后续可在编辑订单时补充。
          </p>
        )}
      </Section>

      {/* ── Section 4: 额外要求 ── */}
      <Section title="额外要求">
        <Textarea
          aria-label="备注"
          value={form.extraNotes}
          onChange={(e) => {
            set("extraNotes", e.target.value);
          }}
          placeholder="可选：交期要求、包装规格、特殊注意事项…"
          rows={3}
          className="border-slate-200 focus:border-blue-400 focus:ring-blue-400 resize-none"
        />
      </Section>

      {error && (
        <div className="flex items-center justify-between gap-3 rounded-md border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-500">
          <span>{error}</span>
        </div>
      )}
    </>
  );

  return (
    <div
      className={
        isPanel
          ? `@container ${styles.compact}`
          : "@container max-w-3xl mx-auto py-8 px-4 space-y-5"
      }
    >
      <fieldset
        disabled={workspace?.disabled || saving || loadFailed}
        className="min-w-0 space-y-5"
      >
        {sections}
      </fieldset>
      {loadFailed && (
        <button
          type="button"
          onClick={() => void load()}
          className="text-sm text-red-600 underline"
        >
          重试加载
        </button>
      )}

      {!isPanel && (
        <div className="flex items-center justify-end gap-3 pt-2 pb-8">
          <Button
            type="button"
            variant="outline"
            onClick={handleCancel}
            className="border-slate-200 text-slate-600"
          >
            取消
          </Button>
          <Button
            type="button"
            onClick={handleSave}
            disabled={saving || loadFailed}
            className="bg-[#C8331F] hover:bg-[#a82a19] text-white px-6"
          >
            {submitLabel}
          </Button>
        </div>
      )}

      {/* ── Dialog: 新建客户 ── */}
      <Dialog
        open={newCustomerOpen}
        onOpenChange={(o) => !o && setNewCustomerOpen(false)}
      >
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle className="text-slate-800">新建客户</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-1.5">
              <Label className="text-slate-700 text-sm font-medium">
                公司名称 <span className="text-red-400">*</span>
              </Label>
              <Input
                value={newCustomerCompany}
                onChange={(e) => setNewCustomerCompany(e.target.value)}
                placeholder="如：华兴包装"
                className="border-slate-200 focus:border-blue-400 focus:ring-blue-400"
                onKeyDown={(e) => e.key === "Enter" && handleCreateCustomer()}
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-slate-700 text-sm font-medium">
                联系人姓名 <span className="text-red-400">*</span>
              </Label>
              <Input
                value={newCustomerContact}
                onChange={(e) => setNewCustomerContact(e.target.value)}
                placeholder="如：张三"
                className="border-slate-200 focus:border-blue-400 focus:ring-blue-400"
                onKeyDown={(e) => e.key === "Enter" && handleCreateCustomer()}
              />
            </div>
            {newCustomerError && (
              <p className="text-sm text-red-500 bg-red-50 border border-red-100 rounded-md px-3 py-2">
                {newCustomerError}
              </p>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setNewCustomerOpen(false)}
              className="border-slate-200 text-slate-600"
            >
              取消
            </Button>
            <Button
              onClick={handleCreateCustomer}
              disabled={newCustomerSaving || workspace?.disabled}
              className="bg-blue-600 hover:bg-blue-700 text-white"
            >
              {newCustomerSaving ? "创建中…" : "创建"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Dialog: 新建产品 ── */}
      <Dialog
        open={newProductOpen}
        onOpenChange={(o) => !o && setNewProductOpen(false)}
      >
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle className="text-slate-800">新建产品</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-1.5">
              <Label className="text-slate-700 text-sm font-medium">
                所属大类 <span className="text-red-400">*</span>
              </Label>
              <select
                value={newProductCategoryId}
                onChange={(e) => setNewProductCategoryId(e.target.value)}
                className="w-full h-9 rounded-md border border-slate-200 bg-white px-3 text-sm text-slate-800 focus:border-blue-400 focus:outline-none focus:ring-1 focus:ring-blue-400"
              >
                <option value="">请选择</option>
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <Label className="text-slate-700 text-sm font-medium">
                产品名称 <span className="text-red-400">*</span>
              </Label>
              <Input
                value={newProductName}
                onChange={(e) => setNewProductName(e.target.value)}
                placeholder="如：透明 PE 拉伸膜"
                className="border-slate-200 focus:border-blue-400 focus:ring-blue-400"
                onKeyDown={(e) => e.key === "Enter" && handleCreateProduct()}
              />
            </div>
            {newProductError && (
              <p className="text-sm text-red-500 bg-red-50 border border-red-100 rounded-md px-3 py-2">
                {newProductError}
              </p>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setNewProductOpen(false)}
              className="border-slate-200 text-slate-600"
            >
              取消
            </Button>
            <Button
              onClick={handleCreateProduct}
              disabled={newProductSaving || workspace?.disabled}
              className="bg-blue-600 hover:bg-blue-700 text-white"
            >
              {newProductSaving ? "创建中…" : "创建"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Dialog: 另存为新配方 ── */}
      <Dialog
        open={saveFormulaOpen}
        onOpenChange={(o) => !o && setSaveFormulaOpen(false)}
      >
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle className="text-slate-800">另存为新配方</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <p className="text-xs text-slate-500">
              当前修改将保存为一个新配方，原配方保持不变。
            </p>
            <div className="space-y-1.5">
              <Label className="text-slate-700 text-sm font-medium">
                新配方名称 <span className="text-red-400">*</span>
              </Label>
              <Input
                value={saveFormulaName}
                onChange={(e) => setSaveFormulaName(e.target.value)}
                placeholder="如：PE-50μm-透明-改"
                className="border-slate-200 focus:border-blue-400 focus:ring-blue-400"
                onKeyDown={(e) => e.key === "Enter" && handleSaveAsNewFormula()}
              />
            </div>
            {saveFormulaError && (
              <p className="text-sm text-red-500 bg-red-50 border border-red-100 rounded-md px-3 py-2">
                {saveFormulaError}
              </p>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setSaveFormulaOpen(false)}
              className="border-slate-200 text-slate-600"
            >
              取消
            </Button>
            <Button
              onClick={handleSaveAsNewFormula}
              disabled={saveFormulaSaving}
              className="bg-blue-600 hover:bg-blue-700 text-white"
            >
              {saveFormulaSaving ? "保存中…" : "保存"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
