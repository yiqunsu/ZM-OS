import { getSession, signOut } from "next-auth/react"

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api"

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const session = await getSession()
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(session?.backendToken ? { Authorization: `Bearer ${session.backendToken}` } : {}),
      ...init?.headers,
    },
  })
  if (res.status === 401) {
    await signOut({ callbackUrl: "/login" })
    throw new ApiError(401, "登录已过期，请重新登录")
  }
  if (!res.ok) {
    let message = "请求失败"
    try {
      const data = await res.json()
      message = data.detail ?? data.error ?? message
    } catch {
      // ignore
    }
    throw new ApiError(res.status, message)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body) }),
  put: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
  delete: (path: string) => request<void>(path, { method: "DELETE" }),
}

/**
 * POST that returns the raw Response for SSE streaming, with the JWT attached.
 * The caller reads `res.body` as a stream. On non-OK, throws ApiError.
 */
export async function postStream(path: string, body: unknown): Promise<Response> {
  const session = await getSession()
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(session?.backendToken ? { Authorization: `Bearer ${session.backendToken}` } : {}),
    },
    body: JSON.stringify(body),
  })
  if (res.status === 401) {
    await signOut({ callbackUrl: "/login" })
    throw new ApiError(401, "登录已过期，请重新登录")
  }
  if (!res.ok) {
    let message = "请求失败"
    try {
      const data = await res.json()
      message = data.detail ?? data.error ?? message
    } catch {
      // ignore
    }
    throw new ApiError(res.status, message)
  }
  return res
}
