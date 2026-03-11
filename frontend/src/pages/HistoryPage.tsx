import React, { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import {
  History,
  ChevronLeft,
  ChevronRight,
  Search,
  Filter,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Clock,
  TrendingUp,
  BarChart3,
  RefreshCw,
} from 'lucide-react'
import {
  fetchHistory,
  fetchStats,
  fetchAppraisalDetail,
  type AppraisalSummary,
} from '../api/history'
import AppraisalDetailDrawer from '../components/history/AppraisalDetailDrawer'

const PAGE_SIZE = 15

const STATUS_OPTIONS = [
  { value: '', label: 'All Statuses' },
  { value: 'completed', label: 'Completed' },
  { value: 'processing', label: 'Processing' },
  { value: 'pending', label: 'Pending' },
  { value: 'failed', label: 'Failed' },
]

const DECISION_BADGE: Record<string, { label: string; cls: string }> = {
  APPROVED: { label: 'Approved', cls: 'bg-emerald-400/10 text-emerald-400 border-emerald-400/20' },
  REJECTED: { label: 'Rejected', cls: 'bg-red-400/10 text-red-400 border-red-400/20' },
  REVIEW: { label: 'Review', cls: 'bg-amber-400/10 text-amber-400 border-amber-400/20' },
}

const RISK_BAND_COLOR: Record<string, string> = {
  PRIME: 'text-emerald-400',
  NEAR_PRIME: 'text-sky-400',
  SUB_PRIME: 'text-amber-400',
  HIGH_RISK: 'text-orange-400',
  HARD_REJECT: 'text-red-400',
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
}

export default function HistoryPage() {
  const [page, setPage] = useState(0)
  const [statusFilter, setStatusFilter] = useState('')
  const [selected, setSelected] = useState<(AppraisalSummary & { result_json?: Record<string, unknown> | null }) | null>(null)

  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['appraisal-stats'],
    queryFn: fetchStats,
  })

  const { data: historyData, isLoading: historyLoading, isFetching, refetch } = useQuery({
    queryKey: ['appraisal-history', page, statusFilter],
    queryFn: () =>
      fetchHistory({ limit: PAGE_SIZE, offset: page * PAGE_SIZE, status: statusFilter || undefined }),
    placeholderData: (prev) => prev,
  })

  const totalPages = Math.ceil((historyData?.count ?? 0) / PAGE_SIZE)

  async function handleRowClick(row: AppraisalSummary) {
    try {
      const detail = await fetchAppraisalDetail(row.id)
      setSelected(detail)
    } catch {
      setSelected(row)
    }
  }

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-sky-500/10 border border-sky-500/20 flex items-center justify-center">
            <History className="w-5 h-5 text-sky-400" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-white">Appraisal History</h1>
            <p className="text-sm text-slate-400">All your credit appraisal runs</p>
          </div>
        </div>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="flex items-center gap-2 px-3 py-1.5 text-sm text-slate-400 hover:text-white border border-slate-700/50 hover:border-slate-600 rounded-lg transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isFetching ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard
          icon={BarChart3}
          label="Total Appraisals"
          value={statsLoading ? '…' : String(stats?.total ?? 0)}
          iconClass="text-sky-400"
          bgClass="bg-sky-400/10"
        />
        <StatCard
          icon={CheckCircle2}
          label="Approved"
          value={statsLoading ? '…' : String(stats?.approved ?? 0)}
          iconClass="text-emerald-400"
          bgClass="bg-emerald-400/10"
        />
        <StatCard
          icon={XCircle}
          label="Rejected"
          value={statsLoading ? '…' : String(stats?.rejected ?? 0)}
          iconClass="text-red-400"
          bgClass="bg-red-400/10"
        />
        <StatCard
          icon={TrendingUp}
          label="Avg Default Prob"
          value={
            statsLoading
              ? '…'
              : stats?.avg_default_probability != null
              ? `${(stats.avg_default_probability * 100).toFixed(1)}%`
              : '—'
          }
          iconClass="text-amber-400"
          bgClass="bg-amber-400/10"
        />
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500 pointer-events-none" />
          <input
            type="text"
            placeholder="Search company…"
            className="w-full pl-9 pr-3 py-2 text-sm bg-slate-800/50 border border-slate-700/50 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:border-sky-500/50 transition-colors"
            disabled
            title="Coming soon"
          />
        </div>
        <div className="relative">
          <Filter className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500 pointer-events-none" />
          <select
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value); setPage(0) }}
            className="pl-9 pr-8 py-2 text-sm bg-slate-800/50 border border-slate-700/50 rounded-lg text-white appearance-none focus:outline-none focus:border-sky-500/50 transition-colors cursor-pointer"
          >
            {STATUS_OPTIONS.map((o) => (
              <option key={o.value} value={o.value} className="bg-slate-800">
                {o.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Table */}
      <div className="bg-slate-900/60 border border-slate-700/50 rounded-2xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-700/50">
                <th className="text-left text-xs font-medium text-slate-500 uppercase tracking-wider px-5 py-3">Company</th>
                <th className="text-left text-xs font-medium text-slate-500 uppercase tracking-wider px-5 py-3">Date</th>
                <th className="text-left text-xs font-medium text-slate-500 uppercase tracking-wider px-5 py-3">Status</th>
                <th className="text-left text-xs font-medium text-slate-500 uppercase tracking-wider px-5 py-3">Decision</th>
                <th className="text-left text-xs font-medium text-slate-500 uppercase tracking-wider px-5 py-3">Risk Band</th>
                <th className="text-right text-xs font-medium text-slate-500 uppercase tracking-wider px-5 py-3">Def. Prob.</th>
              </tr>
            </thead>
            <tbody>
              {historyLoading
                ? Array.from({ length: 6 }).map((_, i) => <SkeletonRow key={i} />)
                : historyData?.appraisals.length === 0
                ? (
                  <tr>
                    <td colSpan={6} className="px-5 py-12 text-center text-slate-500">
                      <Clock className="w-6 h-6 mx-auto mb-2 opacity-40" />
                      No appraisals found
                    </td>
                  </tr>
                )
                : historyData?.appraisals.map((row, i) => (
                  <motion.tr
                    key={row.id}
                    initial={{ opacity: 0, y: 4 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.03 }}
                    onClick={() => handleRowClick(row)}
                    className="border-b border-slate-700/30 hover:bg-slate-700/20 cursor-pointer transition-colors"
                  >
                    <td className="px-5 py-3 font-medium text-white">{row.company_name}</td>
                    <td className="px-5 py-3 text-slate-400">{formatDate(row.created_at)}</td>
                    <td className="px-5 py-3">
                      <StatusPill status={row.status} />
                    </td>
                    <td className="px-5 py-3">
                      {row.decision ? (
                        <span className={`px-2 py-0.5 text-xs font-medium rounded-full border ${DECISION_BADGE[row.decision]?.cls ?? ''}`}>
                          {DECISION_BADGE[row.decision]?.label ?? row.decision}
                        </span>
                      ) : <span className="text-slate-600">—</span>}
                    </td>
                    <td className={`px-5 py-3 font-medium ${RISK_BAND_COLOR[row.risk_band ?? ''] ?? 'text-slate-400'}`}>
                      {row.risk_band ?? '—'}
                    </td>
                    <td className="px-5 py-3 text-right text-slate-300">
                      {row.default_probability != null
                        ? `${(row.default_probability * 100).toFixed(1)}%`
                        : '—'}
                    </td>
                  </motion.tr>
                ))}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {(historyData?.count ?? 0) > PAGE_SIZE && (
          <div className="flex items-center justify-between px-5 py-3 border-t border-slate-700/30">
            <span className="text-xs text-slate-500">
              {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, historyData!.count)} of {historyData!.count}
            </span>
            <div className="flex items-center gap-2">
              <PageButton icon={ChevronLeft} disabled={page === 0} onClick={() => setPage((p) => p - 1)} />
              <span className="text-xs text-slate-400 px-1">{page + 1} / {totalPages}</span>
              <PageButton icon={ChevronRight} disabled={page + 1 >= totalPages} onClick={() => setPage((p) => p + 1)} />
            </div>
          </div>
        )}
      </div>

      <AppraisalDetailDrawer appraisal={selected} onClose={() => setSelected(null)} />
    </div>
  )
}

