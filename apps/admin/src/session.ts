import { createContext, useContext } from 'react'

import type { AdminMe, University } from './api/types'

export const UNIVERSITY_KEY = 'doomich-admin-university'

export interface Session {
  me: AdminMe
  isSuper: boolean
  universities: University[]
  /** Вуз, с которым сейчас работает администратор (у администратора вуза — всегда свой). */
  university: University | null
  selectUniversity: (id: string) => void
}

export const SessionContext = createContext<Session | null>(null)

export function useSession(): Session {
  const session = useContext(SessionContext)
  if (!session) throw new Error('useSession вне SessionProvider')
  return session
}

/** Текущий вуз; страницы вуза без выбранного вуза показывают подсказку. */
export function useUniversity(): University | null {
  return useSession().university
}
