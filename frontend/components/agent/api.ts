const BASE = "/api/agent/v2";
export class AgentError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}
async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    cache: "no-store",
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new AgentError(
      response.status,
      payload?.error?.code ?? "REQUEST_FAILED",
      payload?.error?.message ?? "请求失败，请重试",
    );
  }
  return response.json();
}
export const agentApi = {
  get: <T>(path: string, signal?: AbortSignal) => request<T>(path, { signal }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  put: <T>(path: string, body: unknown) =>
    request<T>(path, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  send: <T>(path: string, body: unknown) =>
    request<T>(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  upload: <T>(path: string, body: FormData) =>
    request<T>(path, { method: "POST", body }),
  async command<T>(
    path: string,
    payload: unknown = {},
    method = "POST",
  ): Promise<T> {
    const body = JSON.stringify(payload);
    const digest = await crypto.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(`${method}:${path}:${body}`),
    );
    const storageKey = `agent-command:${Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("")}`;
    const key = sessionStorage.getItem(storageKey) ?? crypto.randomUUID();
    sessionStorage.setItem(storageKey, key);
    const result = await request<T>(path, {
      method,
      headers: { "Content-Type": "application/json", "Idempotency-Key": key },
      body,
    });
    sessionStorage.removeItem(storageKey);
    return result;
  },
};
export const attachmentUrl = (id: string) =>
  `${BASE}/attachments/${encodeURIComponent(id)}/content`;
