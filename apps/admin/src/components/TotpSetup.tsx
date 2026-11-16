import { Alert, Flex, Modal, Typography } from 'antd'
import { useEffect, useState } from 'react'

import { qrDataUrl } from '../lib/qr'
import { totpSecret } from '../lib/totp'

/** Окно настройки 2FA: QR для приложения-аутентификатора. Показывается один раз. */
export function TotpSetupModal({ login, uri, onClose }: { login: string; uri: string | null; onClose: () => void }) {
  const [rendered, setRendered] = useState<{ uri: string; url: string } | null>(null)
  const qr = rendered && rendered.uri === uri ? rendered.url : null

  useEffect(() => {
    let cancelled = false
    if (uri) {
      qrDataUrl(uri).then((url) => {
        if (!cancelled) setRendered({ uri, url })
      })
    }
    return () => {
      cancelled = true
    }
  }, [uri])

  return (
    <Modal
      title={`Двухфакторный вход для ${login}`}
      open={Boolean(uri)}
      onOk={onClose}
      onCancel={onClose}
      okText="Готово"
      cancelButtonProps={{ style: { display: 'none' } }}
      mask={{ closable: false }}
    >
      <Alert
        type="warning"
        showIcon
        title="QR показывается только сейчас"
        description="Передайте его администратору лично: он отсканирует QR в приложении-аутентификаторе (Яндекс Ключ, Google Authenticator, Aegis и др.)."
        style={{ marginBottom: 16 }}
      />
      <Flex vertical align="center" gap={12}>
        {qr && <img src={qr} alt="QR-код для приложения-аутентификатора" style={{ width: 220, height: 220 }} />}
        {uri && (
          <Typography.Text copyable={{ text: totpSecret(uri) ?? uri }} type="secondary">
            Ключ для ручного ввода: {totpSecret(uri)}
          </Typography.Text>
        )}
      </Flex>
    </Modal>
  )
}
