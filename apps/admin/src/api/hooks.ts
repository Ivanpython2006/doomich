import { useMutation, useQueryClient, type QueryKey } from '@tanstack/react-query'
import { App } from 'antd'

import { ApiError } from './client'

/** Ключи кэша запросов: инвалидация после изменений. */
export const keys = {
  me: ['me'] as const,
  universities: ['universities'] as const,
  campuses: (u: string) => ['campuses', u] as const,
  groups: (u: string, q = '') => ['groups', u, q] as const,
  invites: (u: string) => ['invites', u] as const,
  sources: (u: string) => ['sources', u] as const,
  imports: (u: string) => ['imports', u] as const,
  kb: (u: string) => ['kb', u] as const,
  models: ['models'] as const,
  status: ['status'] as const,
  audit: (limit: number) => ['audit', limit] as const,
  admins: ['admins'] as const,
}

export function errorText(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return String(error)
}

interface ActionOptions<TResult> {
  /** Сообщение об успехе (или функция от результата). */
  success?: string | ((result: TResult) => string)
  /** Какие запросы обновить после успеха (по префиксу ключа). */
  invalidate?: QueryKey[]
}

/** Мутация с сообщением об успехе или ошибке и обновлением связанных данных. */
export function useAction<TArgs, TResult>(fn: (args: TArgs) => Promise<TResult>, options: ActionOptions<TResult> = {}) {
  const { message } = App.useApp()
  const client = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: async (result) => {
      for (const key of options.invalidate ?? []) await client.invalidateQueries({ queryKey: key })
      const text = typeof options.success === 'function' ? options.success(result) : options.success
      if (text) message.success(text)
    },
    onError: (error) => {
      message.error(errorText(error))
    },
  })
}
