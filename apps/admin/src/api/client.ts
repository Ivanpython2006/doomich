/** HTTP-клиент админ-API: токен администратора, понятные ошибки, выход при истёкшей сессии. */

export class ApiError extends Error {
  readonly status: number | null

  constructor(message: string, status: number | null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

const TOKEN_KEY = 'doomich-admin-token'

/** Токен живёт только до закрытия вкладки (sessionStorage) и не попадает в localStorage. */
export const tokenStore = {
  get: (): string | null => sessionStorage.getItem(TOKEN_KEY),
  set: (token: string): void => sessionStorage.setItem(TOKEN_KEY, token),
  clear: (): void => sessionStorage.removeItem(TOKEN_KEY),
}

let unauthorizedHandler: (() => void) | null = null

/** Что делать, если сервер ответил 401 (сессия истекла или администратора отключили). */
export function onUnauthorized(handler: (() => void) | null): void {
  unauthorizedHandler = handler
}

export const API_BASE = `${import.meta.env.VITE_API_BASE ?? ''}/admin/v1`

async function errorMessage(resp: Response): Promise<string> {
  try {
    const data: unknown = await resp.json()
    const detail = (data as { detail?: unknown } | null)?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      const messages = detail.map((d) => (d as { msg?: string }).msg).filter(Boolean)
      if (messages.length) return messages.join('; ')
    }
  } catch {
    // ответ не JSON
  }
  if (resp.status === 403) return 'Недостаточно прав'
  if (resp.status === 413) return 'Файл слишком большой'
  return `Ошибка сервера (${resp.status})`
}

export interface RequestOptions extends Omit<RequestInit, 'body'> {
  json?: unknown
  form?: FormData
  query?: Record<string, string | number | boolean | undefined | null>
}

async function send(path: string, options: RequestOptions = {}): Promise<Response> {
  const { json, form, query, headers: extraHeaders, ...init } = options
  const headers = new Headers(extraHeaders)
  const token = tokenStore.get()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  let body: BodyInit | undefined
  if (json !== undefined) {
    headers.set('Content-Type', 'application/json')
    body = JSON.stringify(json)
  } else if (form) {
    body = form
  }
  let url = API_BASE + path
  if (query) {
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== '') params.set(key, String(value))
    }
    const qs = params.toString()
    if (qs) url += `?${qs}`
  }
  let resp: Response
  try {
    resp = await fetch(url, { ...init, headers, body })
  } catch {
    throw new ApiError('Нет связи с сервером. Проверьте VPN и адрес панели.', null)
  }
  if (resp.status === 401 && path !== '/auth/login') {
    tokenStore.clear()
    unauthorizedHandler?.()
  }
  if (!resp.ok) throw new ApiError(await errorMessage(resp), resp.status)
  return resp
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const resp = await send(path, options)
  if (resp.status === 204) return undefined as T
  return (await resp.json()) as T
}

export async function requestBlob(path: string, options: RequestOptions = {}): Promise<Blob> {
  const resp = await send(path, options)
  return resp.blob()
}

/** Сохранить файл на компьютер администратора. */
export function saveFile(data: Blob | string, filename: string, type = 'application/octet-stream'): void {
  const blob = typeof data === 'string' ? new Blob([data], { type }) : data
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.append(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
