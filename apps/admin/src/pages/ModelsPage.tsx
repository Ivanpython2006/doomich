import { CheckCircleTwoTone, ReloadOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { Button, Flex, Popconfirm, Segmented, Table, Tag, Typography } from 'antd'
import { useMemo, useState } from 'react'

import { api } from '../api/endpoints'
import { keys, useAction } from '../api/hooks'
import type { ModelKind, ModelVersion } from '../api/types'
import { PageHeader } from '../components/common'
import { formatDateTime } from '../lib/format'
import { useSession } from '../session'

const modelKinds: Record<ModelKind, { label: string; help: string }> = {
  llm_lora: { label: 'LoRA для LLM', help: 'Стиль и знания вуза поверх базовой модели; подключается к vLLM без перезапуска.' },
  embeddings: { label: 'Эмбеддинги', help: 'Поиск по документам и базе знаний вуза.' },
  asr: { label: 'Распознавание речи', help: 'Названия дисциплин, корпусов и фамилии преподавателей.' },
  wakeword: { label: 'Слово «Думыч»', help: 'Скачивается на телефоны и работает без сети.' },
  vpr: { label: 'Навигация по фото', help: 'Узнаёт место в кампусе по фотографии.' },
}

function metricTags(metrics: Record<string, number | string>) {
  return Object.entries(metrics).map(([k, v]) => (
    <Tag key={k}>
      {k}: {typeof v === 'number' ? Number(v.toFixed(4)) : v}
    </Tag>
  ))
}

export function ModelsPage() {
  const { isSuper, university } = useSession()
  const [kind, setKind] = useState<ModelKind | 'all'>('all')
  const models = useQuery({ queryKey: keys.models, queryFn: api.models })
  const activate = useAction((m: ModelVersion) => api.activateModel(m), {
    success: 'Версия активирована',
    invalidate: [keys.models],
  })

  const rows = useMemo(
    () =>
      (models.data ?? [])
        .filter((m) => kind === 'all' || m.kind === kind)
        .sort((a, b) => `${a.tenant}/${a.kind}/${a.scope}`.localeCompare(`${b.tenant}/${b.kind}/${b.scope}`) || b.created_at.localeCompare(a.created_at)),
    [models.data, kind],
  )
  const canActivate = (m: ModelVersion) => isSuper || m.tenant === university?.slug

  return (
    <>
      <PageHeader
        title="Модели"
        extra={
          <Button icon={<ReloadOutlined />} onClick={() => models.refetch()} loading={models.isFetching}>
            Обновить
          </Button>
        }
      >
        Модели обучает ML-платформа (<Typography.Text code>doomich-ml</Typography.Text>) отдельно для вуза или
        кампуса и кладёт в реестр вместе с метриками. Здесь выбирается активная версия; «_global» — общие модели по
        умолчанию для всех вузов. Новая версия начинает работать сразу, откатиться можно, активировав прежнюю.
      </PageHeader>
      <Segmented<ModelKind | 'all'>
        style={{ marginBottom: 16 }}
        value={kind}
        onChange={setKind}
        options={[{ value: 'all', label: 'Все' }, ...Object.entries(modelKinds).map(([value, k]) => ({ value: value as ModelKind, label: k.label }))]}
      />
      <Table<ModelVersion>
        rowKey={(m) => `${m.tenant}/${m.kind}/${m.scope}/${m.version}`}
        loading={models.isLoading}
        dataSource={rows}
        pagination={{ pageSize: 30, hideOnSinglePage: true }}
        locale={{ emptyText: 'В реестре пока нет моделей' }}
        columns={[
          { title: 'Вуз', dataIndex: 'tenant', render: (t: string) => <Typography.Text code>{t}</Typography.Text> },
          {
            title: 'Тип',
            dataIndex: 'kind',
            render: (k: ModelKind) => (
              <span title={modelKinds[k]?.help}>{modelKinds[k]?.label ?? k}</span>
            ),
          },
          { title: 'Область', dataIndex: 'scope', render: (s: string) => (s === 'default' ? 'весь вуз' : `кампус ${s}`) },
          { title: 'Версия', dataIndex: 'version' },
          { title: 'Создана', dataIndex: 'created_at', render: formatDateTime, width: 150 },
          { title: 'Метрики', dataIndex: 'metrics', render: metricTags },
          {
            title: '',
            key: 'active',
            width: 170,
            render: (_, m) =>
              m.active ? (
                <Flex gap={6} align="center">
                  <CheckCircleTwoTone twoToneColor="#52c41a" /> активна
                </Flex>
              ) : (
                canActivate(m) && (
                  <Popconfirm
                    title="Сделать эту версию активной?"
                    description="Предыдущая активная версия останется в реестре — к ней можно вернуться."
                    okText="Активировать"
                    onConfirm={() => activate.mutateAsync(m)}
                  >
                    <Button size="small">Активировать</Button>
                  </Popconfirm>
                )
              ),
          },
        ]}
      />
    </>
  )
}
