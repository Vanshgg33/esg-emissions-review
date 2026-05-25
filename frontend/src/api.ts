// In dev, Vite proxies /api → localhost:8000. In prod, set VITE_API_URL to backend origin.
const BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api'

async function req<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  })
  if (!res.ok) {
    const body = await res.text()
    throw new Error(`${res.status} ${res.statusText}: ${body}`)
  }
  return res.json()
}

export const api = {
  getTenants: () => req<import('./types').Tenant[]>('/tenants/'),
  createTenant: (name: string, slug: string) =>
    req('/tenants/', { method: 'POST', body: JSON.stringify({ name, slug }) }),

  getDashboard: (tenantId: number) =>
    req<import('./types').DashboardStats>(`/dashboard/?tenant_id=${tenantId}`),

  getIngestions: (tenantId: number) =>
    req<import('./types').DataIngestion[]>(`/ingestions/?tenant_id=${tenantId}`),

  uploadFile: (formData: FormData) =>
    fetch(`${BASE}/ingestions/upload/`, { method: 'POST', body: formData }).then(async r => {
      if (!r.ok) throw new Error(await r.text())
      return r.json() as Promise<import('./types').DataIngestion>
    }),

  getRecords: (params: {
    tenantId: number
    page?: number
    reviewStatus?: string
    scope?: string
    sourceType?: string
    suspicious?: boolean
  }) => {
    const p = new URLSearchParams({ tenant_id: String(params.tenantId), page: String(params.page ?? 1) })
    if (params.reviewStatus) p.set('review_status', params.reviewStatus)
    if (params.scope) p.set('scope', params.scope)
    if (params.sourceType) p.set('source_type', params.sourceType)
    if (params.suspicious) p.set('suspicious', 'true')
    return req<import('./types').RecordListResponse>(`/records/?${p}`)
  },

  getRecord: (id: number) =>
    req<import('./types').NormalizedRecord>(`/records/${id}/`),

  reviewRecord: (id: number, payload: {
    review_status?: string
    review_notes?: string
    actor?: string
    lock?: boolean
  }) =>
    req<import('./types').NormalizedRecord>(`/records/${id}/review/`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),

  bulkReview: (payload: {
    record_ids: number[]
    review_status: string
    actor?: string
    review_notes?: string
  }) =>
    req<{ updated: number; skipped_locked: number }>('/records/bulk-review/', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  getAuditTrail: (recordId: number) =>
    req<import('./types').AuditEvent[]>(`/records/${recordId}/audit/`),
}
