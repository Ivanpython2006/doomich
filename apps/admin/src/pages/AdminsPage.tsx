import { PlusOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { Button, Form, Input, Modal, Popconfirm, Radio, Result, Select, Space, Table, Tag } from 'antd'
import { useState } from 'react'

import { api } from '../api/endpoints'
import { keys, useAction } from '../api/hooks'
import type { AdminAccount, AdminRole } from '../api/types'
import { PageHeader } from '../components/common'
import { formatDateTime } from '../lib/format'
import { TotpSetupModal } from '../components/TotpSetup'
import { useSession } from '../session'

interface CreateForm {
  login: string
  password: string
  role: AdminRole
  university_id?: string
}

export function AdminsPage() {
  const { me, isSuper, universities, university } = useSession()
  const [creating, setCreating] = useState(false)
  const [totp, setTotp] = useState<{ login: string; uri: string } | null>(null)
  const [form] = Form.useForm<CreateForm>()
  const role = Form.useWatch('role', form)
  const admins = useQuery({ queryKey: keys.admins, queryFn: api.admins, enabled: isSuper })
  const create = useAction((body: CreateForm) => api.createAdmin(body), {
    success: 'Администратор добавлен',
    invalidate: [keys.admins],
  })
  const toggle = useAction((a: AdminAccount) => api.setAdminDisabled(a.id, !a.disabled), {
    success: (a) => (a.disabled ? `${a.login} отключён — вход закрыт сразу` : `${a.login} снова может входить`),
    invalidate: [keys.admins],
  })
  const resetTotp = useAction((a: AdminAccount) => api.resetAdminTotp(a.id), { invalidate: [keys.admins] })

  if (!isSuper) return <Result status="403" title="Раздел доступен только суперадминистратору" />
  const uniName = (id: string | null) => universities.find((u) => u.id === id)?.name ?? '—'

  return (
    <>
      <PageHeader
        title="Администраторы"
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>
            Добавить администратора
          </Button>
        }
      >
        Администратор вуза видит и меняет только свой вуз. Вход — по паролю и коду из приложения-аутентификатора;
        отключение и сброс 2FA действуют сразу.
      </PageHeader>
      <Table<AdminAccount>
        rowKey="id"
        loading={admins.isLoading}
        dataSource={admins.data}
        pagination={false}
        columns={[
          { title: 'Логин', dataIndex: 'login' },
          {
            title: 'Роль',
            dataIndex: 'role',
            render: (r: AdminRole) =>
              r === 'superadmin' ? <Tag color="purple">суперадминистратор</Tag> : <Tag color="blue">администратор вуза</Tag>,
          },
          { title: 'Вуз', dataIndex: 'university_id', render: uniName },
          {
            title: 'Состояние',
            dataIndex: 'disabled',
            render: (d: boolean) => (d ? <Tag color="error">отключён</Tag> : <Tag color="success">активен</Tag>),
          },
          { title: 'Создан', dataIndex: 'created_at', render: formatDateTime, width: 150 },
          {
            title: '',
            key: 'actions',
            width: 260,
            render: (_, a) =>
              a.id !== me.id && (
                <Space>
                  <Popconfirm
                    title={a.disabled ? 'Включить вход?' : 'Отключить администратора?'}
                    okText={a.disabled ? 'Включить' : 'Отключить'}
                    okButtonProps={{ danger: !a.disabled }}
                    onConfirm={() => toggle.mutateAsync(a)}
                  >
                    <Button size="small" danger={!a.disabled}>
                      {a.disabled ? 'Включить' : 'Отключить'}
                    </Button>
                  </Popconfirm>
                  <Popconfirm
                    title="Сбросить 2FA?"
                    description="Старый код из приложения перестанет подходить."
                    okText="Сбросить"
                    onConfirm={() =>
                      resetTotp.mutateAsync(a).then((r) => setTotp({ login: a.login, uri: r.totp_uri }))
                    }
                  >
                    <Button size="small">Сбросить 2FA</Button>
                  </Popconfirm>
                </Space>
              ),
          },
        ]}
      />
      <Modal
        title="Новый администратор"
        open={creating}
        onCancel={() => setCreating(false)}
        onOk={() => form.submit()}
        okText="Добавить"
        confirmLoading={create.isPending}
        destroyOnHidden
      >
        <Form<CreateForm>
          form={form}
          layout="vertical"
          initialValues={{ role: 'university_admin', university_id: university?.id }}
          onFinish={(values) =>
            create.mutate(values, {
              onSuccess: (r) => {
                setCreating(false)
                setTotp({ login: values.login, uri: r.totp_uri })
              },
            })
          }
        >
          <Form.Item name="login" label="Логин" rules={[{ required: true, min: 3, max: 64 }]}>
            <Input autoComplete="off" />
          </Form.Item>
          <Form.Item
            name="password"
            label="Пароль"
            extra="Не короче 12 символов. Передайте его лично, не в мессенджере."
            rules={[{ required: true, min: 12, max: 256 }]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="role" label="Роль">
            <Radio.Group
              options={[
                { value: 'university_admin', label: 'Администратор вуза' },
                { value: 'superadmin', label: 'Суперадминистратор' },
              ]}
            />
          </Form.Item>
          {role !== 'superadmin' && (
            <Form.Item name="university_id" label="Вуз" rules={[{ required: true, message: 'Выберите вуз' }]}>
              <Select
                options={universities.map((u) => ({ value: u.id, label: u.name }))}
                showSearch={{ optionFilterProp: 'label' }}
              />
            </Form.Item>
          )}
        </Form>
      </Modal>
      <TotpSetupModal login={totp?.login ?? ''} uri={totp?.uri ?? null} onClose={() => setTotp(null)} />
    </>
  )
}
