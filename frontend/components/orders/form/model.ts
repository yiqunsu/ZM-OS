export interface Category {
  id: string;
  name: string;
}
export interface Product {
  id: string;
  name: string;
  category_id: string;
  category: Category;
}
export interface Customer {
  id: string;
  company: string;
  contact: string;
}
export interface Formula {
  id: string;
  name: string;
  product_id: string;
  spec_params: Record<string, string>;
  materials: string;
  notes: string | null;
}

export interface SpecParam {
  key: string;
  value: string;
  [k: string]: string;
}
export type FormulaMode = "none" | "existing" | "new";

export interface FormState {
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

export const emptyForm: FormState = {
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
export function specParamsToObj(rows: SpecParam[]): Record<string, string> {
  const obj: Record<string, string> = {};
  rows.forEach(({ key, value }) => {
    if (key.trim()) obj[key.trim()] = value.trim();
  });
  return obj;
}

export function objToSpecParams(obj: Record<string, string>): SpecParam[] {
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
export function formulaLabel(f: Formula): string {
  const parts: string[] = [f.name];
  const hints = Object.entries(f.spec_params ?? {})
    .slice(0, 2)
    .map(([k, v]) => `${k}:${v}`)
    .join(" ");
  if (hints) parts.push(hints);
  if (f.notes?.trim()) parts.push(`备注:${f.notes.trim()}`);
  return parts.join("  ·  ");
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

export interface OrderFormProps {
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

export function initialForm(draft?: OrderDraft): FormState {
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
