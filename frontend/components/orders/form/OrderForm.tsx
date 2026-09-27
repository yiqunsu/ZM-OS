"use client";

import { Button } from "@/components/ui/button";
import type { OrderFormProps } from "./model";
import { useOrderForm } from "./useOrderForm";
import OrderSections from "./OrderSections";
import MasterDataDialogs from "./MasterDataDialogs";
import styles from "./OrderForm.module.css";

export default function OrderForm(props: OrderFormProps) {
  const controller = useOrderForm(props);
  const {
    loading,
    handleCancel,
    handleSave,
    isPanel,
    load,
    loadFailed,
    saving,
    submitLabel,
    workspace,
  } = controller;
  if (loading) {
    return <div className="py-16 text-center text-sm text-slate-400">加载中…</div>;
  }

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
        <OrderSections controller={controller} />
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

      <MasterDataDialogs controller={controller} />
    </div>
  );
}
