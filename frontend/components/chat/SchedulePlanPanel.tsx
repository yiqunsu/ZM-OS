import type { SchedulePlan } from "@/components/chat/types"

interface SchedulePlanPanelProps {
  plan: SchedulePlan
  onConfirmRequest: () => void
  disabled: boolean
}

export default function SchedulePlanPanel({
  plan,
  onConfirmRequest,
  disabled,
}: SchedulePlanPanelProps) {
  const assignedCount = plan.tasks.reduce((total, task) => total + task.order_ids.length, 0)

  return (
    <div className="flex flex-1 min-h-0 flex-col">
      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        <div className="grid grid-cols-3 gap-2">
          <Summary value={plan.tasks.length} label="生产任务" />
          <Summary value={assignedCount} label="已排订单" />
          <Summary value={plan.unassigned.length} label="未排订单" />
        </div>

        {plan.tasks.length === 0 ? (
          <div className="rounded-xl border border-slate-200 bg-white p-5 text-sm text-slate-500">
            当前没有可执行的生产任务，请查看下方未排原因。
          </div>
        ) : (
          plan.tasks.map((task, index) => (
            <section key={`${task.machine_id}-${index}`} className="rounded-xl border border-slate-200 bg-white shadow-sm">
              <div className="flex items-start justify-between border-b border-slate-100 px-4 py-3">
                <div>
                  <h3 className="text-sm font-semibold text-slate-800">{task.machine_name}</h3>
                  <p className="mt-0.5 text-xs text-slate-400">任务 {index + 1}</p>
                </div>
                <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700">
                  合并宽度 {Number(task.total_width.toFixed(2))}mm
                </span>
              </div>
              <div className="space-y-3 px-4 py-3">
                <div className="flex flex-wrap gap-1.5">
                  {task.order_nos.map((orderNo) => (
                    <span key={orderNo} className="rounded-md bg-slate-100 px-2 py-1 text-xs font-medium text-slate-700">
                      {orderNo}
                    </span>
                  ))}
                </div>
                <p className="text-xs leading-relaxed text-slate-500">{task.reason}</p>
              </div>
            </section>
          ))
        )}

        {plan.unassigned.length > 0 && (
          <section className="rounded-xl border border-amber-200 bg-amber-50">
            <div className="border-b border-amber-200 px-4 py-3 text-sm font-semibold text-amber-800">
              暂未排入
            </div>
            <div className="divide-y divide-amber-100">
              {plan.unassigned.map((item) => (
                <div key={item.order_id} className="px-4 py-3">
                  <div className="text-xs font-semibold text-amber-900">{item.order_no}</div>
                  <div className="mt-1 text-xs leading-relaxed text-amber-700">{item.reason}</div>
                </div>
              ))}
            </div>
          </section>
        )}
      </div>

      <div className="shrink-0 border-t border-slate-200 bg-white px-4 py-3">
        <button
          type="button"
          onClick={onConfirmRequest}
          disabled={disabled || plan.tasks.length === 0}
          className="w-full rounded-lg bg-[#C8331F] px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-[#a82a19] disabled:cursor-not-allowed disabled:opacity-50"
        >
          请求确认并执行排产
        </button>
        <p className="mt-2 text-center text-[11px] text-slate-400">确认时后端会重新校验订单和机器状态</p>
      </div>
    </div>
  )
}

function Summary({ value, label }: { value: number; label: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-2 py-3 text-center">
      <div className="text-lg font-semibold text-slate-800">{value}</div>
      <div className="text-[11px] text-slate-400">{label}</div>
    </div>
  )
}
