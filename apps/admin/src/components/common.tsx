import { Empty, Flex, Tag, Tooltip, Typography } from 'antd'
import type { ReactNode } from 'react'

export function PageHeader({ title, extra, children }: { title: ReactNode; extra?: ReactNode; children?: ReactNode }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <Flex justify="space-between" align="center" gap={16} wrap>
        <Typography.Title level={3} style={{ margin: 0 }}>
          {title}
        </Typography.Title>
        {extra && <Flex gap={8} wrap>{extra}</Flex>}
      </Flex>
      {children && (
        <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0, maxWidth: 900 }}>
          {children}
        </Typography.Paragraph>
      )}
    </div>
  )
}

/** Заглушка для страниц вуза, когда вуз ещё не создан или не выбран. */
export function NeedUniversity() {
  return (
    <Empty
      style={{ marginTop: 64 }}
      description="Сначала создайте вуз на странице «Вуз и функции» или выберите его в шапке."
    />
  )
}

const documentStatuses: Record<string, { color: string; label: string }> = {
  queued: { color: 'default', label: 'В очереди' },
  processing: { color: 'processing', label: 'Обработка' },
  ready: { color: 'success', label: 'Готов' },
  error: { color: 'error', label: 'Ошибка' },
}

export function DocumentStatus({ status }: { status: string }) {
  const info = documentStatuses[status] ?? { color: 'default', label: status }
  return <Tag color={info.color}>{info.label}</Tag>
}

/** Состояние внешнего сервиса из /status: ok — зелёный, fake — демо-режим, иначе — ошибка. */
export function HealthTag({ value }: { value: string }) {
  if (value === 'ok') return <Tag color="success">работает</Tag>
  if (value === 'fake') return <Tag color="blue">демо-режим</Tag>
  const label = value.startsWith('unreachable') ? 'недоступен' : value.startsWith('http') ? `ошибка (${value})` : 'ошибка'
  return (
    <Tooltip title={value}>
      <Tag color="error">{label}</Tag>
    </Tooltip>
  )
}
