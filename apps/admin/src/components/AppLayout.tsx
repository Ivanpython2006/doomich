import {
  BankOutlined,
  BookOutlined,
  CalendarOutlined,
  DashboardOutlined,
  EnvironmentOutlined,
  ExperimentOutlined,
  FileSearchOutlined,
  LogoutOutlined,
  QrcodeOutlined,
  SafetyOutlined,
  TeamOutlined,
} from '@ant-design/icons'
import { useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Flex, Layout, Menu, Result, Select, Spin, Tag, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { Navigate, Outlet, useLocation, useNavigate } from 'react-router'

import { onUnauthorized, tokenStore } from '../api/client'
import { errorText } from '../api/hooks'
import { useSession } from '../session'
import { SessionProvider } from './SessionProvider'

const items = [
  { key: '/', icon: <DashboardOutlined />, label: 'Обзор' },
  { key: '/university', icon: <BankOutlined />, label: 'Вуз и функции' },
  { key: '/campuses', icon: <EnvironmentOutlined />, label: 'Кампусы' },
  { key: '/groups', icon: <TeamOutlined />, label: 'Группы' },
  { key: '/invites', icon: <QrcodeOutlined />, label: 'Приглашения' },
  { key: '/schedule', icon: <CalendarOutlined />, label: 'Расписание' },
  { key: '/kb', icon: <BookOutlined />, label: 'База знаний' },
  { key: '/models', icon: <ExperimentOutlined />, label: 'Модели' },
  { key: '/admins', icon: <SafetyOutlined />, label: 'Администраторы', superOnly: true },
  { key: '/audit', icon: <FileSearchOutlined />, label: 'Журнал' },
]

/** Защищённая часть панели: без токена — на страницу входа, при 401 — тоже. */
export function ProtectedLayout() {
  const navigate = useNavigate()
  const client = useQueryClient()

  useEffect(() => {
    onUnauthorized(() => {
      client.clear()
      navigate('/login', { replace: true, state: { expired: true } })
    })
    return () => onUnauthorized(null)
  }, [client, navigate])

  if (!tokenStore.get()) return <Navigate to="/login" replace />
  return (
    <SessionProvider
      fallback={({ error }) =>
        error ? (
          <Result status="error" title="Не удалось загрузить панель" subTitle={errorText(error)} />
        ) : (
          <Flex align="center" justify="center" style={{ minHeight: '100vh' }}>
            <Spin size="large" />
          </Flex>
        )
      }
    >
      <Shell />
    </SessionProvider>
  )
}

function Shell() {
  const { me, isSuper, universities, university, selectUniversity } = useSession()
  const location = useLocation()
  const navigate = useNavigate()
  const client = useQueryClient()
  const [collapsed, setCollapsed] = useState(false)
  const selected = items.find((i) => i.key !== '/' && location.pathname.startsWith(i.key))?.key ?? '/'

  function logout() {
    tokenStore.clear()
    client.clear()
    navigate('/login', { replace: true })
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Layout.Sider collapsible collapsed={collapsed} onCollapse={setCollapsed} breakpoint="lg" theme="light" width={232}>
        <div style={{ padding: '16px 20px', fontWeight: 700, fontSize: 18, whiteSpace: 'nowrap', overflow: 'hidden' }}>
          {collapsed ? 'Д' : 'Думыч · админ'}
        </div>
        <Menu
          mode="inline"
          selectedKeys={[selected]}
          items={items.filter((i) => !i.superOnly || isSuper).map(({ key, icon, label }) => ({ key, icon, label }))}
          onClick={({ key }) => navigate(key)}
        />
      </Layout.Sider>
      <Layout>
        <Layout.Header
          style={{
            background: '#fff',
            padding: '0 24px',
            display: 'flex',
            alignItems: 'center',
            gap: 16,
            borderBottom: '1px solid #eee',
          }}
        >
          <Typography.Text type="secondary">Вуз:</Typography.Text>
          {isSuper ? (
            <Select
              style={{ minWidth: 280 }}
              value={university?.id}
              placeholder="Вузов пока нет"
              onChange={selectUniversity}
              options={universities.map((u) => ({ value: u.id, label: `${u.name} (${u.slug})` }))}
              showSearch={{ optionFilterProp: 'label' }}
            />
          ) : (
            <Typography.Text strong>{university?.name ?? '—'}</Typography.Text>
          )}
          <div style={{ flex: 1 }} />
          <Typography.Text>{me.login}</Typography.Text>
          <Tag color={isSuper ? 'purple' : 'blue'}>{isSuper ? 'суперадминистратор' : 'администратор вуза'}</Tag>
          <Button icon={<LogoutOutlined />} onClick={logout}>
            Выйти
          </Button>
        </Layout.Header>
        <Layout.Content style={{ padding: 24 }}>
          {!isSuper && !university && (
            <Alert type="warning" showIcon title="Учётная запись не привязана к вузу" style={{ marginBottom: 16 }} />
          )}
          <Outlet />
        </Layout.Content>
      </Layout>
    </Layout>
  )
}
