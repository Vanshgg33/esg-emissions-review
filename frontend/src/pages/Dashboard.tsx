import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle, Clock, Leaf, TrendingUp, UploadCloud } from 'lucide-react'
import { api } from '../api'

function StatCard({
  label, value, sub, icon, color,
}: {
  label: string
  value: string | number
  sub?: string
  icon: React.ReactNode
  color: string
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5 flex items-start gap-4">
      <div className={`p-2.5 rounded-lg ${color}`}>{icon}</div>
      <div>
        <p className="text-sm text-gray-500">{label}</p>
        <p className="text-2xl font-bold text-gray-900 mt-0.5">{value}</p>
        {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
      </div>
    </div>
  )
}

function ScopeBar({ label, co2e, total, color }: { label: string; co2e: number; total: number; color: string }) {
  const pct = total > 0 ? (co2e / total) * 100 : 0
  const tonnes = (co2e / 1000).toFixed(2)
  return (
    <div>
      <div className="flex justify-between text-sm mb-1">
        <span className="font-medium text-gray-700">{label}</span>
        <span className="text-gray-500">{tonnes} tCO₂e ({pct.toFixed(1)}%)</span>
      </div>
      <div className="h-2.5 bg-gray-100 rounded-full">
        <div className={`h-2.5 rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

export default function Dashboard({ tenantId }: { tenantId: number }) {
  const { data: stats, isLoading } = useQuery({
    queryKey: ['dashboard', tenantId],
    queryFn: () => api.getDashboard(tenantId),
    refetchInterval: 10_000,
  })

  if (isLoading || !stats) {
    return <div className="p-8 text-gray-400">Loading…</div>
  }

  const totalCo2e = stats.total_co2e_kg
  const sourceLabels: Record<string, string> = {
    SAP_FUEL: 'SAP Fuel',
    UTILITY_ELEC: 'Electricity',
    TRAVEL: 'Travel',
  }

  return (
    <div className="p-8 max-w-6xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Overview</h1>
        <p className="text-gray-500 text-sm mt-1">All ingested data for this client period</p>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 xl:grid-cols-4 gap-4 mb-8">
        <StatCard
          label="Total CO₂e"
          value={`${stats.total_co2e_tonnes.toFixed(1)} t`}
          sub="across all scopes"
          icon={<Leaf size={20} className="text-brand-600" />}
          color="bg-brand-50"
        />
        <StatCard
          label="Pending Review"
          value={stats.pending_review}
          sub={`of ${stats.total_records} records`}
          icon={<Clock size={20} className="text-amber-600" />}
          color="bg-amber-50"
        />
        <StatCard
          label="Approved"
          value={stats.approved}
          sub="ready for audit"
          icon={<CheckCircle size={20} className="text-green-600" />}
          color="bg-green-50"
        />
        <StatCard
          label="Needs Attention"
          value={stats.suspicious + stats.flagged}
          sub={`${stats.suspicious} suspicious, ${stats.flagged} flagged`}
          icon={<AlertTriangle size={20} className="text-red-500" />}
          color="bg-red-50"
        />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6 mb-8">
        {/* Scope breakdown */}
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-base font-semibold text-gray-800 mb-4">Emissions by Scope</h2>
          <div className="space-y-4">
            <ScopeBar
              label="Scope 1 — Direct (fuel combustion)"
              co2e={stats.by_scope.scope_1.co2e_kg}
              total={totalCo2e}
              color="bg-red-400"
            />
            <ScopeBar
              label="Scope 2 — Purchased electricity"
              co2e={stats.by_scope.scope_2.co2e_kg}
              total={totalCo2e}
              color="bg-amber-400"
            />
            <ScopeBar
              label="Scope 3 — Value chain (travel)"
              co2e={stats.by_scope.scope_3.co2e_kg}
              total={totalCo2e}
              color="bg-brand-400"
            />
          </div>
          <div className="mt-5 pt-4 border-t border-gray-100 grid grid-cols-3 gap-3 text-center text-sm">
            {(['scope_1', 'scope_2', 'scope_3'] as const).map((k, i) => (
              <div key={k}>
                <p className="font-bold text-gray-800">
                  {(stats.by_scope[k].co2e_kg / 1000).toFixed(2)} t
                </p>
                <p className="text-xs text-gray-400">{stats.by_scope[k].count} records</p>
                <p className="text-xs text-gray-500">Scope {i + 1}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Recent ingestions */}
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-base font-semibold text-gray-800 mb-4">Recent Ingestions</h2>
          {stats.recent_ingestions.length === 0 ? (
            <div className="text-gray-400 text-sm flex flex-col items-center py-8 gap-2">
              <UploadCloud size={32} className="text-gray-300" />
              No ingestions yet — upload a file to start.
            </div>
          ) : (
            <div className="space-y-2">
              {stats.recent_ingestions.map(ing => (
                <div
                  key={ing.id}
                  className="flex items-center justify-between py-2.5 border-b border-gray-50 last:border-0"
                >
                  <div>
                    <p className="text-sm font-medium text-gray-800">{ing.source_type_display}</p>
                    <p className="text-xs text-gray-400">
                      {ing.original_filename} · {new Date(ing.ingested_at).toLocaleString()}
                    </p>
                  </div>
                  <div className="text-right">
                    <span
                      className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                        ing.status === 'COMPLETE'
                          ? 'bg-green-100 text-green-700'
                          : ing.status === 'FAILED'
                          ? 'bg-red-100 text-red-700'
                          : 'bg-amber-100 text-amber-700'
                      }`}
                    >
                      {ing.status}
                    </span>
                    <p className="text-xs text-gray-400 mt-0.5">
                      {ing.row_count} rows · {ing.error_count} errors
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
