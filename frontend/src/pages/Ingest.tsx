import { useState, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Upload, FileText, CheckCircle2, XCircle, AlertCircle, ChevronDown, ChevronRight } from 'lucide-react'
import { api } from '../api'
import type { DataIngestion } from '../types'

const SOURCE_TYPES = [
  {
    value: 'SAP_FUEL',
    label: 'SAP Fuel & Procurement',
    description: 'MM60-style goods-movement flat file (tab-delimited, German or English headers)',
    accept: '.txt,.csv,.tsv',
    example: 'sap_fuel_mm60.txt',
  },
  {
    value: 'UTILITY_ELEC',
    label: 'Utility Electricity',
    description: 'Portal CSV export — one row per billing period per meter',
    accept: '.csv',
    example: 'utility_portal.csv',
  },
  {
    value: 'TRAVEL',
    label: 'Corporate Travel',
    description: 'Concur / Navan expense report export — flights, hotels, ground transport',
    accept: '.csv',
    example: 'travel_concur.csv',
  },
]

function LogItem({ entry }: { entry: { level: string; row: number | null; message: string } }) {
  const icon =
    entry.level === 'error' ? <XCircle size={14} className="text-red-500 mt-0.5 shrink-0" /> :
    entry.level === 'warning' ? <AlertCircle size={14} className="text-amber-500 mt-0.5 shrink-0" /> :
    <CheckCircle2 size={14} className="text-green-500 mt-0.5 shrink-0" />
  return (
    <li className="flex items-start gap-2 text-xs py-1">
      {icon}
      <span className="text-gray-600">
        {entry.row != null && <span className="font-mono text-gray-400 mr-1">row {entry.row}:</span>}
        {entry.message}
      </span>
    </li>
  )
}

function IngestionCard({ ing }: { ing: DataIngestion }) {
  const [open, setOpen] = useState(false)
  const errors = ing.processing_log.filter(l => l.level === 'error')
  const warnings = ing.processing_log.filter(l => l.level === 'warning')

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <div
        className="flex items-center justify-between px-4 py-3 bg-white cursor-pointer hover:bg-gray-50"
        onClick={() => setOpen(o => !o)}
      >
        <div className="flex items-center gap-3">
          <FileText size={16} className="text-gray-400" />
          <div>
            <p className="text-sm font-medium text-gray-800">{ing.original_filename || ing.source_type_display}</p>
            <p className="text-xs text-gray-400">{new Date(ing.ingested_at).toLocaleString()}</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="text-xs text-right">
            <span className="text-gray-600">{ing.row_count} rows</span>
            {ing.error_count > 0 && <span className="text-red-500 ml-2">{ing.error_count} errors</span>}
            {ing.warning_count > 0 && <span className="text-amber-500 ml-2">{ing.warning_count} warnings</span>}
          </div>
          <span
            className={`text-xs px-2 py-0.5 rounded-full font-medium ${
              ing.status === 'COMPLETE' ? 'bg-green-100 text-green-700' :
              ing.status === 'FAILED' ? 'bg-red-100 text-red-700' :
              'bg-amber-100 text-amber-700'
            }`}
          >
            {ing.status}
          </span>
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </div>
      </div>

      {open && ing.processing_log.length > 0 && (
        <div className="px-4 py-3 bg-gray-50 border-t border-gray-100">
          <ul className="space-y-0.5 max-h-48 overflow-y-auto">
            {ing.processing_log.map((e, i) => <LogItem key={i} entry={e} />)}
          </ul>
        </div>
      )}
    </div>
  )
}

export default function Ingest({ tenantId }: { tenantId: number }) {
  const qc = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const [sourceType, setSourceType] = useState('SAP_FUEL')
  const [dragging, setDragging] = useState(false)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)

  const { data: ingestions = [] } = useQuery({
    queryKey: ['ingestions', tenantId],
    queryFn: () => api.getIngestions(tenantId),
    refetchInterval: 5000,
  })

  const upload = useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData()
      fd.append('tenant_id', String(tenantId))
      fd.append('source_type', sourceType)
      fd.append('ingested_by', 'analyst@breatheesg.com')
      fd.append('file', file)
      return api.uploadFile(fd)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['ingestions', tenantId] })
      qc.invalidateQueries({ queryKey: ['dashboard', tenantId] })
      qc.invalidateQueries({ queryKey: ['records', tenantId] })
      setSelectedFile(null)
    },
  })

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files[0]
    if (file) setSelectedFile(file)
  }

  const selectedSource = SOURCE_TYPES.find(s => s.value === sourceType)!

  return (
    <div className="p-8 max-w-3xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Ingest Data</h1>
        <p className="text-gray-500 text-sm mt-1">Upload a source file to parse and normalise into the review queue</p>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 p-6 mb-6">
        {/* Source type selector */}
        <div className="mb-5">
          <label className="block text-sm font-medium text-gray-700 mb-2">Data source</label>
          <div className="grid grid-cols-1 gap-2">
            {SOURCE_TYPES.map(s => (
              <label
                key={s.value}
                className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                  sourceType === s.value
                    ? 'border-brand-500 bg-brand-50'
                    : 'border-gray-200 hover:border-gray-300'
                }`}
              >
                <input
                  type="radio"
                  name="source_type"
                  value={s.value}
                  checked={sourceType === s.value}
                  onChange={() => setSourceType(s.value)}
                  className="mt-0.5 accent-brand-600"
                />
                <div>
                  <p className="text-sm font-medium text-gray-800">{s.label}</p>
                  <p className="text-xs text-gray-500 mt-0.5">{s.description}</p>
                </div>
              </label>
            ))}
          </div>
        </div>

        {/* Drop zone */}
        <div
          className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors ${
            dragging ? 'border-brand-500 bg-brand-50' : 'border-gray-200 hover:border-gray-300'
          }`}
          onDragOver={e => { e.preventDefault(); setDragging(true) }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
          onClick={() => fileRef.current?.click()}
        >
          <Upload size={28} className="mx-auto text-gray-300 mb-2" />
          {selectedFile ? (
            <p className="text-sm font-medium text-brand-700">{selectedFile.name}</p>
          ) : (
            <>
              <p className="text-sm text-gray-600">Drop file here or click to browse</p>
              <p className="text-xs text-gray-400 mt-1">Accepts {selectedSource.accept}</p>
            </>
          )}
          <input
            ref={fileRef}
            type="file"
            accept={selectedSource.accept}
            className="hidden"
            onChange={e => e.target.files?.[0] && setSelectedFile(e.target.files[0])}
          />
        </div>

        <button
          className="mt-4 w-full py-2.5 bg-brand-600 text-white rounded-lg font-medium text-sm hover:bg-brand-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          disabled={!selectedFile || upload.isPending}
          onClick={() => selectedFile && upload.mutate(selectedFile)}
        >
          {upload.isPending ? 'Processing…' : 'Upload & Ingest'}
        </button>

        {upload.isError && (
          <p className="mt-2 text-xs text-red-600">{String(upload.error)}</p>
        )}
        {upload.isSuccess && (
          <p className="mt-2 text-xs text-green-600">
            Ingestion complete — {upload.data.row_count} rows, {upload.data.error_count} errors
          </p>
        )}
      </div>

      {/* History */}
      <div>
        <h2 className="text-sm font-semibold text-gray-700 mb-3">Ingestion History</h2>
        {ingestions.length === 0 ? (
          <p className="text-sm text-gray-400">No ingestions yet.</p>
        ) : (
          <div className="space-y-2">
            {ingestions.map(ing => <IngestionCard key={ing.id} ing={ing} />)}
          </div>
        )}
      </div>
    </div>
  )
}
