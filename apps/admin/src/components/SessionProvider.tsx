import { useQuery } from '@tanstack/react-query'
import { useCallback, useMemo, useState, type ReactNode } from 'react'

import { api } from '../api/endpoints'
import { keys } from '../api/hooks'
import { SessionContext, UNIVERSITY_KEY, type Session } from '../session'

export function SessionProvider({
  children,
  fallback,
}: {
  children: ReactNode
  fallback: (state: { loading: boolean; error: unknown }) => ReactNode
}) {
  const me = useQuery({ queryKey: keys.me, queryFn: api.me })
  const universities = useQuery({ queryKey: keys.universities, queryFn: api.universities, enabled: me.isSuccess })
  const [selected, setSelected] = useState<string | null>(() => localStorage.getItem(UNIVERSITY_KEY))

  const selectUniversity = useCallback((id: string) => {
    localStorage.setItem(UNIVERSITY_KEY, id)
    setSelected(id)
  }, [])

  const value = useMemo<Session | null>(() => {
    if (!me.data || !universities.data) return null
    const list = universities.data
    const isSuper = me.data.role === 'superadmin'
    const wanted = isSuper ? selected : me.data.university_id
    const university = list.find((u) => u.id === wanted) ?? (isSuper ? (list[0] ?? null) : null)
    return { me: me.data, isSuper, universities: list, university, selectUniversity }
  }, [me.data, universities.data, selected, selectUniversity])

  if (!value) {
    return <>{fallback({ loading: me.isPending || universities.isPending, error: me.error ?? universities.error })}</>
  }
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}
