import { beforeEach, describe, expect, it, vi } from 'vitest'
import { authenticatedFetch, apiJson, ApiError } from '@/lib/api-fetch'
import { clearToken } from '@/lib/auth'

vi.mock('@/lib/api-config', () => ({
  getApiBaseUrl: () => 'https://api.example.test',
}))

vi.mock('@/lib/auth', () => ({
  getToken: () => 'jwt-token',
  clearToken: vi.fn(),
}))

describe('apiFetch', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.mocked(clearToken).mockClear()
  })

  it('adds bearer authentication and parses JSON', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    await expect(apiJson<{ ok: boolean }>('/api/test')).resolves.toEqual({ ok: true })

    const request = fetchMock.mock.calls[0][0] as Request
    expect(request.url).toBe('https://api.example.test/api/test')
    expect(request.headers.get('Authorization')).toBe('Bearer jwt-token')
  })

  it('throws structured JSON errors', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Invalid run' }), {
        status: 422,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    await expect(apiJson('/api/test')).rejects.toEqual(
      expect.objectContaining({ status: 422, message: 'Invalid run' }),
    )
  })

  it('throws structured text errors', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('Gateway unavailable', { status: 503 }),
    )

    await expect(apiJson('/api/test')).rejects.toEqual(
      expect.objectContaining({
        name: 'ApiError',
        status: 503,
        message: 'Gateway unavailable',
        detail: 'Gateway unavailable',
      }),
    )
  })

  it('can return a checked streaming response', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('stream', { status: 200 }))

    const response = await authenticatedFetch('/api/stream')

    await expect(response.text()).resolves.toBe('stream')
  })

  it('supports public requests without authentication or redirects', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('Unauthorized', { status: 401 }),
    )

    await expect(
      authenticatedFetch(
        '/api/auth/login',
        { method: 'POST' },
        { auth: false, redirectOnUnauthorized: false },
      ),
    ).rejects.toBeInstanceOf(ApiError)

    const request = fetchMock.mock.calls[0][0] as Request
    expect(request.headers.has('Authorization')).toBe(false)
    expect(clearToken).not.toHaveBeenCalled()
  })

  it('returns undefined for an empty successful response', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(null, { status: 204 }))

    await expect(apiJson<void>('/api/test', { method: 'DELETE' })).resolves.toBeUndefined()
  })
})
