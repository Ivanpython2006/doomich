import { describe, expect, it } from 'vitest'

import { validateGraph } from './graph'
import { invitesCsv } from './invites'
import { qrDataUrl } from './qr'
import { totpSecret } from './totp'

const graph = {
  buildings: [
    {
      slug: 'a',
      name: 'Корпус А',
      floors: [
        {
          level: 1,
          nodes: [
            { key: 'in', kind: 'entrance', x: 0, y: 0 },
            { key: 'r101', kind: 'room', room: '101', x: 10, y: 0 },
          ],
        },
      ],
    },
  ],
  edges: [{ a: 'in', b: 'r101' }],
}

describe('граф кампуса', () => {
  it('считает корпуса, этажи, узлы и аудитории', () => {
    const result = validateGraph(graph)
    expect(result).toMatchObject({ stats: { buildings: 1, floors: 1, nodes: 2, edges: 1, rooms: 1 } })
  })

  it('находит ошибки до замены графа на сервере', () => {
    expect(validateGraph([])).toEqual({ error: 'Нужны поля buildings (корпуса) и edges (рёбра)' })
    expect(validateGraph({ ...graph, edges: [{ a: 'in', b: 'нет' }] })).toEqual({
      error: 'Ребро ссылается на неизвестный узел: in – нет',
    })
    const duplicate = structuredClone(graph)
    duplicate.buildings[0].floors[0].nodes.push({ key: 'in', kind: 'corridor', x: 1, y: 1 })
    expect(validateGraph(duplicate)).toEqual({ error: 'Повторяется ключ узла in' })
    const badKind = structuredClone(graph)
    badKind.buildings[0].floors[0].nodes[0].kind = 'portal'
    expect(validateGraph(badKind)).toEqual({ error: 'Узел in: неизвестный тип «portal»' })
  })
})

describe('приглашения и 2FA', () => {
  it('CSV открывается в Excel: BOM и точка с запятой', () => {
    const csv = invitesCsv([{ code: 'AB2C-DE3F', link: 'https://d.example/invite/AB2C-DE3F', app_link: 'doomich://invite/AB2C-DE3F' }])
    expect(csv.startsWith('﻿Код;Ссылка;')).toBe(true)
    expect(csv).toContain('AB2C-DE3F;https://d.example/invite/AB2C-DE3F;doomich://invite/AB2C-DE3F\r\n')
  })

  it('QR — векторная картинка', async () => {
    const url = await qrDataUrl('https://d.example/invite/AB2C-DE3F')
    expect(url.startsWith('data:image/svg+xml;charset=utf-8,')).toBe(true)
    expect(decodeURIComponent(url)).toContain('<svg')
  })

  it('секрет 2FA из ссылки otpauth', () => {
    expect(totpSecret('otpauth://totp/Doomich:root?secret=JBSWY3DPEHPK3PXP&issuer=Doomich')).toBe('JBSWY3DPEHPK3PXP')
    expect(totpSecret('не ссылка')).toBeNull()
  })
})
