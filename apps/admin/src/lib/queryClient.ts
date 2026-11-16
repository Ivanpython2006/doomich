import { QueryClient } from '@tanstack/react-query'

import { ApiError } from '../api/client'

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        refetchOnWindowFocus: false,
        // 4xx — ошибка запроса, повторять бессмысленно
        retry: (count, error) => !(error instanceof ApiError && error.status !== null && error.status < 500) && count < 2,
      },
    },
  })
}
