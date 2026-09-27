"use client";

import { useCallback, useEffect, useId, useState } from "react";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { api, ApiError } from "@/lib/api";
import { initialForm, objToSpecParams, specParamsToObj } from "./model";
import type { Category, Product, Customer, Formula, FormState, OrderFormProps } from "./model";

export function useOrderForm({ orderId, workspace }: OrderFormProps) {
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

  const submitLabel = saving ? "保存中…" : isEdit ? "保存修改" : "创建订单";
  const handleCancel = () => router.back();

  return {
    loading,
    canManage,
    categories,
    customers,
    error,
    filteredFormulas,
    form,
    formulaGroup,
    formulaModified,
    formulas,
    handleCancel,
    handleCreateCustomer,
    handleCreateProduct,
    handleFormulaSelect,
    handleSave,
    handleSaveAsNewFormula,
    handleUpdateFormula,
    isPanel,
    load,
    loadFailed,
    newCustomerCompany,
    newCustomerContact,
    newCustomerError,
    newCustomerOpen,
    newCustomerSaving,
    newProductCategoryId,
    newProductError,
    newProductName,
    newProductOpen,
    newProductSaving,
    products,
    saveFormulaError,
    saveFormulaName,
    saveFormulaOpen,
    saveFormulaSaving,
    saving,
    set,
    setForm,
    setNewCustomerCompany,
    setNewCustomerContact,
    setNewCustomerError,
    setNewCustomerOpen,
    setNewProductCategoryId,
    setNewProductError,
    setNewProductName,
    setNewProductOpen,
    setSaveFormulaError,
    setSaveFormulaName,
    setSaveFormulaOpen,
    submitLabel,
    workspace,
  };
}

export type OrderFormController = ReturnType<typeof useOrderForm>;
