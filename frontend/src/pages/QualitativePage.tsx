import React, { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useForm, useWatch } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import toast from 'react-hot-toast'
import { ClipboardList, TrendingUp, TrendingDown, AlertTriangle } from 'lucide-react'
import Input, { Textarea, Select } from '../components/ui/Input'
import Button from '../components/ui/Button'
import Card, { CardHeader, CardTitle, CardBody } from '../components/ui/Card'
import { submitQualitative } from '../api/scoring'
import { useSession } from '../hooks/useSession'
import CompanyHeader from '../components/shared/CompanyHeader'
import {
  QUALITATIVE_CAPACITY_BRACKETS,
  FACILITY_CONDITION_ADJUSTMENTS,
} from '../utils/constants'
import type { QualitativeFormData } from '../store/types'

const schema = z.object({
  site_visit_observations: z.string().min(10, 'At least 10 characters required'),
  capacity_utilization_pct: z.coerce.number().min(0).max(100),
  facility_condition: z.enum(['EXCELLENT', 'GOOD', 'FAIR', 'POOR', 'NOT_VISITED']),
  management_interview_notes: z.string().min(10, 'At least 10 characters required'),
  management_transparency: z.enum([
    'FULLY_TRANSPARENT', 'MOSTLY_TRANSPARENT', 'EVASIVE', 'UNCOOPERATIVE',
  ]),
  group_company_exposure: z.string().optional(),
  inventory_vs_records: z.string().optional(),
  employee_count_vs_records: z.string().optional(),
  other_key_observations: z.string().optional(),
})

type FormData = z.infer<typeof schema>

const transparencyAdj: Record<string, number> = {
  FULLY_TRANSPARENT: 0.5,
  MOSTLY_TRANSPARENT: 0.0,
  EVASIVE: -1.0,
  UNCOOPERATIVE: -2.0,
}

function estimateAdjustment(values: Partial<FormData>): number {
  let total = 0

  // Capacity utilization
  const cap = values.capacity_utilization_pct ?? 0
  for (const bracket of QUALITATIVE_CAPACITY_BRACKETS) {
    if (cap < bracket.threshold) {
      total += bracket.adjustment
      break
    }
  }

  // Facility condition
  if (values.facility_condition) {
    total += FACILITY_CONDITION_ADJUSTMENTS[values.facility_condition] ?? 0
  }

  // Management transparency
  if (values.management_transparency) {
    total += transparencyAdj[values.management_transparency] ?? 0
  }

  return Math.max(-5, Math.min(2, total))
}

