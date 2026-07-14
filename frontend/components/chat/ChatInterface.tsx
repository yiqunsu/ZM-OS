"use client"

import { useEffect, useRef, useState } from "react"
import { api, postStream } from "@/lib/api"

// ─── 类型 ──────────────────────────────────────────────────────────────────────

interface ToolCall {
  function: { name: string; arguments: string }
}

interface ChatMessage {
  id: string
  role: string
  content: string | null
  tool_calls: ToolCall[] | null
  tool_call_id: string | null
  tool_name: string | null
  is_pending: boolean
  created_at: string
}

interface PendingToolCall {
  id: string
  name: string
  args: Record<string, unknown>
  display?: Record<string, unknown>
}

interface Props {
  sessionId: string | null
  onSessionCreated: () => Promise<string>
}

const TOOL_LABELS: Record<string, string> = {
  confirm_and_create_order: "创建订单",
  update_order: "修改订单",
  confirm_and_execute: "执行排单",
}

// ─── Row 辅助组件 ──────────────────────────────────────────────────────────────

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-2">
      <span className="text-slate-400 shrink-0 w-20 text-right text-xs pt-0.5">{label}</span>
      <span className="text-slate-700 font-medium text-xs break-all">{value}</span>
    </div>
  )
}

// ─── 确认卡片 ──────────────────────────────────────────────────────────────────

