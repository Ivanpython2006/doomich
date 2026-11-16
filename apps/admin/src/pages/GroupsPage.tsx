import { PlusOutlined } from '@ant-design/icons'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Button, Form, Input, Modal, Table } from 'antd'
import { useState } from 'react'

import { api } from '../api/endpoints'
import { keys, useAction } from '../api/hooks'
import type { Group } from '../api/types'
import { NeedUniversity, PageHeader } from '../components/common'
import { useUniversity } from '../session'

export function GroupsPage() {
  const university = useUniversity()
  const [query, setQuery] = useState('')
  const [creating, setCreating] = useState(false)
  const [form] = Form.useForm<{ code: string; name?: string; faculty?: string }>()
  const groups = useQuery({
    queryKey: keys.groups(university?.id ?? '', query),
    queryFn: () => api.groups(university!.id, query),
    enabled: Boolean(university),
    placeholderData: keepPreviousData,
  })
  const create = useAction(
    (body: { code: string; name?: string; faculty?: string }) => api.createGroup(university!.id, body),
    { success: (g) => `Группа ${g.code} добавлена`, invalidate: [['groups']] },
  )

  if (!university) return <NeedUniversity />

  return (
    <>
      <PageHeader
        title="Группы"
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>
            Добавить группу
          </Button>
        }
      >
        Группы создаются и при импорте расписания. Коды групп сравниваются без учёта регистра, пробелов и вида тире: «ИВТ–21–1» и «ивт-21-1» — одна группа.
      </PageHeader>
      <Input.Search
        placeholder="Поиск по коду группы"
        allowClear
        onSearch={setQuery}
        style={{ maxWidth: 360, marginBottom: 16 }}
      />
      <Table<Group>
        rowKey="id"
        loading={groups.isFetching}
        dataSource={groups.data}
        pagination={{ pageSize: 50, hideOnSinglePage: true }}
        locale={{ emptyText: query ? 'Ничего не найдено' : 'Групп пока нет' }}
        columns={[
          { title: 'Код', dataIndex: 'code', width: 200 },
          { title: 'Название', dataIndex: 'name', render: (v: string | null) => v ?? '—' },
          { title: 'Факультет', dataIndex: 'faculty', render: (v: string | null) => v ?? '—' },
        ]}
      />
      <Modal
        title="Новая группа"
        open={creating}
        onCancel={() => setCreating(false)}
        onOk={() => form.submit()}
        okText="Добавить"
        confirmLoading={create.isPending}
        destroyOnHidden
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={(values) => create.mutate(values, { onSuccess: () => setCreating(false) })}
        >
          <Form.Item name="code" label="Код группы" rules={[{ required: true, max: 64 }]}>
            <Input placeholder="ИВТ-21-1" />
          </Form.Item>
          <Form.Item name="name" label="Направление">
            <Input placeholder="Информатика и вычислительная техника" />
          </Form.Item>
          <Form.Item name="faculty" label="Факультет">
            <Input />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}
