import React from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { useQuery } from '@tanstack/react-query'
import {
  PlusCircle, Building2, TrendingUp, Clock, CheckCircle2, XCircle,
  AlertTriangle, ArrowRight, Sparkles, BarChart2, Target,
} from 'lucide-react'
import { listCompanies } from '../api/companies'
import type { CompanyListItem } from '../store/types'
import Skeleton, { MetricCardSkeleton } from '../components/ui/Skeleton'
import { RiskBandBadge, DecisionBadge } from '../components/ui/Badge'
import Button from '../components/ui/Button'
import { formatDate } from '../utils/formatters'

const decisionIcons = {
  APPROVE: CheckCircle2,
  CONDITIONAL: AlertTriangle,
  REJECT: XCircle,
}


interface MetricCardProps {
  label: string
  value: string | number
  subText?: string
  icon: React.ElementType
  accentColor: string
  bgClass: string
  delay: number
}

function MetricCard({ label, value, subText, icon: Icon, accentColor, bgClass, delay }: MetricCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration: 0.35, ease: 'easeOut' }}
      className={`relative bg-surface rounded-2xl p-5 border border-border-dark shadow-card overflow-hidden group hover:shadow-card-hover transition-shadow`}
    >
      {/* colored left accent bar */}
      <div className="absolute left-0 top-4 bottom-4 w-1 rounded-r-full" style={{ background: accentColor }} />
      <div className="pl-2">
        <div className="flex items-start justify-between mb-4">
          <p className="text-text-muted text-xs font-medium tracking-wide uppercase">{label}</p>
          <div className={`w-9 h-9 rounded-xl flex items-center justify-center ${bgClass}`}>
            <Icon size={17} style={{ color: accentColor }} />
          </div>
        </div>
        <p className="text-text-primary text-4xl font-extrabold leading-none">{value}</p>
        {subText && <p className="text-text-muted text-xs mt-2">{subText}</p>}
      </div>
    </motion.div>
  )
}

