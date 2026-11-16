/** Типы ответов админ-API (services/api/src/doomich_api/api/admin.py). */

export type AdminRole = 'superadmin' | 'university_admin'

export interface AdminMe {
  id: string
  login: string
  role: AdminRole
  university_id: string | null
}

export interface LoginResult {
  access_token: string
  role: AdminRole
  university_id: string | null
}

export type FeatureKey = 'lectures' | 'navigation' | 'courses' | 'wakeword'

export interface UniversitySettings {
  features?: Partial<Record<FeatureKey, boolean>>
  store_teacher_names?: boolean
  llm_model?: string | null
  [key: string]: unknown
}

export interface University {
  id: string
  slug: string
  name: string
  timezone: string
  settings: UniversitySettings
}

export interface Campus {
  id: string
  slug: string
  name: string
  address: string | null
  nodes: number
}

export interface Group {
  id: string
  code: string
  name: string | null
  faculty: string | null
}

export type InviteRole = 'student' | 'teacher'

export interface InviteBatch {
  id: string
  role: InviteRole
  group_id: string | null
  group_code: string | null
  count: number
  activations: number
  max_uses_per_code: number
  note: string | null
  expires_at: string | null
  revoked: boolean
  created_at: string
}

export interface InviteBatchIn {
  count: number
  role: InviteRole
  group_id?: string | null
  max_uses_per_code: number
  expires_days: number | null
  note?: string | null
}

export interface InviteCode {
  code: string
  link: string
  app_link: string
}

export interface CreatedBatch {
  batch_id: string
  codes: InviteCode[]
}

export interface ImportErrorRow {
  row: number | null
  error: string
}

export interface ImportStats {
  groups: number
  added: number
  removed: number
  changed: number
  unchanged: number
  errors: number
}

export interface ImportSummary {
  preview: boolean
  events: number
  groups: string[]
  errors: ImportErrorRow[]
  stats?: ImportStats
}

export type SourceKind = 'json' | 'html' | 'ics' | 'excel' | 'csv'

export interface ScheduleSource {
  id: string
  name: string
  kind: SourceKind
  config: Record<string, unknown> & { url?: string }
  enabled: boolean
  interval_hours: number
  last_run_at: string | null
  last_status: string | null
  last_error: string | null
}

export interface ScheduleSourceIn {
  name: string
  kind: SourceKind
  config: Record<string, unknown>
  enabled: boolean
  interval_hours: number
}

export type SyncResult = Partial<ImportStats> & { status?: string; error?: string }

export interface ScheduleImport {
  id: string
  filename: string | null
  status: string
  stats: Partial<ImportStats> | null
  errors: ImportErrorRow[]
  created_at: string
}

export interface KbDocument {
  id: string
  title: string
  owner_type: string
  mime: string
  size_bytes: number
  pages: number | null
  status: 'queued' | 'processing' | 'ready' | 'error' | string
  error: string | null
  created_at: string
}

export type ModelKind = 'wakeword' | 'vpr' | 'llm_lora' | 'asr' | 'embeddings'

export interface ModelVersion {
  tenant: string
  kind: ModelKind
  scope: string
  version: string
  created_at: string
  base_model: string | null
  metrics: Record<string, number | string>
  active: boolean
}

export interface SystemStatus {
  checks: Record<string, string>
  documents: Record<string, number>
  users: number
  feedback: Record<string, number>
  embedder: string
}

export interface AdminAccount {
  id: string
  login: string
  role: AdminRole
  university_id: string | null
  disabled: boolean
  created_at: string
}

export interface AuditEntry {
  id: number
  admin_id: string | null
  admin_login: string | null
  action: string
  target: string | null
  details: Record<string, unknown> | null
  created_at: string
}

export type NodeKind = 'corridor' | 'room' | 'stairs' | 'elevator' | 'entrance' | 'poi'

export interface GraphNode {
  key: string
  kind: NodeKind
  name?: string | null
  room?: string | null
  x: number
  y: number
  tags?: string[]
}

export interface GraphFloor {
  level: number
  name?: string | null
  meters_per_px?: number | null
  nodes: GraphNode[]
}

export interface GraphBuilding {
  slug: string
  name: string
  floors: GraphFloor[]
}

export interface GraphEdge {
  a: string
  b: string
  length_m?: number | null
  kind?: 'walk' | 'stairs' | 'elevator'
  accessible?: boolean
}

export interface CampusGraph {
  buildings: GraphBuilding[]
  edges: GraphEdge[]
}
