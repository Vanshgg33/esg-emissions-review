export interface Tenant {
  id: number
  name: string
  slug: string
  created_at: string
}

export interface DataIngestion {
  id: number
  tenant: number
  tenant_name: string
  source_type: string
  source_type_display: string
  status: string
  status_display: string
  ingested_at: string
  ingested_by: string
  original_filename: string
  row_count: number
  error_count: number
  warning_count: number
  processing_log: Array<{ level: string; row: number | null; message: string }>
}

export interface NormalizedRecord {
  id: number
  tenant: number
  tenant_name: string
  scope: number
  scope_display: string
  category: string
  category_display: string
  facility_id: string
  facility_name: string
  description: string
  period_start: string
  period_end: string
  activity_quantity_raw: string
  activity_unit_raw: string
  activity_quantity: string
  activity_unit: string
  emission_factor_value: string
  emission_factor_unit: string
  emission_factor_source: string
  co2e_kg: string
  review_status: 'PENDING' | 'APPROVED' | 'REJECTED' | 'FLAGGED'
  review_status_display: string
  reviewed_by: string
  reviewed_at: string | null
  review_notes: string
  is_locked: boolean
  locked_at: string | null
  locked_by: string
  flags: string[]
  is_suspicious: boolean
  created_at: string
  updated_at: string
  source_type: string
  ingestion_id: number
  raw_data: Record<string, string>
  parse_warnings: string[]
}

export interface AuditEvent {
  id: number
  event_type: string
  event_type_display: string
  actor: string
  timestamp: string
  before_state: Record<string, unknown> | null
  after_state: Record<string, unknown> | null
  note: string
}

export interface DashboardStats {
  total_records: number
  pending_review: number
  approved: number
  flagged: number
  suspicious: number
  total_co2e_kg: number
  total_co2e_tonnes: number
  by_scope: {
    scope_1: { co2e_kg: number; count: number }
    scope_2: { co2e_kg: number; count: number }
    scope_3: { co2e_kg: number; count: number }
  }
  recent_ingestions: DataIngestion[]
}

export interface RecordListResponse {
  count: number
  page: number
  page_size: number
  results: NormalizedRecord[]
}
