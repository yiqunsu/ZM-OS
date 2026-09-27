"use client";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import type { OrderFormController } from "./useOrderForm";

export default function MasterDataDialogs({ controller }: { controller: OrderFormController }) {
  const {
    categories,
    handleCreateCustomer,
    handleCreateProduct,
    handleSaveAsNewFormula,
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
    saveFormulaError,
    saveFormulaName,
    saveFormulaOpen,
    saveFormulaSaving,
    setNewCustomerCompany,
    setNewCustomerContact,
    setNewCustomerOpen,
    setNewProductCategoryId,
    setNewProductName,
    setNewProductOpen,
    setSaveFormulaName,
    setSaveFormulaOpen,
    workspace,
  } = controller;
  return (
    <>
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
    </>
  );
}