function ConfirmCard({
  toolCall, onConfirm, onCancel, isSubmitting,
}: {
  toolCall: PendingToolCall
  onConfirm: () => void
  onCancel: () => void
  isSubmitting: boolean
}) {
  const label = TOOL_LABELS[toolCall.name] ?? toolCall.name
  const d = toolCall.display ?? {}

  const renderDetail = () => {
    if (toolCall.name === "confirm_and_create_order") {
      const spec = d.spec_params as Record<string, string> | undefined
      return (
        <div className="space-y-1.5">
          {!!d.customer && <Row label="客户" value={String(d.customer)} />}
          {!!d.product && <Row label="产品" value={String(d.product)} />}
          {spec && Object.entries(spec).map(([k, v]) => <Row key={k} label={k} value={v} />)}
          {d.quantity != null && <Row label="数量" value={`${String(d.quantity)} ${String(d.unit ?? "")}`} />}
          {!!d.formula_name && (
            <>
              <div className="border-t border-amber-200 my-1.5" />
              <Row label="配方" value={String(d.formula_name)} />
              {!!d.formula_notes && <Row label="配方备注" value={String(d.formula_notes)} />}
            </>
          )}
          {!!d.extra_notes && (
            <>
              <div className="border-t border-amber-200 my-1.5" />
              <Row label="其他要求" value={String(d.extra_notes)} />
            </>
          )}
        </div>
      )
    }
    if (toolCall.name === "update_order") {
      const changes = d.changes as Record<string, unknown> | undefined
      return (
        <div className="space-y-1.5">
          {!!d.order_no && <Row label="订单号" value={String(d.order_no)} />}
          {!!d.customer && <Row label="客户" value={String(d.customer)} />}
          {changes && Object.entries(changes).map(([k, v]) => (
            <Row key={k} label={`修改·${k}`} value={typeof v === "object" ? JSON.stringify(v) : String(v)} />
          ))}
        </div>
      )
    }
    if (toolCall.name === "confirm_and_execute") {
      type EnrichedTask = { machine_name: string; order_nos: string[] }
      const tasks = d.tasks as EnrichedTask[] | undefined
      return (
        <div className="space-y-1.5">
          <Row label="任务总数" value={`${String(d.task_count ?? 0)} 个`} />
          <Row label="订单总数" value={`${String(d.order_count ?? 0)} 张`} />
          {tasks && tasks.length > 0 && (
            <>
              <div className="border-t border-amber-200 my-1.5" />
              {tasks.map((t, i) => (
                <div key={i} className="space-y-0.5">
                  <Row label={`任务${i + 1}`} value={t.machine_name} />
                  {t.order_nos.map((no) => <Row key={no} label="　└ 订单" value={no} />)}
                </div>
              ))}
            </>
          )}
        </div>
      )
    }
    const fallback = Object.keys(d).length > 0 ? d : toolCall.args
    return (
      <div className="space-y-1.5">
        {Object.entries(fallback).map(([k, v]) => (
          <Row key={k} label={k} value={typeof v === "object" ? JSON.stringify(v) : String(v)} />
        ))}
      </div>
    )
  }

  return (
    <div className="mx-4 mb-2">
      <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
        <div className="flex items-center gap-2 mb-3">
          <div className="w-5 h-5 rounded-full bg-amber-400 flex items-center justify-center shrink-0">
            <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9 3.75h.008v.008H12v-.008Z" />
            </svg>
          </div>
          <span className="text-sm font-semibold text-amber-800">即将执行：{label}</span>
        </div>
        <div className="pl-7 mb-4">{renderDetail()}</div>
        <div className="pl-7 flex gap-2">
          <button
            onClick={onConfirm}
            disabled={isSubmitting}
            className="px-4 py-1.5 rounded-lg bg-green-600 hover:bg-green-700 disabled:opacity-50 text-white text-sm font-medium transition-colors"
          >
            {isSubmitting ? "执行中…" : "✓ 确认"}
          </button>
          <button
            onClick={onCancel}
            disabled={isSubmitting}
            className="px-4 py-1.5 rounded-lg border border-slate-200 hover:bg-slate-100 disabled:opacity-50 text-slate-600 text-sm font-medium transition-colors"
          >
            取消
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── 消息气泡 ──────────────────────────────────────────────────────────────────

function MessageBubble({ msg }: { msg: ChatMessage }) {
  if (msg.role === "tool") return null
  if (msg.tool_calls) return null
  if (!msg.content?.trim()) return null

  const isUser = msg.role === "user"
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-3 px-4`}>
      {!isUser && (
        <div className="w-7 h-7 rounded-full bg-gradient-to-br from-green-500 to-emerald-600 flex items-center justify-center shrink-0 mr-2 mt-0.5">
          <svg className="w-3.5 h-3.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z" />
          </svg>
        </div>
      )}
      <div
        className={`max-w-[78%] px-4 py-2.5 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap ${
          isUser
            ? "bg-green-600 text-white rounded-br-sm"
            : "bg-white border border-slate-200 text-slate-800 shadow-sm rounded-bl-sm"
        }`}
      >
        {msg.content ?? ""}
      </div>
    </div>
  )
}

const HINTS = ["录入新订单", "帮我排单", "查看待排单", "查询客户列表"]

// ─── 主组件 ───────────────────────────────────────────────────────────────────

export default function ChatInterface({ sessionId, onSessionCreated }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const [isLoadingHistory, setIsLoadingHistory] = useState(false)
  const [isConfirming, setIsConfirming] = useState(false)
  const [pendingToolCall, setPendingToolCall] = useState<PendingToolCall | null>(null)
  const [error, setError] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const isLoadingRef = useRef(false)
  useEffect(() => { isLoadingRef.current = isLoading }, [isLoading])
  const isSendingRef = useRef(false)

  useEffect(() => {
    if (isLoadingRef.current) return
    setMessages([])
    setPendingToolCall(null)
    setError(null)
    if (!sessionId) return

    let cancelled = false
    setIsLoadingHistory(true)
    api.get<ChatMessage[]>(`/agent/chat?session_id=${sessionId}`)
      .then((data) => {
        if (cancelled) return
        setMessages(data)
        const pending = data.find((m) => m.is_pending && m.tool_calls)
        if (pending?.tool_calls) {
          const tc = pending.tool_calls[0]
          setPendingToolCall({
            id: pending.id,
            name: tc.function.name,
            args: JSON.parse(tc.function.arguments),
          })
        }
      })
      .catch(() => { if (!cancelled) setError("加载历史消息失败，请刷新页面") })
      .finally(() => { if (!cancelled) setIsLoadingHistory(false) })
    return () => { cancelled = true }
  }, [sessionId])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, pendingToolCall])

  function handleInputChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setInput(e.target.value)
    e.target.style.height = "auto"
    e.target.style.height = Math.min(e.target.scrollHeight, 160) + "px"
  }

  /** Consume an SSE stream, managing a live streaming assistant bubble. */
  async function consumeStream(res: Response) {
    const reader = res.body!.getReader()
    const decoder = new TextDecoder()
    let buf = ""
    let streamMsgId: string | null = null
    let streamContent = ""

    const ensureBubble = () => {
      if (!streamMsgId) {
        setIsLoading(false)
        streamMsgId = `stream-${Date.now()}`
        const sid = streamMsgId
        setMessages((prev) => [...prev, {
          id: sid, role: "assistant", content: streamContent,
          tool_calls: null, tool_call_id: null, tool_name: null,
          is_pending: false, created_at: new Date().toISOString(),
        }])
      }
    }

    outer: while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const lines = buf.split("\n")
      buf = lines.pop() ?? ""
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue
        const raw = line.slice(6).trim()
        if (!raw) continue
        let event: Record<string, unknown>
        try { event = JSON.parse(raw) } catch { continue }

        if (event.type === "delta") {
          streamContent += event.content as string
          ensureBubble()
          const sid = streamMsgId
          const snap = streamContent
          setMessages((prev) => prev.map((m) => m.id === sid ? { ...m, content: snap } : m))
        } else if (event.type === "cancel_delta") {
          if (streamMsgId) {
            const sid = streamMsgId
            setMessages((prev) => prev.filter((m) => m.id !== sid))
            streamMsgId = null
            streamContent = ""
            setIsLoading(true)
          }
        } else if (event.type === "text_done") {
          const sid = streamMsgId
          setMessages((prev) => prev.map((m) =>
            m.id === sid ? { ...m, id: event.message_id as string } : m
          ))
          break outer
        } else if (event.type === "pending_confirmation") {
          setPendingToolCall(event.tool_call as PendingToolCall)
          break outer
        } else if (event.type === "error") {
          setError(event.error as string)
          if (streamMsgId) {
            const sid = streamMsgId
            setMessages((prev) => prev.filter((m) => m.id !== sid))
          }
          break outer
        }
      }
    }
  }

  async function handleSend() {
    const text = input.trim()
    if (!text || isLoading || pendingToolCall || isSendingRef.current) return

    isSendingRef.current = true
    setIsLoading(true)
    setInput("")
    setError(null)
    if (textareaRef.current) textareaRef.current.style.height = "auto"

    let activeSessionId = sessionId
    if (!activeSessionId) {
      try {
        activeSessionId = await onSessionCreated()
      } catch {
        setError("创建对话失败，请重试")
        setIsLoading(false)
        isSendingRef.current = false
        return
      }
    }

    const tempId = `temp-${Date.now()}`
    setMessages((prev) => [...prev, {
      id: tempId, role: "user", content: text,
      tool_calls: null, tool_call_id: null, tool_name: null,
      is_pending: false, created_at: new Date().toISOString(),
    }])

    try {
      const res = await postStream("/agent/chat", { content: text, session_id: activeSessionId })
      await consumeStream(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : "网络错误，请重试")
      setMessages((prev) => prev.filter((m) => m.id !== tempId))
    } finally {
      setIsLoading(false)
      isSendingRef.current = false
    }
  }

  async function handleConfirm() {
    if (!pendingToolCall || isConfirming || !sessionId) return
    setIsConfirming(true)
    setError(null)
    setPendingToolCall(null)
    setIsLoading(true)
    try {
      const res = await postStream("/agent/chat/confirm", { session_id: sessionId })
      await consumeStream(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : "确认失败")
    } finally {
      setIsConfirming(false)
      setIsLoading(false)
    }
  }

  async function handleCancel() {
    if (!pendingToolCall || isConfirming || !sessionId) return
    setIsConfirming(true)
    setError(null)
    setPendingToolCall(null)
    setIsLoading(true)
    try {
      const res = await postStream("/agent/chat/cancel", { session_id: sessionId })
      await consumeStream(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : "取消失败")
    } finally {
      setIsConfirming(false)
      setIsLoading(false)
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend() }
  }

  const isInputDisabled = isLoading || !!pendingToolCall

  return (
    <div className="flex flex-col flex-1 overflow-hidden bg-slate-50">
      <div className="flex-1 overflow-y-auto py-4">
        {isLoadingHistory && (
          <div className="flex flex-col items-center justify-center h-full text-center pb-20">
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 bg-green-400 rounded-full animate-bounce [animation-delay:0ms]" />
              <span className="w-2 h-2 bg-green-400 rounded-full animate-bounce [animation-delay:150ms]" />
              <span className="w-2 h-2 bg-green-400 rounded-full animate-bounce [animation-delay:300ms]" />
            </div>
            <p className="text-slate-400 text-sm mt-3">加载历史对话…</p>
          </div>
        )}

        {messages.length === 0 && !isLoading && !isLoadingHistory && (
          <div className="flex flex-col items-center justify-center h-full text-center px-8 pb-20">
            <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-green-500 to-emerald-600 flex items-center justify-center mb-4 shadow-lg shadow-green-200">
              <svg className="w-7 h-7 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z" />
              </svg>
            </div>
            <p className="text-slate-700 font-semibold text-base mb-1">AI 助手已就绪</p>
            <p className="text-slate-400 text-sm max-w-xs mb-5">用自然语言录入订单、安排生产、查询数据</p>
            <div className="flex flex-wrap gap-2 justify-center">
              {HINTS.map((hint) => (
                <button
                  key={hint}
                  onClick={() => { setInput(hint); textareaRef.current?.focus() }}
                  className="px-3 py-1.5 rounded-full border border-slate-200 bg-white text-slate-500 text-xs hover:border-green-300 hover:text-green-600 transition-colors"
                >
                  {hint}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg) => <MessageBubble key={msg.id} msg={msg} />)}

        {isLoading && (
          <div className="flex justify-start mb-3 px-4">
            <div className="w-7 h-7 rounded-full bg-gradient-to-br from-green-500 to-emerald-600 flex items-center justify-center shrink-0 mr-2 mt-0.5">
              <svg className="w-3.5 h-3.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z" />
              </svg>
            </div>
            <div className="bg-white border border-slate-200 rounded-2xl rounded-bl-sm px-4 py-3 shadow-sm flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 bg-slate-300 rounded-full animate-bounce [animation-delay:0ms]" />
              <span className="w-1.5 h-1.5 bg-slate-300 rounded-full animate-bounce [animation-delay:150ms]" />
              <span className="w-1.5 h-1.5 bg-slate-300 rounded-full animate-bounce [animation-delay:300ms]" />
            </div>
          </div>
        )}

        {pendingToolCall && (
          <ConfirmCard
            toolCall={pendingToolCall}
            onConfirm={handleConfirm}
            onCancel={handleCancel}
            isSubmitting={isConfirming}
          />
        )}

        <div ref={bottomRef} />
      </div>

      {error && (
        <div className="mx-4 mb-2 px-4 py-2.5 rounded-lg bg-red-50 border border-red-100 text-sm text-red-600 flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="ml-3 text-red-400 hover:text-red-600 shrink-0">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      )}

      <div className="border-t border-slate-200 bg-white px-4 py-3">
        <div className={`flex items-end gap-2 rounded-xl border transition-all ${
          isInputDisabled
            ? "border-slate-100 bg-slate-50"
            : "border-slate-200 bg-white focus-within:border-green-400 focus-within:ring-2 focus-within:ring-green-100"
        }`}>
          <textarea
            ref={textareaRef}
            value={input}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            disabled={isInputDisabled}
            placeholder={pendingToolCall ? "请先处理上方的确认操作…" : "输入消息，Enter 发送，Shift+Enter 换行"}
            rows={1}
            className="flex-1 resize-none bg-transparent px-3 py-2.5 text-sm text-slate-800 placeholder:text-slate-400 outline-none disabled:cursor-not-allowed min-h-[40px] max-h-40"
          />
          <button
            onClick={handleSend}
            disabled={isInputDisabled || !input.trim()}
            className="mb-2 mr-2 w-8 h-8 rounded-lg bg-green-600 hover:bg-green-700 disabled:bg-slate-200 text-white flex items-center justify-center transition-colors shrink-0"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 12 3.269 3.125A59.769 59.769 0 0 1 21.485 12 59.768 59.768 0 0 1 3.27 20.875L5.999 12Zm0 0h7.5" />
            </svg>
          </button>
        </div>
        <p className="text-center text-xs text-slate-300 mt-2">AI 可能出错，重要操作请二次核对</p>
      </div>
    </div>
  )
}
