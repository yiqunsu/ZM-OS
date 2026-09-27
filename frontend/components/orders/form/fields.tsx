"use client";

import { useId } from "react";
import { Input } from "@/components/ui/input";
import type { SpecParam } from "./model";

export function SpecParamRows({
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
export function UnitChoices({
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

export function Section({
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
