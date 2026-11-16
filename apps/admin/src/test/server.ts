import { vi } from 'vitest'

export interface Call {
  method: string
  path: string
  body: unknown
  auth: string | null
}

type Json = null | boolean | number | string | Json[] | { [key: string]: Json }
type Handler = (call: Call) => Json | Response

/** Подменный fetch: отвечает по таблице «МЕТОД путь» и запоминает запросы. */
export function mockServer(routes: Record<string, Handler | Json>) {
  const calls: Call[] = []
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://panel.test')
    const method = (init?.method ?? 'GET').toUpperCase()
    const path = url.pathname.replace(/^\/admin\/v1/, '')
    const headers = new Headers(init?.headers)
    let body: unknown = init?.body
    if (typeof body === 'string') body = JSON.parse(body)
    const call: Call = { method, path, body, auth: headers.get('Authorization') }
    calls.push(call)
    const route = routes[`${method} ${path}`]
    if (route === undefined) return new Response(JSON.stringify({ detail: `нет маршрута ${method} ${path}` }), { status: 404 })
    const result = typeof route === 'function' ? (route as Handler)(call) : route
    if (result instanceof Response) return result
    return new Response(JSON.stringify(result), { status: 200, headers: { 'Content-Type': 'application/json' } })
  })
  vi.stubGlobal('fetch', fetchMock)
  return { calls, fetchMock }
}

export function jsonResponse(data: unknown, status: number): Response {
  return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })
}