function StatCard({
  icon: Icon,
  label,
  value,
  iconClass,
  bgClass,
}: {
  icon: React.ElementType
  label: string
  value: string
  iconClass: string
  bgClass: string
}) {
  return (
    <div className="p-4 rounded-2xl bg-slate-900/60 border border-slate-700/50">
      <div className={`w-8 h-8 rounded-lg ${bgClass} flex items-center justify-center mb-3`}>
        <Icon className={`w-4 h-4 ${iconClass}`} />
      </div>
      <p className="text-xs text-slate-500 mb-1">{label}</p>
      <p className="text-2xl font-bold text-white">{value}</p>
    </div>
  )
}

function StatusPill({ status }: { status: string }) {
  const cfg: Record<string, string> = {
    completed: 'bg-emerald-400/10 text-emerald-400 border-emerald-400/20',
    processing: 'bg-sky-400/10 text-sky-400 border-sky-400/20',
    pending: 'bg-amber-400/10 text-amber-400 border-amber-400/20',
    failed: 'bg-red-400/10 text-red-400 border-red-400/20',
  }
  return (
    <span className={`px-2 py-0.5 text-xs font-medium rounded-full border capitalize ${cfg[status] ?? ''}`}>
      {status}
    </span>
  )
}

function PageButton({
  icon: Icon,
  disabled,
  onClick,
}: {
  icon: React.ElementType
  disabled: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="w-7 h-7 flex items-center justify-center rounded-lg border border-slate-700/50 text-slate-400 hover:text-white hover:border-slate-500 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
    >
      <Icon className="w-3.5 h-3.5" />
    </button>
  )
}

function SkeletonRow() {
  return (
    <tr className="border-b border-slate-700/30">
      {Array.from({ length: 6 }).map((_, i) => (
        <td key={i} className="px-5 py-3">
          <div className="h-4 bg-slate-800 rounded animate-pulse" style={{ width: `${60 + i * 10}%` }} />
        </td>
      ))}
    </tr>
  )
}
