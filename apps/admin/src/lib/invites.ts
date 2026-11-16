import type { InviteCode } from '../api/types'

/** CSV для Excel: разделитель «;» и BOM, чтобы кириллица открылась без настроек. */
export function invitesCsv(codes: InviteCode[]): string {
  const lines = ['Код;Ссылка;Ссылка для приложения', ...codes.map((c) => `${c.code};${c.link};${c.app_link}`)]
  return `﻿${lines.join('\r\n')}\r\n`
}
