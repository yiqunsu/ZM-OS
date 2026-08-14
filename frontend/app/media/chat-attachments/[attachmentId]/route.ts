import { auth } from "@/auth";

const BACKEND_INTERNAL_URL = (process.env.BACKEND_INTERNAL_URL ?? "http://backend:8000").replace(/\/$/, "");
const SUPPORTED_IMAGE_TYPES = new Set(["image/jpeg", "image/png"]);

const PRIVATE_MEDIA_HEADERS = {
  "Cache-Control": "private, no-store, max-age=0",
  "Content-Disposition": "inline",
  "Content-Security-Policy": "default-src 'none'",
  Pragma: "no-cache",
  "X-Content-Type-Options": "nosniff",
} as const;

export const dynamic = "force-dynamic";

function errorResponse(status: number, detail: string): Response {
  return Response.json(
    { detail },
    {
      status,
      headers: PRIVATE_MEDIA_HEADERS,
    },
  );
}

function safeUpstreamError(status: number): Response {
  if (status === 401) return errorResponse(401, "登录已过期，请重新登录");
  if (status === 403) return errorResponse(403, "无权访问此附件");
  if (status === 404) return errorResponse(404, "附件不存在");
  const safeStatus = status >= 400 && status <= 599 ? status : 502;
  return errorResponse(safeStatus, "附件读取失败");
}

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ attachmentId: string }> },
): Promise<Response> {
  const session = await auth();
  if (!session?.backendToken) {
    return errorResponse(401, "请先登录");
  }

  const { attachmentId } = await params;
  if (!attachmentId.trim()) {
    return errorResponse(404, "附件不存在");
  }

  let upstream: Response;
  try {
    upstream = await fetch(
      `${BACKEND_INTERNAL_URL}/api/agent/attachments/${encodeURIComponent(attachmentId)}`,
      {
        headers: { Authorization: `Bearer ${session.backendToken}` },
        cache: "no-store",
      },
    );
  } catch {
    return errorResponse(502, "附件服务暂时不可用");
  }

  if (!upstream.ok) {
    return safeUpstreamError(upstream.status);
  }

  const contentType = upstream.headers.get("content-type")?.split(";", 1)[0].trim().toLowerCase();
  if (!contentType || !SUPPORTED_IMAGE_TYPES.has(contentType) || !upstream.body) {
    return errorResponse(502, "附件响应无效");
  }

  const headers = new Headers(PRIVATE_MEDIA_HEADERS);
  headers.set("Content-Type", contentType);
  const contentLength = upstream.headers.get("content-length");
  if (contentLength && /^\d+$/.test(contentLength)) {
    headers.set("Content-Length", contentLength);
  }

  return new Response(upstream.body, {
    status: 200,
    headers,
  });
}
