import { CloseOutlined, PrinterOutlined } from '@ant-design/icons'
import { Button, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'

import type { InviteCode, InviteRole } from '../api/types'
import { formatDate } from '../lib/format'
import { qrDataUrl } from '../lib/qr'

export interface InviteSheetProps {
  codes: InviteCode[]
  universityName: string
  role: InviteRole
  groupCode?: string | null
  expiresAt?: string | null
  maxUses: number
  onClose: () => void
}

/** Листы с QR-кодами приглашений: 12 карточек на листе A4, линии для разрезания. */
export function InviteSheet({ codes, universityName, role, groupCode, expiresAt, maxUses, onClose }: InviteSheetProps) {
  const [qrs, setQrs] = useState<string[] | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.all(codes.map((c) => qrDataUrl(c.link))).then((urls) => {
      if (!cancelled) setQrs(urls)
    })
    return () => {
      cancelled = true
    }
  }, [codes])

  useEffect(() => {
    document.body.classList.add('printing-invites')
    return () => document.body.classList.remove('printing-invites')
  }, [])

  const who = role === 'teacher' ? 'Для преподавателя' : groupCode ? `Группа ${groupCode}` : 'Для студента'
  const usage = maxUses > 1 ? `до ${maxUses} активаций` : 'одноразовый'
  const until = expiresAt ? ` · до ${formatDate(expiresAt)}` : ''

  return createPortal(
    <div className="invite-sheet" role="dialog" aria-label="Листы приглашений">
      <div className="invite-sheet__toolbar">
        <Typography.Text strong>Листы приглашений: {codes.length} шт.</Typography.Text>
        <Typography.Text type="secondary">Печать на A4, 12 карточек на листе. Разрежьте по пунктиру.</Typography.Text>
        <div style={{ flex: 1 }} />
        <Button type="primary" icon={<PrinterOutlined />} disabled={!qrs} onClick={() => window.print()}>
          Печать
        </Button>
        <Button icon={<CloseOutlined />} onClick={onClose}>
          Закрыть
        </Button>
      </div>
      <div className="invite-sheet__grid">
        {codes.map((c, i) => (
          <div className="invite-card" key={c.code}>
            <div className="invite-card__title">Думыч</div>
            <div className="invite-card__uni">{universityName}</div>
            {qrs ? (
              <img className="invite-card__qr" src={qrs[i]} alt={`QR-код приглашения ${c.code}`} />
            ) : (
              <div className="invite-card__qr" />
            )}
            <div className="invite-card__code">{c.code}</div>
            <div className="invite-card__meta">
              {who} · {usage}
              {until}
            </div>
            <div className="invite-card__help">
              Установите «Думыч», нажмите «Начать» и отсканируйте QR или введите код. Без телефона, почты и имени.
            </div>
          </div>
        ))}
      </div>
    </div>,
    document.body,
  )
}
