import { DownloadOutlined, PlusOutlined, PrinterOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Checkbox,
  Flex,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Radio,
  Select,
  Table,
  Tag,
  Typography,
} from 'antd'
import dayjs from 'dayjs'
import { useState } from 'react'

import { saveFile } from '../api/client'
import { api } from '../api/endpoints'
import { keys, useAction } from '../api/hooks'
import type { CreatedBatch, InviteBatch, InviteBatchIn, InviteRole } from '../api/types'
import { NeedUniversity, PageHeader } from '../components/common'
import { formatDate, formatDateTime } from '../lib/format'
import { InviteSheet } from '../components/InviteSheet'
import { invitesCsv } from '../lib/invites'
import { useUniversity } from '../session'

interface CreateForm {
  role: InviteRole
  group_id?: string
  count: number
  max_uses_per_code: number
  expires_days: number
  no_expiry: boolean
  note?: string
}

interface Issued {
  batch: CreatedBatch
  request: InviteBatchIn
  groupCode: string | null
}

function batchState(b: InviteBatch) {
  if (b.revoked) return <Tag color="error">отозвана</Tag>
  if (b.expires_at && dayjs(b.expires_at).isBefore(dayjs())) return <Tag>истекла</Tag>
  return <Tag color="success">действует</Tag>
}

