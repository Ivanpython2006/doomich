import { DeleteOutlined, InboxOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { Button, Popconfirm, Table, Tooltip, Upload } from 'antd'

import { api } from '../api/endpoints'
import { keys, useAction } from '../api/hooks'
import type { KbDocument } from '../api/types'
import { DocumentStatus, NeedUniversity, PageHeader } from '../components/common'
import { formatBytes, formatDateTime } from '../lib/format'
import { useUniversity } from '../session'

const inProgress = (docs: KbDocument[] | undefined) =>
  docs?.some((d) => d.status === 'queued' || d.status === 'processing') ?? false

export function KnowledgePage() {
  const university = useUniversity()
  const docs = useQuery({
    queryKey: keys.kb(university?.id ?? ''),
    queryFn: () => api.knowledgeBase(university!.id),
    enabled: Boolean(university),
    // пока документы обрабатываются — обновляем список
    refetchInterval: (query) => (inProgress(query.state.data) ? 3000 : false),
  })
  const upload = useAction((file: File) => api.uploadKnowledge(university!.id, file), {
    success: (d) => `«${d.title}» загружен`,
    invalidate: [['kb']],
  })
  const remove = useAction((id: string) => api.deleteKnowledge(id), { success: 'Документ удалён', invalidate: [['kb']] })

  if (!university) return <NeedUniversity />

  return (
    <>
      <PageHeader title="База знаний вуза">
        Положения, приказы, FAQ, правила стипендий и общежитий. Думыч ищет ответы на вопросы о вузе в этих документах и
        ссылается на них. Документы видят все студенты вуза — не загружайте персональные данные.
      </PageHeader>
      <Upload.Dragger
        accept=".pdf,.docx,.xlsx,.pptx,.txt,.md,.html"
        height={170}
        multiple
        showUploadList={false}
        beforeUpload={(file) => {
          upload.mutate(file)
          return false
        }}
        style={{ marginBottom: 16 }}
      >
        <p className="ant-upload-drag-icon">
          <InboxOutlined />
        </p>
        <p className="ant-upload-text">Перетащите документы или нажмите, чтобы выбрать</p>
        <p className="ant-upload-hint">PDF, DOCX, XLSX, PPTX, TXT, Markdown — до 50 МБ каждый</p>
      </Upload.Dragger>
      <Table<KbDocument>
        rowKey="id"
        loading={docs.isLoading || upload.isPending}
        dataSource={docs.data}
        pagination={{ pageSize: 20, hideOnSinglePage: true }}
        locale={{ emptyText: 'Документов пока нет' }}
        columns={[
          { title: 'Документ', dataIndex: 'title' },
          { title: 'Размер', dataIndex: 'size_bytes', render: formatBytes, width: 110 },
          { title: 'Страниц', dataIndex: 'pages', render: (v: number | null) => v ?? '—', width: 100 },
          {
            title: 'Статус',
            key: 'status',
            width: 130,
            render: (_, d) =>
              d.error ? (
                <Tooltip title={d.error}>
                  <span>
                    <DocumentStatus status={d.status} />
                  </span>
                </Tooltip>
              ) : (
                <DocumentStatus status={d.status} />
              ),
          },
          { title: 'Загружен', dataIndex: 'created_at', render: formatDateTime, width: 150 },
          {
            title: '',
            key: 'actions',
            width: 60,
            render: (_, d) => (
              <Popconfirm
                title="Удалить документ из базы знаний?"
                okText="Удалить"
                okButtonProps={{ danger: true }}
                onConfirm={() => remove.mutateAsync(d.id)}
              >
                <Button danger icon={<DeleteOutlined />} aria-label={`Удалить ${d.title}`} />
              </Popconfirm>
            ),
          },
        ]}
      />
    </>
  )
}
