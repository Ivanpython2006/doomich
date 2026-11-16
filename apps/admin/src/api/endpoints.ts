import { request, requestBlob } from './client'
import type {
  AdminAccount,
  AdminMe,
  AdminRole,
  AuditEntry,
  Campus,
  CampusGraph,
  CreatedBatch,
  Group,
  ImportSummary,
  InviteBatch,
  InviteBatchIn,
  KbDocument,
  LoginResult,
  ModelKind,
  ModelVersion,
  ScheduleImport,
  ScheduleSource,
  ScheduleSourceIn,
  SyncResult,
  SystemStatus,
  University,
  UniversitySettings,
} from './types'

const uni = (id: string) => `/universities/${encodeURIComponent(id)}`

export const api = {
  login: (login: string, password: string, totp: string) =>
    request<LoginResult>('/auth/login', { method: 'POST', json: { login, password, totp } }),
  me: () => request<AdminMe>('/me'),

  // вузы
  universities: () => request<University[]>('/universities'),
  createUniversity: (body: { slug: string; name: string; timezone: string }) =>
    request<University>('/universities', { method: 'POST', json: body }),
  updateUniversity: (id: string, body: { name?: string; timezone?: string; settings?: UniversitySettings }) =>
    request<University>(uni(id), { method: 'PATCH', json: body }),

  // кампусы и граф
  campuses: (universityId: string) => request<Campus[]>(`${uni(universityId)}/campuses`),
  createCampus: (universityId: string, body: { slug: string; name: string; address?: string | null }) =>
    request<Campus>(`${uni(universityId)}/campuses`, { method: 'POST', json: body }),
  campusGraph: (campusId: string) => request<CampusGraph>(`/campuses/${encodeURIComponent(campusId)}/graph`),
  putCampusGraph: (campusId: string, graph: CampusGraph) =>
    request<{ nodes: number; edges: number }>(`/campuses/${encodeURIComponent(campusId)}/graph`, {
      method: 'PUT',
      json: graph,
    }),

  // группы
  groups: (universityId: string, q = '') => request<Group[]>(`${uni(universityId)}/groups`, { query: { q } }),
  createGroup: (universityId: string, body: { code: string; name?: string | null; faculty?: string | null }) =>
    request<Group>(`${uni(universityId)}/groups`, { method: 'POST', json: body }),

  // приглашения
  inviteBatches: (universityId: string) => request<InviteBatch[]>(`${uni(universityId)}/invite-batches`),
  createInvites: (universityId: string, body: InviteBatchIn) =>
    request<CreatedBatch>(`${uni(universityId)}/invite-batches`, { method: 'POST', json: body }),
  revokeInvites: (batchId: string) =>
    request<{ ok: boolean }>(`/invite-batches/${encodeURIComponent(batchId)}/revoke`, { method: 'POST' }),

  // расписание
  scheduleTemplate: () => requestBlob('/schedule/template'),
  importSchedule: (
    universityId: string,
    file: File,
    options: { preview: boolean; semesterStart?: string | null; group?: string | null },
  ) => {
    const form = new FormData()
    form.append('file', file)
    form.append('preview', String(options.preview))
    if (options.semesterStart) form.append('semester_start', options.semesterStart)
    if (options.group) form.append('group', options.group)
    return request<ImportSummary>(`${uni(universityId)}/schedule/import`, { method: 'POST', form })
  },
  scheduleSources: (universityId: string) => request<ScheduleSource[]>(`${uni(universityId)}/schedule/sources`),
  createScheduleSource: (universityId: string, body: ScheduleSourceIn) =>
    request<ScheduleSource>(`${uni(universityId)}/schedule/sources`, { method: 'POST', json: body }),
  deleteScheduleSource: (sourceId: string) =>
    request<{ ok: boolean }>(`/schedule/sources/${encodeURIComponent(sourceId)}`, { method: 'DELETE' }),
  syncScheduleSource: (sourceId: string) =>
    request<SyncResult>(`/schedule/sources/${encodeURIComponent(sourceId)}/sync`, { method: 'POST' }),
  scheduleImports: (universityId: string) => request<ScheduleImport[]>(`${uni(universityId)}/schedule/imports`),

  // база знаний
  knowledgeBase: (universityId: string) => request<KbDocument[]>(`${uni(universityId)}/kb`),
  uploadKnowledge: (universityId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<KbDocument>(`${uni(universityId)}/kb`, { method: 'POST', form })
  },
  deleteKnowledge: (documentId: string) =>
    request<{ ok: boolean }>(`/kb/${encodeURIComponent(documentId)}`, { method: 'DELETE' }),

  // модели
  models: () => request<ModelVersion[]>('/models'),
  activateModel: (body: { tenant: string; kind: ModelKind; scope: string; version: string }) =>
    request<unknown>('/models/activate', { method: 'POST', json: body }),

  // система
  status: () => request<SystemStatus>('/status'),
  audit: (limit: number) => request<AuditEntry[]>('/audit', { query: { limit } }),

  // администраторы
  admins: () => request<AdminAccount[]>('/admins'),
  createAdmin: (body: { login: string; password: string; role: AdminRole; university_id?: string | null }) =>
    request<{ id: string; totp_uri: string }>('/admins', { method: 'POST', json: body }),
  setAdminDisabled: (adminId: string, disabled: boolean) =>
    request<AdminAccount>(`/admins/${encodeURIComponent(adminId)}`, { method: 'PATCH', json: { disabled } }),
  resetAdminTotp: (adminId: string) =>
    request<{ id: string; totp_uri: string }>(`/admins/${encodeURIComponent(adminId)}/reset-totp`, {
      method: 'POST',
    }),
}
