import { describe, expect, it, vi } from 'vitest'

import { jsonResponse, mockServer } from '../test/server'
import { ApiError, onUnauthorized, request, tokenStore } from './client'

describe('клиент админ-API', () => {
  it('добавляет токен и передаёт параметры запроса', async () => {
    tokenStore.set('t-1')
    const { calls } = mockServer({ 'GET /audit': [] })
    await request('/audit', { query: { limit: 50, empty: '' } })
    expect(calls[0]).toMatchObject({ path: '/audit', auth: 'Bearer t-1' })
    expect(String(vi.mocked(fetch).mock.calls[0][0])).toBe('/admin/v1/audit?limit=50')
  })

  it('показывает текст ошибки сервера', async () => {
    mockServer({
      'POST /universities': () => jsonResponse({ detail: 'Такой slug уже занят' }, 409),
      'POST /groups': () => jsonResponse({ detail: [{ msg: 'Поле обязательно' }] }, 422),
    })
    await expect(request('/universities', { method: 'POST', json: {} })).rejects.toEqual(new ApiError('Такой slug уже занят', 409))
    await expect(request('/groups', { method: 'POST', json: {} })).rejects.toThrow('Поле обязательно')
  })

  it('при 401 забывает токен и отправляет на вход', async () => {
    tokenStore.set('old')
    const expired = vi.fn()
    onUnauthorized(expired)
    mockServer({ 'GET /me': () => jsonResponse({ detail: 'Сессия администратора истекла' }, 401) })
    await expect(request('/me')).rejects.toMatchObject({ status: 401 })
    expect(tokenStore.get()).toBeNull()
    expect(expired).toHaveBeenCalledOnce()
    onUnauthorized(null)
  })

  it('без сети — понятная ошибка', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    await expect(request('/me')).rejects.toMatchObject({ status: null, message: expect.stringContaining('VPN') })
  })
})