function ApprovalDonut({ approved, rejected, conditional }: { approved: number; rejected: number; conditional: number }) {
  const total = approved + rejected + conditional || 1
  const aP = (approved / total) * 100
  const rP = (rejected / total) * 100
  const cP = (conditional / total) * 100

  const segments = [
    { pct: aP, color: '#22c55e', label: 'Approved' },
    { pct: cP, color: '#f59e0b', label: 'Conditional' },
    { pct: rP, color: '#ef4444', label: 'Rejected' },
  ]

  // Build CSS conic gradient
  let cumulative = 0
  const stops = segments.map((s) => {
    const start = cumulative
    cumulative += s.pct
    return `${s.color} ${start.toFixed(1)}% ${cumulative.toFixed(1)}%`
  })
  const gradient = `conic-gradient(${stops.join(', ')})`

  return (
    <div className="flex items-center gap-6">
      <div className="relative flex-shrink-0">
        <div className="w-20 h-20 rounded-full" style={{ background: gradient }} />
        <div className="absolute inset-2 rounded-full bg-surface" />
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-lg font-extrabold text-text-primary">{total}</span>
        </div>
      </div>
      <div className="space-y-1.5">
        {segments.map((s) => (
          <div key={s.label} className="flex items-center gap-2 text-xs">
            <span className="w-2.5 h-2.5 rounded-sm flex-shrink-0" style={{ background: s.color }} />
            <span className="text-text-secondary">{s.label}</span>
            <span className="text-text-primary font-semibold ml-auto">{s.pct.toFixed(0)}%</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function Dashboard() {
  const navigate = useNavigate()
  const { data: companies, isLoading } = useQuery({
    queryKey: ['companies'],
    queryFn: listCompanies,
    staleTime: 0,
  })

  const list = companies?.companies ?? []
  const approved = list.filter((c) => c.decision === 'APPROVE').length
  const rejected = list.filter((c) => c.decision === 'REJECT').length
  const conditional = list.filter((c) => c.decision === 'CONDITIONAL' || c.decision === 'CONDITIONAL_APPROVE').length
  const avgScore = list.length
    ? list.reduce((s, c) => s + (c.risk_score ?? 0), 0) / list.length
    : 0

  const today = new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long' })

  return (
    <div className="max-w-6xl mx-auto space-y-7">

      {/* Top greeting bar */}
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="flex flex-col sm:flex-row sm:items-end justify-between gap-3"
      >
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Sparkles size={16} className="text-amber-400" />
            <span className="text-text-muted text-sm font-medium">{today}</span>
          </div>
          <h1 className="text-text-primary text-2xl font-extrabold">Greetings, Credit Officer 👋</h1>
          <p className="text-text-secondary text-sm mt-0.5">Here's your portfolio snapshot</p>
        </div>
        <Button icon={<PlusCircle size={15} />} onClick={() => navigate('/new')}>
          New Appraisal
        </Button>
      </motion.div>

      {/* Stat row */}
      {isLoading ? (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => <MetricCardSkeleton key={i} />)}
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <MetricCard label="Total Cases" value={list.length} subText="All time" icon={Building2} accentColor="#2563EB" bgClass="bg-blue-500/10" delay={0} />
          <MetricCard label="Approved" value={approved} subText={list.length ? `${((approved/list.length)*100).toFixed(0)}% of total` : undefined} icon={CheckCircle2} accentColor="#22C55E" bgClass="bg-green-500/10" delay={0.06} />
          <MetricCard label="Rejected" value={rejected} subText={list.length ? `${((rejected/list.length)*100).toFixed(0)}% of total` : undefined} icon={XCircle} accentColor="#EF4444" bgClass="bg-red-500/10" delay={0.12} />
          <MetricCard label="Avg Risk Score" value={avgScore.toFixed(1)} subText="↑ higher = riskier" icon={TrendingUp} accentColor="#F59E0B" bgClass="bg-amber-500/10" delay={0.18} />
        </div>
      )}

      {/* Summary + table split */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">

        {/* Left: distribution donut + quick actions */}
        <div className="space-y-4">
          {/* Donut card */}
          <div className="bg-surface border border-border-dark rounded-2xl p-5 shadow-card">
            <div className="flex items-center gap-2 mb-4">
              <Target size={15} className="text-primary" />
              <p className="text-text-primary font-semibold text-sm">Decision Breakdown</p>
            </div>
            {isLoading ? (
              <Skeleton className="h-24 rounded-xl" />
            ) : list.length > 0 ? (
              <ApprovalDonut approved={approved} rejected={rejected} conditional={conditional} />
            ) : (
              <p className="text-text-muted text-sm py-4 text-center">No data yet</p>
            )}
          </div>

          {/* Quick actions */}
          <div className="bg-surface border border-border-dark rounded-2xl p-5 shadow-card space-y-2">
            <p className="text-text-primary font-semibold text-sm mb-3">Quick Actions</p>
            {[
              { label: 'Start New Appraisal', icon: PlusCircle, color: 'text-primary', bg: 'bg-primary/10', to: '/new' },
              { label: 'All Companies', icon: Building2, color: 'text-text-secondary', bg: 'bg-surface2', to: '/companies' },
            ].map(({ label, icon: Icon, color, bg, to }) => (
              <button
                key={to}
                onClick={() => navigate(to)}
                className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl hover:bg-surface2 transition-colors text-left"
              >
                <div className={`w-8 h-8 rounded-lg ${bg} flex items-center justify-center flex-shrink-0`}>
                  <Icon size={15} className={color} />
                </div>
                <span className="text-text-primary text-sm font-medium">{label}</span>
                <ArrowRight size={13} className="text-text-muted ml-auto" />
              </button>
            ))}
          </div>
        </div>

        {/* Right: recent appraisals table */}
        <div className="lg:col-span-2 bg-surface border border-border-dark rounded-2xl shadow-card overflow-hidden">
          <div className="px-5 py-4 border-b border-border-dark flex items-center justify-between">
            <div className="flex items-center gap-2">
              <BarChart2 size={15} className="text-text-muted" />
              <p className="text-text-primary font-semibold text-sm">Recent Appraisals</p>
              {!isLoading && list.length > 0 && (
                <span className="ml-1 text-xs text-text-muted bg-surface2 px-2 py-0.5 rounded-full">{list.length}</span>
              )}
            </div>
            <Link to="/companies" className="flex items-center gap-1 text-xs text-primary hover:text-primary-hover font-medium transition-colors">
              View all <ArrowRight size={11} />
            </Link>
          </div>

          {isLoading ? (
            <div className="p-5 space-y-3">
              {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-10 rounded-lg" />)}
            </div>
          ) : list.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-center px-6">
              <div className="w-14 h-14 rounded-2xl bg-surface2 flex items-center justify-center mb-4">
                <Building2 size={22} className="text-text-muted" />
              </div>
              <p className="text-text-primary font-semibold text-sm mb-1">No appraisals yet</p>
              <p className="text-text-muted text-xs mb-5">Run your first AI credit appraisal to see it here.</p>
              <Button size="sm" icon={<PlusCircle size={13} />} onClick={() => navigate('/new')}>
                New Appraisal
              </Button>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border-dark">
                    {['Company', 'Score', 'Band', 'Decision', 'Date'].map((h) => (
                      <th key={h} className="text-left text-xs text-text-muted font-semibold px-5 py-3 uppercase tracking-wide">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {list.slice(0, 8).map((c, i) => {
                    const DecIcon = decisionIcons[c.decision as keyof typeof decisionIcons]
                    const isApprove = c.decision === 'APPROVE'
                    const isReject = c.decision === 'REJECT'
                    return (
                      <motion.tr
                        key={c.company_id}
                        initial={{ opacity: 0, x: -6 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: i * 0.035 }}
                        onClick={() => navigate(`/companies/${c.company_id}`)}
                        className="border-b border-border-dark/40 hover:bg-surface2/60 cursor-pointer transition-colors group"
                      >
                        <td className="px-5 py-3.5">
                          <div className="flex items-center gap-2.5">
                            <div className="w-7 h-7 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0 group-hover:bg-primary/20 transition-colors">
                              <Building2 size={12} className="text-primary" />
                            </div>
                            <span className="text-text-primary font-medium text-xs truncate max-w-[140px]">{c.company_name || '—'}</span>
                          </div>
                        </td>
                        <td className="px-5 py-3.5">
                          <span className={`font-bold text-sm ${isApprove ? 'text-green-700' : isReject ? 'text-red-600' : 'text-amber-600'}`}>
                            {c.risk_score?.toFixed(1) ?? '—'}
                          </span>
                        </td>
                        <td className="px-5 py-3.5">
                          {c.risk_band ? <RiskBandBadge band={c.risk_band} size="xs" /> : <span className="text-text-muted">—</span>}
                        </td>
                        <td className="px-5 py-3.5">
                          {c.decision ? (
                            <div className="flex items-center gap-1.5">
                              {DecIcon && (
                                <DecIcon size={12} className={isApprove ? 'text-green-500' : isReject ? 'text-red-500' : 'text-amber-500'} />
                              )}
                              <DecisionBadge decision={c.decision} size="xs" />
                            </div>
                          ) : <span className="text-text-muted">—</span>}
                        </td>
                        <td className="px-5 py-3.5">
                          <span className="text-text-muted text-xs flex items-center gap-1">
                            <Clock size={10} />
                            {c.appraisal_date ? formatDate(c.appraisal_date) : '—'}
                          </span>
                        </td>
                      </motion.tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
