"use client";
import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  CheckCircle2,
  ImagePlus,
  Plus,
  LoaderCircle,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { agentApi } from "./api";
import type { Session, Snapshot, WorkItem } from "./types";
import { useAgentComposer } from "./useAgentComposer";
import { useAgentOperation } from "./useAgentOperation";
import OrderDraftEditor, { type OrderEditorHandle } from "./OrderDraftEditor";
import OrderIntakeList from "./OrderIntakeList";
import OrderSourceImage from "./OrderSourceImage";
import BackToAssistantButton from "./BackToAssistantButton";
import { PendingImagePreview } from "./ImagePreview";
import "./OrderWorkbench.css";
import { useConfirmation } from "@/components/ConfirmationProvider";
import { screenshotGroups, screenshotLabel } from "./screenshotGroups";
import { useScreenshotList, type ScreenshotTab } from "./useScreenshotList";
import type { ScreenshotGroup } from "./screenshotGroups";

export default function OrderWorkbench({
  snapshot,
  refresh,
  loadError,
}: {
  snapshot: Snapshot;
  refresh: () => Promise<Snapshot | null>;
  loadError: string;
}) {
  const router = useRouter();
  const search = useSearchParams();
  const [tab, setTab] = useState<ScreenshotTab>(search.get("tab") === "created" ? "created" : "pending");
  const confirm = useConfirmation();
  const { working, act, error, setError } = useAgentOperation();
  const { session, active_run: run } = snapshot;
  const archived = tab === "archived";
  const busy = working || !!run || archived || session.status === "ARCHIVED";
  const composer = useAgentComposer({
    session,
    busy: working || !!run || session.status === "ARCHIVED",
    act,
    refresh,
    setError,
    recognizeOnly: true,
  });
  const { input: uploadInput, files, uncertain, addFiles, removeFile, send } = composer;
  const [uploadOpen, setUploadOpen] = useState(false);
  const library = useScreenshotList(tab, `${session.id}:${snapshot.event_cursor}`);
  const [viewed, setViewed] = useState<WorkItem | null>(null);
  const [notice, setNotice] = useState("");
  const [mobile, setMobile] = useState<"list" | "image" | "form">("form");
  const editor = useRef<OrderEditorHandle>(null);
  const liveCurrent = snapshot.active_work_item ?? snapshot.work_items.find(i => i.id === session.active_work_item_id);
  // Keep the selected draft visible when its screenshot is beyond the loaded list pages.
  const selectedGroup = tab === "pending" && liveCurrent && liveCurrent.status !== "CLOSED" && !liveCurrent.source_archived
    ? screenshotGroups([...snapshot.work_items.filter(i => i.source_attachment_id === liveCurrent.source_attachment_id && i.id !== liveCurrent.id), liveCurrent])
    : [];
  const screenshots = [...library.screenshots, ...selectedGroup.filter(g => !library.screenshots.some(row => row.id === g.id))]
    .sort((a,b) => b.day.localeCompare(a.day) || a.position-b.position);
  const items = screenshots.flatMap(group => group.items);
  const current = viewed?.status !== "CLOSED" && viewed && !!viewed.source_archived === archived ? viewed :
    tab === "pending" && liveCurrent?.status !== "CLOSED" && !liveCurrent?.source_archived ? liveCurrent : undefined;
  const source = current ?? (tab === "pending" ? items.find(i => i.id === run?.work_item_id) : undefined);
  const currentGroup = screenshots.find(g => g.id === current?.source_attachment_id)
    ?? (current ? screenshotGroups([current])[0] : undefined);
  const sourceGroup = source?.id === current?.id ? currentGroup : screenshots.find(g => g.id === source?.source_attachment_id);
  const viewedId = viewed?.id;
  useEffect(() => {
    if (!viewedId) return;
    let cancelled = false;
    agentApi.get<WorkItem>(`/items/${viewedId}`).then(item => {
      if (!cancelled) setViewed(item.status === "CLOSED" ? null : item);
    }).catch(() => { if (!cancelled) setError("订单记录更新失败，请刷新重试"); });
    return () => { cancelled = true; };
  }, [viewedId, snapshot.event_cursor, setError]);
  async function refreshAfterEdit() {
    const next = await refresh();
    await library.reload();
    return next;
  }
  async function saved() {
    return !editor.current || (await editor.current.saveForNavigation());
  }
  useEffect(() => {
    const guard = (e: MouseEvent) => {
      const link = e.target instanceof Element ? e.target.closest<HTMLAnchorElement>('a[href]:not([target="_blank"])') : null;
      if (!link || !document.querySelector('[data-unsaved-draft="true"]')) return;
      e.preventDefault();
      e.stopPropagation();
      void confirm({title: "离开当前订单？", description: "还有未保存的修改，离开后这些修改会丢失。", confirmLabel: "放弃修改并离开", cancelLabel: "继续编辑"})
        .then((ok) => { if (ok) router.push(link.href); });
    };
    document.addEventListener("click", guard, true);
    return () => document.removeEventListener("click", guard, true);
  }, [confirm, router]);
  async function select(item: WorkItem) {
    await act(async () => {
      if (!(await saved())) return;
      if (archived || item.status === "CREATED") {
        setViewed(await agentApi.get<WorkItem>(`/items/${item.id}`));
      } else {
        const sid = item.session_id ?? session.id;
        const target = sid === session.id ? snapshot : await agentApi.get<Snapshot>(`/sessions/${sid}/snapshot`);
        if (item.id !== target.session.active_work_item_id)
          await agentApi.command(`/items/${item.id}/select`, {
            expected_revision: item.revision,
            expected_state_revision: target.session.state_revision,
          });
        setViewed(null);
        if (sid !== session.id) router.push(`/?session=${encodeURIComponent(sid)}`);
        else await refreshAfterEdit();
      }
      setMobile("form");
    });
  }
  async function changeTab(next: ScreenshotTab) {
    if (!(await saved())) return;
    setViewed(null);
    setTab(next);
  }
  async function archiveScreenshot(group: ScreenshotGroup) {
    await act(async () => {
      if (!(await saved())) return;
      if (!group.archived && !(await confirm({
        title: "归档这张截图？",
        description: "截图和它下面的所有订单将移到“已归档”。原图、草稿和已创建订单都会保留，可以随时恢复。",
        confirmLabel: "归档截图", destructive: false,
      }))) return;
      await agentApi.command(`/intake/screenshots/${group.id}/${group.archived ? "restore" : "archive"}`, {
        expected_revision: group.revision ?? 0,
      });
      setViewed(null);
      setNotice(group.archived ? "截图已恢复，可继续处理。" : "截图已归档，可在“已归档”中查看和恢复。");
      await refreshAfterEdit();
    });
  }
  async function deleteScreenshot(group: ScreenshotGroup) {
    await act(async () => {
      if (!(await saved())) return;
      if (!(await confirm({
        title: "删除这张归档截图？",
        description: "将永久删除原图及其全部识别记录和草稿，无法恢复。已创建的正式订单会保留，订单管理不受影响。",
        confirmLabel: "删除截图", destructive: true,
      }))) return;
      await agentApi.command(`/intake/screenshots/${group.id}`, {
        expected_revision: group.revision ?? 0,
      }, "DELETE");
      setViewed(null);
      setNotice("归档记录已删除，原图正在清理。已创建的正式订单保留。");
      await refreshAfterEdit();
    });
  }
  async function openUpload() {
    if (!(await saved())) return;
    if (session.status === "ARCHIVED") {
      const next = await agentApi.command<{session: Session}>("/intake/workspace");
      router.push(`/?session=${encodeURIComponent(next.session.id)}`);
      return;
    }
    setUploadOpen(true);
  }
  const done =
    library.counts?.CREATED ??
    items.filter((i) => i.status === "CREATED").length;
  return (
    <main
      className="order-workbench"
      onPaste={(e) => {
        // Portal events can reach this React ancestor again through the DOM root.
        if (e.defaultPrevented) return;
        const images = [...e.clipboardData.files];
        if (images.length && !busy) {
          e.preventDefault();
          e.stopPropagation();
          addFiles(images);
          setUploadOpen(true);
        }
      }}
    >
      <header className="workbench-header">
        <div className="flex items-center gap-3">
          <BackToAssistantButton
            disabled={working}
            onClick={() =>
              void act(async () => {
                if (await saved()) router.push("/");
              })
            }
          />
          <div>
            <h1>截图创建订单</h1>
            <p>上传截图，对照核对，一键创建</p>
          </div>
        </div>
        <div className="workbench-actions">
          <button className="workbench-primary" disabled={working || !!run || uncertain}
            onClick={() => void act(openUpload)}>
            <Plus size={17} />添加截图
          </button>
        </div>
      </header>
      {(error || loadError || library.error) && (
        <div role="alert" className="workbench-error">
          {error || loadError || library.error}{" "}
          <button onClick={() => void act(refreshAfterEdit)}>刷新</button>
        </div>
      )}
      {notice && (
        <div role="status" className="workbench-success">
          <CheckCircle2 size={16} />
          {notice}
          <button aria-label="关闭提示" onClick={() => setNotice("")}>
            ×
          </button>
        </div>
      )}
      {run && (
        <div role="status" className="workbench-progress">
          <LoaderCircle size={15} className="animate-spin" />
          正在识别{screenshots.find(g => g.items.some(i => i.id === run.work_item_id))
            ? ` ${screenshotLabel(screenshots.find(g => g.items.some(i => i.id === run.work_item_id)))}` : "订单截图"}，完成后即可核对。{done > 0 && ` 已创建 ${done} 笔订单。`}
        </div>
      )}
      {archived && (
        <div className="workbench-progress">
          已归档的截图和订单保存在这里，恢复截图后可继续处理。
        </div>
      )}
      <nav className="workbench-mobile-tabs">
        {(
          [
            ["list", "订单列表"],
            ["image", "原始截图"],
            ["form", "订单表单"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            aria-pressed={mobile === key}
            onClick={() => setMobile(key)}
          >
            {label}
          </button>
        ))}
      </nav>
        <div className="workbench-columns" data-mobile-view={mobile}>
          <OrderIntakeList
            screenshots={screenshots}
            counts={library.counts}
            tab={tab}
            onTab={(next) => void act(() => changeTab(next))}
            onArchive={(group) => void archiveScreenshot(group)}
            onDelete={(group) => void deleteScreenshot(group)}
            selectedId={current?.id}
            runningId={run?.work_item_id}
            disabled={working || !!run}
            readOnly={archived}
            onSelect={(i) => void select(i)}
            onRetry={(i) =>
              void act(async () => {
                if (!(await saved())) return;
                await agentApi.command(`/items/${i.id}/recognize`, {
                  expected_revision: i.revision,
                });
                await refresh();
              })
            }
            more={<>
              {library.loading && <p role="status" className="list-empty">正在加载截图…</p>}
              {library.hasMore && <button className="list-more" disabled={working}
                onClick={() => void act(library.more)}>加载更多截图</button>}
            </>}

          />
          <OrderSourceImage
            key={source?.source_attachment_id ?? "empty"}
            attachmentId={source?.source_attachment_id}
            label={sourceGroup ? screenshotLabel(sourceGroup) : undefined}
          />
          <aside className="workbench-form" aria-label="工作区">
            {current?.recognition_status === "SUCCEEDED" ? (
              <OrderDraftEditor
                key={current.id}
                editorRef={editor}
                item={current}
                busy={busy}
                readOnly={archived || session.status === "ARCHIVED" || current.status === "CREATED"}
                workbench
                sourceLabel={screenshotLabel(currentGroup)}
                onChanged={refreshAfterEdit}
                onCompleted={(message) => {
                  setNotice(message);
                  setViewed(null);
                }}
              />
            ) : (
              <div className="workbench-empty">
                <CheckCircle2 size={32} />
                <h2>
                  {run
                    ? "正在整理订单"
                    : done
                      ? `已创建 ${done} 笔订单`
                      : items.length ? "选择一笔订单开始核对" : archived ? "暂无归档截图" : "把订单截图放进来"}
                </h2>
                <p>
                  {run
                    ? "截图识别完成后，订单会显示在这里。"
                    : "从左侧选择待处理订单，或继续添加截图。"}
                </p>
                {!busy && (
                  <button
                    className="workbench-primary"
                    onClick={() => void openUpload()}
                  >
                    {items.length ? "继续添加截图" : "添加订单截图"}
                  </button>
                )}
              </div>
            )}
          </aside>
        </div>
      <Dialog
        open={uploadOpen}
        onOpenChange={(open) => {
          if (!working && !uncertain) setUploadOpen(open);
        }}
      >
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>添加订单截图</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-slate-500">
            每次最多 5 张，每张不超过 5MB。
          </p>
          <input
            ref={uploadInput}
            aria-label="选择订单截图"
            type="file"
            className="hidden"
            multiple
            accept="image/png,image/jpeg"
            onChange={(e) => {
              addFiles([...(e.target.files ?? [])]);
              e.target.value = "";
            }}
          />
          <div className="upload-previews">
            {files.map((f, i) => (
              <div key={f.uploadId}>
                <PendingImagePreview file={f.file} index={i + 1} />
                <button
                  disabled={working || uncertain}
                  aria-label={`移除截图 ${i + 1}`}
                  onClick={() => removeFile(f.uploadId)}
                >
                  ×
                </button>
              </div>
            ))}
            <button
              className="upload-add"
              disabled={working || uncertain}
              onClick={() => uploadInput.current?.click()}
            >
              <ImagePlus size={22} />
              选择图片
            </button>
          </div>
          {error && (
            <p role="alert" className="text-sm text-red-700">
              {error}
            </p>
          )}
          {uncertain && (
            <p className="text-sm text-amber-700">
              上传结果暂未确认，重试不会重复创建任务。
            </p>
          )}
          <button
            className="workbench-primary justify-center"
            disabled={working || !!run || !files.length}
            onClick={() =>
              void (async () => {
                if (!(await saved())) return;
                if (await send()) {
                  setUploadOpen(false);
                  setTab("pending");
                  await library.reload();
                  setNotice("");
                }
              })()
            }
          >
            {working
              ? "正在上传…"
              : uncertain
                ? "重试识别"
                : `识别订单${files.length ? `（${files.length} 张）` : ""}`}
          </button>
        </DialogContent>
      </Dialog>

    </main>
  );
}
