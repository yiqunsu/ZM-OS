import OrderForm from "@/components/orders/OrderForm";

export default async function EditOrderPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <>
      <header className="sticky top-0 z-40 bg-white border-b border-slate-200 shadow-sm">
        <div className="px-8 flex items-center h-14">
          <h1 className="text-base font-semibold text-slate-800">编辑订单</h1>
        </div>
      </header>
      <main className="flex-1 bg-slate-50">
        <OrderForm orderId={id} />
      </main>
    </>
  );
}
