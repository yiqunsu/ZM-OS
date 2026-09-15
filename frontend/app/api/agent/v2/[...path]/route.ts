import { auth } from "@/auth";

export const dynamic = "force-dynamic";
const BACKEND = (
  process.env.BACKEND_INTERNAL_URL ?? "http://backend:8000"
).replace(/\/$/, "");
const MAX_BODY = 6 * 1024 * 1024;

function failure(status: number, code: string, message: string) {
  return Response.json(
    { error: { code, message, retryable: status >= 500, details: {} } },
    { status, headers: { "Cache-Control": "private, no-store" } },
  );
}

async function proxy(
  request: Request,
  context: { params: Promise<{ path: string[] }> },
) {
  const session = await auth();
  if (!session?.backendToken) return failure(401, "AUTH_REQUIRED", "请先登录");
  const { path } = await context.params;
  if (!path.length || path.some((part) => !/^[a-zA-Z0-9_-]+$/.test(part))) {
    return failure(404, "RESOURCE_NOT_FOUND", "资源不存在");
  }
  const siteOrigin = new URL(
    process.env.AUTH_URL ?? process.env.NEXTAUTH_URL ?? request.url,
  ).origin;
  if (
    request.method !== "GET" &&
    request.headers.get("origin") !== siteOrigin
  ) {
    return failure(403, "ORIGIN_REJECTED", "请求来源无效，请刷新页面");
  }
  const headers = new Headers({
    Authorization: `Bearer ${session.backendToken}`,
  });
  for (const key of ["content-type", "idempotency-key", "last-event-id"]) {
    const value = request.headers.get(key);
    if (value) headers.set(key, value);
  }
  let body: Uint8Array | undefined;
  if (request.method !== "GET" && request.body) {
    const reader = request.body.getReader();
    const chunks: Uint8Array[] = [];
    let size = 0;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > MAX_BODY) {
        await reader.cancel();
        return failure(413, "ATTACHMENT_LIMIT", "请求内容过大");
      }
      chunks.push(value);
    }
    body = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) {
      body.set(chunk, offset);
      offset += chunk.byteLength;
    }
  }
  try {
    const upstream = await fetch(
      `${BACKEND}/api/agent/v2/${path.map(encodeURIComponent).join("/")}${new URL(request.url).search}`,
      {
        method: request.method,
        headers,
        body: body as BodyInit | undefined,
        cache: "no-store",
        signal: request.signal,
        redirect: "error",
      },
    );
    const responseHeaders = new Headers({
      "Cache-Control": "private, no-store, no-transform",
      "X-Content-Type-Options": "nosniff",
    });
    for (const key of ["content-type", "x-request-id"]) {
      const value = upstream.headers.get(key);
      if (value) responseHeaders.set(key, value);
    }
    if (upstream.headers.get("content-type")?.includes("text/event-stream")) {
      responseHeaders.set("X-Accel-Buffering", "no");
    }
    return new Response(upstream.body, {
      status: upstream.status,
      headers: responseHeaders,
    });
  } catch {
    return failure(502, "BACKEND_UNAVAILABLE", "连接服务失败，请稍后重试");
  }
}

export {
  proxy as GET,
  proxy as POST,
  proxy as PATCH,
  proxy as PUT,
  proxy as DELETE,
};
