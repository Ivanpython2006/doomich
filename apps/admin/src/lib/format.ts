import dayjs from 'dayjs'
import 'dayjs/locale/ru'

dayjs.locale('ru')

export function formatDateTime(iso: string | null | undefined): string {
  return iso ? dayjs(iso).format('DD.MM.YYYY HH:mm') : '—'
}

export function formatDate(iso: string | null | undefined): string {
  return iso ? dayjs(iso).format('DD.MM.YYYY') : '—'
}

export function formatBytes(size: number): string {
  if (size < 1024) return `${size} Б`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} КБ`
  return `${(size / 1024 / 1024).toFixed(1)} МБ`
}
