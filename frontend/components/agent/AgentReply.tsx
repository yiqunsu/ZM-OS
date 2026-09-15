import { isAgentPresentation } from "./presentation"

// Only a small text-formatting subset is supported. Never interpret model HTML.
function InlineText({ text }: { text: string }) {
  return <>{text.split(/(\*\*[^*]+\*\*)/g).map((part, index) => part.startsWith("**") && part.endsWith("**")
    ? <strong key={index} className="font-semibold text-slate-900">{part.slice(2, -2)}</strong>
    : part)}</>
}

export default function AgentReply({ content, presentation }: { content: string; presentation?: unknown }) {
  const card = isAgentPresentation(presentation) ? presentation : null
  return <div className="space-y-4 whitespace-normal">
    <div className="space-y-2.5 break-words text-[13px] leading-7 text-slate-600">
      {content.split(/\n+/).filter(line => line.trim()).map((line, index) => {
        const bullet = /^\s*(?:[-*]|\d+[.)、])\s+/.test(line)
        const heading = /^#{1,6}\s+/.test(line)
        const text = line.replace(/^\s*(?:#{1,6}\s+|[-*]\s+|\d+[.)、]\s+)/, "")
        return <div key={index} className={bullet ? "flex items-start gap-2" : heading ? "font-semibold text-slate-800" : undefined}>
          {bullet && <span aria-hidden="true" className="mt-3 h-1 w-1 shrink-0 rounded-full bg-slate-400" />}
          <span><InlineText text={text} /></span>
        </div>
      })}
    </div>
    {card && <section aria-label={card.title} className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center justify-between gap-2 border-b border-slate-100 px-4 py-3"><h3 className="text-sm font-semibold text-slate-800">{card.title}</h3><span className="shrink-0 rounded-full bg-slate-100 px-2 py-1 text-[10px] text-slate-500">{card.kind === "schedule" ? "草案 · 非执行凭证" : "查询结果"}</span></div>
      <div className="grid grid-cols-3 gap-2 bg-slate-50/80 px-4 py-4">{card.metrics.map((metric, index) => <div key={index}><p className="text-xl font-semibold tabular-nums text-slate-900">{metric.value}</p><p className="mt-1 text-[10px] text-slate-400">{metric.label}</p></div>)}</div>
      {card.rows.length > 0 && <details className="px-4 py-3"><summary className="cursor-pointer text-xs font-medium text-slate-600">机器分布 · {card.rows.length} 台</summary><dl className="mt-2 divide-y divide-slate-100">{card.rows.map((row, index) => <div key={index} className="flex justify-between gap-3 py-2 text-xs"><dt className="text-slate-700">{row.label}</dt><dd className="text-right text-slate-400">{row.detail}</dd></div>)}</dl></details>}
      {card.warnings.length > 0 && <details open className="mx-3 mb-3 rounded-lg bg-amber-50 px-3 py-2.5"><summary className="cursor-pointer text-xs font-medium text-amber-800">需要处理 · {card.warnings.length} 项</summary><ul className="mt-2 max-h-48 space-y-2 overflow-y-auto text-xs leading-5 text-amber-700">{card.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></details>}
      <div className="border-t border-slate-100 px-4 py-3"><p className="mb-1 text-[10px] font-semibold text-slate-500">{card.kind === "schedule" ? "下一步" : "提示"}</p><p className="text-xs leading-5 text-slate-500">{card.next_step}</p></div>
    </section>}
  </div>
}
