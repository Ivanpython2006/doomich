import { DeleteOutlined, DownloadOutlined, InboxOutlined, PlusOutlined, SyncOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import {
  Alert,
  App,
  Button,
  Card,
  DatePicker,
  Descriptions,
  Flex,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  Upload,
} from 'antd'
import type { Dayjs } from 'dayjs'
import { useState } from 'react'

import { saveFile } from '../api/client'
import { api } from '../api/endpoints'
import { errorText, keys, useAction } from '../api/hooks'
import type { ImportErrorRow, ImportSummary, ScheduleImport, ScheduleSource, SourceKind } from '../api/types'
import { NeedUniversity, PageHeader } from '../components/common'
import { formatDateTime } from '../lib/format'
import { useUniversity } from '../session'

export function SchedulePage() {
  const university = useUniversity()
  if (!university) return <NeedUniversity />
  return (
    <>
      <PageHeader title="Расписание">
        Загрузите файл расписания (Excel по шаблону, CSV или календарь .ics) или подключите сайт вуза как источник —
        он будет синхронизироваться автоматически. Время указывается в часовом поясе вуза ({university.timezone}).
      </PageHeader>
      <Tabs
        items={[
          { key: 'file', label: 'Загрузка файла', children: <FileImport universityId={university.id} /> },
          { key: 'sources', label: 'Источники', children: <Sources universityId={university.id} /> },
          { key: 'history', label: 'История импорта', children: <History universityId={university.id} /> },
        ]}
      />
    </>
  )
}

const errorColumns = [
  { title: 'Строка', dataIndex: 'row', width: 90, render: (v: number | null) => v ?? '—' },
  { title: 'Что не так', dataIndex: 'error' },
]

function ImportErrors({ errors }: { errors: ImportErrorRow[] }) {
  if (!errors.length) return null
  return (
    <Table<ImportErrorRow>
      size="small"
      rowKey={(r) => `${r.row}-${r.error}`}
      dataSource={errors}
      columns={errorColumns}
      pagination={{ pageSize: 10, hideOnSinglePage: true }}
      title={() => `Строки с ошибками (${errors.length}) — они будут пропущены`}
    />
  )
}

function FileImport({ universityId }: { universityId: string }) {
  const { message } = App.useApp()
  const [file, setFile] = useState<File | null>(null)
  const [semesterStart, setSemesterStart] = useState<Dayjs | null>(null)
  const [group, setGroup] = useState('')
  const [preview, setPreview] = useState<ImportSummary | null>(null)
  const [applied, setApplied] = useState<ImportSummary | null>(null)
  const isIcs = file?.name.toLowerCase().endsWith('.ics') ?? false

  const run = useAction(
    (mode: { preview: boolean }) =>
      api.importSchedule(universityId, file!, {
        preview: mode.preview,
        semesterStart: semesterStart?.format('YYYY-MM-DD'),
        group: group.trim() || null,
      }),
    { invalidate: [['imports'], ['groups']] },
  )

  function check() {
    setApplied(null)
    run.mutate({ preview: true }, { onSuccess: setPreview })
  }

  function apply() {
    run.mutate(
      { preview: false },
      {
        onSuccess: (result) => {
          setApplied(result)
          setPreview(null)
          message.success('Расписание обновлено')
        },
      },
    )
  }

  async function downloadTemplate() {
    try {
      saveFile(await api.scheduleTemplate(), 'schedule-template.xlsx')
    } catch (e) {
      message.error(errorText(e))
    }
  }

  return (
    <Flex vertical gap={16} style={{ maxWidth: 900 }}>
      <Card size="small">
        <Typography.Paragraph style={{ marginBottom: 8 }}>
          Шаблон Excel: группа, дата или день недели с чётностью, время, дисциплина, тип занятия, аудитория, корпус,
          преподаватель, подгруппа. Повторная загрузка заменяет занятия групп из файла за те же дни, студенты увидят
          изменения.
        </Typography.Paragraph>
        <Button icon={<DownloadOutlined />} onClick={downloadTemplate}>
          Скачать шаблон Excel
        </Button>
      </Card>
      <Upload.Dragger
        accept=".xlsx,.xlsm,.csv,.ics"
        height={170}
        maxCount={1}
        beforeUpload={(f) => {
          setFile(f)
          setPreview(null)
          setApplied(null)
          return false
        }}
        onRemove={() => {
          setFile(null)
          setPreview(null)
        }}
        fileList={file ? [{ uid: 'schedule', name: file.name, status: 'done' }] : []}
      >
        <p className="ant-upload-drag-icon">
          <InboxOutlined />
        </p>
        <p className="ant-upload-text">Перетащите файл расписания или нажмите, чтобы выбрать</p>
        <p className="ant-upload-hint">.xlsx, .csv или .ics, до 20 МБ</p>
      </Upload.Dragger>
      <Flex gap={16} wrap align="end">
        <div>
          <Typography.Text>Начало семестра</Typography.Text>
          <Tooltip title="Нужно для чётности недель («числитель/знаменатель»), если в файле не даты, а дни недели">
            <DatePicker
              style={{ display: 'block', marginTop: 4 }}
              value={semesterStart}
              onChange={setSemesterStart}
              format="DD.MM.YYYY"
              placeholder="не обязательно"
            />
          </Tooltip>
        </div>
        {isIcs && (
          <div>
            <Typography.Text>Группа для календаря</Typography.Text>
            <Input
              style={{ display: 'block', marginTop: 4, width: 220 }}
              value={group}
              onChange={(e) => setGroup(e.target.value)}
              placeholder="ИВТ-21-1"
            />
          </div>
        )}
        <Button type="primary" disabled={!file || (isIcs && !group.trim())} loading={run.isPending} onClick={check}>
          Проверить
        </Button>
      </Flex>

      {preview && (
        <Card title="Проверка файла" size="small">
          <Descriptions column={1} size="small">
            <Descriptions.Item label="Занятий">{preview.events}</Descriptions.Item>
            <Descriptions.Item label="Групп">
              <Flex gap={4} wrap>
                {preview.groups.map((g) => (
                  <Tag key={g}>{g}</Tag>
                ))}
              </Flex>
            </Descriptions.Item>
          </Descriptions>
          <ImportErrors errors={preview.errors} />
          {preview.events > 0 ? (
            <Popconfirm
              title="Применить расписание?"
              description="Занятия этих групп за дни из файла будут заменены."
              okText="Применить"
              onConfirm={apply}
            >
              <Button type="primary" loading={run.isPending} style={{ marginTop: 12 }}>
                Применить
              </Button>
            </Popconfirm>
          ) : (
            <Alert type="error" showIcon title="В файле не найдено ни одного занятия" style={{ marginTop: 12 }} />
          )}
        </Card>
      )}
      {applied?.stats && (
        <Alert
          type="success"
          showIcon
          title="Расписание обновлено"
          description={`Групп: ${applied.stats.groups}, добавлено занятий: ${applied.stats.added}, изменено: ${applied.stats.changed}, удалено: ${applied.stats.removed}, без изменений: ${applied.stats.unchanged}.`}
        />
      )}
    </Flex>
  )
}

const sourceKinds: { value: SourceKind; label: string; example: Record<string, unknown> }[] = [
  {
    value: 'json',
    label: 'JSON API',
    example: {
      url: 'https://rasp.example.ru/api/lessons',
      items: 'data.lessons',
      fields: { group: 'group.name', date: 'date', start: 'time_start', end: 'time_end', subject: 'discipline', room: 'auditorium', teacher: 'teacher.name', kind: 'type' },
    },
  },
  {
    value: 'html',
    label: 'HTML-таблица на сайте',
    example: {
      url: 'https://rasp.example.ru/group/ivt-21-1',
      row_selector: 'table.schedule tr',
      cell_selector: 'td',
      columns: ['date', 'start', 'end', 'subject', 'room', 'teacher'],
      group: 'ИВТ-21-1',
    },
  },
  { value: 'ics', label: 'Календарь .ics', example: { url: 'https://rasp.example.ru/ivt-21-1.ics', group: 'ИВТ-21-1' } },
  { value: 'excel', label: 'Файл Excel по ссылке', example: { url: 'https://rasp.example.ru/schedule.xlsx' } },
  { value: 'csv', label: 'Файл CSV по ссылке', example: { url: 'https://rasp.example.ru/schedule.csv' } },
]

const sourceStatus: Record<string, { color: string; label: string }> = {
  ok: { color: 'success', label: 'обновлено' },
  unchanged: { color: 'default', label: 'без изменений' },
  partial: { color: 'warning', label: 'с ошибками' },
  error: { color: 'error', label: 'ошибка' },
}

interface SourceForm {
  name: string
  kind: SourceKind
  config: string
  interval_hours: number
  enabled: boolean
}

function Sources({ universityId }: { universityId: string }) {
  const { modal } = App.useApp()
  const [creating, setCreating] = useState(false)
  const [form] = Form.useForm<SourceForm>()
  const sources = useQuery({ queryKey: keys.sources(universityId), queryFn: () => api.scheduleSources(universityId) })
  const create = useAction(
    (values: SourceForm) =>
      api.createScheduleSource(universityId, {
        name: values.name,
        kind: values.kind,
        config: JSON.parse(values.config) as Record<string, unknown>,
        interval_hours: values.interval_hours,
        enabled: values.enabled,
      }),
    { success: 'Источник добавлен', invalidate: [['sources']] },
  )
  const remove = useAction((id: string) => api.deleteScheduleSource(id), {
    success: 'Источник удалён',
    invalidate: [['sources']],
  })
  const sync = useAction((id: string) => api.syncScheduleSource(id), { invalidate: [['sources'], ['imports']] })

  function syncNow(source: ScheduleSource) {
    sync.mutate(source.id, {
      onSuccess: (result) => {
        if (result.status === 'error') {
          modal.error({ title: `Не удалось обновить «${source.name}»`, content: result.error })
        } else if (result.status === 'unchanged') {
          modal.info({ title: 'Расписание не изменилось с прошлой синхронизации' })
        } else {
          modal.success({
            title: `«${source.name}» обновлён`,
            content: `Добавлено: ${result.added ?? 0}, изменено: ${result.changed ?? 0}, удалено: ${result.removed ?? 0}.`,
          })
        }
      },
    })
  }

  function pickKind(kind: SourceKind) {
    const example = sourceKinds.find((k) => k.value === kind)?.example ?? { url: '' }
    form.setFieldValue('config', JSON.stringify(example, null, 2))
  }

  return (
    <>
      <Flex justify="space-between" style={{ marginBottom: 16 }} gap={16} wrap>
        <Typography.Text type="secondary" style={{ maxWidth: 760 }}>
          Источник опрашивается по расписанию (раз в N часов); расписание меняется, только если ответ изменился.
          Серверы во внутренней сети вуза нужно разрешить в настройке DOOMICH_SCHEDULE_SOURCE_PRIVATE_HOSTS.
        </Typography.Text>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => setCreating(true)}
        >
          Добавить источник
        </Button>
      </Flex>
      <Table<ScheduleSource>
        rowKey="id"
        loading={sources.isLoading}
        dataSource={sources.data}
        pagination={false}
        locale={{ emptyText: 'Источников пока нет' }}
        columns={[
          { title: 'Название', dataIndex: 'name' },
          { title: 'Тип', dataIndex: 'kind', render: (k: SourceKind) => sourceKinds.find((s) => s.value === k)?.label ?? k },
          {
            title: 'Адрес',
            key: 'url',
            ellipsis: true,
            render: (_, s) => <Typography.Text type="secondary">{String(s.config.url ?? '')}</Typography.Text>,
          },
          { title: 'Каждые', dataIndex: 'interval_hours', render: (h: number) => `${h} ч`, width: 90 },
          { title: 'Включён', dataIndex: 'enabled', render: (v: boolean) => (v ? 'да' : 'нет'), width: 90 },
          { title: 'Последний запуск', dataIndex: 'last_run_at', render: formatDateTime, width: 150 },
          {
            title: 'Итог',
            key: 'status',
            width: 140,
            render: (_, s) => {
              if (!s.last_status) return '—'
              const info = sourceStatus[s.last_status] ?? { color: 'default', label: s.last_status }
              const tag = <Tag color={info.color}>{info.label}</Tag>
              return s.last_error ? <Tooltip title={s.last_error}>{tag}</Tooltip> : tag
            },
          },
          {
            title: '',
            key: 'actions',
            width: 110,
            render: (_, s) => (
              <Space>
                <Tooltip title="Обновить сейчас">
                  <Button
                    icon={<SyncOutlined />}
                    loading={sync.isPending && sync.variables === s.id}
                    onClick={() => syncNow(s)}
                  />
                </Tooltip>
                <Popconfirm title="Удалить источник?" okText="Удалить" okButtonProps={{ danger: true }} onConfirm={() => remove.mutateAsync(s.id)}>
                  <Button danger icon={<DeleteOutlined />} />
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />
      <Modal
        title="Новый источник расписания"
        open={creating}
        onCancel={() => setCreating(false)}
        onOk={() => form.submit()}
        okText="Добавить"
        confirmLoading={create.isPending}
        width={680}
        destroyOnHidden
      >
        <Form<SourceForm>
          form={form}
          layout="vertical"
          initialValues={{ kind: 'json', interval_hours: 24, enabled: true, config: JSON.stringify(sourceKinds[0].example, null, 2) }}
          onFinish={(values) => create.mutate(values, { onSuccess: () => setCreating(false) })}
        >
          <Form.Item name="name" label="Название" rules={[{ required: true, max: 255 }]}>
            <Input placeholder="Сайт расписания вуза" />
          </Form.Item>
          <Form.Item name="kind" label="Тип">
            <Select options={sourceKinds.map(({ value, label }) => ({ value, label }))} onChange={pickKind} />
          </Form.Item>
          <Form.Item
            name="config"
            label="Настройки (JSON)"
            extra="Пример уже подставлен: замените адрес и названия полей на те, что отдаёт сайт вуза."
            rules={[
              { required: true },
              {
                validator: async (_, value: string) => {
                  let parsed: unknown
                  try {
                    parsed = JSON.parse(value)
                  } catch {
                    throw new Error('Это не JSON')
                  }
                  if (typeof (parsed as { url?: unknown })?.url !== 'string') throw new Error('Нужен адрес в поле url')
                },
              },
            ]}
          >
            <Input.TextArea autoSize={{ minRows: 6, maxRows: 16 }} style={{ fontFamily: 'monospace' }} />
          </Form.Item>
          <Flex gap={24}>
            <Form.Item name="interval_hours" label="Опрашивать каждые, ч">
              <InputNumber min={1} max={720} />
            </Form.Item>
            <Form.Item name="enabled" label="Включён" valuePropName="checked">
              <Switch />
            </Form.Item>
          </Flex>
        </Form>
      </Modal>
    </>
  )
}

function History({ universityId }: { universityId: string }) {
  const imports = useQuery({ queryKey: keys.imports(universityId), queryFn: () => api.scheduleImports(universityId) })
  return (
    <Table<ScheduleImport>
      rowKey="id"
      loading={imports.isLoading}
      dataSource={imports.data}
      pagination={{ pageSize: 20, hideOnSinglePage: true }}
      locale={{ emptyText: 'Импортов ещё не было' }}
      expandable={{
        rowExpandable: (r) => r.errors.length > 0,
        expandedRowRender: (r) => <ImportErrors errors={r.errors} />,
      }}
      columns={[
        { title: 'Когда', dataIndex: 'created_at', render: formatDateTime, width: 150 },
        { title: 'Файл или источник', dataIndex: 'filename', render: (v: string | null) => v ?? '—' },
        { title: 'Статус', dataIndex: 'status', width: 120 },
        {
          title: 'Изменения',
          key: 'stats',
          render: (_, r) =>
            r.stats
              ? `+${r.stats.added ?? 0} / ~${r.stats.changed ?? 0} / −${r.stats.removed ?? 0}`
              : '—',
        },
        { title: 'Ошибок', key: 'errors', render: (_, r) => r.errors.length, width: 90 },
      ]}
    />
  )
}
