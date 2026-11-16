import { LockOutlined, SafetyOutlined, UserOutlined } from '@ant-design/icons'
import { useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Card, Flex, Form, Input, Typography } from 'antd'
import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router'

import { tokenStore } from '../api/client'
import { api } from '../api/endpoints'
import { errorText } from '../api/hooks'

interface LoginForm {
  login: string
  password: string
  totp: string
}

export function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const client = useQueryClient()
  const [error, setError] = useState<string | null>(
    (location.state as { expired?: boolean } | null)?.expired ? 'Сессия истекла — войдите снова.' : null,
  )
  const [busy, setBusy] = useState(false)

  async function submit(values: LoginForm) {
    setBusy(true)
    setError(null)
    try {
      const result = await api.login(values.login.trim(), values.password, values.totp.replace(/\s/g, ''))
      tokenStore.set(result.access_token)
      client.clear()
      navigate('/', { replace: true })
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Flex align="center" justify="center" style={{ minHeight: '100vh', padding: 16, background: '#f3f2f8' }}>
      <Card style={{ width: 400, maxWidth: '100%' }}>
        <Typography.Title level={3} style={{ marginTop: 0 }}>
          Думыч · администрирование
        </Typography.Title>
        <Typography.Paragraph type="secondary">
          Вход только для администраторов: пароль и одноразовый код из приложения-аутентификатора.
        </Typography.Paragraph>
        {error && <Alert type="error" title={error} showIcon style={{ marginBottom: 16 }} />}
        <Form<LoginForm> layout="vertical" onFinish={submit} requiredMark={false} disabled={busy}>
          <Form.Item name="login" label="Логин" rules={[{ required: true, message: 'Введите логин' }]}>
            <Input prefix={<UserOutlined />} autoComplete="username" autoFocus />
          </Form.Item>
          <Form.Item name="password" label="Пароль" rules={[{ required: true, message: 'Введите пароль' }]}>
            <Input.Password prefix={<LockOutlined />} autoComplete="current-password" />
          </Form.Item>
          <Form.Item
            name="totp"
            label="Код 2FA"
            rules={[{ required: true, pattern: /^\s*\d{3}\s*\d{3}\s*$/, message: '6 цифр из приложения' }]}
          >
            <Input prefix={<SafetyOutlined />} inputMode="numeric" autoComplete="one-time-code" maxLength={7} />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={busy}>
            Войти
          </Button>
        </Form>
      </Card>
    </Flex>
  )
}