export default function QualitativePage() {
  const navigate = useNavigate()
  const { session_id, company, results, recordQualitative, qualitative_submitted } = useSession()

  const form = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: {
      capacity_utilization_pct: 70,
      facility_condition: 'GOOD',
      management_transparency: 'MOSTLY_TRANSPARENT',
    },
  })

  const watchedValues = useWatch({ control: form.control })
  const estimated = estimateAdjustment(watchedValues as Partial<FormData>)
  const baseScore = results?.score?.risk_score ?? null

  const onSubmit = async (data: FormData) => {
    if (!session_id) {
      toast.error('No active session — start a new appraisal first')
      return
    }
    try {
      const payload: QualitativeFormData = { ...data, session_id }
      await submitQualitative(payload)
      recordQualitative(payload)
      toast.success('Qualitative assessment saved!')
      navigate('/results')
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Failed to submit')
    }
  }

  if (!session_id) {
    return (
      <div className="max-w-2xl mx-auto mt-12 text-center">
        <AlertTriangle size={40} className="text-gold mx-auto mb-3" />
        <h2 className="text-text-primary font-semibold text-lg mb-2">No active session</h2>
        <p className="text-text-secondary text-sm mb-5">
          Complete the pipeline analysis first, then return here for qualitative assessment.
        </p>
        <Button onClick={() => navigate('/new')}>Start New Appraisal</Button>
      </div>
    )
  }

  return (
    <div className="max-w-5xl mx-auto space-y-5">
      {company && (
        <CompanyHeader company={company} subtitle="Credit Officer Qualitative Assessment" />
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* Form */}
        <div className="lg:col-span-2">
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-5">
            {/* Site Visit */}
            <Card>
              <CardHeader>
                <CardTitle
                  icon={<ClipboardList size={16} className="text-accent" />}
                >
                  Site Visit Observations
                </CardTitle>
              </CardHeader>
              <CardBody className="space-y-4">
                <Textarea
                  label="Site Visit Observations *"
                  rows={4}
                  placeholder="Describe the physical state of the facility, operations observed, etc."
                  {...form.register('site_visit_observations')}
                  error={form.formState.errors.site_visit_observations?.message}
                />
                <div className="grid grid-cols-2 gap-4">
                  <Input
                    label="Capacity Utilization (%)"
                    type="number"
                    {...form.register('capacity_utilization_pct')}
                    error={form.formState.errors.capacity_utilization_pct?.message}
                  />
                  <Select
                    label="Facility Condition"
                    options={[
                      { value: 'EXCELLENT', label: 'Excellent' },
                      { value: 'GOOD', label: 'Good' },
                      { value: 'FAIR', label: 'Fair' },
                      { value: 'POOR', label: 'Poor' },
                      { value: 'NOT_VISITED', label: 'Not Visited' },
                    ]}
                    {...form.register('facility_condition')}
                    error={form.formState.errors.facility_condition?.message}
                  />
                </div>
                <Textarea
                  label="Inventory vs Records"
                  rows={2}
                  placeholder="Physical inventory vs documented levels…"
                  {...form.register('inventory_vs_records')}
                />
                <Textarea
                  label="Employee Count vs Records"
                  rows={2}
                  placeholder="Actual headcount compared to HR records…"
                  {...form.register('employee_count_vs_records')}
                />
              </CardBody>
            </Card>

            {/* Management Interview */}
            <Card>
              <CardHeader>
                <CardTitle>Management Interview</CardTitle>
              </CardHeader>
              <CardBody className="space-y-4">
                <Textarea
                  label="Management Interview Notes *"
                  rows={4}
                  placeholder="Key observations from management meeting — future plans, concerns, responses to questions…"
                  {...form.register('management_interview_notes')}
                  error={form.formState.errors.management_interview_notes?.message}
                />
                <Select
                  label="Management Transparency"
                  options={[
                    { value: 'FULLY_TRANSPARENT', label: 'Fully Transparent' },
                    { value: 'MOSTLY_TRANSPARENT', label: 'Mostly Transparent' },
                    { value: 'EVASIVE', label: 'Evasive' },
                    { value: 'UNCOOPERATIVE', label: 'Uncooperative' },
                  ]}
                  {...form.register('management_transparency')}
                  error={form.formState.errors.management_transparency?.message}
                />
                <Textarea
                  label="Group Company Exposure"
                  rows={2}
                  placeholder="Cross-holdings, guarantees, or related-party transactions observed…"
                  {...form.register('group_company_exposure')}
                />
              </CardBody>
            </Card>

            {/* Other */}
            <Card>
              <CardHeader>
                <CardTitle>Other Observations</CardTitle>
              </CardHeader>
              <CardBody>
                <Textarea
                  label="Other Key Observations"
                  rows={4}
                  placeholder="Any additional information relevant to the credit decision…"
                  {...form.register('other_key_observations')}
                />
              </CardBody>
            </Card>

            <div className="flex justify-end">
              <Button
                type="submit"
                loading={form.formState.isSubmitting}
                disabled={qualitative_submitted}
              >
                {qualitative_submitted ? 'Already Submitted' : 'Submit Assessment'}
              </Button>
            </div>
          </form>
        </div>

        {/* Live preview panel */}
        <div className="space-y-4">
          <Card elevated>
            <CardHeader>
              <CardTitle>Live Adjustment Preview</CardTitle>
            </CardHeader>
            <CardBody className="space-y-4">
              <div className="text-center py-3">
                <p className="text-text-muted text-xs mb-1">Estimated Adjustment</p>
                <p className={[
                  'text-3xl font-bold',
                  estimated > 0 ? 'text-success' : estimated < 0 ? 'text-danger' : 'text-text-secondary',
                ].join(' ')}>
                  {estimated >= 0 ? '+' : ''}{estimated.toFixed(2)}
                </p>
                <p className="text-text-muted text-xs mt-0.5">points (max ±5)</p>
              </div>

              {baseScore !== null && (
                <div className="bg-surface2 rounded-xl p-3 text-center">
                  <p className="text-text-muted text-xs mb-1">Adjusted Risk Score</p>
                  <p className="text-text-primary text-2xl font-bold">
                    {Math.max(0, Math.min(10, baseScore + estimated)).toFixed(1)}
                  </p>
                  <p className="text-text-muted text-xs">
                    Base: {baseScore.toFixed(1)} {estimated >= 0 ? '↑' : '↓'}
                  </p>
                </div>
              )}

              <div className="space-y-2">
                <p className="text-text-muted text-xs font-medium">Component Breakdown</p>
                {[
                  {
                    label: 'Capacity Utilization',
                    value: (() => {
                      const cap = watchedValues.capacity_utilization_pct ?? 0
                      for (const b of QUALITATIVE_CAPACITY_BRACKETS) if (cap < b.threshold) return b.adjustment
                      return 0
                    })(),
                  },
                  {
                    label: 'Facility Condition',
                    value: FACILITY_CONDITION_ADJUSTMENTS[watchedValues.facility_condition ?? ''] ?? 0,
                  },
                  {
                    label: 'Management Transparency',
                    value: transparencyAdj[watchedValues.management_transparency ?? ''] ?? 0,
                  },
                ].map(({ label, value }) => (
                  <div key={label} className="flex items-center justify-between text-xs">
                    <span className="text-text-secondary">{label}</span>
                    <span className={value > 0 ? 'text-success font-medium' : value < 0 ? 'text-danger font-medium' : 'text-text-muted'}>
                      {value >= 0 ? '+' : ''}{value.toFixed(1)}
                    </span>
                  </div>
                ))}
                <div className="text-text-muted text-[10px] pt-1 border-t border-border-dark">
                  * Text-field adjustments applied server-side via NLP
                </div>
              </div>

              <div className={[
                'flex items-start gap-2 p-3 rounded-lg text-xs',
                estimated >= 0 ? 'bg-success/8 text-success' : 'bg-danger/8 text-danger',
              ].join(' ')}>
                {estimated >= 0 ? <TrendingUp size={13} className="flex-shrink-0 mt-0.5" /> : <TrendingDown size={13} className="flex-shrink-0 mt-0.5" />}
                <span>{estimated >= 0 ? 'Qualitative factors are adding positive weight.' : 'Qualitative factors are reducing the risk score.'}</span>
              </div>
            </CardBody>
          </Card>
        </div>
      </div>
    </div>
  )
}
