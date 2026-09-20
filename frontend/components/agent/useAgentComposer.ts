"use client";
import { useRef, useState } from "react";
import { AgentError, agentApi } from "./api";
import type { Session } from "./types";
import type { AgentOperation } from "./useAgentOperation";
type PendingFile = { file: File; uploadId: string };
type MessageInput = {
  client_message_id: string;
  content: string;
  attachment_ids: string[];
  expected_state_revision: number;
  target_work_item_id: string | null;
};

export function useAgentComposer({
  session,
  busy,
  act,
  refresh,
  setError,
  recognizeOnly = false,
}: {
  session: Session | undefined;
  busy: boolean;
  act: AgentOperation;
  refresh: () => Promise<unknown>;
  setError: (message: string) => void;
  recognizeOnly?: boolean;
}) {
  const [text, setText] = useState("");
  const [files, setFiles] = useState<PendingFile[]>([]);
  const [uncertain, setUncertain] = useState(false);
  // The parent is keyed by session ID: uploads and uncertain sends never cross sessions.
  const pending = useRef<MessageInput | null>(null);
  const uploadedAttachments = useRef(new Map<string, string>());
  const input = useRef<HTMLInputElement>(null);
  function addFiles(selected: File[]) {
    if (busy || uncertain || session?.agent_type !== "ORDER_INTAKE") return;
    if (
      files.length + selected.length > 5 ||
      selected.some(
        (f) =>
          f.size > 5 * 1024 * 1024 ||
          !["image/png", "image/jpeg"].includes(f.type),
      )
    ) {
      setError("每次最多5张PNG或JPEG截图，每张不超过5MB。");
      return;
    }
    setFiles((old) => [
      ...old,
      ...selected.map((file) => ({ file, uploadId: crypto.randomUUID() })),
    ]);
  }
  async function send() {
    if (!session || busy || (!text.trim() && !files.length && !pending.current))
      return;
    let accepted = false;
    await act(async () => {
      try {
        if (!pending.current) {
          const attachmentIds = [];
          for (const entry of files) {
            let attachmentId = uploadedAttachments.current.get(entry.uploadId);
            if (!attachmentId) {
              const form = new FormData();
              form.set("file", entry.file);
              form.set("client_upload_id", entry.uploadId);
              const uploaded = await agentApi.upload<{ id: string }>(
                `/sessions/${session.id}/attachments`,
                form,
              );
              attachmentId = uploaded.id;
              uploadedAttachments.current.set(entry.uploadId, attachmentId);
            }
            attachmentIds.push(attachmentId);
          }
          pending.current = {
            client_message_id: crypto.randomUUID(),
            content: recognizeOnly ? "" : text.trim(),
            attachment_ids: attachmentIds,
            expected_state_revision: session.state_revision,
            target_work_item_id: attachmentIds.length
              ? null
              : session.active_work_item_id,
          };
        }
        await agentApi.send(
          `/sessions/${session.id}/${recognizeOnly ? "recognize" : "messages"}`,
          pending.current,
        );
        accepted = true;
        pending.current = null;
        setUncertain(false);
        setText("");
        setFiles([]);
        uploadedAttachments.current.clear();
      } catch (e) {
        // A transport failure may follow a committed acceptance. Retry the exact same input and ID.
        if (e instanceof AgentError && e.status >= 400 && e.status < 500) {
          pending.current = null;
          setUncertain(false);
          await refresh();
        } else setUncertain(true);
        throw e;
      }
      await refresh();
    });
    return accepted;
  }
  function removeFile(uploadId: string) {
    if (busy || uncertain) return;
    uploadedAttachments.current.delete(uploadId);
    setFiles((old) => old.filter((entry) => entry.uploadId !== uploadId));
  }
  return { text, setText, files, uncertain, input, addFiles, removeFile, send };
}
export type AgentComposerState = ReturnType<typeof useAgentComposer>;
