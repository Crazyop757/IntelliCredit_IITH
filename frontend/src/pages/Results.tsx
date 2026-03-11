import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  Download, AlertTriangle, BarChart3, FileText,
  Globe, Building2, Shield, DollarSign, Briefcase,
  ChevronDown, ChevronUp
} from 'lucide-react'
import { useSession } from '../hooks/useSession'
import { useDownload } from '../hooks/useDownload'
import { Tabs, TabList, TabTrigger, TabContent } from '../components/ui/Tabs'
import Card from '../components/ui/Card'
import DecisionBanner from '../components/shared/DecisionBanner'
import CompanyHeader from '../components/shared/CompanyHeader'
import RiskGauge from '../components/charts/RiskGauge'
import SHAPWaterfall from '../components/charts/SHAPWaterfall'
import FinancialTrend from '../components/charts/FinancialTrend'
import EWSRadar from '../components/charts/EWSRadar'
import RiskClauseList from '../components/shared/RiskClauseList'
import DataQualityPanel from '../components/shared/DataQualityPanel'
import { RiskBandBadge, SeverityBadge } from '../components/ui/Badge'
import Button from '../components/ui/Button'
import { formatINR, formatCrore, formatPct, formatDate } from '../utils/formatters'
import type { FinancialYear, SHAPFactor } from '../store/types'
import { downloadFile } from '../api/client'

function MetricCard({ label, value, sub }: { label: string; value: React.ReactNode; sub?: string }) {
  return (
    <div className="bg-surface2 rounded-xl p-4 text-center">
      <p className="text-text-muted text-xs mb-1">{label}</p>
      <p className="text-text-primary text-xl font-bold">{value}</p>
      {sub && <p className="text-text-muted text-xs mt-0.5">{sub}</p>}
    </div>
  )
}

