import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { describe, expect, it } from 'vitest'

import { tokenStore } from './api/client'
import { InviteSheet } from './components/InviteSheet'
import { createQueryClient } from './lib/queryClient'
import { Providers } from './providers'
import { routes } from './routes'
import { jsonResponse, mockServer } from './test/server'

function renderPanel(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  render(
    <Providers client={createQueryClient()}>
      <RouterProvider router={router} />
    </Providers>,
  )
  return router
}

const university = { id: 'u1', slug: 'demo', name: 'Демо-университет', timezone: 'Europe/Moscow', settings: {} }

describe('панель администратора', () => {
  it('без входа открывает страницу входа, после входа — обзор', async () => {
    const { calls } = mockServer({
      'POST /auth/login': (call) =>
        (call.body as { totp: string }).totp === '123456'
          ? { access_token: 'tok', role: 'superadmin', university_id: null }
          : jsonResponse({ detail: 'Неверный код из приложения-аутентификатора' }, 401),
      'GET /me': { id: 'a1', login: 'root', role: 'superadmin', university_id: null },
      'GET /universities': [university],
      'GET /status': {
        checks: { database: 'ok', llm: 'fake' },
        documents: { ready: 3 },
        users: 42,
        feedback: { '1': 5, '-1': 1 },
        embedder: 'fake-embedder',
      },
    })
    const user = userEvent.setup()
    const router = renderPanel('/')
    expect(await screen.findByText('Думыч · администрирование')).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/login')

    await user.type(screen.getByLabelText('Логин'), 'root')
    await user.type(screen.getByLabelText('Пароль'), 'очень-длинный-пароль')
    await user.type(screen.getByLabelText('Код 2FA'), '000 000')
    await user.click(screen.getByRole('button', { name: 'Войти' }))
    expect(await screen.findByText('Неверный код из приложения-аутентификатора')).toBeInTheDocument()

    await user.clear(screen.getByLabelText('Код 2FA'))
    await user.type(screen.getByLabelText('Код 2FA'), '123 456')
    await user.click(screen.getByRole('button', { name: 'Войти' }))
    expect(await screen.findByText('Пользователей')).toBeInTheDocument()
    expect(await screen.findByText('42')).toBeInTheDocument()
    expect(screen.getByText('демо-режим')).toBeInTheDocument()
    expect(tokenStore.get()).toBe('tok')
    expect(calls.find((c) => c.path === '/auth/login' && (c.body as { totp: string }).totp === '123456')).toBeTruthy()
    expect(calls.filter((c) => c.path === '/status').every((c) => c.auth === 'Bearer tok')).toBe(true)
  })

  it('администратор вуза не видит раздел администраторов и работает только со своим вузом', async () => {
    tokenStore.set('tok')
    mockServer({
      'GET /me': { id: 'a2', login: 'demo-admin', role: 'university_admin', university_id: 'u1' },
      'GET /universities': [university],
      'GET /universities/u1/groups': [{ id: 'g1', code: 'ИВТ-21-1', name: null, faculty: 'ФИТ' }],
    })
    renderPanel('/groups')
    expect(await screen.findByText('ИВТ-21-1')).toBeInTheDocument()
    expect(screen.getByText('Демо-университет')).toBeInTheDocument()
    expect(screen.queryByText('Администраторы')).not.toBeInTheDocument()
    expect(screen.getByText('администратор вуза')).toBeInTheDocument()
  })

  it('истёкшая сессия возвращает на страницу входа', async () => {
    tokenStore.set('expired')
    mockServer({ 'GET /me': () => jsonResponse({ detail: 'Сессия администратора истекла' }, 401) })
    const router = renderPanel('/audit')
    expect(await screen.findByText('Сессия истекла — войдите снова.')).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/login')
  })
})

describe('листы приглашений', () => {
  it('карточка на каждый код с QR и пометкой группы, класс для печати снимается при закрытии', async () => {
    const codes = ['AB2C-DE3F', 'GH4J-KL5M'].map((code) => ({
      code,
      link: `https://d.example/invite/${code}`,
      app_link: `doomich://invite/${code}`,
    }))
    const { unmount } = render(
      <InviteSheet
        codes={codes}
        universityName="Демо-университет"
        role="student"
        groupCode="ИВТ-21-1"
        expiresAt="2027-01-15T00:00:00Z"
        maxUses={1}
        onClose={() => {}}
      />,
    )
    const sheet = screen.getByRole('dialog', { name: 'Листы приглашений' })
    expect(within(sheet).getByText('AB2C-DE3F')).toBeInTheDocument()
    expect(within(sheet).getAllByText(/Группа ИВТ-21-1 · одноразовый · до 15\.01\.2027/)).toHaveLength(2)
    await waitFor(() => expect(within(sheet).getAllByRole('img')).toHaveLength(2))
    expect(document.body).toHaveClass('printing-invites')
    unmount()
    expect(document.body).not.toHaveClass('printing-invites')
  })
})
