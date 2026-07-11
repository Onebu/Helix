import { getApiBaseUrl } from '@/lib/api-config'
import { clearToken, getToken } from '@/lib/auth'

export class ApiError extends Error {
  readonly status: number
  readonly detail: unknown

  constructor(message: string, status: number, detail: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

interface RequestOptions {
  auth?: boolean
  redirectOnUnauthorized?: boolean
}

export async function authenticatedFetch(
  path: string,
  init: RequestInit = {},
  options: RequestOptions = {},
): Promise<Response> {
  const headers = new Headers(init.headers)
  const token = getToken()
  if (options.auth !== false && token) headers.set('Authorization', `Bearer ${token}`)

  const baseUrl = getApiBaseUrl()
  const url = baseUrl ? `${baseUrl}${path}` : new URL(path, window.location.origin).href
  const response = await fetch(new Request(url, { ...init, headers }))
  if (response.status === 401 && options.redirectOnUnauthorized !== false) {
    clearToken()
    if (window.location.pathname !== '/login') window.location.assign('/login')
  }
  if (response.ok) return response

  const contentType = response.headers.get('content-type') ?? ''
  const detail = contentType.includes('application/json')
    ? await response.clone().json().catch(() => response.text())
    : await response.text()
  const message = typeof detail === 'object' && detail && 'detail' in detail
    ? String((detail as { detail: unknown }).detail)
    : String(detail || `Request failed with status ${response.status}`)
  throw new ApiError(message, response.status, detail)
}

export async function apiJson<T>(
  path: string,
  init: RequestInit = {},
  options: RequestOptions = {},
): Promise<T> {
  const response = await authenticatedFetch(path, init, options)
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}
