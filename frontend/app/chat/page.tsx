"use client"

import { useEffect, useRef, useState } from "react"
import ChatInterface from "@/components/chat/ChatInterface"
import { api } from "@/lib/api"

interface Session {
  id: string
  title: string
  created_at: string
  message_count?: number
}

function SessionList({
  sessions, activeSessionId, onSelect, onNew, onDelete,
}: {
  sessions: Session[]
  activeSessionId: string | null
  onSelect: (id: string) => void
  onNew: () => void
  onDelete: (id: string, e: React.MouseEvent) => void
}) {
  return (
    <>
      <div className="px-3 py-3 border-b border-slate-100">
        <button
          onClick={onNew}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium text-slate-600 hover:bg-slate-100 transition-colors"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
          </svg>
          新建对话
        </button>
      </div>
      <div className="flex-1 overflow-y-auto py-1">
        {sessions.length === 0 ? (
          <p className="text-xs text-slate-400 text-center mt-6 px-3">暂无历史对话</p>
        ) : (
          sessions.map((s) => (
            <div
              key={s.id}
              className={`group relative flex items-center transition-colors hover:bg-slate-50 ${
                activeSessionId === s.id ? "bg-green-50 border-r-2 border-green-500" : ""
              }`}
            >
              <button
                onClick={() => onSelect(s.id)}
                className={`flex-1 text-left px-3 py-2.5 text-xs min-w-0 ${
                  activeSessionId === s.id ? "text-green-700 font-medium" : "text-slate-600"
                }`}
              >
                <div className="flex items-center gap-1.5">
                  <svg className="w-3 h-3 shrink-0 opacity-50" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z" />
                  </svg>
                  <span className="truncate">{s.title}</span>
                </div>
              </button>
              <button
                onClick={(e) => onDelete(s.id, e)}
                className="opacity-0 group-hover:opacity-100 shrink-0 mr-2 w-5 h-5 flex items-center justify-center rounded hover:bg-red-100 text-slate-400 hover:text-red-500 transition-all"
                title="删除对话"
              >
                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          ))
        )}
      </div>
    </>
  )
}

export default function ChatPage() {
  const [sessions, setSessions] = useState<Session[]>([])
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
  const [chatKey, setChatKey] = useState(0)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const activeSessionIdRef = useRef<string | null>(null)
  useEffect(() => { activeSessionIdRef.current = activeSessionId }, [activeSessionId])

  const loadSessions = async () => {
    try {
      setSessions(await api.get<Session[]>("/agent/sessions"))
    } catch {
      // ignore
    }
  }

  useEffect(() => { loadSessions() }, [])

  const deleteSession = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation()
    await api.delete(`/agent/sessions/${id}`)
    setSessions((prev) => prev.filter((s) => s.id !== id))
    if (activeSessionIdRef.current === id) goNew()
  }

  const createSession = async (): Promise<string> => {
    const session = await api.post<Session>("/agent/sessions", {})
    setSessions((prev) => [session, ...prev])
    setActiveSessionId(session.id)
    return session.id
  }

  const selectSession = (id: string) => {
    if (id === activeSessionIdRef.current) return
    setActiveSessionId(id)
    setChatKey((k) => k + 1)
    setDrawerOpen(false)
  }

  const goNew = () => {
    setActiveSessionId(null)
    setChatKey((k) => k + 1)
    setDrawerOpen(false)
  }

  return (
    <div className="flex h-[calc(100dvh-64px)] md:h-screen">
      <aside className="hidden md:flex w-56 shrink-0 flex-col border-r border-slate-200 bg-white">
        <SessionList
          sessions={sessions}
          activeSessionId={activeSessionId}
          onSelect={selectSession}
          onNew={goNew}
          onDelete={deleteSession}
        />
      </aside>

      {drawerOpen && (
        <div className="md:hidden fixed inset-0 z-50 flex">
          <div className="absolute inset-0 bg-black/40" onClick={() => setDrawerOpen(false)} />
          <div className="relative w-72 max-w-[85vw] bg-white flex flex-col shadow-2xl">
            <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
              <span className="text-sm font-semibold text-slate-700">历史对话</span>
              <button
                onClick={() => setDrawerOpen(false)}
                className="w-7 h-7 flex items-center justify-center rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <SessionList
              sessions={sessions}
              activeSessionId={activeSessionId}
              onSelect={selectSession}
              onNew={goNew}
              onDelete={deleteSession}
            />
          </div>
        </div>
      )}

      <div className="flex flex-col flex-1 overflow-hidden">
        <header className="shrink-0 bg-white border-b border-slate-200">
          <div className="px-4 md:px-6 flex items-center h-14 gap-3">
            <button
              onClick={() => setDrawerOpen(true)}
              className="md:hidden w-8 h-8 flex items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 transition-colors"
              title="历史对话"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
              </svg>
            </button>
            <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-green-500 to-emerald-600 flex items-center justify-center shadow-sm shrink-0">
              <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z" />
              </svg>
            </div>
            <div className="min-w-0">
              <h1 className="text-sm font-semibold text-slate-800 leading-tight">AI 助手</h1>
              <p className="text-xs text-slate-400 leading-tight truncate">
                {activeSessionId
                  ? sessions.find((s) => s.id === activeSessionId)?.title ?? "对话进行中"
                  : "DeepSeek · 智能录单 & 排单"}
              </p>
            </div>
          </div>
        </header>

        <ChatInterface
          key={chatKey}
          sessionId={activeSessionId}
          onSessionCreated={createSession}
        />
      </div>
    </div>
  )
}
