"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import Image from "next/image"
import { useRouter } from "next/navigation"
import { api, postStream } from "@/lib/api"
import OrderForm, { type OrderDraft } from "@/components/orders/OrderForm"
import SchedulePlanPanel from "@/components/chat/SchedulePlanPanel"
import {
  isUserMessageCommittedEvent,
  type ChatMessage,
  type SchedulePlan,
} from "@/components/chat/types"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog"

// ─── 类型 ──────────────────────────────────────────────────────────────────────

interface PendingToolCall {
  id: string
  name: string
  args: Record<string, unknown>
  display?: Record<string, unknown>
}

interface ChatInterfaceProps {
  requestedSessionId?: string | null
}

const TOOL_LABELS: Record<string, string> = {
  submit_order_form: "下发当前订单",
  execute_schedule_plan: "执行排产方案",
  confirm_and_create_order: "创建订单",
  update_order: "修改订单",
  confirm_and_execute: "执行排单",
}

const ACCENT = "#C8331F"
const MAX_IMAGE_SIZE = 5 * 1024 * 1024
type SupportedImageMime = "image/jpeg" | "image/png"

interface StreamResult {
  succeeded: boolean
  userMessageId: string | null
  userMessageCommitted: boolean
}

interface WorkspaceSnapshot {
  active_workspace: "order_form" | "schedule_plan" | null
  order_draft: OrderDraft | null
  schedule_plan: SchedulePlan | null
}

let localMessageSequence = 0

function createLocalMessageId(prefix: string): string {
  localMessageSequence += 1
  return `${prefix}-${Date.now()}-${localMessageSequence}`
}

function attachmentMediaUrl(attachmentId: string): string {
  return `/media/chat-attachments/${encodeURIComponent(attachmentId)}`
}

function supportedImageMime(file: File): SupportedImageMime | null {
  const mime = file.type.toLowerCase()
  if (["image/jpeg", "image/jpg", "image/pjpeg"].includes(mime)) return "image/jpeg"
  if (["image/png", "image/x-png"].includes(mime)) return "image/png"

  // Some Safari clipboard/file paths leave the MIME empty. Only fall back to
  // the extension when the browser did not provide a meaningful image type.
  if (mime && mime !== "application/octet-stream") return null
  if (/\.jpe?g$/i.test(file.name)) return "image/jpeg"
  if (/\.png$/i.test(file.name)) return "image/png"
  return null
}

function normalizeImageFile(file: File, mime: SupportedImageMime): File {
  if (file.type === mime && file.name) return file
  const extension = mime === "image/png" ? "png" : "jpg"
  const name = file.name || `clipboard-image.${extension}`
  return new File([file], name, { type: mime, lastModified: file.lastModified })
}

function clipboardImageFiles(clipboardData: DataTransfer): File[] {
  const itemFiles: File[] = []

  for (const item of Array.from(clipboardData.items)) {
    if (item.kind !== "file") continue
    const file = item.getAsFile()
    if (!file) continue
    itemFiles.push(
      (!file.type || file.type.toLowerCase() === "application/octet-stream") && item.type
        ? new File([file], file.name, { type: item.type, lastModified: file.lastModified })
        : file,
    )
  }

  // Chrome commonly exposes the same clipboard entries through both lists,
  // while Safari may populate only one. Reconcile them as multisets so the
  // duplicate representation is removed without collapsing two real images
  // that happen to have identical metadata.
  const files = [...itemFiles]
  const remainingItemMatches = new Map<string, number>()
  for (const file of itemFiles) {
    const key = `${file.name}\u0000${file.size}\u0000${file.lastModified}`
    remainingItemMatches.set(key, (remainingItemMatches.get(key) ?? 0) + 1)
  }
  for (const file of Array.from(clipboardData.files)) {
    const key = `${file.name}\u0000${file.size}\u0000${file.lastModified}`
    const remaining = remainingItemMatches.get(key) ?? 0
    if (remaining > 0) {
      remainingItemMatches.set(key, remaining - 1)
    } else {
      files.push(file)
    }
  }

  return files.filter((file) => {
    const isImage = file.type.toLowerCase().startsWith("image/") || /\.(?:jpe?g|png)$/i.test(file.name)
    return isImage
  })
}

function readImageAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      if (typeof reader.result === "string") resolve(reader.result)
      else reject(new Error("图片读取失败"))
    }
    reader.onerror = () => reject(new Error("图片读取失败"))
    reader.readAsDataURL(file)
  })
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
    if (toolCall.name === "submit_order_form") {
      return <Row label="操作" value={String(d.message ?? "提交右侧表单的当前内容")} />
    }
    if (toolCall.name === "execute_schedule_plan") {
      return (
        <div className="space-y-1.5">
          <Row label="任务总数" value={`${String(d.task_count ?? 0)} 个`} />
          <Row label="订单总数" value={`${String(d.order_count ?? 0)} 张`} />
          <Row label="校验" value="执行前重新校验订单与机器状态" />
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
    <div className="mx-auto w-full max-w-3xl px-4 mb-2">
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
            className="px-4 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white text-sm font-medium transition-colors"
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

// ─── AI 头像 ────────────────────────────────────────────────────────────────────

function AgentAvatar({ className = "w-7 h-7" }: { className?: string }) {
  return (
    <div className={`${className} rounded-full bg-[#C8331F] flex items-center justify-center shrink-0`}>
      <svg className="w-1/2 h-1/2 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09Z" />
      </svg>
    </div>
  )
}

// ─── 消息气泡 ──────────────────────────────────────────────────────────────────

function OrderImagePreview({
  src,
  alt,
  onRemove,
  onOpenPreview,
  removeDisabled = false,
}: {
  src: string
  alt: string
  onRemove?: () => void
  onOpenPreview?: () => void
  removeDisabled?: boolean
}) {
  const previewImage = (
    <Image
      src={src}
      alt={alt}
      fill
      sizes="128px"
      unoptimized
      className="object-contain p-1.5"
    />
  )

  return (
    <div className="relative h-32 w-32 shrink-0 overflow-hidden rounded-2xl border border-slate-200 bg-slate-50 shadow-sm">
      {onOpenPreview ? (
        <button
          type="button"
          onClick={onOpenPreview}
          className="absolute inset-0 cursor-zoom-in rounded-2xl focus-visible:outline-2 focus-visible:-outline-offset-4 focus-visible:outline-slate-900"
          aria-label="打开订单图片大图预览"
          title="查看大图"
        >
          {previewImage}
        </button>
      ) : previewImage}
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          disabled={removeDisabled}
          className="absolute right-1.5 top-1.5 z-10 flex h-7 w-7 items-center justify-center rounded-full bg-slate-900/85 text-white shadow-md transition-colors hover:bg-slate-950 disabled:cursor-not-allowed disabled:opacity-40"
          aria-label="移除已附加的订单图片"
          title="移除图片"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.25}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
          </svg>
        </button>
      )}
    </div>
  )
}

