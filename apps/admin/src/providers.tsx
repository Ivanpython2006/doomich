import { type QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App as AntApp, ConfigProvider } from 'antd'
import ruRU from 'antd/locale/ru_RU'
import type { ReactNode } from 'react'

export function Providers({ client, children }: { client: QueryClient; children: ReactNode }) {
  return (
    <ConfigProvider locale={ruRU} theme={{ token: { colorPrimary: '#4f5b93', borderRadius: 8 } }}>
      <AntApp>
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      </AntApp>
    </ConfigProvider>
  )
}
