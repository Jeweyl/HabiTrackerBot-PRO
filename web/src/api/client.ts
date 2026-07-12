import { clearAccessToken, getAccessToken } from "@/auth/session"

/** API base: empty = same origin (nginx proxy / vite proxy). */
export function apiBase(): string {
  const raw = import.meta.env.VITE_API_BASE_URL
  if (raw === undefined || raw === null) {
    return ""
  }
  return String(raw).replace(/\/$/, "")
}

export class ApiError extends Error {
  status: number
  body: unknown

  constructor(message: string, status: number, body: unknown = null) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.body = body
  }
}

export type RequestOptions = {
  method?: string
  body?: unknown
  auth?: boolean
  signal?: AbortSignal
}

export async function apiRequest<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { method = "GET", body, auth = true, signal } = options
  const headers: Record<string, string> = {
    Accept: "application/json",
  }

  if (body !== undefined) {
    headers["Content-Type"] = "application/json"
  }

  if (auth) {
    const token = getAccessToken()
    if (token) {
      headers.Authorization = `Bearer ${token}`
    }
  }

  const url = `${apiBase()}${path.startsWith("/") ? path : `/${path}`}`

  let response: Response
  try {
    response = await fetch(url, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    })
  } catch (err) {
    throw new ApiError(
      err instanceof Error ? err.message : "Network error",
      0,
    )
  }

  if (response.status === 401 && auth) {
    clearAccessToken()
  }

  const text = await response.text()
  let data: unknown = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = text
    }
  }

  if (!response.ok) {
    const detail =
      typeof data === "object" &&
      data !== null &&
      "detail" in data &&
      (data as { detail: unknown }).detail !== undefined
        ? String((data as { detail: unknown }).detail)
        : `HTTP ${response.status}`
    throw new ApiError(detail, response.status, data)
  }

  return data as T
}
