"use client";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Section, SpecParamRows, UnitChoices } from "./fields";
import type { FormulaMode } from "./model";
import { formulaLabel } from "./model";
import type { OrderFormController } from "./useOrderForm";
import OrderFieldHint from "./OrderFieldHint";

export default function OrderSections({ controller }: { controller: OrderFormController }) {
  const {
    canManage,
    categories,
    customers,
    error,
    filteredFormulas,
    form,
    formulaGroup,
    formulaModified,
    formulas,
    handleFormulaSelect,
    handleUpdateFormula,
    isPanel,
    products,
    set,
    setForm,
    setNewCustomerError,
    setNewCustomerOpen,
    setNewProductCategoryId,
    setNewProductError,
    setNewProductOpen,
    setSaveFormulaError,
    setSaveFormulaName,
    setSaveFormulaOpen,
    workspace,
  } = controller;
  function fieldHint(...fields: string[]) {
    const issues = workspace?.issues?.filter((issue) => fields.includes(issue.field)) ?? [];
    if (!issues.length) return null;
    const names: Record<string, string> = {customer_id: "客户", product_id: "产品", quantity: "数量", formula_id: "配方"};
    return <OrderFieldHint issues={issues} label={names[fields[0]] ?? fields[0].replace("spec_params.", "")} />;
  }

  return (
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
}
