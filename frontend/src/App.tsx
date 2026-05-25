import { BrowserRouter, Routes, Route, NavLink, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { LayoutDashboard, Upload, ClipboardCheck, Leaf } from 'lucide-react'
import { api } from './api'
import type { Tenant } from './types'
import Dashboard from './pages/Dashboard'
import Ingest from './pages/Ingest'
import Review from './pages/Review'

function Shell() {
  const { data: tenants = [] } = useQuery({ queryKey: ['tenants'], queryFn: api.getTenants })
  const [tenantId, setTenantId] = useState<number | null>(null)

  const activeTenant = tenants.find(t => t.id === tenantId) ?? tenants[0] ?? null
  const effectiveTenantId = activeTenant?.id ?? null

  const navClass = ({ isActive }: { isActive: boolean }) =>
    `flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
      isActive
        ? 'bg-brand-700 text-white'
        : 'text-brand-100 hover:bg-brand-700/60'
    }`

  return (
    <div className="flex h-screen">
      {/* Sidebar */}
      <aside className="w-56 bg-brand-800 flex flex-col">
        <div className="px-4 py-5 border-b border-brand-700">
          <div className="flex items-center gap-2">
            <Leaf className="text-brand-300" size={22} />
            <span className="font-bold text-white text-lg">Breathe ESG</span>
          </div>
          <p className="text-brand-300 text-xs mt-1">Emissions Data Review</p>
        </div>

        {/* Tenant selector */}
        <div className="px-3 pt-4 pb-2">
          <label className="text-xs text-brand-400 uppercase tracking-wide mb-1 block">Client</label>
          <select
            className="w-full text-sm bg-brand-700 text-white rounded px-2 py-1.5 border border-brand-600 focus:outline-none"
            value={activeTenant?.id ?? ''}
            onChange={e => setTenantId(Number(e.target.value))}
          >
            {tenants.map(t => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
        </div>

        <nav className="flex flex-col gap-1 px-3 py-2 flex-1">
          <NavLink to="/" end className={navClass}>
            <LayoutDashboard size={16} /> Dashboard
          </NavLink>
          <NavLink to="/ingest" className={navClass}>
            <Upload size={16} /> Ingest Data
          </NavLink>
          <NavLink to="/review" className={navClass}>
            <ClipboardCheck size={16} /> Review
          </NavLink>
        </nav>

        <div className="px-4 py-3 border-t border-brand-700 text-xs text-brand-400">
          Analyst: demo@breatheesg.com
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-auto">
        {!effectiveTenantId ? (
          <div className="flex items-center justify-center h-full text-gray-500">
            No tenants found — run <code className="mx-1 bg-gray-100 px-1 rounded">python manage.py seed_data</code>
          </div>
        ) : (
          <Routes>
            <Route path="/" element={<Dashboard tenantId={effectiveTenantId} />} />
            <Route path="/ingest" element={<Ingest tenantId={effectiveTenantId} />} />
            <Route path="/review" element={<Review tenantId={effectiveTenantId} />} />
          </Routes>
        )}
      </main>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Shell />
    </BrowserRouter>
  )
}