const MIN_IMAGE_ZOOM = 0.5
const MAX_IMAGE_ZOOM = 3
const IMAGE_ZOOM_STEP = 0.25

function SentImageLightbox({
  src,
  alt,
  onClose,
}: {
  src: string
  alt: string
  onClose: () => void
}) {
  const [zoom, setZoom] = useState(1)
  const zoomPercent = Math.round(zoom * 100)

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent
        showCloseButton={false}
        className="h-[calc(100dvh-2rem)] max-w-[calc(100%-2rem)] grid-rows-[auto_minmax(0,1fr)] gap-0 overflow-hidden rounded-xl bg-slate-950 p-0 text-white ring-white/15 sm:max-w-[calc(100%-2rem)]"
      >
        <DialogTitle className="sr-only">订单图片预览</DialogTitle>
        <DialogDescription className="sr-only">
          使用工具栏放大、缩小或重置图片。按 Escape 键或点击关闭按钮退出预览。
        </DialogDescription>

        <div className="flex flex-wrap items-center gap-2 border-b border-white/10 bg-slate-900 px-3 py-2.5 sm:px-4">
          <div className="w-full text-sm font-medium text-white sm:mr-auto sm:w-auto">订单图片预览</div>
          <div className="flex items-center gap-2" role="group" aria-label="图片缩放控制">
            <button
              type="button"
              onClick={() => setZoom((value) => Math.max(MIN_IMAGE_ZOOM, value - IMAGE_ZOOM_STEP))}
              disabled={zoom <= MIN_IMAGE_ZOOM}
              className="inline-flex h-10 w-10 items-center justify-center gap-1.5 rounded-lg bg-white/10 text-xs font-medium text-white transition-colors hover:bg-white/20 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white disabled:cursor-not-allowed disabled:opacity-40 sm:h-9 sm:w-auto sm:px-3"
              aria-label="缩小图片"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 19.5 15 15m-5.25-2.25h-4.5m12 0a4.5 4.5 0 1 1-9 0 4.5 4.5 0 0 1 9 0Z" />
              </svg>
              <span className="hidden sm:inline">缩小</span>
            </button>
            <span className="min-w-12 text-center text-xs tabular-nums text-slate-300" aria-live="polite">
              {zoomPercent}%
            </span>
            <button
              type="button"
              onClick={() => setZoom((value) => Math.min(MAX_IMAGE_ZOOM, value + IMAGE_ZOOM_STEP))}
              disabled={zoom >= MAX_IMAGE_ZOOM}
              className="inline-flex h-10 w-10 items-center justify-center gap-1.5 rounded-lg bg-white/10 text-xs font-medium text-white transition-colors hover:bg-white/20 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white disabled:cursor-not-allowed disabled:opacity-40 sm:h-9 sm:w-auto sm:px-3"
              aria-label="放大图片"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 19.5 15 15m-5.25-4.5v4.5m2.25-2.25h-4.5m12 0a4.5 4.5 0 1 1-9 0 4.5 4.5 0 0 1 9 0Z" />
              </svg>
              <span className="hidden sm:inline">放大</span>
            </button>
            <button
              type="button"
              onClick={() => setZoom(1)}
              className="h-10 rounded-lg bg-white/10 px-2 text-xs font-medium text-white transition-colors hover:bg-white/20 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white sm:h-9 sm:px-3"
              aria-label="重置图片缩放"
            >
              重置
            </button>
          </div>
          <DialogClose
            className="inline-flex h-10 w-10 items-center justify-center gap-1.5 rounded-lg bg-white text-xs font-semibold text-slate-900 transition-colors hover:bg-slate-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white sm:h-9 sm:w-auto sm:px-3"
            aria-label="关闭图片预览"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
            </svg>
            <span className="hidden sm:inline">关闭</span>
          </DialogClose>
        </div>

        <div
          className="overflow-auto bg-slate-950 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-white"
          role="region"
          tabIndex={0}
          aria-label={`订单图片，当前缩放 ${zoomPercent}%，放大后可滚动查看`}
        >
          <div
            className="flex items-center justify-center"
            style={{
              height: `${Math.max(1, zoom) * 100}%`,
              width: `${Math.max(1, zoom) * 100}%`,
            }}
          >
            <div
              className="relative shrink-0"
              style={{
                height: `${Math.min(1, zoom) * 100}%`,
                width: `${Math.min(1, zoom) * 100}%`,
              }}
            >
              <Image
                src={src}
                alt={alt}
                fill
                sizes="100vw"
                unoptimized
                className="object-contain p-4"
                priority
              />
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function isImageOrderPlaceholder(content: string): boolean {
  const prefix = "[图片订单"
  if (!content.startsWith(prefix) || !content.endsWith("]")) return false
  const suffix = content.slice(prefix.length, -1)
  return suffix === "" || suffix.startsWith("：") || suffix.startsWith(":")
}

function MessageBubble({
  msg,
  onOpenImagePreview,
}: {
  msg: ChatMessage
  onOpenImagePreview: (src: string, alt: string) => void
}) {
  if (msg.role === "tool") return null
  if (msg.tool_calls) return null

  const isUser = msg.role === "user"
  const rawContent = msg.content?.trim() ?? ""
  const isImagePlaceholder = isUser && isImageOrderPlaceholder(rawContent)
  const content = isImagePlaceholder ? "" : rawContent
  const persistedAttachment = isUser ? msg.attachments?.[0] : undefined
  const imageSource = isUser
    ? msg.optimistic_image_preview_data_url
      ?? (persistedAttachment ? attachmentMediaUrl(persistedAttachment.id) : undefined)
    : undefined
  const showSafeImagePlaceholder = isImagePlaceholder && !imageSource
  if (!content && !imageSource && !showSafeImagePlaceholder) return null

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-4`}>
      {!isUser && <AgentAvatar className="w-7 h-7 mr-2.5 mt-0.5" />}
      <div
        className={`max-w-[80%] rounded-2xl text-sm leading-relaxed whitespace-pre-wrap ${
          isUser
            ? `bg-[#C8331F] text-white rounded-br-md ${imageSource ? "p-1.5" : "px-4 py-2.5"}`
            : "bg-white border border-slate-200 text-slate-800 shadow-sm rounded-bl-md px-4 py-2.5"
        }`}
      >
        {imageSource && (
          <OrderImagePreview
            src={imageSource}
            alt="本次消息附带的订单图片"
            onOpenPreview={() => onOpenImagePreview(imageSource, "本次消息附带的订单图片")}
          />
        )}
        {showSafeImagePlaceholder && (
          <span className="inline-flex items-center gap-1.5" aria-label="本消息包含一张未保留预览的订单图片">
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" d="m2.25 15.75 5.159-5.159a2.25 2.25 0 0 1 3.182 0l5.159 5.159m-1.5-1.5 1.409-1.409a2.25 2.25 0 0 1 3.182 0l2.909 2.909m-18 3.75h16.5a1.5 1.5 0 0 0 1.5-1.5V6a1.5 1.5 0 0 0-1.5-1.5H3.75A1.5 1.5 0 0 0 2.25 6v12a1.5 1.5 0 0 0 1.5 1.5Z" />
            </svg>
            图片订单
          </span>
        )}
        {content && (
          <div className={imageSource ? "px-2.5 pb-1 pt-2" : undefined}>{content}</div>
        )}
      </div>
    </div>
  )
}

const HINTS = [
  { label: "录入新订单", prompt: "帮我录入一张新订单" },
  { label: "帮我排单", prompt: "帮我把待排单的订单排一下" },
  { label: "查看待排单", prompt: "查看当前待排单的订单" },
  { label: "查询客户", prompt: "帮我查一下客户列表" },
]

// ─── 输入框 ────────────────────────────────────────────────────────────────────

function InputBox({
  input, onChange, onKeyDown, onSend, disabled, textareaRef, placeholder, autoFocus,
  image, imagePreviewUrl, imageNotice, onImageSelect, onImageRemove, onPaste,
}: {
  input: string
  onChange: (e: React.ChangeEvent<HTMLTextAreaElement>) => void
  onKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void
  onSend: () => void
  disabled: boolean
  textareaRef: React.RefObject<HTMLTextAreaElement | null>
  placeholder: string
  autoFocus?: boolean
  image: File | null
  imagePreviewUrl: string | null
  imageNotice: string | null
  onImageSelect: (file: File) => void
  onImageRemove: () => void
  onPaste: (event: React.ClipboardEvent<HTMLTextAreaElement>) => void
}) {
  const fileInputRef = useRef<HTMLInputElement>(null)
  return (
    <div className="space-y-2">
      <div
        className={`rounded-2xl border bg-white transition-all ${
          disabled
            ? "border-slate-200"
            : "border-slate-200 shadow-sm focus-within:border-slate-300 focus-within:ring-4 focus-within:ring-slate-900/[0.04]"
        }`}
      >
        {image && imagePreviewUrl && (
          <div className="flex gap-3 overflow-x-auto px-3 pt-3" aria-label="已附加的图片">
            <OrderImagePreview
              src={imagePreviewUrl}
              alt="待发送的订单图片"
              onRemove={onImageRemove}
              removeDisabled={disabled}
            />
            <span className="sr-only" role="status" aria-live="polite">已附加 1 张图片</span>
          </div>
        )}
        <div className="flex items-end gap-2">
          <input
            ref={fileInputRef}
            type="file"
            accept=".jpg,.jpeg,.png,image/jpeg,image/png"
            disabled={disabled}
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (file) onImageSelect(file)
              event.target.value = ""
            }}
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={disabled}
            className="mb-2.5 ml-2.5 h-9 w-9 shrink-0 rounded-xl text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 disabled:opacity-40"
            title="上传 JPG/PNG 订单图片"
            aria-label="上传订单图片"
          >
            <svg className="mx-auto h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="m2.25 15.75 5.159-5.159a2.25 2.25 0 0 1 3.182 0l5.159 5.159m-1.5-1.5 1.409-1.409a2.25 2.25 0 0 1 3.182 0l2.909 2.909m-18 3.75h16.5a1.5 1.5 0 0 0 1.5-1.5V6a1.5 1.5 0 0 0-1.5-1.5H3.75A1.5 1.5 0 0 0 2.25 6v12a1.5 1.5 0 0 0 1.5 1.5Z" />
            </svg>
          </button>
          <textarea
            ref={textareaRef}
            value={input}
            onChange={onChange}
            onKeyDown={onKeyDown}
            onPaste={onPaste}
            disabled={disabled}
            autoFocus={autoFocus}
            aria-label="对话消息"
            placeholder={placeholder}
            rows={1}
            className="flex-1 resize-none bg-transparent px-1 py-3.5 text-sm text-slate-800 placeholder:text-slate-400 outline-none disabled:cursor-not-allowed min-h-[52px] max-h-40"
          />
          <button
            type="button"
            onClick={onSend}
            disabled={disabled || (!input.trim() && !image)}
            style={{ backgroundColor: !disabled && (input.trim() || image) ? ACCENT : undefined }}
            className="mb-2.5 mr-2.5 w-9 h-9 rounded-xl disabled:bg-slate-200 text-white flex items-center justify-center transition-colors shrink-0"
            title="发送"
            aria-label="发送消息"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.4}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 10.5 12 3m0 0 7.5 7.5M12 3v18" />
            </svg>
          </button>
        </div>
      </div>
      {imageNotice && (
        <p className="px-1 text-xs text-amber-700" role="status" aria-live="polite">
          {imageNotice}
        </p>
      )}
    </div>
  )
}

// ─── 欢迎主视觉 ─────────────────────────────────────────────────────────────────

function HeroMark() {
  return (
    <div className="relative w-16 h-16 mb-7">
      <svg viewBox="0 0 100 100" className="w-full h-full">
        <polygon points="50,6 88,28 88,72 50,94 12,72 12,28" fill="none" stroke="#e2e8f0" strokeWidth="2" />
        <polygon points="50,20 76,35 76,65 50,80 24,65 24,35" fill="none" stroke="#cbd5e1" strokeWidth="1.5" />
        <circle cx="50" cy="50" r="13" fill={ACCENT} opacity="0.1" />
        <circle cx="50" cy="50" r="7" fill={ACCENT} />
      </svg>
    </div>
  )
}

// ─── 主组件 ───────────────────────────────────────────────────────────────────

function pendingToolCallFrom(messages: ChatMessage[]): PendingToolCall | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index]
    if (!message.is_pending || !Array.isArray(message.tool_calls) || message.tool_calls.length === 0) continue

    const toolCall = message.tool_calls[0]
    if (toolCall.name) {
      return {
        id: toolCall.id ?? message.id,
        name: toolCall.name,
        args: toolCall.args ?? {},
        display: toolCall.display,
      }
    }

    if (toolCall.function) {
      let args: Record<string, unknown> = {}
      try {
        args = JSON.parse(toolCall.function.arguments) as Record<string, unknown>
      } catch {
        // Keep the confirmation recoverable even if old arguments are malformed.
      }
      return {
        id: toolCall.id ?? message.id,
        name: toolCall.function.name,
        args,
      }
    }
  }

  return null
}

export default function ChatInterface({ requestedSessionId = null }: ChatInterfaceProps) {
  const router = useRouter()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const [isHistoryLoading, setIsHistoryLoading] = useState(Boolean(requestedSessionId))
  const [historyLoadFailed, setHistoryLoadFailed] = useState(false)
  const [historyRetryKey, setHistoryRetryKey] = useState(0)
  const [isConfirming, setIsConfirming] = useState(false)
  const [pendingToolCall, setPendingToolCall] = useState<PendingToolCall | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selectedImage, setSelectedImage] = useState<File | null>(null)
  const [imagePreviewUrl, setImagePreviewUrl] = useState<string | null>(null)
  const [imageNotice, setImageNotice] = useState<string | null>(null)
  const [sentImageLightbox, setSentImageLightbox] = useState<{ src: string; alt: string } | null>(null)
  // ─── 协同录单分栏 ───
  const [panelOpen, setPanelOpen] = useState(false)
  const [draft, setDraft] = useState<OrderDraft | null>(null)
  const [schedulePlan, setSchedulePlan] = useState<SchedulePlan | null>(null)
  const [mobileView, setMobileView] = useState<"chat" | "form">("chat")
  const bottomRef = useRef<HTMLDivElement>(null)
  const heroTextareaRef = useRef<HTMLTextAreaElement>(null)
  const dockTextareaRef = useRef<HTMLTextAreaElement>(null)
  const sessionIdRef = useRef<string | null>(requestedSessionId)
  const isSendingRef = useRef(false)
  const imagePreviewUrlRef = useRef<string | null>(null)
  const draftSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const started = messages.length > 0 || isLoading || isHistoryLoading

  function replaceSelectedImage(image: File | null) {
    const nextPreviewUrl = image ? URL.createObjectURL(image) : null
    const previousPreviewUrl = imagePreviewUrlRef.current

    imagePreviewUrlRef.current = nextPreviewUrl
    setSelectedImage(image)
    setImagePreviewUrl(nextPreviewUrl)

    if (previousPreviewUrl) URL.revokeObjectURL(previousPreviewUrl)
  }

  useEffect(() => () => {
    const previewUrl = imagePreviewUrlRef.current
    if (previewUrl) URL.revokeObjectURL(previewUrl)
    if (draftSaveTimerRef.current) clearTimeout(draftSaveTimerRef.current)
  }, [])

  useEffect(() => {
    if (!requestedSessionId) return

    let cancelled = false
    Promise.all([
      api.get<ChatMessage[]>(`/agent/chat?session_id=${encodeURIComponent(requestedSessionId)}`),
      api.get<WorkspaceSnapshot>(`/agent/workspace?session_id=${encodeURIComponent(requestedSessionId)}`),
    ])
      .then(([history, workspace]) => {
        if (cancelled) return
        setMessages(history)
        setPendingToolCall(pendingToolCallFrom(history))
        if (workspace.active_workspace === "order_form") {
          setPanelOpen(true)
          setDraft(workspace.order_draft)
          setSchedulePlan(null)
          setMobileView("form")
        } else if (workspace.active_workspace === "schedule_plan" && workspace.schedule_plan) {
          setPanelOpen(true)
          setDraft(null)
          setSchedulePlan(workspace.schedule_plan)
          setMobileView("form")
        } else {
          closePanelState()
        }
        setHistoryLoadFailed(false)
      })
      .catch((loadError) => {
        if (cancelled) return
        setHistoryLoadFailed(true)
        setError(loadError instanceof Error ? loadError.message : "加载会话失败，请重试")
      })
      .finally(() => {
        if (!cancelled) setIsHistoryLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [historyRetryKey, requestedSessionId])

  useEffect(() => {
    if (started) bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, pendingToolCall, started])

  function handleInputChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setInput(e.target.value)
    e.target.style.height = "auto"
    e.target.style.height = Math.min(e.target.scrollHeight, 160) + "px"
  }

  function handlePaste(event: React.ClipboardEvent<HTMLTextAreaElement>) {
    if (event.currentTarget.disabled) return
    const clipboardImages = clipboardImageFiles(event.clipboardData)
    if (clipboardImages.length === 0) return

    // Avoid browser-specific insertion of an image name, URL, or other file
    // representation. Restore genuine plain text explicitly so text + image
    // remains a single message.
    event.preventDefault()
    const textarea = event.currentTarget
    const pastedText = event.clipboardData.getData("text/plain")
    const isOnlyImageFileName = clipboardImages.some((file) => pastedText.trim() === file.name)
    if (pastedText && !isOnlyImageFileName) {
      const start = textarea.selectionStart
      const end = textarea.selectionEnd
      const nextInput = `${textarea.value.slice(0, start)}${pastedText}${textarea.value.slice(end)}`
      const nextCursor = start + pastedText.length
      setInput(nextInput)
      requestAnimationFrame(() => {
        textarea.setSelectionRange(nextCursor, nextCursor)
        textarea.style.height = "auto"
        textarea.style.height = Math.min(textarea.scrollHeight, 160) + "px"
      })
    }

    const supportedImages = clipboardImages.filter((file) => supportedImageMime(file) !== null)
    const eligibleImages = supportedImages.filter((file) => file.size <= MAX_IMAGE_SIZE)
    const replacingImage = selectedImage !== null
    const candidate = eligibleImages[0] ?? supportedImages[0] ?? clipboardImages[0]
    const selected = handleImageSelect(candidate)

    if (!selected) {
      if (clipboardImages.length > 1) {
        setImageNotice(
          replacingImage
            ? "检测到多张图片，但没有符合要求的 JPG/PNG，已保留原图片。"
            : "检测到多张图片，但没有符合要求的 JPG/PNG，未添加图片。",
        )
      }
      return
    }

    if (clipboardImages.length > 1) {
      setImageNotice(
        replacingImage
          ? "检测到多张图片，一次只能添加一张，已用第一张符合要求的 JPG/PNG 替换原图片。"
          : "检测到多张图片，一次只能添加一张，已采用第一张符合要求的 JPG/PNG。",
      )
    } else if (replacingImage) {
      setImageNotice("已用粘贴的图片替换原图片。")
    }
  }

  async function createSession(): Promise<string> {
    const session = await api.post<{ id: string }>("/agent/sessions", {})
    sessionIdRef.current = session.id
    return session.id
  }

  function resetConversation() {
    if (isLoading || isHistoryLoading || isConfirming) return
    const previousSessionId = sessionIdRef.current
    if (panelOpen) void clearWorkspace(previousSessionId)
    sessionIdRef.current = null
    setMessages([])
    setPendingToolCall(null)
    setHistoryLoadFailed(false)
    setError(null)
    setInput("")
    replaceSelectedImage(null)
    setImageNotice(null)
    closePanelState()
    router.push("/", { scroll: false })
  }

  function closePanelState() {
    if (draftSaveTimerRef.current) {
      clearTimeout(draftSaveTimerRef.current)
      draftSaveTimerRef.current = null
    }
    setPanelOpen(false)
    setDraft(null)
    setSchedulePlan(null)
    setMobileView("chat")
  }

  const persistOrderDraft = useCallback((nextDraft: OrderDraft) => {
    const sessionId = sessionIdRef.current
    if (!sessionId) return
    setDraft(nextDraft)
    if (draftSaveTimerRef.current) clearTimeout(draftSaveTimerRef.current)
    draftSaveTimerRef.current = setTimeout(() => {
      draftSaveTimerRef.current = null
      void api.put<WorkspaceSnapshot>("/agent/workspace/order-draft", {
        session_id: sessionId,
        draft: nextDraft,
      }).catch((saveError) => {
        setError(saveError instanceof Error ? saveError.message : "订单草稿保存失败")
      })
    }, 400)
  }, [])

  async function clearWorkspace(sessionId = sessionIdRef.current) {
    if (!sessionId) return
    try {
      await api.post<void>("/agent/workspace/close", { session_id: sessionId })
    } catch (workspaceError) {
      setError(workspaceError instanceof Error ? workspaceError.message : "关闭录单工作区失败")
    }
  }

  function closeOrderPanel() {
    closePanelState()
    void clearWorkspace()
  }

  function closeSchedulePanel() {
    closePanelState()
    void clearWorkspace()
  }

  function appendAssistant(content: string) {
    setMessages((prev) => [...prev, {
      id: createLocalMessageId("local"), role: "assistant", content,
      tool_calls: null, tool_call_id: null, tool_name: null,
      is_pending: false, created_at: new Date().toISOString(), attachments: [],
    }])
  }

  function handleOrderSubmitted(order: { order_no?: string; id?: string }) {
    const no = order?.order_no
    closePanelState()
    void clearWorkspace()
    appendAssistant(`✅ 已创建订单${no ? ` No.${no}` : ""}，可在「订单列表」查看。`)
  }

  /** Consume an SSE stream, managing a live streaming assistant bubble. */
  async function consumeStream(
    res: Response,
    temporaryUserMessageId: string | null = null,
  ): Promise<StreamResult> {
    if (!res.body) throw new Error("服务未返回可读取的响应流")
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buf = ""
    let streamMsgId: string | null = null
    let streamContent = ""
    let succeeded = true
    let userMessageId: string | null = null
    let userMessageCommitted = false
    let receivedTerminalEvent = false

    const ensureBubble = () => {
      if (!streamMsgId) {
        setIsLoading(false)
        streamMsgId = createLocalMessageId("stream")
        const sid = streamMsgId
        setMessages((prev) => [...prev, {
          id: sid, role: "assistant", content: streamContent,
          tool_calls: null, tool_call_id: null, tool_name: null,
          is_pending: false, created_at: new Date().toISOString(), attachments: [],
        }])
      }
    }

    try {
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
          let parsedEvent: unknown
          try {
            parsedEvent = JSON.parse(raw) as unknown
          } catch {
            succeeded = false
            setError("助手响应格式无效，请重试")
            break outer
          }
          if (!parsedEvent || typeof parsedEvent !== "object") {
            succeeded = false
            setError("助手响应格式无效，请重试")
            break outer
          }
          const event = parsedEvent as Record<string, unknown>

          if (event.type === "user_message_committed") {
            if (!temporaryUserMessageId || !isUserMessageCommittedEvent(event)) {
              succeeded = false
              setError("消息提交确认格式无效，请刷新会话")
              break outer
            }
            userMessageId = event.user_message_id.trim()
            userMessageCommitted = true
            const persistedUserMessageId = userMessageId
            setMessages((prev) => prev.map((message) => (
              message.id === temporaryUserMessageId
                ? {
                    ...message,
                    id: persistedUserMessageId,
                    attachments: event.attachments,
                    optimistic_image_preview_data_url: undefined,
                  }
                : message
            )))
          } else if (
            temporaryUserMessageId
            && !userMessageCommitted
            && typeof event.user_message_id === "string"
            && event.user_message_id.trim()
          ) {
            // Compatibility with older terminal events. New servers always send
            // user_message_committed first so persisted attachment metadata wins.
            userMessageId = event.user_message_id.trim()
            userMessageCommitted = true
            const persistedUserMessageId = userMessageId
            setMessages((prev) => prev.map((message) => (
              message.id === temporaryUserMessageId
                ? { ...message, id: persistedUserMessageId }
                : message
            )))
          }

          if (event.type === "delta") {
          if (typeof event.content !== "string") {
            succeeded = false
            setError("助手响应格式无效，请重试")
            break outer
          }
          streamContent += event.content
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
          if (typeof event.message_id !== "string" || !event.message_id.trim()) {
            succeeded = false
            setError("助手响应格式无效，请重试")
            break outer
          }
          receivedTerminalEvent = true
          const sid = streamMsgId
          setMessages((prev) => prev.map((m) =>
            m.id === sid ? { ...m, id: event.message_id as string } : m
          ))
          break outer
        } else if (event.type === "pending_confirmation") {
          if (!event.tool_call || typeof event.tool_call !== "object") {
            succeeded = false
            setError("助手响应格式无效，请重试")
            break outer
          }
          receivedTerminalEvent = true
          setPendingToolCall(event.tool_call as PendingToolCall)
          break outer
        } else if (event.type === "panel") {
          if (event.action === "open") {
            setPanelOpen(true)
            if (event.panel === "order_form") setSchedulePlan(null)
            setMobileView("form")
          } else if (event.action === "close") {
            closePanelState()
          }
        } else if (event.type === "form_update") {
          const fields = event.fields as OrderDraft
          setDraft((prev) => ({
            ...(prev ?? {}),
            ...fields,
            ...(fields.spec_params
              ? { spec_params: { ...(prev?.spec_params ?? {}), ...fields.spec_params } }
              : {}),
          }))
        } else if (event.type === "order_created") {
          // The backend has already created the order atomically. The following
          // panel/delta events update the visible workspace and conversation.
        } else if (event.type === "schedule_plan") {
          setSchedulePlan(event.plan as unknown as SchedulePlan)
          setPanelOpen(true)
          setMobileView("form")
        } else if (event.type === "schedule_applied") {
          setSchedulePlan((prev) => prev ? { ...prev, status: "APPLIED" } : prev)
          } else if (event.type === "error") {
            succeeded = false
            setError(typeof event.error === "string" ? event.error : "请求处理失败，请重试")
            if (streamMsgId) {
              const sid = streamMsgId
              setMessages((prev) => prev.filter((m) => m.id !== sid))
            }
            break outer
          }
        }
      }
    } catch (streamError) {
      succeeded = false
      setError(streamError instanceof Error ? streamError.message : "助手响应中断，请重试")
    }

    if (succeeded && temporaryUserMessageId && (!userMessageCommitted || !receivedTerminalEvent)) {
      succeeded = false
      if (streamMsgId) {
        const incompleteAssistantMessageId = streamMsgId
        setMessages((prev) => prev.filter((message) => message.id !== incompleteAssistantMessageId))
      }
      setError("助手响应未完整结束，请重试")
    }
    return { succeeded, userMessageId, userMessageCommitted }
  }

  async function send(text: string, image: File | null = null) {
    if ((!text && !image) || isLoading || pendingToolCall || isSendingRef.current) return

    isSendingRef.current = true
    setIsLoading(true)
    setInput("")
    setError(null)
    if (heroTextareaRef.current) heroTextareaRef.current.style.height = "auto"
    if (dockTextareaRef.current) dockTextareaRef.current.style.height = "auto"

    let imageDataUrl: string | null = null
    if (image) {
      try {
        imageDataUrl = await readImageAsDataUrl(image)
      } catch (imageError) {
        setError(imageError instanceof Error ? imageError.message : "图片读取失败")
        setInput(text)
        setIsLoading(false)
        isSendingRef.current = false
        return
      }
    }

    // The composer owns the File only until the message is ready to send. From
    // this point the optimistic message owns the data URL; a pre-commit failure
    // is the only transition that restores the original File to the composer.
    if (image) {
      replaceSelectedImage(null)
      setImageNotice(null)
    }

    const tempId = createLocalMessageId("temp")
    setMessages((prev) => [...prev, {
      id: tempId, role: "user", content: text || null,
      tool_calls: null, tool_call_id: null, tool_name: null,
      is_pending: false, created_at: new Date().toISOString(),
      attachments: [],
      ...(imageDataUrl ? { optimistic_image_preview_data_url: imageDataUrl } : {}),
    }])

    let activeSessionId = sessionIdRef.current
    if (!activeSessionId) {
      try {
        activeSessionId = await createSession()
      } catch {
        setError("初始化对话失败，请重试")
        setMessages((prev) => prev.filter((message) => message.id !== tempId))
        setInput(text)
        if (image) replaceSelectedImage(image)
        setIsLoading(false)
        isSendingRef.current = false
        return
      }
    }

    try {
      const res = await postStream("/agent/chat", {
        content: text,
        session_id: activeSessionId,
        image_data_url: imageDataUrl,
      })
      const result = await consumeStream(res, tempId)
      if (requestedSessionId !== activeSessionId && result.userMessageCommitted) {
        router.replace(`/?session=${encodeURIComponent(activeSessionId)}`, { scroll: false })
      }
      if (!result.succeeded) {
        if (!result.userMessageCommitted) {
          setMessages((prev) => prev.filter((message) => message.id !== tempId))
          setInput(text)
          if (image) replaceSelectedImage(image)
        }
        return
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "网络错误，请重试")
      setMessages((prev) => prev.filter((m) => m.id !== tempId))
      setInput(text)
      if (image) replaceSelectedImage(image)
    } finally {
      setIsLoading(false)
      isSendingRef.current = false
    }
  }

  function handleSend() {
    send(input.trim(), selectedImage)
  }

  function handleImageSelect(file: File): boolean {
    setImageNotice(null)
    const mime = supportedImageMime(file)
    if (!mime) {
      setError("仅支持 JPG 或 PNG 图片")
      return false
    }
    if (file.size > MAX_IMAGE_SIZE) {
      setError("图片不能超过 5MB")
      return false
    }
    setError(null)
    replaceSelectedImage(normalizeImageFile(file, mime))
    return true
  }

  async function handleConfirm() {
    if (!pendingToolCall || isConfirming || !sessionIdRef.current) return
    setIsConfirming(true)
    setError(null)
    const currentPending = pendingToolCall
    setPendingToolCall(null)
    setIsLoading(true)
    try {
      if (draftSaveTimerRef.current) {
        clearTimeout(draftSaveTimerRef.current)
        draftSaveTimerRef.current = null
      }
      const res = await postStream("/agent/chat/confirm", {
        session_id: sessionIdRef.current,
        ...(currentPending.name === "submit_order_form" ? { order_draft: draft } : {}),
      })
      await consumeStream(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : "确认失败")
      setPendingToolCall(currentPending)
    } finally {
      setIsConfirming(false)
      setIsLoading(false)
    }
  }

  async function handleCancel() {
    if (!pendingToolCall || isConfirming || !sessionIdRef.current) return
    setIsConfirming(true)
    setError(null)
    const currentPending = pendingToolCall
    setPendingToolCall(null)
    setIsLoading(true)
    try {
      const res = await postStream("/agent/chat/cancel", { session_id: sessionIdRef.current })
      await consumeStream(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : "取消失败")
      setPendingToolCall(currentPending)
    } finally {
      setIsConfirming(false)
      setIsLoading(false)
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend() }
  }

  function retryHistory() {
    if (!requestedSessionId || isHistoryLoading) return
    setError(null)
    setHistoryLoadFailed(false)
    setIsHistoryLoading(true)
    setHistoryRetryKey((value) => value + 1)
  }

  const isInputDisabled = isLoading || isHistoryLoading || historyLoadFailed || !!pendingToolCall

  // ─── 欢迎态：居中主视觉 ──────────────────────────────────────────────────────
  if (!started) {
    return (
      <div className="flex flex-col h-[calc(100dvh-4rem)] md:h-screen overflow-y-auto bg-slate-50">
        <div className="flex-1 flex flex-col items-center justify-center px-6 py-12">
          <div className="w-full max-w-2xl flex flex-col items-center text-center">
            <HeroMark />
            <h1 className="text-[26px] md:text-[30px] font-semibold text-slate-900 tracking-tight leading-tight">
              我是 FilmOS 助手，你的智能排产伙伴。
            </h1>
            <p className="text-slate-500 mt-3 text-[15px]">
              今天想让我帮你做点什么？录单、排产、查询，一句话就够了。
            </p>

            <div className="w-full mt-9">
              <InputBox
                input={input}
                onChange={handleInputChange}
                onKeyDown={handleKeyDown}
                onSend={handleSend}
                disabled={isInputDisabled}
                textareaRef={heroTextareaRef}
                placeholder="在此输入你的问题或订单需求…"
                autoFocus
                image={selectedImage}
                imagePreviewUrl={imagePreviewUrl}
                imageNotice={imageNotice}
                onImageSelect={handleImageSelect}
                onImageRemove={() => {
                  replaceSelectedImage(null)
                  setImageNotice(null)
                }}
                onPaste={handlePaste}
              />
            </div>

            <div className="flex flex-wrap gap-2 justify-center mt-5">
              {HINTS.map((hint) => (
                <button
                  key={hint.label}
                  onClick={() => send(hint.prompt)}
                  className="group inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl border border-slate-200 bg-white text-slate-600 text-[13px] hover:border-slate-300 hover:text-slate-900 hover:shadow-sm transition-all"
                >
                  {hint.label}
                  <svg className="w-3.5 h-3.5 text-slate-300 group-hover:text-slate-400 transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 19.5 19.5 4.5m0 0H9m10.5 0V15" />
                  </svg>
                </button>
              ))}
            </div>

            {error && (
              <div className="mt-6 flex items-center gap-3 text-sm text-red-500">
                <span>{error}</span>
                {historyLoadFailed && (
                  <button
                    type="button"
                    onClick={retryHistory}
                    className="rounded-lg border border-red-200 bg-white px-2.5 py-1 text-xs font-medium text-red-600 transition-colors hover:bg-red-50"
                  >
                    重试加载
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
        <p className="text-center text-xs text-slate-300 pb-5">FilmOS 助手 · AI 可能出错，重要操作请二次核对</p>
      </div>
    )
  }

  // ─── 对话态（含协同录单分栏）────────────────────────────────────────────────
  // 面板打开时，桌面端对话与表单各占一半；手机端用顶部切换。
  const chatColClass = panelOpen
    ? `flex-col min-w-0 min-h-0 w-full md:w-1/2 md:shrink-0 ${
        mobileView === "chat" ? "flex" : "hidden"
      } md:flex`
    : "flex flex-col flex-1 min-w-0 min-h-0"

  return (
    <div className="flex flex-col h-[calc(100dvh-4rem)] md:h-screen overflow-hidden bg-slate-50">
      {panelOpen && (
        <div className="md:hidden shrink-0 flex items-stretch border-b border-slate-200 bg-white">
          {(["chat", "form"] as const).map((v) => (
            <button
              key={v}
              onClick={() => setMobileView(v)}
              className={`flex-1 py-2.5 text-sm font-medium transition-colors ${
                mobileView === v ? "text-[#C8331F] border-b-2 border-[#C8331F]" : "text-slate-500"
              }`}
            >
              {v === "chat" ? "对话" : schedulePlan ? "排产方案" : "录入订单"}
            </button>
          ))}
        </div>
      )}

      <div className="flex flex-1 min-h-0">
        {/* 对话列 */}
        <div className={chatColClass}>
          <header className="shrink-0 bg-white/80 backdrop-blur border-b border-slate-200">
            <div className="mx-auto w-full max-w-3xl px-4 flex items-center h-13 py-2.5 gap-2.5">
              <AgentAvatar className="w-7 h-7" />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold text-slate-800 leading-tight">FilmOS 助手</div>
                <div className="text-[11px] text-slate-400 leading-tight">智能录单 · 排产</div>
              </div>
              <button
                onClick={resetConversation}
                disabled={isLoading || isHistoryLoading || isConfirming}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-slate-500 hover:text-slate-800 hover:bg-slate-100 disabled:opacity-40 text-xs font-medium transition-colors"
                title="开启新对话"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                </svg>
                新对话
              </button>
            </div>
          </header>

          <div className="flex-1 overflow-y-auto py-6">
            <div className="mx-auto w-full max-w-3xl px-4">
              {messages.map((msg) => (
                <MessageBubble
                  key={msg.id}
                  msg={msg}
                  onOpenImagePreview={(src, alt) => setSentImageLightbox({ src, alt })}
                />
              ))}

              {(isLoading || isHistoryLoading) && (
                <div className="flex justify-start mb-4">
                  <AgentAvatar className="w-7 h-7 mr-2.5 mt-0.5" />
                  <div className="bg-white border border-slate-200 rounded-2xl rounded-bl-md px-4 py-3 shadow-sm flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 bg-slate-300 rounded-full animate-bounce [animation-delay:0ms]" />
                    <span className="w-1.5 h-1.5 bg-slate-300 rounded-full animate-bounce [animation-delay:150ms]" />
                    <span className="w-1.5 h-1.5 bg-slate-300 rounded-full animate-bounce [animation-delay:300ms]" />
                  </div>
                </div>
              )}
            </div>

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
            <div className="mx-auto w-full max-w-3xl px-4 mb-2">
              <div className="px-4 py-2.5 rounded-lg bg-red-50 border border-red-100 text-sm text-red-600 flex items-center justify-between">
                <span>{error}</span>
                <button onClick={() => setError(null)} className="ml-3 text-red-400 hover:text-red-600 shrink-0">
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            </div>
          )}

          <div className="border-t border-slate-200 bg-white px-4 py-3">
            <div className="mx-auto w-full max-w-3xl">
              <InputBox
                input={input}
                onChange={handleInputChange}
                onKeyDown={handleKeyDown}
                onSend={handleSend}
                disabled={isInputDisabled}
                textareaRef={dockTextareaRef}
                placeholder={pendingToolCall ? "请先处理上方的确认操作…" : "输入消息，Enter 发送，Shift+Enter 换行"}
                image={selectedImage}
                imagePreviewUrl={imagePreviewUrl}
                imageNotice={imageNotice}
                onImageSelect={handleImageSelect}
                onImageRemove={() => {
                  replaceSelectedImage(null)
                  setImageNotice(null)
                }}
                onPaste={handlePaste}
              />
              <p className="text-center text-xs text-slate-300 mt-2">AI 可能出错，重要操作请二次核对</p>
            </div>
          </div>
        </div>

        {/* 录入订单面板 */}
        {panelOpen && (
          <aside
            className={`flex-col w-full md:flex-1 min-w-0 border-l border-slate-200 bg-slate-50 ${
              mobileView === "form" ? "flex" : "hidden"
            } md:flex`}
          >
            <div className="shrink-0 flex items-center h-13 px-4 py-2.5 border-b border-slate-200 bg-white gap-2.5">
              <div className="w-7 h-7 rounded-lg bg-[#C8331F]/10 text-[#C8331F] flex items-center justify-center shrink-0">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
                </svg>
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold text-slate-800 leading-tight">
                  {schedulePlan ? "排产方案" : "录入订单"}
                </div>
                <div className="text-[11px] text-slate-400 leading-tight">
                  {schedulePlan ? "后端规则生成 · 确认时重新校验" : "对话填写或手动修改，随时下发"}
                </div>
              </div>
              <button
                onClick={schedulePlan ? closeSchedulePanel : closeOrderPanel}
                title="关闭表单"
                className="w-7 h-7 flex items-center justify-center rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors shrink-0"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            {schedulePlan ? (
              <SchedulePlanPanel
                plan={schedulePlan}
                onConfirmRequest={() => send("确认排产")}
                disabled={isLoading || isConfirming || Boolean(pendingToolCall)}
              />
            ) : (
              <OrderForm
                variant="panel"
                draft={draft}
                onDraftChange={persistOrderDraft}
                onSubmitted={handleOrderSubmitted}
                onCancel={closeOrderPanel}
              />
            )}
          </aside>
        )}
      </div>

      {sentImageLightbox && (
        <SentImageLightbox
          src={sentImageLightbox.src}
          alt={sentImageLightbox.alt}
          onClose={() => setSentImageLightbox(null)}
        />
      )}
    </div>
  )
}
