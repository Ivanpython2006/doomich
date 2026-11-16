import { useQuery } from '@tanstack/react-query'
import { Flex, Input, Select, Table, Typography } from 'antd'
import { useMemo, useState } from 'react'

import { api } from '../api/endpoints'
import { keys } from '../api/hooks'
import type { AuditEntry } from '../api/types'
import { PageHeader } from '../components/common'
import { formatDateTime } from '../lib/format'

const auditActions: Record<string, string> = {
  login: 'Вход в панель',
  'admin.create': 'Создан администратор',
  'admin.disable': 'Администратор отключён',
  'admin.enable': 'Администратор включён',
  'admin.reset_totp': 'Сброшена 2FA',
  'university.create': 'Создан вуз',
  'university.update': 'Изменены настройки вуза',
  'campus.create': 'Создан кампус',
  'campus.graph.replace': 'Загружен граф кампуса',
  'invites.create': 'Выпущены коды приглашения',
  'invites.revoke': 'Отозваны коды приглашения',
  'schedule.import': 'Импортировано расписание',
  'schedule.source.create': 'Добавлен источник расписания',
  'schedule.source.delete': 'Удалён источник расписания',
  'kb.upload': 'Загружен документ базы знаний',
  'kb.delete': 'Удалён документ базы знаний',
  'model.activate': 'Активирована модель',
}

function details(entry: AuditEntry): string {
  if (!entry.details || Object.keys(entry.details).length === 0) return ''
  return Object.entries(entry.details)
    .map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : String(v)}`)
    .join(', ')
}

export function AuditPage() {
  const [limit, setLimit] = useState(200)
  const [filter, setFilter] = useState('')
  const audit = useQuery({ queryKey: keys.audit(limit), queryFn: () => api.audit(limit) })

  const rows = useMemo(() => {
    const q = filter.trim().toLowerCase()
    if (!q) return audit.data ?? []
    return (audit.data ?? []).filter((e) =>
      [e.action, auditActions[e.action], e.admin_login, e.target, details(e)].some((v) => v?.toLowerCase().includes(q)),
    )
  }, [audit.data, filter])

  return (
    <>
      <PageHeader title="Журнал действий">
        Все изменения в панели: кто, когда и что сделал. Действия студентов сюда не попадают.
      </PageHeader>
      <Flex gap={12} style={{ marginBottom: 16 }} wrap>
        <Input.Search placeholder="Фильтр: действие, логин, объект" allowClear onChange={(e) => setFilter(e.target.value)} style={{ maxWidth: 360 }} />
        <Select
          value={limit}
          onChange={setLimit}
          options={[100, 200, 500].map((n) => ({ value: n, label: `последние ${n}` }))}
          style={{ width: 160 }}
        />
      </Flex>
      <Table<AuditEntry>
        rowKey="id"
        size="small"
        loading={audit.isLoading}
        dataSource={rows}
        pagination={{ pageSize: 50, hideOnSinglePage: true }}
        columns={[
          { title: 'Когда', dataIndex: 'created_at', render: formatDateTime, width: 150 },
          { title: 'Кто', dataIndex: 'admin_login', render: (v: string | null) => v ?? 'удалённый администратор', width: 180 },
          { title: 'Действие', dataIndex: 'action', render: (a: string) => auditActions[a] ?? a },
          { title: 'Объект', dataIndex: 'target', render: (v: string | null) => v ?? '—', ellipsis: true },
          {
            title: 'Подробности',
            key: 'details',
            render: (_, e) => <Typography.Text type="secondary">{details(e)}</Typography.Text>,
          },
        ]}
      />
    </>
  )
}
