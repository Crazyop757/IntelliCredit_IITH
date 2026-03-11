import React, { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { AlertCircle } from 'lucide-react'
import { getCompany } from '../api/companies'
import Card, { CardBody } from '../components/ui/Card'
import CompanyHeader from '../components/shared/CompanyHeader'
import DecisionBanner from '../components/shared/DecisionBanner'
import RiskGauge from '../components/charts/RiskGauge'
import FinancialTrend from '../components/charts/FinancialTrend'
import EWSRadar from '../components/charts/EWSRadar'
import SHAPWaterfall from '../components/charts/SHAPWaterfall'
import RiskClauseList from '../components/shared/RiskClauseList'
import { Tabs, TabList, TabTrigger, TabContent } from '../components/ui/Tabs'
import { RiskBandBadge, SeverityBadge } from '../components/ui/Badge'
import Button from '../components/ui/Button'
import Skeleton, { CardSkeleton } from '../components/ui/Skeleton'
import { formatDate, formatINR, formatPct } from '../utils/formatters'
import type { FinancialYear, SHAPFactor, CompanyDetailData } from '../store/types'

export default function CompanyDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [tab, setTab] = useState('overview')

  const { data: pipeline, isLoading, error } = useQuery({
    queryKey: ['company', id],
    queryFn: (): Promise<CompanyDetailData> => getCompany(id!),
    enabled: !!id,
  })

  if (error) {
    return (
      <div className="max-w-xl mx-auto mt-12 text-center">
        <AlertCircle size={36} className="text-danger mx-auto mb-3" />
        <h2 className="text-text-primary font-semibold mb-2">Company not found</h2>
        <p className="text-text-secondary text-sm mb-5">
          The company ID "{id}" does not exist or has no data.
        </p>
        <Button onClick={() => navigate('/companies')}>Back to Companies</Button>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="max-w-5xl mx-auto space-y-5">
        <Skeleton className="h-24 rounded-xl" />
        <div className="grid grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => <CardSkeleton key={i} />)}
        </div>
        <Skeleton className="h-64 rounded-xl" />
      </div>
    )
  }

  if (!pipeline) return null

  const { company, score, ews, ingest, research, five_cs } = pipeline
  const financialData = ingest?.extracted_financials ?? {}

  // Fall back to delta-lake silver records when there is no ingest result.
  // Silver records use the same KPI field names as FinancialYear.
  const deltaYears: FinancialYear[] = (pipeline.records ?? []).map((r) => ({
    revenue: (r.revenue as number | null) ?? null,
    ebitda: (r.ebitda as number | null) ?? null,
    pat: (r.pat as number | null) ?? null,
    ebitda_margin: (r.ebitda_margin as number | null) ?? null,
    pat_margin: (r.pat_margin as number | null) ?? null,
    debt_equity: (r.debt_equity as number | null) ?? null,
    current_ratio: (r.current_ratio as number | null) ?? null,
    dscr: (r.dscr as number | null) ?? null,
    revenue_growth: (r.revenue_growth as number | null) ?? null,
    total_debt: (r.total_debt as number | null) ?? null,
    net_worth: (r.net_worth as number | null) ?? null,
    year: `FY${r.fiscal_year ?? '?'}`,
  })).sort((a, b) => (a.year ?? '').localeCompare(b.year ?? ''))

  const financialYears: FinancialYear[] = Object.keys(financialData).length > 0
    ? Object.entries(financialData)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([yr, fy]) => ({ ...fy, year: yr }))
    : deltaYears

  const allSHAP: SHAPFactor[] = [
    ...(score?.shap_explanations?.top_risk_factors ?? []),
    ...(score?.shap_explanations?.top_positive_factors ?? []),
  ]

  const riskClauses = ingest?.risk_clauses ?? []

  return (
    <div className="max-w-5xl mx-auto space-y-5">
      {/* Show full company header from pipeline result, or a minimal one from delta data */}
      {company ? (
        <CompanyHeader company={company} subtitle={`CIN: ${company.cin ?? ''}`}>
          <Button size="sm" variant="ghost" onClick={() => navigate('/companies')}>
            ← Back
          </Button>
        </CompanyHeader>
      ) : (
        <CompanyHeader
          company={{ company_name: pipeline.latest?.company_name ?? pipeline.company_id, cin: '', loan_amount_requested: 0, tenure_months: 0 }}
          subtitle={`ID: ${pipeline.company_id}`}
        >
          <Button size="sm" variant="ghost" onClick={() => navigate('/companies')}>
            ← Back
          </Button>
        </CompanyHeader>
      )}

      {score && <DecisionBanner score={score} />}

      {score && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { label: 'Risk Score', value: `${score.risk_score.toFixed(1)}/10` },
            { label: 'Risk Band', value: <RiskBandBadge band={score.risk_band} /> },
            { label: 'Default Probability', value: `${((score.default_probability ?? 0) * 100).toFixed(1)}%` },
            { label: 'EWS Score', value: ews?.ews_score?.toFixed(2) ?? '—' },
          ].map(({ label, value }) => (
            <div key={label} className="bg-surface2 rounded-xl p-4 text-center">
              <p className="text-text-muted text-xs mb-1">{label}</p>
              <p className="text-text-primary text-lg font-bold">{value}</p>
            </div>
          ))}
        </div>
      )}

      <Card>
        <Tabs value={tab} onChange={setTab}>
          <TabList className="px-2 pt-2">
            <TabTrigger value="overview">Overview</TabTrigger>
            {financialYears.length > 0 && <TabTrigger value="financial">Financial</TabTrigger>}
            {research && <TabTrigger value="research">Research</TabTrigger>}
            {allSHAP.length > 0 && <TabTrigger value="shap">SHAP</TabTrigger>}
          </TabList>

          <TabContent value="overview" className="p-6">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {score && (
                <div className="flex flex-col items-center">
                  <p className="text-text-secondary text-sm font-medium mb-3">Risk Score</p>
                  <RiskGauge score={score.risk_score} size={200} />
                </div>
              )}
              {ews && (
                <div>
                  <p className="text-text-secondary text-sm font-medium mb-3">Early Warning</p>
                  <EWSRadar flags={ews} />
                </div>
              )}
              {riskClauses.length > 0 && (
                <div className="lg:col-span-2">
                  <RiskClauseList clauses={riskClauses} />
                </div>
              )}
              {!score && !ews && riskClauses.length === 0 && (
                <div className="lg:col-span-2 py-10 text-center">
                  <p className="text-text-muted text-sm">No scoring data available for this company yet.</p>
                  <Button className="mt-4" onClick={() => navigate('/new')}>Run New Appraisal</Button>
                </div>
              )}
            </div>
          </TabContent>

          {financialYears.length > 0 && (
            <TabContent value="financial" className="p-6">
              <FinancialTrend years={financialYears} height={280} />
              <div className="mt-5 overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-border-dark">
                      {['FY', 'Revenue (Cr)', 'EBITDA (Cr)', 'PAT (Cr)', 'DSCR'].map((h) => (
                        <th key={h} className="text-left text-text-muted font-medium px-4 py-2.5">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {financialYears.map((fy) => (
                      <tr key={fy.year} className="border-b border-border-dark/40">
                        <td className="px-4 py-3 text-text-primary font-medium">{fy.year}</td>
                        <td className="px-4 py-3 text-text-secondary">{fy.revenue?.toFixed(2) ?? '—'}</td>
                        <td className="px-4 py-3 text-text-secondary">{fy.ebitda?.toFixed(2) ?? '—'}</td>
                        <td className="px-4 py-3 text-text-secondary">{fy.pat?.toFixed(2) ?? '—'}</td>
                        <td className="px-4 py-3 text-text-secondary">{fy.dscr?.toFixed(2) ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </TabContent>
          )}

          {research && (
            <TabContent value="research" className="p-6 space-y-4">
              {research.synthesis_report && (
                <div className="p-4 bg-surface2/60 border border-border-dark rounded-xl text-sm">
                  <p className="text-text-secondary font-medium mb-1">External Risk Score</p>
                  <p className="text-text-primary font-bold text-2xl mb-3">
                    {research.synthesis_report.overall_external_risk_score?.toFixed(1) ?? '—'}
                  </p>
                  {research.synthesis_report.key_red_flags?.map((f, i) => (
                    <div key={i} className="flex gap-2 text-xs text-danger mt-1">
                      <span className="flex-shrink-0">●</span> {f}
                    </div>
                  ))}
                  {research.synthesis_report.positive_signals?.map((s, i) => (
                    <div key={i} className="flex gap-2 text-xs text-success mt-1">
                      <span className="flex-shrink-0">✓</span> {s}
                    </div>
                  ))}
                </div>
              )}
              {research.news_report?.articles?.slice(0, 4).map((a, i) => (
                <div key={i} className="flex items-start gap-3 p-3 bg-surface2/40 rounded-lg">
                  <SeverityBadge
                    severity={a.risk_type === 'HIGH_RISK' ? 'HIGH' : a.sentiment === 'negative' ? 'MEDIUM' : 'LOW'}
                    className="flex-shrink-0"
                  />
                  <div>
                    <p className="text-text-primary text-xs font-medium">{a.title}</p>
                    <p className="text-text-muted text-xs mt-0.5">{a.source_domain} · {formatDate(a.publication_date)}</p>
                  </div>
                </div>
              ))}
            </TabContent>
          )}

          {allSHAP.length > 0 && (
            <TabContent value="shap" className="p-6">
              <SHAPWaterfall factors={allSHAP} height={340} />
            </TabContent>
          )}
        </Tabs>
      </Card>
    </div>
  )
}
