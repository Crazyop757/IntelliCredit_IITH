/**
 * AppraisalPage — unified single-page experience:
 *   Phase 1 · INPUT     : company details + documents + optional qualitative
 *   Phase 2 · ANALYSIS  : animated live pipeline
 *   Phase 3 · RESULTS   : full credit verdict + analysis tabs
 */
import React, { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { useForm, useWatch } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import toast from 'react-hot-toast'
import {
  Building2, Upload, ChevronDown, ChevronUp, Rocket,
  CheckCircle2, XCircle, AlertTriangle, ChevronRight,
  Download, BarChart3, DollarSign, Globe, Briefcase,
  Shield, TrendingUp, Clock, Circle, Loader2, Terminal,
  Zap, FileText, ClipboardList, Activity,
} from 'lucide-react'

import Input, { Textarea, Select } from '../components/ui/Input'
import Button from '../components/ui/Button'
import FileDropzone from '../components/shared/FileDropzone'
import Card, { CardHeader, CardTitle, CardBody } from '../components/ui/Card'
import { Tabs, TabList, TabTrigger, TabContent } from '../components/ui/Tabs'
import RiskGauge from '../components/charts/RiskGauge'
import SHAPWaterfall from '../components/charts/SHAPWaterfall'
import FinancialTrend from '../components/charts/FinancialTrend'
import EWSRadar from '../components/charts/EWSRadar'
import RiskClauseList from '../components/shared/RiskClauseList'
import { RiskBandBadge, SeverityBadge, DecisionBadge } from '../components/ui/Badge'
import GSTNetworkGraph from '../components/charts/GSTNetworkGraph'
import RiskBreakdown from '../components/charts/RiskBreakdown'
import BankTransactionTimeline from '../components/charts/BankTransactionTimeline'
import MetricTrends from '../components/charts/MetricTrends'

import { runFullPipeline } from '../api/analysis'
import { submitQualitative } from '../api/scoring'
import { downloadFile } from '../api/client'
import { useDownload } from '../hooks/useDownload'
import { usePipeline } from '../hooks/usePipeline'
import { useSession } from '../hooks/useSession'
import {
  PIPELINE_STAGES,
  QUALITATIVE_CAPACITY_BRACKETS, FACILITY_CONDITION_ADJUSTMENTS,
} from '../utils/constants'
import { formatINR, formatCrore, formatPct, formatDate } from '../utils/formatters'
import type { FinancialYear, SHAPFactor, QualitativeFormData } from '../store/types'

// ─── Schemas ─────────────────────────────────────────────────────────────────

const companySchema = z.object({
  company_name: z.string().min(3, 'Company name is required'),
  loan_amount_requested: z.coerce.number().positive('Loan amount must be positive'),
  tenure_months: z.coerce.number().int().min(1).max(360),
})

const qualSchema = z.object({
  site_visit_observations: z.string().min(10, 'At least 10 characters'),
  capacity_utilization_pct: z.coerce.number().min(0).max(100),
  facility_condition: z.enum(['EXCELLENT', 'GOOD', 'FAIR', 'POOR', 'NOT_VISITED']),
  management_interview_notes: z.string().min(10, 'At least 10 characters'),
  management_transparency: z.enum(['FULLY_TRANSPARENT', 'MOSTLY_TRANSPARENT', 'EVASIVE', 'UNCOOPERATIVE']),
  group_company_exposure: z.string().optional(),
  inventory_vs_records: z.string().optional(),
  employee_count_vs_records: z.string().optional(),
  other_key_observations: z.string().optional(),
})

type CompanyForm = z.infer<typeof companySchema>
type QualForm = z.infer<typeof qualSchema>

const transparencyAdj: Record<string, number> = {
  FULLY_TRANSPARENT: 0.5, MOSTLY_TRANSPARENT: 0.0, EVASIVE: -1.0, UNCOOPERATIVE: -2.0,
}

function estimateQualAdj(values: Partial<QualForm>): number {
  let total = 0
  const cap = values.capacity_utilization_pct ?? 0
  for (const b of QUALITATIVE_CAPACITY_BRACKETS) {
    if (cap < b.threshold) { total += b.adjustment; break }
  }
  if (values.facility_condition) total += FACILITY_CONDITION_ADJUSTMENTS[values.facility_condition] ?? 0
  if (values.management_transparency) total += transparencyAdj[values.management_transparency] ?? 0
  return Math.max(-5, Math.min(2, total))
}

// ─── Phase indicator ─────────────────────────────────────────────────────────

function PhaseTrack({ phase }: { phase: 'input' | 'analysis' | 'results' }) {
  const phases = [
    { key: 'input',    label: 'Details & Documents', icon: Building2 },
    { key: 'analysis', label: 'AI Analysis',          icon: Zap },
    { key: 'results',  label: 'Credit Decision',      icon: BarChart3 },
  ] as const
  const currentIdx = phases.findIndex((p) => p.key === phase)

  return (
    <div className="flex items-center gap-0 mb-8">
      {phases.map((p, i) => {
        const Icon = p.icon
        const done = i < currentIdx
        const active = i === currentIdx
        return (
          <React.Fragment key={p.key}>
            <div className={[
              'flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all duration-300',
              active ? 'bg-primary text-white shadow-md' : '',
              done ? 'text-primary' : (!active ? 'text-text-muted' : ''),
            ].join(' ')}>
              {done ? <CheckCircle2 size={16} className="text-primary" /> : <Icon size={16} />}
              <span>{p.label}</span>
            </div>
            {i < phases.length - 1 && (
              <div className={`h-px flex-1 mx-2 transition-colors duration-500 ${i < currentIdx ? 'bg-primary' : 'bg-border-dark'}`} />
            )}
          </React.Fragment>
        )
      })}
    </div>
  )
}

// ─── Input section (phase 1) ─────────────────────────────────────────────────

function InputSection({
  onLaunch,
}: {
  onLaunch: (form: CompanyForm, files: {
    annualReport: File | null
    bankStatement: File | null
    gstFiles: File[]
    itrFile: File | null
    mcaFile: File | null
  }, quals: QualForm | null) => Promise<void>
}) {
  const [annualReport, setAnnualReport] = useState<File | null>(null)
  const [bankStatement, setBankStatement] = useState<File | null>(null)
  const [gstFiles, setGstFiles] = useState<File[]>([])
  const [itrFile, setItrFile] = useState<File | null>(null)
  const [mcaFile, setMcaFile] = useState<File | null>(null)
  const [showQual, setShowQual] = useState(false)
  const [launching, setLaunching] = useState(false)

  const form = useForm<CompanyForm>({
    resolver: zodResolver(companySchema),
    defaultValues: { tenure_months: 60 },
  })
  const qualForm = useForm<QualForm>({
    resolver: zodResolver(qualSchema),
    defaultValues: { capacity_utilization_pct: 70, facility_condition: 'GOOD', management_transparency: 'MOSTLY_TRANSPARENT' },
  })
  const qualValues = useWatch({ control: qualForm.control })
  const qualEst = estimateQualAdj(qualValues as Partial<QualForm>)

  const handleSubmit = form.handleSubmit(async (data) => {
    if (!annualReport && !bankStatement && gstFiles.length === 0 && !itrFile && !mcaFile) { 
      toast.error('Upload at least one document'); 
      return 
    }
    let quals: QualForm | null = null
    if (showQual) {
      const ok = await qualForm.trigger()
      if (!ok) { toast.error('Fix qualitative form errors'); return }
      quals = qualForm.getValues()
    }
    setLaunching(true)
    try {
      await onLaunch(data, { annualReport, bankStatement, gstFiles, itrFile, mcaFile }, quals)
    } finally {
      setLaunching(false)
    }
  })

  return (
    <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -20 }} className="space-y-5">
      {/* Company + Loan */}
      <div className="bg-surface border border-border-dark rounded-2xl shadow-card overflow-hidden">
        <div className="px-6 py-4 border-b border-border-dark flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-blue-500/10 flex items-center justify-center">
            <Building2 size={18} className="text-primary" />
          </div>
          <div>
            <p className="font-semibold text-text-primary text-sm">Company & Loan Details</p>
            <p className="text-text-muted text-xs">Basic borrower information</p>
          </div>
        </div>
        <div className="p-6">
          <form id="company-form" onSubmit={handleSubmit}>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <Input label="Company Name *" placeholder="Reliance Industries Ltd" {...form.register('company_name')} error={form.formState.errors.company_name?.message} />
              <Input label="Loan Amount Requested (₹ Cr) *" type="number" placeholder="100" {...form.register('loan_amount_requested')} error={form.formState.errors.loan_amount_requested?.message} />
              <Input label="Tenure (months) *" type="number" placeholder="60" {...form.register('tenure_months')} error={form.formState.errors.tenure_months?.message} />
            </div>
          </form>
        </div>
      </div>

      {/* Upload Documents */}
      <div className="bg-surface border border-border-dark rounded-2xl shadow-card overflow-hidden">
        <div className="px-6 py-4 border-b border-border-dark flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-sky-500/10 flex items-center justify-center">
            <Upload size={18} className="text-sky-400" />
          </div>
          <div>
            <p className="font-semibold text-text-primary text-sm">Upload Documents</p>
            <p className="text-text-muted text-xs">Upload required documents for AI analysis</p>
          </div>
        </div>
        <div className="p-6 space-y-5">
          {/* Annual Report */}
          <div>
            <label className="block text-sm font-medium text-text-secondary mb-2">
              Annual Report <span className="text-red-400">*</span>
              <span className="ml-2 text-xs font-normal text-text-muted">(PDF only)</span>
            </label>
            <input
              type="file"
              accept=".pdf"
              onChange={(e) => setAnnualReport(e.target.files?.[0] || null)}
              className="block w-full text-sm text-text-muted file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-blue-500/10 file:text-blue-400 hover:file:bg-blue-500/20 cursor-pointer border border-border-dark rounded-lg bg-surface2 focus:outline-none focus:ring-2 focus:ring-primary"
            />
            {annualReport && (
              <p className="mt-1 text-xs text-green-600 flex items-center gap-1">
                <CheckCircle2 size={12} /> {annualReport.name} ({(annualReport.size / 1024 / 1024).toFixed(2)} MB)
              </p>
            )}
          </div>

          {/* Bank Statement */}
          <div>
            <label className="block text-sm font-medium text-text-secondary mb-2">
              Bank Statement <span className="text-red-400">*</span>
              <span className="ml-2 text-xs font-normal text-text-muted">(CSV or Excel)</span>
            </label>
            <input
              type="file"
              accept=".csv,.xlsx,.xls"
              onChange={(e) => setBankStatement(e.target.files?.[0] || null)}
              className="block w-full text-sm text-text-muted file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-emerald-500/10 file:text-emerald-400 hover:file:bg-emerald-500/20 cursor-pointer border border-border-dark rounded-lg bg-surface2 focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
            {bankStatement && (
              <p className="mt-1 text-xs text-green-600 flex items-center gap-1">
                <CheckCircle2 size={12} /> {bankStatement.name} ({(bankStatement.size / 1024 / 1024).toFixed(2)} MB)
              </p>
            )}
          </div>

          {/* GST Files */}
          <div>
            <label className="block text-sm font-medium text-text-secondary mb-2">
              GST Returns <span className="text-red-400">*</span>
              <span className="ml-2 text-xs font-normal text-text-muted">(GSTR-1, GSTR-2A, GSTR-3B JSON files)</span>
            </label>
            <input
              type="file"
              accept=".json"
              multiple
              onChange={(e) => setGstFiles(e.target.files ? Array.from(e.target.files) : [])}
              className="block w-full text-sm text-text-muted file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-amber-500/10 file:text-amber-400 hover:file:bg-amber-500/20 cursor-pointer border border-border-dark rounded-lg bg-surface2 focus:outline-none focus:ring-2 focus:ring-amber-500"
            />
            {gstFiles.length > 0 && (
              <div className="mt-2 space-y-1">
                {gstFiles.map((f, i) => (
                  <p key={i} className="text-xs text-green-600 flex items-center gap-1">
                    <CheckCircle2 size={12} /> {f.name} ({(f.size / 1024).toFixed(0)} KB)
                  </p>
                ))}
              </div>
            )}
          </div>

          {/* ITR (Optional) */}
          <div>
            <label className="block text-sm font-medium text-text-secondary mb-2">
              Income Tax Return (ITR)
              <span className="ml-2 text-xs font-normal text-text-muted">(Optional)</span>
            </label>
            <input
              type="file"
              accept=".pdf,.json"
              onChange={(e) => setItrFile(e.target.files?.[0] || null)}
              className="block w-full text-sm text-text-muted file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-purple-500/10 file:text-purple-400 hover:file:bg-purple-500/20 cursor-pointer border border-border-dark rounded-lg bg-surface2 focus:outline-none focus:ring-2 focus:ring-purple-500"
            />
            {itrFile && (
              <p className="mt-1 text-xs text-green-600 flex items-center gap-1">
                <CheckCircle2 size={12} /> {itrFile.name} ({(itrFile.size / 1024 / 1024).toFixed(2)} MB)
              </p>
            )}
          </div>

          {/* MCA (Optional) */}
          <div>
            <label className="block text-sm font-medium text-text-secondary mb-2">
              MCA Filing Document
              <span className="ml-2 text-xs font-normal text-text-muted">(Optional)</span>
            </label>
            <input
              type="file"
              accept=".pdf,.json"
              onChange={(e) => setMcaFile(e.target.files?.[0] || null)}
              className="block w-full text-sm text-text-muted file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-rose-500/10 file:text-rose-400 hover:file:bg-rose-500/20 cursor-pointer border border-border-dark rounded-lg bg-surface2 focus:outline-none focus:ring-2 focus:ring-rose-500"
            />
            {mcaFile && (
              <p className="mt-1 text-xs text-green-600 flex items-center gap-1">
                <CheckCircle2 size={12} /> {mcaFile.name} ({(mcaFile.size / 1024 / 1024).toFixed(2)} MB)
              </p>
            )}
          </div>
        </div>
      </div>

      {/* Optional Qualitative */}
      <div className="bg-surface border border-border-dark rounded-2xl shadow-card overflow-hidden">
        <button
          type="button"
          onClick={() => setShowQual(!showQual)}
          className="w-full px-6 py-4 flex items-center justify-between hover:bg-surface2 transition-colors"
        >
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-purple-500/10 flex items-center justify-center">
              <ClipboardList size={18} className="text-purple-400" />
            </div>
            <div className="text-left">
              <p className="font-semibold text-text-primary text-sm">Qualitative Assessment <span className="ml-1 text-xs font-normal text-text-muted">(Optional)</span></p>
              <p className="text-text-muted text-xs">Credit officer's site visit & management observations</p>
            </div>
          </div>
          <div className={`transition-transform duration-200 ${showQual ? 'rotate-180' : ''}`}>
            <ChevronDown size={18} className="text-text-muted" />
          </div>
        </button>

        <AnimatePresence>
          {showQual && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.3, ease: 'easeInOut' }}
              className="overflow-hidden"
            >
              <div className="px-6 pb-6 border-t border-border-dark">
                {/* Score preview */}
                <div className="mt-4 mb-5 p-3 rounded-xl bg-purple-500/10 border border-purple-500/20 flex items-center gap-3">
                  <div className={`text-xs font-bold px-2 py-1 rounded-lg ${qualEst >= 0 ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>
                    {qualEst >= 0 ? `−${qualEst.toFixed(1)}` : `+${Math.abs(qualEst).toFixed(1)}`} risk pts
                  </div>
                  <p className="text-text-secondary text-xs">Estimated qualitative risk adjustment</p>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <Input label="Capacity Utilization %" type="number" {...qualForm.register('capacity_utilization_pct')} error={qualForm.formState.errors.capacity_utilization_pct?.message} />
                  <Select label="Facility Condition" options={[
                    { value: 'EXCELLENT', label: 'Excellent' }, { value: 'GOOD', label: 'Good' },
                    { value: 'FAIR', label: 'Fair' }, { value: 'POOR', label: 'Poor' },
                    { value: 'NOT_VISITED', label: 'Not Visited' },
                  ]} {...qualForm.register('facility_condition')} />
                  <Select label="Management Transparency" options={[
                    { value: 'FULLY_TRANSPARENT', label: 'Fully Transparent' },
                    { value: 'MOSTLY_TRANSPARENT', label: 'Mostly Transparent' },
                    { value: 'EVASIVE', label: 'Evasive' },
                    { value: 'UNCOOPERATIVE', label: 'Uncooperative' },
                  ]} {...qualForm.register('management_transparency')} />
                  <Input label="Group Company Exposure" placeholder="Brief description" {...qualForm.register('group_company_exposure')} />
                </div>
                <div className="mt-4 space-y-4">
                  <Textarea label="Site Visit Observations *" rows={2} placeholder="Describe the factory/office condition…" {...qualForm.register('site_visit_observations')} error={qualForm.formState.errors.site_visit_observations?.message} />
                  <Textarea label="Management Interview Notes *" rows={2} placeholder="Summary of management discussion…" {...qualForm.register('management_interview_notes')} error={qualForm.formState.errors.management_interview_notes?.message} />
                  <Textarea label="Other Key Observations" rows={2} placeholder="Any additional risk observations…" {...qualForm.register('other_key_observations')} />
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Launch button */}
      <div className="flex justify-end">
        <button
          type="submit"
          form="company-form"
          disabled={launching}
          className="flex items-center gap-2 bg-primary hover:bg-primary-hover disabled:opacity-60 text-white font-semibold px-8 py-3 rounded-xl transition-colors shadow-md hover:shadow-lg text-sm"
        >
          {launching ? <Loader2 size={17} className="animate-spin" /> : <Rocket size={17} />}
          {launching ? 'Launching…' : 'Launch AI Analysis'}
        </button>
      </div>
    </motion.div>
  )
}

// ─── Analysis section (phase 2) ──────────────────────────────────────────────

function AnalysisSection({
  jobId,
  companyName,
  onComplete,
  onFailed,
}: {
  jobId: string
  companyName: string
  onComplete: () => void
  onFailed: () => void
}) {
  const { job, isComplete, isFailed } = usePipeline(jobId)
  const { recordResults } = useSession()
  const called = useRef(false)

  useEffect(() => {
    if (isComplete && job?.result && !called.current) {
      called.current = true
      recordResults(job.result)
      setTimeout(onComplete, 900)
    }
    if (isFailed && !called.current) {
      called.current = true
      setTimeout(onFailed, 600)
    }
  }, [isComplete, isFailed, job, recordResults, onComplete, onFailed])

  const progress = job?.progress_pct ?? 0

  const logLines: string[] = job?.stages?.flatMap((s) => {
    const lines: string[] = []
    if (s.started_at) lines.push(`[${new Date(s.started_at).toLocaleTimeString()}] ${s.stage_name ?? s.name}`)
    if (s.output_snippet ?? s.message) lines.push(`  → ${s.output_snippet ?? s.message}`)
    if (s.status === 'done') lines.push(`  ✓ Done${(s.duration_s ?? s.duration_seconds) ? ` in ${(s.duration_s ?? s.duration_seconds)!.toFixed(1)}s` : ''}`)
    if (s.status === 'failed') lines.push(`  ✗ Failed`)
    return lines
  }) ?? []

  return (
    <motion.div
      initial={{ opacity: 0, y: 32 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: 'easeOut' }}
      className="space-y-5"
    >
      {/* Header */}
      <div className="text-center py-2">
        <p className="text-text-muted text-sm font-medium">Analysing</p>
        <p className="text-text-primary text-xl font-bold mt-0.5">{companyName}</p>
      </div>

      {/* Progress rail */}
      <div className="bg-surface border border-border-dark rounded-2xl p-6 shadow-card">
        <div className="flex items-center justify-between mb-2">
          <span className="text-text-secondary text-sm font-medium">Overall Progress</span>
          <span className="text-primary font-bold text-lg">{Math.round(progress)}%</span>
        </div>
        <div className="h-3 bg-surface2 rounded-full overflow-hidden mb-6">
          <motion.div
            className="h-full rounded-full"
            style={{ background: 'linear-gradient(90deg, #4F46E5, #06B6D4)' }}
            initial={{ width: 0 }}
            animate={{ width: `${progress}%` }}
            transition={{ duration: 0.6, ease: 'easeOut' }}
          />
        </div>

        {/* Stage dots rail */}
        <div className="flex items-start justify-between relative">
          <div className="absolute top-4 left-0 right-0 h-px bg-border-dark z-0" />
          {PIPELINE_STAGES.map((stage, i) => {
            const stg = job?.stages?.find((s) => (s.name ?? s.stage_name) === stage.key || s.stage_name === stage.label)
            const _status: 'pending' | 'running' | 'done' | 'failed' = (() => {
              if (!job) return 'pending'
              const currentIdx = PIPELINE_STAGES.findIndex((s) => s.key === job.current_stage)
              if (job.status === 'DONE') return 'done'
              if (job.status === 'FAILED' && i === currentIdx) return 'failed'
              if (i < currentIdx) return 'done'
              if (i === currentIdx) return job.status === 'RUNNING' ? 'running' : 'pending'
              return 'pending'
            })()

            return (
              <div key={stage.key} className="flex flex-col items-center gap-2 z-10 flex-1">
                <motion.div
                  animate={_status === 'running' ? { scale: [1, 1.2, 1] } : {}}
                  transition={{ repeat: Infinity, duration: 1.4 }}
                  className={[
                    'w-8 h-8 rounded-full border-2 flex items-center justify-center transition-all duration-300',
                    _status === 'done'    ? 'bg-green-500 border-green-500'      : '',
                    _status === 'running' ? 'bg-primary border-primary shadow-lg shadow-primary/20' : '',
                    _status === 'pending' ? 'bg-surface border-border-strong'          : '',
                    _status === 'failed'  ? 'bg-red-500 border-red-500'          : '',
                  ].join(' ')}
                >
                  {_status === 'done'    && <CheckCircle2 size={14} className="text-white" />}
                  {_status === 'running' && <Loader2 size={14} className="text-white animate-spin" />}
                  {_status === 'pending' && <Circle size={10} className="text-text-muted" />}
                  {_status === 'failed'  && <XCircle size={14} className="text-white" />}
                </motion.div>
                <span className={`text-xs font-medium text-center leading-tight max-w-[72px] ${_status === 'running' ? 'text-primary' : _status === 'done' ? 'text-green-400' : 'text-text-muted'}`}>
                  {stage.label}
                </span>
                {stg?.duration_s && (
                  <span className="text-xs text-text-muted">{stg.duration_s.toFixed(1)}s</span>
                )}
              </div>
            )
          })}
        </div>

        {/* Status message */}
        <div className="mt-6 text-center">
          {isComplete && (
            <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="text-green-400 font-semibold text-sm">
              ✓ Analysis complete — loading results…
            </motion.p>
          )}
          {isFailed && (
            <p className="text-red-400 font-semibold text-sm">✗ Pipeline failed — {job?.error ?? 'check logs'}</p>
          )}
          {!isComplete && !isFailed && (
            <p className="text-text-muted text-sm animate-pulse">
              {job?.current_stage ? `Running: ${PIPELINE_STAGES.find((s) => s.key === job.current_stage)?.label ?? job.current_stage}…` : 'Starting pipeline…'}
            </p>
          )}
        </div>
      </div>

      {/* Live log */}
      <div className="rounded-xl overflow-hidden border border-border-dark">
        <div className="flex items-center gap-2 px-4 py-2.5 bg-surface2 border-b border-border-dark">
          <div className="flex gap-1.5">
            <div className="w-3 h-3 rounded-full bg-red-400" />
            <div className="w-3 h-3 rounded-full bg-yellow-400" />
            <div className="w-3 h-3 rounded-full bg-green-400" />
          </div>
          <Terminal size={13} className="text-text-muted ml-1" />
          <span className="text-text-muted text-xs font-mono">pipeline.log</span>
          <span className="ml-auto text-text-muted text-xs">{logLines.length} entries</span>
        </div>
        <div className="bg-[#0A0E17] h-48 overflow-y-auto p-4 font-mono text-xs space-y-0.5">
          {logLines.length === 0 ? (
            <p className="text-text-muted italic">Waiting for pipeline to start…</p>
          ) : (
            logLines.map((line, i) => {
              const l = line.toLowerCase()
              const cls = l.includes('error') || l.includes('failed') ? 'text-red-400'
                : l.includes('warn') ? 'text-yellow-400'
                : l.includes('done') || l.includes('success') || l.includes('complete') ? 'text-green-400'
                : l.includes('start') || l.includes('running') ? 'text-blue-400'
                : 'text-text-muted'
              return <div key={i} className={`leading-5 ${cls}`}>{line}</div>
            })
          )}
        </div>
      </div>
    </motion.div>
  )
}

// ─── Decision verdict hero ────────────────────────────────────────────────────

function VerdictHero({ decision, riskScore, riskBand }: { decision: string; riskScore: number; riskBand: string }) {
  const configs = {
    APPROVE: { bg: 'from-green-900/20 to-emerald-900/20', border: 'border-green-500/30', icon: CheckCircle2, iconBg: 'bg-green-500/20', iconColor: 'text-green-400', label: 'APPROVED', sub: 'Recommended for sanction', badgeCls: 'bg-green-500/20 text-green-400' },
    CONDITIONAL: { bg: 'from-amber-900/20 to-yellow-900/20', border: 'border-amber-500/30', icon: AlertTriangle, iconBg: 'bg-amber-500/20', iconColor: 'text-amber-400', label: 'CONDITIONAL', sub: 'Subject to additional conditions', badgeCls: 'bg-amber-500/20 text-amber-400' },
    CONDITIONAL_APPROVE: { bg: 'from-amber-900/20 to-yellow-900/20', border: 'border-amber-500/30', icon: AlertTriangle, iconBg: 'bg-amber-500/20', iconColor: 'text-amber-400', label: 'CONDITIONAL', sub: 'Subject to additional conditions', badgeCls: 'bg-amber-500/20 text-amber-400' },
    REJECT: { bg: 'from-red-900/20 to-rose-900/20', border: 'border-red-500/30', icon: XCircle, iconBg: 'bg-red-500/20', iconColor: 'text-red-400', label: 'REJECTED', sub: 'Credit exposure not recommended', badgeCls: 'bg-red-500/20 text-red-400' },
  } as const
  const key = (decision as keyof typeof configs) in configs ? (decision as keyof typeof configs) : 'CONDITIONAL'
  const cfg = configs[key]
  const Icon = cfg.icon

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.96, y: 12 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      transition={{ duration: 0.5, type: 'spring', stiffness: 80 }}
      className={`bg-gradient-to-br ${cfg.bg} border ${cfg.border} rounded-2xl p-6 flex items-center gap-6`}
    >
      <motion.div
        initial={{ scale: 0 }}
        animate={{ scale: 1 }}
        transition={{ delay: 0.2, type: 'spring', stiffness: 200 }}
        className={`w-16 h-16 rounded-2xl ${cfg.iconBg} flex items-center justify-center flex-shrink-0`}
      >
        <Icon size={32} className={cfg.iconColor} />
      </motion.div>
      <div className="flex-1 min-w-0">
        <p className="text-text-muted text-xs font-semibold uppercase tracking-widest mb-0.5">Credit Decision</p>
        <h2 className="text-2xl font-extrabold text-text-primary">{cfg.label}</h2>
        <p className="text-text-muted text-sm mt-0.5">{cfg.sub}</p>
      </div>
      <div className="text-right flex-shrink-0">
        <p className="text-text-muted text-xs mb-1">Risk Score</p>
        <p className="text-4xl font-extrabold text-text-primary">{riskScore.toFixed(1)}<span className="text-lg text-text-muted">/10</span></p>
        <RiskBandBadge band={riskBand} />
      </div>
    </motion.div>
  )
}

// ─── Metric strip ────────────────────────────────────────────────────────────

function MetricStrip({ score, ews }: { score: any; ews: any }) {
  const items = [
    { label: 'Default Probability', value: `${((score.default_probability ?? 0) * 100).toFixed(1)}%`, color: '#DC2626' },
    { label: 'Risk Band', value: score.risk_band ?? '—', color: '#4F46E5' },
    { label: 'EWS Score', value: ews?.ews_score != null ? ews.ews_score.toFixed(2) : '—', color: '#D97706' },
    { label: 'SMA Class', value: ews?.sma_classification ?? '—', color: '#0891B2' },
  ]
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      {items.map(({ label, value, color }) => (
        <div key={label} className="bg-surface border border-border-dark rounded-xl p-4 text-center shadow-card">
          <p className="text-text-muted text-xs mb-1">{label}</p>
          <p className="text-text-primary font-bold text-base" style={{ color }}>{value}</p>
        </div>
      ))}
    </div>
  )
}

// ─── 5-C accordion ──────────────────────────────────────────────────────────

function FiveCSection({ title, content }: { title: string; content?: string }) {
  const [open, setOpen] = useState(true)
  if (!content) return null
  return (
    <div className="border border-border-dark rounded-xl overflow-hidden">
      <button onClick={() => setOpen(!open)} className="w-full flex items-center justify-between px-5 py-3.5 bg-surface2 hover:bg-surface-hover transition-colors text-left">
        <span className="text-text-primary font-semibold text-sm">{title}</span>
        {open ? <ChevronUp size={15} className="text-text-muted" /> : <ChevronDown size={15} className="text-text-muted" />}
      </button>
      {open && (
        <div className="px-5 py-4 text-text-secondary text-sm leading-relaxed whitespace-pre-line">
          {content}
        </div>
      )}
    </div>
  )
}

// ─── Results section (phase 3) ───────────────────────────────────────────────

function ResultsSection() {
  const navigate = useNavigate()
  const { results, company } = useSession()
  const { download: downloadCAM, loading: camLoading } = useDownload()
  const [tab, setTab] = useState('overview')
  const [qualOpen, setQualOpen] = useState(false)

  const qualForm = useForm<QualForm>({
    resolver: zodResolver(qualSchema),
    defaultValues: { capacity_utilization_pct: 70, facility_condition: 'GOOD', management_transparency: 'MOSTLY_TRANSPARENT' },
  })
  const { session_id, recordQualitative, qualitative_submitted } = useSession()

  if (!results) return null

  const { score, ews, ingest, research, five_cs, cam_download_url } = results
  const financialYears: FinancialYear[] = Object.entries(ingest?.extracted_financials ?? {})
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([yr, fy]) => ({ ...fy, year: yr }))
  const allSHAP: SHAPFactor[] = [
    ...(score?.shap_explanations?.top_risk_factors ?? []),
    ...(score?.shap_explanations?.top_positive_factors ?? []),
  ]

  const handleDownload = async () => {
    if (cam_download_url) {
      try { await downloadFile(cam_download_url) } catch {}
    } else if (company) {
      await downloadCAM({
        company_id: results.session_id, company_name: company.company_name, cin: company.cin,
        five_cs_text: five_cs, scoring_result: score, research_report: research,
      })
    }
  }

  const handleQualSubmit = qualForm.handleSubmit(async (data) => {
    if (!session_id) { toast.error('No active session'); return }
    try {
      const payload: QualitativeFormData = { ...data, session_id }
      await submitQualitative(payload)
      recordQualitative(payload)
      toast.success('Qualitative assessment applied!')
      setQualOpen(false)
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Failed to submit')
    }
  })

  return (
    <motion.div
      initial={{ opacity: 0, y: 40 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6, ease: 'easeOut' }}
      className="space-y-5"
    >
      {/* Verdict hero */}
      {score && (
        <VerdictHero
          decision={score.decision ?? 'CONDITIONAL'}
          riskScore={score.risk_score}
          riskBand={score.risk_band}
        />
      )}

      {/* Metric strip */}
      {score && <MetricStrip score={score} ews={ews} />}

      {/* Action bar */}
      <div className="flex flex-wrap items-center gap-3">
        <Button icon={<Download size={14} />} loading={camLoading} onClick={handleDownload}>
          Download CAM Report
        </Button>
        <Button variant="ghost" onClick={() => navigate('/companies')}>
          View All Companies
        </Button>
        <Button variant="ghost" onClick={() => navigate('/new')}>
          New Appraisal
        </Button>
      </div>

      {/* Main analysis card */}
      <Card>
        <Tabs value={tab} onChange={setTab}>
          <TabList className="px-2 pt-2">
            <TabTrigger value="overview"  icon={<BarChart3  size={14} />}>Overview</TabTrigger>
            <TabTrigger value="visualizations" icon={<Activity size={14} />}>Visualizations</TabTrigger>
            <TabTrigger value="financial" icon={<DollarSign size={14} />}>Financial</TabTrigger>
            <TabTrigger value="gst"       icon={<Building2  size={14} />}>GST & Bank</TabTrigger>
            <TabTrigger value="research"  icon={<Globe      size={14} />}>Research</TabTrigger>
            <TabTrigger value="fivecs"    icon={<Briefcase  size={14} />}>Five C's</TabTrigger>
            <TabTrigger value="shap"      icon={<Shield     size={14} />}>SHAP</TabTrigger>
          </TabList>

          {/* Overview */}
          <TabContent value="overview" className="p-6">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {score && (
                <div className="flex flex-col items-center">
                  <p className="text-text-secondary text-sm font-medium mb-3">Risk Score Gauge</p>
                  <RiskGauge score={score.risk_score} size={220} />
                  <p className="text-xs text-text-muted mt-2">0 = safest · 10 = highest risk</p>
                </div>
              )}
              {ews && (
                <div>
                  <p className="text-text-secondary text-sm font-medium mb-3">Early Warning Signals</p>
                  <EWSRadar flags={ews} />
                </div>
              )}
              {ingest?.risk_clauses && ingest.risk_clauses.length > 0 && (
                <div className="lg:col-span-2">
                  <RiskClauseList clauses={ingest.risk_clauses} />
                </div>
              )}
            </div>
          </TabContent>

          {/* Visualizations */}
          <TabContent value="visualizations" className="p-6">
            <div className="space-y-6">
              {/* Risk Breakdown */}
              {score && (
                <RiskBreakdown
                  riskFactors={{
                    high: ingest?.risk_clauses?.filter((c: any) => c.severity === 'HIGH').length || 0,
                    medium: ingest?.risk_clauses?.filter((c: any) => c.severity === 'MEDIUM').length || 0,
                    low: ingest?.risk_clauses?.filter((c: any) => c.severity === 'LOW').length || 0,
                    minimal: Math.max(0, 10 - (ingest?.risk_clauses?.length || 0)),
                  }}
                  totalScore={score.risk_score ?? 0}
                />
              )}

              {/* GST Network Graph */}
              {ingest?.gst_reconciliation && (ingest.gst_reconciliation.graph_nodes?.length ?? 0) > 0 && (
                <div>
                  <GSTNetworkGraph
                    nodes={ingest.gst_reconciliation.graph_nodes!}
                    edges={ingest.gst_reconciliation.graph_edges || []}
                    circularPatterns={ingest.gst_reconciliation.circular_patterns || []}
                    height={500}
                  />
                </div>
              )}

              {/* Bank Transaction Timeline */}
              {ingest?.bank_metrics && (
                <BankTransactionTimeline
                  data={[
                    { period: 'Q1', inflow: (ingest.bank_metrics.total_annual_credits || 0) * 0.20, outflow: (ingest.bank_metrics.total_annual_credits || 0) * 0.18, balance: ingest.bank_metrics.avg_monthly_balance || 0, transactions: 45 },
                    { period: 'Q2', inflow: (ingest.bank_metrics.total_annual_credits || 0) * 0.25, outflow: (ingest.bank_metrics.total_annual_credits || 0) * 0.23, balance: (ingest.bank_metrics.avg_monthly_balance || 0) * 1.1, transactions: 52 },
                    { period: 'Q3', inflow: (ingest.bank_metrics.total_annual_credits || 0) * 0.28, outflow: (ingest.bank_metrics.total_annual_credits || 0) * 0.27, balance: (ingest.bank_metrics.avg_monthly_balance || 0) * 1.15, transactions: 48 },
                    { period: 'Q4', inflow: (ingest.bank_metrics.total_annual_credits || 0) * 0.27, outflow: (ingest.bank_metrics.total_annual_credits || 0) * 0.24, balance: (ingest.bank_metrics.avg_monthly_balance || 0) * 1.2, transactions: 55 },
                  ]}
                />
              )}

              {/* Metric Trends */}
              {financialYears.length > 0 && (
                <MetricTrends
                  metrics={[
                    {
                      label: 'Revenue Growth',
                      data: financialYears.map(fy => ({ period: fy.year || '', value: fy.revenue || 0 })),
                      color: '#10B981',
                      trend: 'up',
                      unit: '₹',
                    },
                    {
                      label: 'EBITDA Margin',
                      data: financialYears.map(fy => ({ 
                        period: fy.year || '', 
                        value: fy.revenue && fy.ebitda ? (fy.ebitda / fy.revenue) * 100 : 0 
                      })),
                      color: '#3B82F6',
                      trend: 'stable',
                      unit: '%',
                    },
                    {
                      label: 'Debt-to-Equity',
                      data: financialYears.map(fy => ({ period: fy.year || '', value: fy.debt_equity || 0 })),
                      color: '#F59E0B',
                      trend: 'down',
                    },
                    {
                      label: 'DSCR',
                      data: financialYears.map(fy => ({ period: fy.year || '', value: fy.dscr || 0 })),
                      color: '#8B5CF6',
                      trend: 'up',
                    },
                  ]}
                />
              )}
            </div>
          </TabContent>

          {/* Financial */}
          <TabContent value="financial" className="p-6">
            {financialYears.length > 0 ? (
              <div className="space-y-6">
                <p className="text-text-secondary text-sm font-medium">Revenue, EBITDA & DSCR Trend</p>
                <FinancialTrend years={financialYears} height={300} />
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-border-dark">
                        {['FY', 'Revenue (Cr)', 'EBITDA (Cr)', 'PAT (Cr)', 'DSCR', 'D/E', 'Current Ratio'].map((h) => (
                          <th key={h} className="text-left text-text-muted font-semibold px-4 py-2.5">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {financialYears.map((fy) => (
                        <tr key={fy.year} className="border-b border-border-dark/40 hover:bg-surface2 transition-colors">
                          <td className="px-4 py-3 text-text-primary font-medium">{fy.year}</td>
                          <td className="px-4 py-3 text-text-secondary">{fy.revenue != null ? fy.revenue.toFixed(2) : '—'}</td>
                          <td className="px-4 py-3 text-text-secondary">{fy.ebitda != null ? fy.ebitda.toFixed(2) : '—'}</td>
                          <td className="px-4 py-3 text-text-secondary">{fy.pat != null ? fy.pat.toFixed(2) : '—'}</td>
                          <td className="px-4 py-3 text-text-secondary">{fy.dscr != null ? fy.dscr.toFixed(2) : '—'}</td>
                          <td className="px-4 py-3 text-text-secondary">{fy.debt_equity != null ? fy.debt_equity.toFixed(2) : '—'}</td>
                          <td className="px-4 py-3 text-text-secondary">{fy.current_ratio != null ? fy.current_ratio.toFixed(2) : '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : <p className="text-text-muted text-sm py-8 text-center">No financial data extracted</p>}
          </TabContent>

          {/* GST & Bank */}
          <TabContent value="gst" className="p-6">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {ingest?.gst_reconciliation && (
                <div>
                  <h3 className="text-text-primary font-semibold text-sm mb-3">GST Reconciliation</h3>
                  <div className="space-y-0">
                    {[
                      ['GST Health Score', ingest.gst_reconciliation.gst_health_score?.toFixed(2)],
                      ['ITC Gap %', formatPct(ingest.gst_reconciliation.itc_gap_pct)],
                      ['ITC Claimed (3B)', formatCrore(ingest.gst_reconciliation.itc_claimed_3b)],
                      ['ITC Available (2A)', formatCrore(ingest.gst_reconciliation.itc_available_2a)],
                      ['Filing Regularity', ingest.gst_reconciliation.filing_regularity],
                      ['Circular Trading', String(ingest.gst_reconciliation.circular_trading_flag)],
                      ['ITC Fraud Risk', ingest.gst_reconciliation.gst_itc_fraud_risk],
                    ].map(([label, value]) => (
                      <div key={label} className="flex justify-between items-center py-2.5 border-b border-border-dark/40">
                        <span className="text-text-muted text-xs">{label}</span>
                        <span className="text-text-primary text-xs font-semibold">{value ?? '—'}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {ingest?.bank_metrics && (
                <div>
                  <h3 className="text-text-primary font-semibold text-sm mb-3">Bank Statement Analysis</h3>
                  <div className="space-y-0">
                    {[
                      ['Avg Monthly Balance', formatINR(ingest.bank_metrics.avg_monthly_balance ?? 0)],
                      ['Total Annual Credits', formatINR(ingest.bank_metrics.total_annual_credits ?? 0)],
                      ['Debit/Credit Ratio', ingest.bank_metrics.debit_credit_ratio?.toFixed(2)],
                      ['Bounce Count', String(ingest.bank_metrics.bounce_count)],
                      ['UPI %', formatPct(ingest.bank_metrics.upi_percentage)],
                      ['Cash Deposit %', formatPct(ingest.bank_metrics.cash_deposit_pct)],
                    ].map(([label, value]) => (
                      <div key={label} className="flex justify-between items-center py-2.5 border-b border-border-dark/40">
                        <span className="text-text-muted text-xs">{label}</span>
                        <span className="text-text-primary text-xs font-semibold">{value ?? '—'}</span>
                      </div>
                    ))}
                    {(ingest.bank_metrics.anomalies?.length ?? 0) > 0 && (
                      <div className="pt-3">
                        <p className="text-text-muted text-xs font-medium mb-2">Anomalies</p>
                        {ingest.bank_metrics.anomalies!.map((a, i) => {
                          const text = typeof a === 'string' ? a : `${a.description || a.type || 'Anomaly'} — ₹${((a.amount ?? 0) / 1e5).toFixed(1)}L (${a.severity || ''})`;
                          return (
                            <div key={i} className="flex items-start gap-2 text-xs text-amber-600 mb-1">
                              <span>⚠</span> {text}
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </TabContent>

          {/* Research */}
          <TabContent value="research" className="p-6">
            {research ? (
              <div className="space-y-5">
                {research.synthesis_report && (
                  <div className="bg-surface2 border border-border-dark rounded-xl p-5">
                    <h3 className="text-text-primary font-semibold mb-4 flex items-center gap-2 text-sm">
                      <Globe size={15} className="text-indigo-500" /> External Risk Summary
                    </h3>
                    <div className="grid grid-cols-2 gap-4 text-sm mb-4">
                      <div>
                        <p className="text-text-muted text-xs">Overall External Risk Score</p>
                        <p className="text-text-primary font-bold text-xl mt-0.5">{research.synthesis_report.overall_external_risk_score?.toFixed(1) ?? '—'}</p>
                      </div>
                      <div>
                        <p className="text-text-muted text-xs">Promoter Risk</p>
                        <SeverityBadge severity={research.synthesis_report.promoter_risk_flag} className="mt-1" />
                      </div>
                    </div>
                    {research.synthesis_report.key_red_flags?.length > 0 && (
                      <div className="space-y-1 mb-3">
                        <p className="text-text-muted text-xs font-medium">Key Red Flags</p>
                        {research.synthesis_report.key_red_flags.map((f: string, i: number) => (
                          <div key={i} className="flex items-start gap-2 text-xs text-red-600"><span>●</span> {f}</div>
                        ))}
                      </div>
                    )}
                    {research.synthesis_report.positive_signals?.length > 0 && (
                      <div className="space-y-1">
                        <p className="text-text-muted text-xs font-medium">Positive Signals</p>
                        {research.synthesis_report.positive_signals.map((s: string, i: number) => (
                          <div key={i} className="flex items-start gap-2 text-xs text-green-600"><span>✓</span> {s}</div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
                {research.news_report?.articles?.length > 0 && (
                  <div>
                    <h4 className="text-text-secondary text-sm font-semibold mb-3">Recent News</h4>
                    <div className="space-y-2">
                      {research.news_report.articles.slice(0, 6).map((a: any, i: number) => (
                        <div key={i} className="flex items-start gap-3 p-3 bg-surface2 rounded-lg">
                          <SeverityBadge severity={a.risk_type === 'HIGH_RISK' ? 'HIGH' : a.sentiment === 'negative' ? 'MEDIUM' : 'LOW'} className="flex-shrink-0 mt-0.5" />
                          <div>
                            <p className="text-text-primary text-xs font-medium leading-relaxed">{a.title}</p>
                            <p className="text-text-muted text-xs mt-0.5">{a.source_domain} · {formatDate(a.publication_date)}</p>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {research.rbi_check && (
                  <div className={`p-4 rounded-xl border text-sm ${research.rbi_check.any_match ? 'bg-red-500/10 border-red-500/20' : 'bg-green-500/10 border-green-500/20'}`}>
                    <p className={research.rbi_check.any_match ? 'text-red-400 font-semibold' : 'text-green-400 font-semibold'}>
                      RBI Defaulter List: {research.rbi_check.any_match ? '⚠ MATCH FOUND' : '✓ No match'}
                    </p>
                    {research.rbi_check.matches?.length > 0 && research.rbi_check.matches.map((m: string, i: number) => (
                      <p key={i} className="text-text-secondary text-xs mt-1">• {m}</p>
                    ))}
                  </div>
                )}
              </div>
            ) : <p className="text-text-muted text-sm py-8 text-center">No research data available</p>}
          </TabContent>

          {/* Five C's */}
          <TabContent value="fivecs" className="p-6">
            {five_cs ? (
              <div className="space-y-3 max-w-3xl">
                <FiveCSection title="Character — Creditworthiness & Integrity" content={five_cs.character} />
                <FiveCSection title="Capacity — Repayment Ability" content={five_cs.capacity} />
                <FiveCSection title="Capital — Financial Strength" content={five_cs.capital} />
                <FiveCSection title="Collateral — Security Coverage" content={five_cs.collateral} />
                <FiveCSection title="Conditions — Market & Economic Context" content={five_cs.conditions} />
              </div>
            ) : <p className="text-text-muted text-sm py-8 text-center">Five C's report not yet generated</p>}
          </TabContent>

          {/* SHAP */}
          <TabContent value="shap" className="p-6">
            {allSHAP.length > 0 ? (
              <div className="space-y-4 max-w-3xl">
                <p className="text-text-muted text-xs">SHAP values show each feature's contribution to the predicted default probability. Red bars increase risk; green bars reduce risk.</p>
                <SHAPWaterfall factors={allSHAP} height={380} />
              </div>
            ) : <p className="text-text-muted text-sm py-8 text-center">No SHAP explanations available</p>}
          </TabContent>
        </Tabs>
      </Card>

      {/* Optional post-pipeline qualitative */}
      {!qualitative_submitted && (
        <div className="bg-surface border border-border-dark rounded-2xl shadow-sm overflow-hidden">
          <button
            type="button"
            onClick={() => setQualOpen(!qualOpen)}
            className="w-full px-6 py-4 flex items-center justify-between hover:bg-surface2 transition-colors"
          >
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-xl bg-purple-500/10 flex items-center justify-center">
                <ClipboardList size={18} className="text-purple-400" />
              </div>
              <div className="text-left">
                <p className="font-semibold text-text-primary text-sm">Add Qualitative Adjustment</p>
                <p className="text-text-muted text-xs">Apply credit-officer observations to adjust risk score</p>
              </div>
            </div>
            <div className={`transition-transform duration-200 ${qualOpen ? 'rotate-180' : ''}`}>
              <ChevronDown size={18} className="text-text-muted" />
            </div>
          </button>
          <AnimatePresence>
            {qualOpen && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.3 }}
                className="overflow-hidden"
              >
                <div className="px-6 pb-6 border-t border-border-dark space-y-4 pt-4">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <Input label="Capacity Utilization %" type="number" {...qualForm.register('capacity_utilization_pct')} />
                    <Select label="Facility Condition" options={[
                      { value: 'EXCELLENT', label: 'Excellent' }, { value: 'GOOD', label: 'Good' },
                      { value: 'FAIR', label: 'Fair' }, { value: 'POOR', label: 'Poor' },
                      { value: 'NOT_VISITED', label: 'Not Visited' },
                    ]} {...qualForm.register('facility_condition')} />
                    <Select label="Management Transparency" options={[
                      { value: 'FULLY_TRANSPARENT', label: 'Fully Transparent' },
                      { value: 'MOSTLY_TRANSPARENT', label: 'Mostly Transparent' },
                      { value: 'EVASIVE', label: 'Evasive' }, { value: 'UNCOOPERATIVE', label: 'Uncooperative' },
                    ]} {...qualForm.register('management_transparency')} />
                    <Input label="Group Company Exposure" {...qualForm.register('group_company_exposure')} />
                  </div>
                  <Textarea label="Site Visit Observations *" rows={2} {...qualForm.register('site_visit_observations')} error={qualForm.formState.errors.site_visit_observations?.message} />
                  <Textarea label="Management Interview Notes *" rows={2} {...qualForm.register('management_interview_notes')} error={qualForm.formState.errors.management_interview_notes?.message} />
                  <Button onClick={handleQualSubmit}>Apply Qualitative Assessment</Button>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}
      {qualitative_submitted && (
        <div className="bg-green-500/10 border border-green-500/20 rounded-xl p-4 flex items-center gap-3 text-sm text-green-400">
          <CheckCircle2 size={18} /> Qualitative assessment applied
        </div>
      )}
    </motion.div>
  )
}

// ─── Main page ───────────────────────────────────────────────────────────────

export default function AppraisalPage() {
  const { startSession, recordJob, job_id, results, reset } = useSession()
  // Always start fresh on this page
  const [phase, setPhase] = useState<'input' | 'analysis' | 'results'>('input')
  const [companyNameDisplay, setCompanyNameDisplay] = useState('')
  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  const resultsRef = useRef<HTMLDivElement>(null)
  const analysisRef = useRef<HTMLDivElement>(null)

  // Clear any stale previous session when landing on this page
  useEffect(() => {
    reset()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const handleLaunch = async (
    form: CompanyForm, 
    files: {
      annualReport: File | null
      bankStatement: File | null
      gstFiles: File[]
      itrFile: File | null
      mcaFile: File | null
    }, 
    quals: QualForm | null
  ) => {
    const fd = new FormData()
    fd.append('company_name', form.company_name)
    fd.append('loan_amount_requested', String(form.loan_amount_requested))
    fd.append('loan_tenure_months', String(form.tenure_months))

    // Append files with correct field names
    if (files.annualReport) fd.append('pdf_file', files.annualReport)
    if (files.bankStatement) fd.append('bank_file', files.bankStatement)
    files.gstFiles.forEach((f) => fd.append('gst_files', f))
    if (files.itrFile) fd.append('itr_file', files.itrFile)
    if (files.mcaFile) fd.append('mca_file', files.mcaFile)

    const job = await runFullPipeline(fd)

    startSession(job.job_id, {
      company_name: form.company_name,
      loan_amount_requested: form.loan_amount_requested,
      tenure_months: form.tenure_months,
      session_id: job.job_id,
    })
    recordJob(job.job_id)
    setCompanyNameDisplay(form.company_name)
    setActiveJobId(job.job_id)
    setPhase('analysis')

    setTimeout(() => analysisRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 150)
    toast.success('Analysis pipeline started!')
  }

  const handleComplete = () => {
    setPhase('results')
    setTimeout(() => resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 150)
  }

  const handleFailed = () => {
    toast.error('Pipeline failed — please try again')
    setPhase('input')
  }

  const handleNewAppraisal = () => {
    setPhase('input')
    setActiveJobId(null)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  return (
    <div className="max-w-4xl mx-auto pb-16">
      {/* Title */}
      <div className="mb-6">
        <h1 className="text-2xl font-extrabold text-text-primary">
          {phase === 'input' ? 'New Credit Appraisal' : phase === 'analysis' ? 'Running Analysis' : 'Credit Assessment Results'}
        </h1>
        <p className="text-text-muted text-sm mt-0.5">
          {phase === 'input' ? 'Upload documents and launch the AI credit pipeline' : phase === 'analysis' ? 'AI models are processing the documents' : 'Full credit appraisal memo ready'}
        </p>
      </div>

      <PhaseTrack phase={phase} />

      <AnimatePresence mode="wait">
        {phase === 'input' && (
          <motion.div key="input" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0, y: -10 }}>
            <InputSection onLaunch={handleLaunch} />
          </motion.div>
        )}
      </AnimatePresence>

      {phase !== 'input' && (
        <div ref={analysisRef}>
          <AnalysisSection
            jobId={activeJobId ?? ''}
            companyName={companyNameDisplay}
            onComplete={handleComplete}
            onFailed={handleFailed}
          />
        </div>
      )}

      {phase === 'results' && (
        <div ref={resultsRef} className="mt-8">
          <ResultsSection />
          <div className="mt-6 pt-6 border-t border-border-dark flex justify-center">
            <button
              onClick={handleNewAppraisal}
              className="text-sm text-text-muted hover:text-primary flex items-center gap-1.5 transition-colors"
            >
              <Rocket size={14} /> Start another appraisal
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
