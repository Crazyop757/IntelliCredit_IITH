import React from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, Building2, Calendar, TrendingUp, ShieldCheck, ShieldX, AlertTriangle, DollarSign, Percent } from 'lucide-react'
import type { AppraisalSummary } from '../../api/history'

interface Props {
  appraisal: (AppraisalSummary & { result_json?: Record<string, unknown> | null }) | null
  onClose: () => void
}

const DECISION_CONFIG: Record<string, { label: string; color: string; icon: React.ElementType }> = {
  APPROVED: { label: 'Approved', color: 'text-emerald-400 bg-emerald-400/10 border-emerald-400/30', icon: ShieldCheck },
  REJECTED: { label: 'Rejected', color: 'text-red-400 bg-red-400/10 border-red-400/30', icon: ShieldX },
  REVIEW: { label: 'Under Review', color: 'text-amber-400 bg-amber-400/10 border-amber-400/30', icon: AlertTriangle },
}

const RISK_BAND_COLOR: Record<string, string> = {
  PRIME: 'text-emerald-400',
  NEAR_PRIME: 'text-sky-400',
  SUB_PRIME: 'text-amber-400',
  HIGH_RISK: 'text-orange-400',
  HARD_REJECT: 'text-red-400',
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleString('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatCurrency(amount: number | null) {
  if (amount == null) return '—'
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(amount)
}

export default function AppraisalDetailDrawer({ appraisal, onClose }: Props) {
  const decisionCfg = appraisal?.decision ? DECISION_CONFIG[appraisal.decision] ?? DECISION_CONFIG.REVIEW : null
  const DecisionIcon = decisionCfg?.icon ?? ShieldCheck

  return (
    <AnimatePresence>
      {appraisal && (
        <>
          {/* Backdrop */}
          <motion.div
            className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />

          {/* Drawer */}
          <motion.aside
            className="fixed right-0 top-0 bottom-0 w-full max-w-xl bg-[#0F1623] border-l border-slate-700/60 shadow-2xl z-50 flex flex-col overflow-hidden"
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ type: 'spring', damping: 28, stiffness: 260 }}
          >
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700/60 shrink-0">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-xl bg-sky-500/10 border border-sky-500/20 flex items-center justify-center">
                  <Building2 className="w-4 h-4 text-sky-400" />
                </div>
                <div>
                  <h2 className="text-sm font-semibold text-white">{appraisal.company_name}</h2>
                  <p className="text-xs text-slate-500 font-mono">{appraisal.job_id.slice(0, 16)}…</p>
                </div>
              </div>
              <button
                onClick={onClose}
                className="w-8 h-8 rounded-lg flex items-center justify-center text-slate-400 hover:text-white hover:bg-slate-700/60 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
              {/* Decision chip */}
              {decisionCfg && (
                <div className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border text-sm font-semibold ${decisionCfg.color}`}>
                  <DecisionIcon className="w-4 h-4" />
                  {decisionCfg.label}
                </div>
              )}

              {/* Meta row */}
              <div className="flex items-center gap-2 text-xs text-slate-500">
                <Calendar className="w-3.5 h-3.5" />
                {formatDate(appraisal.created_at)}
              </div>

              {/* Key metrics */}
              <div className="grid grid-cols-2 gap-3">
                <MetricCard
                  icon={TrendingUp}
                  label="Risk Band"
                  value={appraisal.risk_band ?? '—'}
                  valueClass={RISK_BAND_COLOR[appraisal.risk_band ?? ''] ?? 'text-slate-300'}
                />
                <MetricCard
                  icon={Percent}
                  label="Default Probability"
                  value={appraisal.default_probability != null ? `${(appraisal.default_probability * 100).toFixed(1)}%` : '—'}
                  valueClass="text-slate-300"
                />
                <MetricCard
                  icon={DollarSign}
                  label="Credit Limit"
                  value={formatCurrency(appraisal.credit_limit)}
                  valueClass="text-emerald-400"
                />
                <MetricCard
                  icon={Percent}
                  label="Interest Rate"
                  value={appraisal.interest_rate != null ? `${appraisal.interest_rate.toFixed(2)}% p.a.` : '—'}
                  valueClass="text-slate-300"
                />
              </div>

              {/* Status badge */}
              <StatusBadge status={appraisal.status} />

              {/* Raw result JSON (collapsible) */}
              {appraisal.result_json && (
                <details className="group">
                  <summary className="cursor-pointer text-xs text-slate-400 hover:text-slate-200 transition-colors select-none list-none flex items-center gap-2">
                    <span className="w-3 h-3 border border-slate-600 rounded-sm flex items-center justify-center text-[10px] group-open:hidden">+</span>
                    <span className="w-3 h-3 border border-slate-600 rounded-sm items-center justify-center text-[10px] hidden group-open:flex">−</span>
                    Full analysis result
                  </summary>
                  <pre className="mt-3 p-3 bg-[#080C14] rounded-xl text-[11px] text-slate-300 overflow-x-auto border border-slate-700/40 leading-relaxed max-h-96 overflow-y-auto">
                    {JSON.stringify(appraisal.result_json, null, 2)}
                  </pre>
                </details>
              )}
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  )
}

function MetricCard({
  icon: Icon,
  label,
  value,
  valueClass = 'text-slate-300',
}: {
  icon: React.ElementType
  label: string
  value: string
  valueClass?: string
}) {
  return (
    <div className="p-3 rounded-xl bg-slate-800/40 border border-slate-700/40">
      <div className="flex items-center gap-1.5 mb-1.5">
        <Icon className="w-3.5 h-3.5 text-slate-500" />
        <span className="text-[11px] text-slate-500 uppercase tracking-wider font-medium">{label}</span>
      </div>
      <p className={`text-sm font-semibold ${valueClass}`}>{value}</p>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const cfg: Record<string, { color: string; label: string }> = {
    completed: { color: 'bg-emerald-400/10 text-emerald-400 border-emerald-400/20', label: 'Completed' },
    processing: { color: 'bg-sky-400/10 text-sky-400 border-sky-400/20', label: 'Processing' },
    pending: { color: 'bg-amber-400/10 text-amber-400 border-amber-400/20', label: 'Pending' },
    failed: { color: 'bg-red-400/10 text-red-400 border-red-400/20', label: 'Failed' },
  }
  const { color, label } = cfg[status] ?? cfg.pending
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-slate-500">Status</span>
      <span className={`px-2 py-0.5 text-xs font-medium rounded-full border ${color}`}>{label}</span>
    </div>
  )
}