function FiveCSection({ title, content }: { title: string; content?: string }) {
  const [open, setOpen] = useState(true)
  if (!content) return null
  return (
    <div className="border border-border-dark rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-5 py-3.5 bg-surface2/60 hover:bg-surface2 transition-colors text-left"
      >
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

export default function Results() {
  const navigate = useNavigate()
  const { results, company } = useSession()
  const { download: downloadCAM, loading: camLoading } = useDownload()
  const [tab, setTab] = useState('overview')

  if (!results) {
    return (
      <div className="max-w-2xl mx-auto mt-12 text-center">
        <AlertTriangle size={40} className="text-gold mx-auto mb-3" />
        <h2 className="text-text-primary font-semibold text-lg mb-2">No results available</h2>
        <p className="text-text-secondary text-sm mb-5">
          Complete the analysis pipeline to view credit results.
        </p>
        <Button onClick={() => navigate('/new')}>Start New Appraisal</Button>
      </div>
    )
  }

  const { score, ews, ingest, research, five_cs, cam_download_url, stage_results, data_quality_report } = results
  const financialData = ingest?.extracted_financials ?? {}
  const financialYears: FinancialYear[] = Object.entries(financialData)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([yr, fy]) => ({ ...fy, year: yr }))

  const allSHAP: SHAPFactor[] = [
    ...(score?.shap_explanations?.top_risk_factors ?? []),
    ...(score?.shap_explanations?.top_positive_factors ?? []),
  ]

  const handleDownload = async () => {
    if (cam_download_url) {
      try {
        await downloadFile(cam_download_url)
      } catch {
        // fallback to generate
        if (company) {
          await downloadCAM({
            company_id: results.session_id,
            company_name: company.company_name,
            cin: company.cin,
            five_cs_text: five_cs,
            scoring_result: score,
            research_report: research,
          })
        }
      }
    } else if (company) {
      await downloadCAM({
        company_id: results.session_id,
        company_name: company.company_name,
        cin: company.cin,
        five_cs_text: five_cs,
        scoring_result: score,
        research_report: research,
      })
    }
  }

  return (
    <div className="max-w-6xl mx-auto space-y-5">
      {/* Header */}
      {company && (
        <CompanyHeader company={company} subtitle="Credit Appraisal Results">
          <Button
            size="sm"
            variant="outline"
            icon={<Download size={14} />}
            loading={camLoading}
            onClick={handleDownload}
          >
            Download CAM
          </Button>
          <Button size="sm" variant="ghost" onClick={() => navigate('/qualitative')}>
            Qualitative
          </Button>
        </CompanyHeader>
      )}

      {/* Decision Banner */}
      {score && <DecisionBanner score={score} />}

      {/* Metric row */}
      {score && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <MetricCard
            label="Risk Score"
            value={<span className="text-2xl">{score.risk_score.toFixed(1)}/10</span>}
          />
          <MetricCard label="Risk Band" value={<RiskBandBadge band={score.risk_band} />} />
          <MetricCard
            label="Default Probability"
            value={`${((score.default_probability ?? 0) * 100).toFixed(1)}%`}
          />
          <MetricCard
            label="EWS Level"
            value={ews?.ews_score != null ? ews.ews_score.toFixed(2) : '—'}
            sub={ews?.sma_classification}
          />
        </div>
      )}

      {/* Tabs */}
      <Card>
        <Tabs value={tab} onChange={setTab}>
          <TabList className="px-2 pt-2">
            <TabTrigger value="overview" icon={<BarChart3 size={14} />}>Overview</TabTrigger>
            <TabTrigger value="financial" icon={<DollarSign size={14} />}>Financial</TabTrigger>
            <TabTrigger value="gst" icon={<Building2 size={14} />}>GST & Bank</TabTrigger>
            <TabTrigger value="research" icon={<Globe size={14} />}>Research</TabTrigger>
            <TabTrigger value="fivecs" icon={<Briefcase size={14} />}>Five C's</TabTrigger>
            <TabTrigger value="shap" icon={<Shield size={14} />}>SHAP</TabTrigger>
          </TabList>

          {/* Overview */}
          <TabContent value="overview" className="p-6">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {score && (
                <div className="flex flex-col items-center">
                  <p className="text-text-secondary text-sm font-medium mb-3">Risk Score Gauge</p>
                  <RiskGauge score={score.risk_score} size={220} />
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

          {/* Financial */}
          <TabContent value="financial" className="p-6">
            {financialYears.length > 0 ? (
              <div className="space-y-6">
                <div>
                  <p className="text-text-secondary text-sm font-medium mb-3">Revenue, EBITDA & DSCR Trend</p>
                  <FinancialTrend years={financialYears} height={300} />
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-border-dark">
                        {['FY', 'Revenue (Cr)', 'EBITDA (Cr)', 'PAT (Cr)', 'DSCR', 'D/E', 'Current Ratio'].map((h) => (
                          <th key={h} className="text-left text-text-muted font-medium px-4 py-2.5">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {financialYears.map((fy) => (
                        <tr key={fy.year} className="border-b border-border-dark/40">
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
            ) : (
              <p className="text-text-muted text-sm py-8 text-center">No financial data extracted</p>
            )}
          </TabContent>

          {/* GST & Bank */}
          <TabContent value="gst" className="p-6">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              {/* GST */}
              {ingest?.gst_reconciliation && (
                <div className="space-y-3">
                  <h3 className="text-text-primary font-semibold text-sm">GST Reconciliation</h3>
                  {[
                    { label: 'GST Health Score', value: ingest.gst_reconciliation.gst_health_score?.toFixed(2) },
                    { label: 'ITC Gap %', value: formatPct(ingest.gst_reconciliation.itc_gap_pct) },
                    { label: 'ITC Claimed (3B)', value: formatCrore(ingest.gst_reconciliation.itc_claimed_3b) },
                    { label: 'ITC Available (2A)', value: formatCrore(ingest.gst_reconciliation.itc_available_2a) },
                    { label: 'Filing Regularity', value: ingest.gst_reconciliation.filing_regularity },
                    { label: 'Circular Trading', value: ingest.gst_reconciliation.circular_trading_flag },
                    { label: 'ITC Fraud Risk', value: ingest.gst_reconciliation.gst_itc_fraud_risk },
                  ].map(({ label, value }) => (
                    <div key={label} className="flex justify-between items-center py-2 border-b border-border-dark/40">
                      <span className="text-text-muted text-xs">{label}</span>
                      <span className="text-text-primary text-xs font-medium">{value ?? '—'}</span>
                    </div>
                  ))}
                </div>
              )}
              {/* Bank */}
              {ingest?.bank_metrics && (
                <div className="space-y-3">
                  <h3 className="text-text-primary font-semibold text-sm">Bank Statement Analysis</h3>
                  {[
                    { label: 'Avg Monthly Balance', value: formatINR(ingest.bank_metrics.avg_monthly_balance ?? 0) },
                    { label: 'Total Annual Credits', value: formatINR(ingest.bank_metrics.total_annual_credits ?? 0) },
                    { label: 'Debit/Credit Ratio', value: ingest.bank_metrics.debit_credit_ratio?.toFixed(2) },
                    { label: 'Bounce Count', value: ingest.bank_metrics.bounce_count },
                    { label: 'UPI %', value: formatPct(ingest.bank_metrics.upi_percentage) },
                    { label: 'Cash Deposit %', value: formatPct(ingest.bank_metrics.cash_deposit_pct) },
                  ].map(({ label, value }) => (
                    <div key={label} className="flex justify-between items-center py-2 border-b border-border-dark/40">
                      <span className="text-text-muted text-xs">{label}</span>
                      <span className="text-text-primary text-xs font-medium">{value ?? '—'}</span>
                    </div>
                  ))}
                  {(ingest.bank_metrics.anomalies?.length ?? 0) > 0 && (
                    <div className="pt-2">
                      <p className="text-text-muted text-xs font-medium mb-1.5">Anomalies</p>
                      <ul className="space-y-1">
                        {ingest.bank_metrics.anomalies!.map((a, i) => {
                          const text = typeof a === 'string' ? a : `${a.description || a.type || 'Anomaly'} — ₹${((a.amount ?? 0) / 1e5).toFixed(1)}L (${a.severity || ''})`;
                          return (
                            <li key={i} className="flex items-start gap-2 text-xs text-gold">
                              <span className="mt-0.5">⚠</span> {text}
                            </li>
                          );
                        })}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </div>
          </TabContent>

          {/* Research */}
          <TabContent value="research" className="p-6">
            {research ? (
              <div className="space-y-6">
                {/* Synthesis */}
                {research.synthesis_report && (
                  <div className="bg-surface2/60 border border-border-dark rounded-xl p-5">
                    <h3 className="text-text-primary font-semibold mb-3 flex items-center gap-2">
                      <Globe size={15} className="text-accent" /> External Risk Summary
                    </h3>
                    <div className="grid grid-cols-2 gap-4 text-sm mb-4">
                      <div>
                        <p className="text-text-muted text-xs">Overall External Risk Score</p>
                        <p className="text-text-primary font-bold text-xl mt-0.5">
                          {research.synthesis_report.overall_external_risk_score?.toFixed(1) ?? '—'}
                        </p>
                      </div>
                      <div>
                        <p className="text-text-muted text-xs">Promoter Risk</p>
                        <SeverityBadge severity={research.synthesis_report.promoter_risk_flag} className="mt-1" />
                      </div>
                    </div>
                    {research.synthesis_report.key_red_flags?.length > 0 && (
                      <div className="space-y-1">
                        <p className="text-text-muted text-xs font-medium">Key Red Flags</p>
                        {research.synthesis_report.key_red_flags.map((f, i) => (
                          <div key={i} className="flex items-start gap-2 text-xs text-danger">
                            <span className="mt-0.5 flex-shrink-0">●</span> {f}
                          </div>
                        ))}
                      </div>
                    )}
                    {research.synthesis_report.positive_signals?.length > 0 && (
                      <div className="space-y-1 mt-3">
                        <p className="text-text-muted text-xs font-medium">Positive Signals</p>
                        {research.synthesis_report.positive_signals.map((s, i) => (
                          <div key={i} className="flex items-start gap-2 text-xs text-success">
                            <span className="mt-0.5 flex-shrink-0">✓</span> {s}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* News */}
                {research.news_report?.articles?.length > 0 && (
                  <div>
                    <h4 className="text-text-secondary text-sm font-semibold mb-3">Recent News</h4>
                    <div className="space-y-2">
                      {research.news_report.articles.slice(0, 6).map((a, i) => (
                        <div key={i} className="flex items-start gap-3 p-3 bg-surface2/40 rounded-lg">
                          <SeverityBadge severity={a.risk_type === 'HIGH_RISK' ? 'HIGH' : a.sentiment === 'negative' ? 'MEDIUM' : 'LOW'} className="flex-shrink-0 mt-0.5" />
                          <div className="min-w-0">
                            <p className="text-text-primary text-xs font-medium leading-relaxed">{a.title}</p>
                            <p className="text-text-muted text-xs mt-0.5">{a.source_domain} · {formatDate(a.publication_date)}</p>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Court cases */}
                {research.ecourts_report?.cases?.length > 0 && (
                  <div>
                    <h4 className="text-text-secondary text-sm font-semibold mb-3">
                      Litigation ({research.ecourts_report.cases.length} cases)
                    </h4>
                    <div className="space-y-2">
                      {research.ecourts_report.cases.slice(0, 5).map((c, i) => (
                        <div key={i} className="flex items-start gap-3 p-3 bg-surface2/40 rounded-lg text-xs">
                          <SeverityBadge severity={c.severity} className="flex-shrink-0 mt-0.5" />
                          <div>
                            <p className="text-text-primary font-medium">{c.case_number} — {c.court_name}</p>
                            <p className="text-text-muted mt-0.5">{c.case_type} · {c.case_status} · {formatDate(c.filing_date)}</p>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* RBI Check */}
                {research.rbi_check && (
                  <div className={[
                    'p-4 rounded-xl border text-sm',
                    research.rbi_check.any_match
                      ? 'bg-danger/8 border-danger/30'
                      : 'bg-success/8 border-success/30',
                  ].join(' ')}>
                    <p className={research.rbi_check.any_match ? 'text-danger font-semibold' : 'text-success font-semibold'}>
                      RBI Defaulter List: {research.rbi_check.any_match ? '⚠ MATCH FOUND' : '✓ No match'}
                    </p>
                    {research.rbi_check.matches?.length > 0 && (
                      <ul className="mt-2 space-y-0.5">
                        {research.rbi_check.matches.map((m, i) => (
                          <li key={i} className="text-text-secondary text-xs">• {m}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <p className="text-text-muted text-sm py-8 text-center">No research data available</p>
            )}
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
            ) : (
              <p className="text-text-muted text-sm py-8 text-center">
                Five C's report not yet generated — download CAM to trigger generation.
              </p>
            )}
          </TabContent>

          {/* SHAP */}
          <TabContent value="shap" className="p-6">
            {allSHAP.length > 0 ? (
              <div className="space-y-4 max-w-3xl">
                <p className="text-text-secondary text-xs">
                  SHAP values show each feature's contribution to the predicted default probability.
                  Red bars increase risk; green bars reduce risk.
                </p>
                <SHAPWaterfall factors={allSHAP} height={380} />
              </div>
            ) : (
              <p className="text-text-muted text-sm py-8 text-center">No SHAP explanations available</p>
            )}
          </TabContent>
        </Tabs>
      </Card>

      {/* Data Quality */}
      <DataQualityPanel report={data_quality_report} stageResults={stage_results} />
    </div>
  )
}
