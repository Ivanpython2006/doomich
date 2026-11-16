import { DownloadOutlined, PlusOutlined, UploadOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { App, Button, Form, Input, Modal, Table, Typography, Upload } from 'antd'
import { useState } from 'react'

import { saveFile } from '../api/client'
import { api } from '../api/endpoints'
import { errorText, keys, useAction } from '../api/hooks'
import type { Campus, CampusGraph } from '../api/types'
import { NeedUniversity, PageHeader } from '../components/common'
import { validateGraph } from '../lib/graph'
import { useUniversity } from '../session'

export function CampusesPage() {
  const university = useUniversity()
  const { message, modal } = App.useApp()
  const [creating, setCreating] = useState(false)
  const [form] = Form.useForm<{ slug: string; name: string; address?: string }>()
  const campuses = useQuery({
    queryKey: keys.campuses(university?.id ?? ''),
    queryFn: () => api.campuses(university!.id),
    enabled: Boolean(university),
  })
  const create = useAction(
    (body: { slug: string; name: string; address?: string }) => api.createCampus(university!.id, body),
    { success: 'Кампус добавлен', invalidate: [['campuses']] },
  )
  const upload = useAction(({ id, graph }: { id: string; graph: CampusGraph }) => api.putCampusGraph(id, graph), {
    success: (r) => `Граф загружен: ${r.nodes} узлов, ${r.edges} рёбер`,
    invalidate: [['campuses']],
  })

  if (!university) return <NeedUniversity />

  async function download(campus: Campus) {
    try {
      const graph = await api.campusGraph(campus.id)
      saveFile(JSON.stringify(graph, null, 2), `campus-${campus.slug}-graph.json`, 'application/json')
    } catch (e) {
      message.error(errorText(e))
    }
  }

  async function pickGraph(campus: Campus, file: File) {
    let data: unknown
    try {
      data = JSON.parse(await file.text())
    } catch {
      message.error('Файл не похож на JSON')
      return
    }
    const checked = validateGraph(data)
    if ('error' in checked) {
      message.error(checked.error)
      return
    }
    const { stats } = checked
    modal.confirm({
      title: `Заменить граф кампуса «${campus.name}»?`,
      content: `Корпусов: ${stats.buildings}, этажей: ${stats.floors}, узлов: ${stats.nodes} (аудиторий: ${stats.rooms}), рёбер: ${stats.edges}. Текущий граф будет заменён целиком.`,
      okText: 'Заменить',
      onOk: () => upload.mutateAsync({ id: campus.id, graph: checked.graph }),
    })
  }

  return (
    <>
      <PageHeader
        title="Кампусы"
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>
            Добавить кампус
          </Button>
        }
      >
        Граф кампуса — корпуса, этажи, узлы (коридоры, аудитории, лестницы) и переходы между ними — нужен для навигации.
        Скачайте текущий граф в JSON, поправьте и загрузите обратно; формат описан в docs/dev/campus-graph.md.
      </PageHeader>
      <Table<Campus>
        rowKey="id"
        loading={campuses.isLoading}
        dataSource={campuses.data}
        pagination={false}
        locale={{ emptyText: 'Кампусов пока нет' }}
        columns={[
          { title: 'Название', dataIndex: 'name' },
          { title: 'Код', dataIndex: 'slug', render: (v: string) => <Typography.Text code>{v}</Typography.Text> },
          { title: 'Адрес', dataIndex: 'address', render: (v: string | null) => v ?? '—' },
          { title: 'Узлов графа', dataIndex: 'nodes', width: 130 },
          {
            title: '',
            key: 'actions',
            width: 330,
            render: (_, campus) => (
              <>
                <Button icon={<DownloadOutlined />} onClick={() => download(campus)} style={{ marginRight: 8 }}>
                  Скачать граф
                </Button>
                <Upload
                  accept=".json,application/json"
                  showUploadList={false}
                  beforeUpload={(file) => {
                    void pickGraph(campus, file)
                    return false
                  }}
                >
                  <Button icon={<UploadOutlined />} loading={upload.isPending && upload.variables?.id === campus.id}>
                    Загрузить граф
                  </Button>
                </Upload>
              </>
            ),
          },
        ]}
      />
      <Modal
        title="Новый кампус"
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
          <Form.Item name="name" label="Название" rules={[{ required: true, max: 255 }]}>
            <Input placeholder="Главный кампус" />
          </Form.Item>
          <Form.Item
            name="slug"
            label="Код (латиницей)"
            extra="Используется в реестре моделей навигации: например, main."
            rules={[{ required: true, pattern: /^[a-z0-9][a-z0-9-]{1,62}$/, message: 'Строчные латинские буквы, цифры и дефис' }]}
          >
            <Input />
          </Form.Item>
          <Form.Item name="address" label="Адрес" rules={[{ max: 500 }]}>
            <Input />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}
