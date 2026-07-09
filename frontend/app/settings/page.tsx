"use client";

import { useState } from "react";
import CustomerTab from "@/components/settings/CustomerTab";
import MachineTab  from "@/components/settings/MachineTab";
import ProductTab  from "@/components/settings/ProductTab";
import FormulaTab  from "@/components/settings/FormulaTab";

const TABS = [
  { key: "customers", label: "客户" },
  { key: "machines",  label: "机器" },
  { key: "products",  label: "产品" },
  { key: "formulas",  label: "配方" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

export default function SettingsPage() {
  const [active, setActive] = useState<TabKey>("customers");

  return (
    <>
      <header className="sticky top-0 z-40 bg-white border-b border-slate-200 shadow-sm">
        {/* 手机端：两行 */}
        <div className="md:hidden">
          <div className="px-4 flex items-center h-14">
            <h1 className="text-base font-semibold text-slate-800">基础数据管理</h1>
          </div>
          <nav className="flex items-center border-t border-slate-100 px-2">
            {TABS.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActive(tab.key)}
                className={`relative flex-1 h-10 text-sm font-medium transition-colors ${
                  active === tab.key ? "text-blue-600" : "text-slate-500"
                }`}
              >
                {tab.label}
                {active === tab.key && (
                  <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-blue-600 rounded-full" />
                )}
              </button>
            ))}
          </nav>
        </div>
        {/* 桌面端：单行 */}
        <div className="hidden md:flex px-8 items-center h-14">
          <h1 className="text-base font-semibold text-slate-800 shrink-0 mr-8">基础数据管理</h1>
          <nav className="flex items-center h-14 gap-1">
            {TABS.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActive(tab.key)}
                className={`relative h-full px-4 text-sm font-medium transition-colors ${
                  active === tab.key ? "text-blue-600" : "text-slate-500 hover:text-slate-800"
                }`}
              >
                {tab.label}
                {active === tab.key && (
                  <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-blue-600 rounded-full" />
                )}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="flex-1 px-4 md:px-8 py-4 md:py-6">
        {active === "customers" && <CustomerTab />}
        {active === "machines"  && <MachineTab />}
        {active === "products"  && <ProductTab />}
        {active === "formulas"  && <FormulaTab />}
      </main>
    </>
  );
}
