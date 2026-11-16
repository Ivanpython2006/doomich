import { ReloadOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Card, Col, Descriptions, Row, Skeleton, Statistic } from 'antd'

import { api } from '../api/endpoints'
import { errorText, keys } from '../api/hooks'
import { HealthTag, PageHeader } from '../components/common'
import { useSession } from '../session'

const serviceNames: Record<string, string> = {
  database: 'База данных',
  llm: 'Языковая модель (vLLM)',
  asr: 'Распознавание речи',
  tts: 'Синтез речи',
  nav: 'Навигация по кампусу',
}

const documentStatuses: Record<string, string> = {
  queued: 'в очереди',
  processing: 'обрабатываются',
  ready: 'готовы',
  error: 'с ошибкой',
}

export function DashboardPage() {
  const { isSuper, university } = useSession()
  const status = useQuery({ queryKey: keys.status, queryFn: api.status, refetchInterval: 30_000 })
  const data = status.data

  return (
    <>
      <PageHeader
        title="Обзор"
        extra={
          <Button icon={<ReloadOutlined />} onClick={() => status.refetch()} loading={status.isFetching}>
            Обновить
          </Button>
        }
      >
        {isSuper ? 'Состояние всей установки.' : `Состояние сервиса для «${university?.name ?? 'вуза'}».`} Данные
        обновляются каждые 30 секунд.
      </PageHeader>
      {status.error && <Alert type="error" showIcon title={errorText(status.error)} style={{ marginBottom: 16 }} />}
      {!data ? (
        <Skeleton active />
      ) : (
        <Row gutter={[16, 16]}>
          <Col xs={24} sm={12} lg={6}>
            <Card>
              <Statistic title="Пользователей" value={data.users} />
            </Card>
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <Card>
              <Statistic title="Документов готово" value={data.documents.ready ?? 0} />
            </Card>
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <Card>
              <Statistic title="Полезных ответов 👍" value={data.feedback['1'] ?? 0} />
            </Card>
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <Card>
              <Statistic title="Неудачных ответов 👎" value={data.feedback['-1'] ?? 0} />
            </Card>
          </Col>
          <Col xs={24} lg={12}>
            <Card title="Сервисы">
              <Descriptions column={1} size="small">
                {Object.entries(data.checks).map(([name, value]) => (
                  <Descriptions.Item key={name} label={serviceNames[name] ?? name}>
                    <HealthTag value={value} />
                  </Descriptions.Item>
                ))}
                <Descriptions.Item label="Модель эмбеддингов">{data.embedder}</Descriptions.Item>
              </Descriptions>
            </Card>
          </Col>
          <Col xs={24} lg={12}>
            <Card title="Документы студентов и базы знаний">
              <Descriptions column={1} size="small">
                {Object.keys(data.documents).length === 0 && <Descriptions.Item label="Документов">0</Descriptions.Item>}
                {Object.entries(data.documents).map(([name, count]) => (
                  <Descriptions.Item key={name} label={documentStatuses[name] ?? name}>
                    {count}
                  </Descriptions.Item>
                ))}
              </Descriptions>
            </Card>
          </Col>
        </Row>
      )}
    </>
  )
}