export function InvitesPage() {
  const university = useUniversity()
  const [creating, setCreating] = useState(false)
  const [issued, setIssued] = useState<Issued | null>(null)
  const [printing, setPrinting] = useState(false)
  const [groupQuery, setGroupQuery] = useState('')
  const [form] = Form.useForm<CreateForm>()
  const role = Form.useWatch('role', form)
  const noExpiry = Form.useWatch('no_expiry', form)

  const batches = useQuery({
    queryKey: keys.invites(university?.id ?? ''),
    queryFn: () => api.inviteBatches(university!.id),
    enabled: Boolean(university),
  })
  const groups = useQuery({
    queryKey: keys.groups(university?.id ?? '', groupQuery),
    queryFn: () => api.groups(university!.id, groupQuery),
    enabled: Boolean(university) && creating,
  })
  const create = useAction((body: InviteBatchIn) => api.createInvites(university!.id, body), {
    invalidate: [['invites']],
  })
  const revoke = useAction((id: string) => api.revokeInvites(id), {
    success: 'Пачка отозвана: неиспользованные коды больше не работают',
    invalidate: [['invites']],
  })

  if (!university) return <NeedUniversity />

  function submit(values: CreateForm) {
    const request: InviteBatchIn = {
      role: values.role,
      group_id: values.role === 'student' ? (values.group_id ?? null) : null,
      count: values.count,
      max_uses_per_code: values.max_uses_per_code,
      expires_days: values.no_expiry ? null : values.expires_days,
      note: values.note?.trim() || null,
    }
    const groupCode = groups.data?.find((g) => g.id === request.group_id)?.code ?? null
    create.mutate(request, {
      onSuccess: (batch) => {
        setCreating(false)
        setIssued({ batch, request, groupCode })
      },
    })
  }

  const expiresAt =
    issued && issued.request.expires_days ? dayjs().add(issued.request.expires_days, 'day').toISOString() : null

  return (
    <>
      <PageHeader
        title="Приглашения"
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>
            Выпустить коды
          </Button>
        }
      >
        Регистрация в «Думыче» — только по коду приглашения. Коды показываются один раз сразу после выпуска (в базе
        хранятся только их хэши), поэтому распечатайте листы с QR или скачайте CSV сразу.
      </PageHeader>
      <Table<InviteBatch>
        rowKey="id"
        loading={batches.isLoading}
        dataSource={batches.data}
        pagination={{ pageSize: 20, hideOnSinglePage: true }}
        locale={{ emptyText: 'Кодов пока не выпускали' }}
        columns={[
          { title: 'Выпущены', dataIndex: 'created_at', render: formatDateTime, width: 150 },
          {
            title: 'Для кого',
            key: 'who',
            render: (_, b) => (b.role === 'teacher' ? 'Преподаватели' : b.group_code ? `Группа ${b.group_code}` : 'Студенты'),
          },
          { title: 'Кодов', dataIndex: 'count', width: 80 },
          {
            title: 'Активаций',
            key: 'activations',
            width: 120,
            render: (_, b) => `${b.activations} из ${b.count * b.max_uses_per_code}`,
          },
          { title: 'Действуют до', dataIndex: 'expires_at', render: (v: string | null) => (v ? formatDate(v) : 'бессрочно') },
          { title: 'Заметка', dataIndex: 'note', render: (v: string | null) => v ?? '—' },
          { title: 'Состояние', key: 'state', render: (_, b) => batchState(b), width: 120 },
          {
            title: '',
            key: 'actions',
            width: 120,
            render: (_, b) =>
              !b.revoked && (
                <Popconfirm
                  title="Отозвать пачку?"
                  description="Неиспользованные коды перестанут работать. Уже зарегистрированных это не затронет."
                  okText="Отозвать"
                  okButtonProps={{ danger: true }}
                  onConfirm={() => revoke.mutateAsync(b.id)}
                >
                  <Button danger size="small">
                    Отозвать
                  </Button>
                </Popconfirm>
              ),
          },
        ]}
      />

      <Modal
        title="Выпустить коды приглашения"
        open={creating}
        onCancel={() => setCreating(false)}
        onOk={() => form.submit()}
        okText="Выпустить"
        confirmLoading={create.isPending}
        destroyOnHidden
      >
        <Form<CreateForm>
          form={form}
          layout="vertical"
          initialValues={{ role: 'student', count: 30, max_uses_per_code: 1, expires_days: 60, no_expiry: false }}
          onFinish={submit}
        >
          <Form.Item name="role" label="Кому">
            <Radio.Group
              options={[
                { value: 'student', label: 'Студентам' },
                { value: 'teacher', label: 'Преподавателям' },
              ]}
              optionType="button"
            />
          </Form.Item>
          {role !== 'teacher' && (
            <Form.Item
              name="group_id"
              label="Группа"
              extra="Студент сразу попадёт в группу и увидит её расписание. Без группы — выберет сам в приложении."
            >
              <Select
                allowClear
                placeholder="Начните вводить код группы"
                showSearch={{ filterOption: false, onSearch: setGroupQuery }}
                loading={groups.isFetching}
                options={groups.data?.map((g) => ({ value: g.id, label: g.code }))}
              />
            </Form.Item>
          )}
          <Flex gap={16} wrap>
            <Form.Item name="count" label="Сколько кодов" rules={[{ required: true }]}>
              <InputNumber min={1} max={2000} />
            </Form.Item>
            <Form.Item
              name="max_uses_per_code"
              label="Активаций на код"
              tooltip="1 — личный код для каждого. Больше — общий код, например на слайде для всей потоковой аудитории."
              rules={[{ required: true }]}
            >
              <InputNumber min={1} max={1000} />
            </Form.Item>
          </Flex>
          <Flex gap={16} align="center">
            <Form.Item name="expires_days" label="Срок действия, дней" rules={[{ required: !noExpiry }]}>
              <InputNumber min={1} max={400} disabled={noExpiry} />
            </Form.Item>
            <Form.Item name="no_expiry" valuePropName="checked" label=" " colon={false}>
              <Checkbox>Бессрочно</Checkbox>
            </Form.Item>
          </Flex>
          <Form.Item name="note" label="Заметка для себя" rules={[{ max: 255 }]}>
            <Input placeholder="Первокурсники, сентябрь" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="Коды выпущены"
        open={Boolean(issued) && !printing}
        closable={false}
        mask={{ closable: false }}
        width={720}
        footer={
          <Button type="primary" onClick={() => setIssued(null)}>
            Я сохранил коды
          </Button>
        }
      >
        {issued && (
          <>
            <Alert
              type="warning"
              showIcon
              title="Коды показываются только сейчас"
              description="В базе хранятся лишь хэши кодов: после закрытия окна их не восстановить, только выпустить новые."
              style={{ marginBottom: 16 }}
            />
            <Flex gap={8} style={{ marginBottom: 16 }} wrap>
              <Button type="primary" icon={<PrinterOutlined />} onClick={() => setPrinting(true)}>
                Листы с QR для печати
              </Button>
              <Button
                icon={<DownloadOutlined />}
                onClick={() =>
                  saveFile(invitesCsv(issued.batch.codes), `invites-${university.slug}-${dayjs().format('YYYY-MM-DD')}.csv`, 'text/csv;charset=utf-8')
                }
              >
                Скачать CSV
              </Button>
            </Flex>
            <Table
              size="small"
              rowKey="code"
              dataSource={issued.batch.codes}
              pagination={{ pageSize: 10, hideOnSinglePage: true }}
              columns={[
                {
                  title: 'Код',
                  dataIndex: 'code',
                  render: (v: string) => (
                    <Typography.Text copyable code>
                      {v}
                    </Typography.Text>
                  ),
                },
                { title: 'Ссылка', dataIndex: 'link', ellipsis: true },
              ]}
            />
          </>
        )}
      </Modal>
      {issued && printing && (
        <InviteSheet
          codes={issued.batch.codes}
          universityName={university.name}
          role={issued.request.role}
          groupCode={issued.groupCode}
          expiresAt={expiresAt}
          maxUses={issued.request.max_uses_per_code}
          onClose={() => setPrinting(false)}
        />
      )}
    </>
  )
}
