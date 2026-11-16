import { PlusOutlined } from '@ant-design/icons'
import { Button, Card, Form, Input, Modal, Select, Switch, Typography } from 'antd'
import { useEffect, useMemo, useState } from 'react'

import { api } from '../api/endpoints'
import { keys, useAction } from '../api/hooks'
import type { FeatureKey, University, UniversitySettings } from '../api/types'
import { NeedUniversity, PageHeader } from '../components/common'
import { useSession } from '../session'

const features: { key: FeatureKey; label: string; help: string; default: boolean }[] = [
  { key: 'lectures', label: 'Конспекты лекций', help: 'Загрузка записи пары и конспект по ней.', default: true },
  { key: 'navigation', label: 'Навигация по кампусу', help: 'Нужен граф кампуса (раздел «Кампусы»).', default: false },
  { key: 'courses', label: 'Курсы и задания', help: 'Раздел курсов в приложении (R3).', default: false },
  { key: 'wakeword', label: 'Слово активации «Думыч»', help: 'Нужна активная модель wakeword.', default: false },
]

function timezones(): string[] {
  try {
    return Intl.supportedValuesOf('timeZone')
  } catch {
    return ['Europe/Kaliningrad', 'Europe/Moscow', 'Europe/Samara', 'Asia/Yekaterinburg', 'Asia/Novosibirsk']
  }
}

interface SettingsForm {
  name: string
  timezone: string
  features: Record<FeatureKey, boolean>
  store_teacher_names: boolean
  llm_model: string
}

function toForm(u: University): SettingsForm {
  const s = u.settings ?? {}
  return {
    name: u.name,
    timezone: u.timezone,
    features: Object.fromEntries(features.map((f) => [f.key, s.features?.[f.key] ?? f.default])) as Record<
      FeatureKey,
      boolean
    >,
    store_teacher_names: Boolean(s.store_teacher_names),
    llm_model: typeof s.llm_model === 'string' ? s.llm_model : '',
  }
}

export function UniversityPage() {
  const { university, isSuper, selectUniversity } = useSession()
  const [form] = Form.useForm<SettingsForm>()
  const [creating, setCreating] = useState(false)
  const zoneOptions = useMemo(() => timezones().map((z) => ({ value: z, label: z })), [])

  useEffect(() => {
    if (university) form.setFieldsValue(toForm(university))
  }, [university, form])

  const save = useAction(
    (values: SettingsForm) => {
      const settings: UniversitySettings = {
        features: values.features,
        store_teacher_names: values.store_teacher_names,
        llm_model: values.llm_model.trim() || null,
      }
      return api.updateUniversity(university!.id, { name: values.name, timezone: values.timezone, settings })
    },
    { success: 'Настройки сохранены', invalidate: [keys.universities] },
  )
  const create = useAction((body: { slug: string; name: string; timezone: string }) => api.createUniversity(body), {
    success: (u) => `Вуз «${u.name}» создан`,
    invalidate: [keys.universities],
  })

  return (
    <>
      <PageHeader
        title="Вуз и функции"
        extra={
          isSuper && (
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>
              Новый вуз
            </Button>
          )
        }
      >
        Название, часовой пояс (по нему показывается расписание) и функции, доступные студентам вуза.
      </PageHeader>
      {!university ? (
        <NeedUniversity />
      ) : (
        <Card style={{ maxWidth: 760 }}>
          <Typography.Paragraph type="secondary">
            Код вуза в ссылках и реестре моделей: <Typography.Text code>{university.slug}</Typography.Text>
          </Typography.Paragraph>
          <Form<SettingsForm> form={form} layout="vertical" onFinish={(v) => save.mutate(v)}>
            <Form.Item name="name" label="Название" rules={[{ required: true, max: 255 }]}>
              <Input />
            </Form.Item>
            <Form.Item name="timezone" label="Часовой пояс" rules={[{ required: true }]}>
              <Select options={zoneOptions} showSearch={{ optionFilterProp: 'label' }} />
            </Form.Item>
            <Typography.Title level={5}>Функции приложения</Typography.Title>
            {features.map((f) => (
              <Form.Item key={f.key} name={['features', f.key]} label={f.label} extra={f.help} valuePropName="checked">
                <Switch />
              </Form.Item>
            ))}
            <Typography.Title level={5}>Данные и модели</Typography.Title>
            <Form.Item
              name="store_teacher_names"
              label="Хранить ФИО преподавателей в расписании"
              extra="Включайте, только если вуз разрешил: иначе ФИО при импорте отбрасываются."
              valuePropName="checked"
            >
              <Switch />
            </Form.Item>
            <Form.Item
              name="llm_model"
              label="Модель ответов (необязательно)"
              extra="Имя модели в vLLM, если вузу нужна не модель по умолчанию. Активный LoRA-адаптер вуза из раздела «Модели» важнее."
            >
              <Input placeholder="по умолчанию" />
            </Form.Item>
            <Button type="primary" htmlType="submit" loading={save.isPending}>
              Сохранить
            </Button>
          </Form>
        </Card>
      )}
      <CreateUniversityModal
        open={creating}
        busy={create.isPending}
        timezones={zoneOptions}
        onCancel={() => setCreating(false)}
        onCreate={(body) =>
          create.mutate(body, {
            onSuccess: (u) => {
              setCreating(false)
              selectUniversity(u.id)
            },
          })
        }
      />
    </>
  )
}

function CreateUniversityModal(props: {
  open: boolean
  busy: boolean
  timezones: { value: string; label: string }[]
  onCancel: () => void
  onCreate: (body: { slug: string; name: string; timezone: string }) => void
}) {
  const [form] = Form.useForm<{ slug: string; name: string; timezone: string }>()
  return (
    <Modal
      title="Новый вуз"
      open={props.open}
      onCancel={props.onCancel}
      onOk={() => form.submit()}
      okText="Создать"
      confirmLoading={props.busy}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" initialValues={{ timezone: 'Europe/Moscow' }} onFinish={props.onCreate}>
        <Form.Item name="name" label="Название" rules={[{ required: true, max: 255 }]}>
          <Input placeholder="Национальный исследовательский университет" />
        </Form.Item>
        <Form.Item
          name="slug"
          label="Код (латиницей)"
          extra="Используется в реестре моделей и не меняется: например, hse или mipt."
          rules={[{ required: true, pattern: /^[a-z0-9][a-z0-9-]{1,62}$/, message: 'Строчные латинские буквы, цифры и дефис' }]}
        >
          <Input />
        </Form.Item>
        <Form.Item name="timezone" label="Часовой пояс" rules={[{ required: true }]}>
          <Select options={props.timezones} showSearch={{ optionFilterProp: 'label' }} />
        </Form.Item>
      </Form>
    </Modal>
  )
}
