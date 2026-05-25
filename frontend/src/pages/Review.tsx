import { useState } from 'react'
import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query'
import type { RecordListResponse } from '../types'
import {
  CheckCircle, XCircle, Flag, Lock, AlertTriangle,
  ChevronLeft, ChevronRight, Eye, X
} from 'lucide-react'
import { api } from '../api'
import type { NormalizedRecord } from '../types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    PENDING: 'bg-gray-100 text-gray-600',
    APPROVED: 'bg-green-100 text-green-700',
    REJECTED: 'bg-red-100 text-red-700',
    FLAGGED: 'bg-amber-100 text-amber-700',
  }
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${map[status] ?? 'bg-gray-100 text-gray-500'}`}>
      {status}
    </span>
  )
}

function ScopeBadge({ scope }: { scope: number }) {
  const map: Record<number, string> = {
    1: 'bg-red-50 text-red-700 border-red-200',
    2: 'bg-amber-50 text-amber-700 border-amber-200',
    3: 'bg-brand-50 text-brand-700 border-brand-200',
  }
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded border font-mono ${map[scope]}`}>
      S{scope}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Record Detail Drawer
// ---------------------------------------------------------------------------

function RecordDrawer({ record, onClose, onReview }: {
  record: NormalizedRecord
  onClose: () => void
  onReview: (status: string, notes?: string) => void
}) {
  const { data: auditTrail = [] } = useQuery({
    queryKey: ['audit', record.id],
    queryFn: () => api.getAuditTrail(record.id),
  })
  const [notes, setNotes] = useState(record.review_notes)

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="flex-1 bg-black/30" onClick={onClose} />
      <div className="w-[520px] bg-white h-full overflow-y-auto shadow-xl flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 sticky top-0 bg-white z-10">
          <div>
            <h2 className="text-base font-semibold text-gray-900">{record.category_display}</h2>
            <p className="text-xs text-gray-400 mt-0.5">Record #{record.id} · {record.facility_name || record.facility_id}</p>
          </div>
          <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-700">
            <X size={18} />
          </button>
        </div>

        <div className="p-5 space-y-5 flex-1">
          {/* Flags */}
          {record.flags.length > 0 && (
            <div className="bg-amber-50 border border-amber-200 rounded-lg p-3">
              <p className="text-xs font-semibold text-amber-800 mb-1.5">Quality flags</p>
              <ul className="space-y-1">
                {record.flags.map((f, i) => (
                  <li key={i} className="flex items-start gap-1.5 text-xs text-amber-700">
                    <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                    {f}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Classification */}
          <section>
            <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Classification</h3>
            <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
              <Row label="Scope" value={<ScopeBadge scope={record.scope} />} />
              <Row label="Category" value={record.category_display} />
              <Row label="Facility" value={record.facility_name || record.facility_id || '—'} />
              <Row label="Period" value={`${record.period_start} → ${record.period_end}`} />
            </div>
          </section>

          {/* Activity */}
          <section>
            <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Activity</h3>
            <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
              <Row label="Raw quantity" value={`${record.activity_quantity_raw} ${record.activity_unit_raw}`} />
              <Row label="Normalised" value={`${Number(record.activity_quantity).toLocaleString()} ${record.activity_unit}`} />
              <Row label="Emission factor" value={`${record.emission_factor_value} ${record.emission_factor_unit}`} />
              <Row label="EF source" value={record.emission_factor_source} />
              <Row label="CO₂e" value={<span className="font-semibold">{Number(record.co2e_kg).toLocaleString()} kg</span>} />
            </div>
          </section>

          {/* Raw data */}
          <section>
            <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Raw source data</h3>
            <div className="bg-gray-50 rounded-lg p-3 text-xs font-mono overflow-x-auto">
              {Object.entries(record.raw_data).map(([k, v]) => (
                <div key={k} className="flex gap-2">
                  <span className="text-gray-400 shrink-0">{k}:</span>
                  <span className="text-gray-800">{v}</span>
                </div>
              ))}
            </div>
          </section>

          {/* Review */}
          {!record.is_locked && (
            <section>
              <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Review</h3>
              <textarea
                className="w-full text-sm border border-gray-200 rounded-lg p-2.5 resize-none focus:outline-none focus:ring-1 focus:ring-brand-500"
                rows={3}
                placeholder="Review notes (optional)"
                value={notes}
                onChange={e => setNotes(e.target.value)}
              />
              <div className="flex gap-2 mt-2">
                <button
                  onClick={() => onReview('APPROVED', notes)}
                  className="flex-1 flex items-center justify-center gap-1.5 py-2 bg-green-600 text-white text-sm rounded-lg hover:bg-green-700"
                >
                  <CheckCircle size={14} /> Approve
                </button>
                <button
                  onClick={() => onReview('FLAGGED', notes)}
                  className="flex-1 flex items-center justify-center gap-1.5 py-2 bg-amber-500 text-white text-sm rounded-lg hover:bg-amber-600"
                >
                  <Flag size={14} /> Flag
                </button>
                <button
                  onClick={() => onReview('REJECTED', notes)}
                  className="flex-1 flex items-center justify-center gap-1.5 py-2 bg-red-600 text-white text-sm rounded-lg hover:bg-red-700"
                >
                  <XCircle size={14} /> Reject
                </button>
              </div>
            </section>
          )}

          {record.is_locked && (
            <div className="flex items-center gap-2 text-xs text-gray-500 bg-gray-50 rounded-lg p-3">
              <Lock size={14} className="shrink-0" />
              Locked for audit by {record.locked_by} on {record.locked_at?.slice(0, 10)}
            </div>
          )}

          {/* Audit trail */}
          <section>
            <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Audit trail</h3>
            {auditTrail.length === 0 ? (
              <p className="text-xs text-gray-400">No events yet.</p>
            ) : (
              <ol className="relative border-l border-gray-200 space-y-3 ml-2">
                {auditTrail.map(ev => (
                  <li key={ev.id} className="pl-4">
                    <span className="absolute -left-1.5 top-1.5 h-3 w-3 rounded-full bg-brand-200 border-2 border-brand-500" />
                    <p className="text-xs font-medium text-gray-700">{ev.event_type_display}</p>
                    <p className="text-xs text-gray-400">{ev.actor} · {new Date(ev.timestamp).toLocaleString()}</p>
                    {ev.note && <p className="text-xs text-gray-500 mt-0.5 italic">"{ev.note}"</p>}
                  </li>
                ))}
              </ol>
            )}
          </section>
        </div>
      </div>
    </div>
  )
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <p className="text-xs text-gray-400">{label}</p>
      <p className="text-sm text-gray-800 mt-0.5">{value}</p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main Review page
// ---------------------------------------------------------------------------

export default function Review({ tenantId }: { tenantId: number }) {
  const qc = useQueryClient()
  const [page, setPage] = useState(1)
  const [filterStatus, setFilterStatus] = useState('')
  const [filterScope, setFilterScope] = useState('')
  const [filterSource, setFilterSource] = useState('')
  const [filterSuspicious, setFilterSuspicious] = useState(false)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [detailRecord, setDetailRecord] = useState<NormalizedRecord | null>(null)

  const { data, isLoading } = useQuery<RecordListResponse>({
    queryKey: ['records', tenantId, page, filterStatus, filterScope, filterSource, filterSuspicious],
    queryFn: () => api.getRecords({
      tenantId,
      page,
      reviewStatus: filterStatus || undefined,
      scope: filterScope || undefined,
      sourceType: filterSource || undefined,
      suspicious: filterSuspicious || undefined,
    }),
    placeholderData: keepPreviousData,
  })

  const reviewMutation = useMutation({
    mutationFn: ({ id, status, notes }: { id: number; status: string; notes?: string }) =>
      api.reviewRecord(id, { review_status: status, review_notes: notes, actor: 'analyst@breatheesg.com' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['records', tenantId] })
      qc.invalidateQueries({ queryKey: ['dashboard', tenantId] })
      setDetailRecord(null)
    },
  })

  const bulkMutation = useMutation({
    mutationFn: (status: string) =>
      api.bulkReview({
        record_ids: Array.from(selected),
        review_status: status,
        actor: 'analyst@breatheesg.com',
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['records', tenantId] })
      qc.invalidateQueries({ queryKey: ['dashboard', tenantId] })
      setSelected(new Set())
    },
  })

  const records = data?.results ?? []
  const totalPages = data ? Math.ceil(data.count / data.page_size) : 1

  const toggleSelect = (id: number) => {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const toggleAll = () => {
    if (selected.size === records.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(records.map(r => r.id)))
    }
  }

  return (
    <div className="p-6 flex flex-col h-full">
      <div className="mb-4 flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Review Queue</h1>
          <p className="text-gray-500 text-sm">{data?.count ?? '…'} records</p>
        </div>

        {/* Filters */}
        <div className="flex flex-wrap gap-2">
          <select
            className="text-sm border border-gray-200 rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-brand-500"
            value={filterStatus}
            onChange={e => { setFilterStatus(e.target.value); setPage(1) }}
          >
            <option value="">All statuses</option>
            <option value="PENDING">Pending</option>
            <option value="APPROVED">Approved</option>
            <option value="REJECTED">Rejected</option>
            <option value="FLAGGED">Flagged</option>
          </select>

          <select
            className="text-sm border border-gray-200 rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-brand-500"
            value={filterScope}
            onChange={e => { setFilterScope(e.target.value); setPage(1) }}
          >
            <option value="">All scopes</option>
            <option value="1">Scope 1</option>
            <option value="2">Scope 2</option>
            <option value="3">Scope 3</option>
          </select>

          <select
            className="text-sm border border-gray-200 rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-brand-500"
            value={filterSource}
            onChange={e => { setFilterSource(e.target.value); setPage(1) }}
          >
            <option value="">All sources</option>
            <option value="SAP_FUEL">SAP Fuel</option>
            <option value="UTILITY_ELEC">Electricity</option>
            <option value="TRAVEL">Travel</option>
          </select>

          <label className="flex items-center gap-1.5 text-sm text-gray-700 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={filterSuspicious}
              onChange={e => { setFilterSuspicious(e.target.checked); setPage(1) }}
              className="accent-brand-600"
            />
            <AlertTriangle size={14} className="text-amber-500" />
            Suspicious only
          </label>
        </div>
      </div>

      {/* Bulk action bar */}
      {selected.size > 0 && (
        <div className="mb-3 flex items-center gap-3 bg-brand-50 border border-brand-200 rounded-lg px-4 py-2.5">
          <span className="text-sm font-medium text-brand-800">{selected.size} selected</span>
          <button
            onClick={() => bulkMutation.mutate('APPROVED')}
            disabled={bulkMutation.isPending}
            className="flex items-center gap-1 text-sm px-3 py-1 bg-green-600 text-white rounded-lg hover:bg-green-700"
          >
            <CheckCircle size={13} /> Approve all
          </button>
          <button
            onClick={() => bulkMutation.mutate('REJECTED')}
            disabled={bulkMutation.isPending}
            className="flex items-center gap-1 text-sm px-3 py-1 bg-red-600 text-white rounded-lg hover:bg-red-700"
          >
            <XCircle size={13} /> Reject all
          </button>
          <button
            onClick={() => setSelected(new Set())}
            className="text-sm text-gray-500 hover:text-gray-700 ml-auto"
          >
            Clear
          </button>
        </div>
      )}

      {/* Table */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden flex-1">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50 text-xs text-gray-500 uppercase tracking-wide">
                <th className="px-4 py-3 w-8">
                  <input
                    type="checkbox"
                    checked={selected.size === records.length && records.length > 0}
                    onChange={toggleAll}
                    className="accent-brand-600"
                  />
                </th>
                <th className="px-4 py-3 text-left">Scope</th>
                <th className="px-4 py-3 text-left">Category</th>
                <th className="px-4 py-3 text-left">Facility / Description</th>
                <th className="px-4 py-3 text-left">Period</th>
                <th className="px-4 py-3 text-right">Activity</th>
                <th className="px-4 py-3 text-right">CO₂e (kg)</th>
                <th className="px-4 py-3 text-center">Status</th>
                <th className="px-4 py-3 text-center">Flags</th>
                <th className="px-4 py-3 w-10" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {isLoading ? (
                <tr>
                  <td colSpan={10} className="text-center py-12 text-gray-400">Loading…</td>
                </tr>
              ) : records.length === 0 ? (
                <tr>
                  <td colSpan={10} className="text-center py-12 text-gray-400">No records match filters.</td>
                </tr>
              ) : (
                records.map(r => (
                  <tr
                    key={r.id}
                    className={`hover:bg-gray-50 transition-colors ${
                      r.is_suspicious ? 'bg-amber-50/40' : ''
                    } ${selected.has(r.id) ? 'bg-brand-50/50' : ''}`}
                  >
                    <td className="px-4 py-3">
                      <input
                        type="checkbox"
                        checked={selected.has(r.id)}
                        onChange={() => toggleSelect(r.id)}
                        disabled={r.is_locked}
                        className="accent-brand-600"
                      />
                    </td>
                    <td className="px-4 py-3">
                      <ScopeBadge scope={r.scope} />
                    </td>
                    <td className="px-4 py-3 text-gray-700 max-w-[140px]">
                      <span className="truncate block">{r.category_display}</span>
                    </td>
                    <td className="px-4 py-3 text-gray-600 max-w-[180px]">
                      <span className="truncate block">{r.facility_name || r.description || r.facility_id || '—'}</span>
                    </td>
                    <td className="px-4 py-3 text-gray-500 whitespace-nowrap">
                      {r.period_start}
                      {r.period_end !== r.period_start && <><br /><span className="text-gray-400">→ {r.period_end}</span></>}
                    </td>
                    <td className="px-4 py-3 text-right text-gray-700 font-mono text-xs whitespace-nowrap">
                      {Number(r.activity_quantity).toLocaleString()} {r.activity_unit}
                    </td>
                    <td className="px-4 py-3 text-right font-mono font-medium text-gray-900">
                      {Number(r.co2e_kg).toLocaleString(undefined, { maximumFractionDigits: 1 })}
                    </td>
                    <td className="px-4 py-3 text-center">
                      <StatusBadge status={r.review_status} />
                      {r.is_locked && <Lock size={11} className="inline ml-1 text-gray-400" />}
                    </td>
                    <td className="px-4 py-3 text-center">
                      {r.flags.length > 0 && (
                        <span title={r.flags.join('\n')}>
                          <AlertTriangle size={14} className="text-amber-400 mx-auto" />
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => setDetailRecord(r)}
                        className="p-1 text-gray-400 hover:text-brand-600"
                        title="View detail"
                      >
                        <Eye size={15} />
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-3">
          <p className="text-xs text-gray-400">
            Page {page} of {totalPages} · {data?.count} records
          </p>
          <div className="flex gap-1">
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page === 1}
              className="p-1.5 rounded border border-gray-200 text-gray-500 hover:bg-gray-50 disabled:opacity-40"
            >
              <ChevronLeft size={14} />
            </button>
            <button
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="p-1.5 rounded border border-gray-200 text-gray-500 hover:bg-gray-50 disabled:opacity-40"
            >
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      )}

      {/* Detail drawer */}
      {detailRecord && (
        <RecordDrawer
          record={detailRecord}
          onClose={() => setDetailRecord(null)}
          onReview={(status, notes) =>
            reviewMutation.mutate({ id: detailRecord.id, status, notes })
          }
        />
      )}
    </div>
  )
}
