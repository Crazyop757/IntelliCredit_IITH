// ─── Core Entities ────────────────────────────────────────────────────────────

export interface Company {
  company_name: string
  cin?: string
  loan_amount_requested: number
  tenure_months: number
  session_id?: string
  company_type?: string
  sector?: string
  created_at?: string
  promoter_name?: string
  registered_address?: string
}

export interface FinancialYear {
  /** raw fields from backend */
  revenue: number | null
  ebitda: number | null
  pat: number | null
  ebitda_margin: number | null
  pat_margin: number | null
  debt_equity: number | null
  current_ratio: number | null
  dscr: number | null
  revenue_growth: number | null
  total_debt: number | null
  net_worth: number | null
  /** convenience aliases that may also be present */
  year?: string
  total_revenue?: number | null
  net_profit?: number | null
  net_profit_margin?: number | null
}

// ─── Ingest ───────────────────────────────────────────────────────────────────

export interface BankMetrics {
  avg_monthly_balance: number | null
  total_annual_credits: number | null
  debit_credit_ratio: number | null
  bounce_count: number
  upi_percentage: number | null
  cash_deposit_pct: number | null
  anomalies: Array<string | { type?: string; description?: string; amount?: number; date?: string; severity?: string; detail?: string }>
}

export interface GSTGraphNode {
  id: string
  name: string
  total_sales: number
  total_purchases: number
  net_gst_paid: number
  risk_score: number
  is_circular: boolean
  is_suspicious: boolean
  sector?: string
  state?: string
}

export interface GSTGraphEdge {
  source: string
  target: string
  invoice_value: number
  tax_amount: number
  transaction_count: number
  is_circular: boolean
}

export interface CircularPattern {
  cycle: string[]
  cycle_length: number
  cycle_value: number
  mean_edge_value: number
  value_spread_pct: number
  all_values_similar: boolean
  flag: string
}

export interface GSTReconciliation {
  gst_health_score: number | null
  itc_gap_pct: number | null
  itc_claimed_3b: number | null
  itc_available_2a: number | null
  filing_regularity: string | null
  circular_trading_flag: string | null
  gst_itc_fraud_risk: string | null
  fictitious_vendor_count: number
  graph_nodes?: GSTGraphNode[]
  graph_edges?: GSTGraphEdge[]
  circular_patterns?: CircularPattern[]
}

export interface RiskClause {
  severity: 'HIGH' | 'MEDIUM' | 'LOW' | 'CRITICAL'
  clause_text: string
  clause?: string    // alias used by some backend versions
  source?: string
}

export interface Director {
  name: string
  designation?: string
}

export interface SentimentResult {
  overall_sentiment: 'positive' | 'negative' | 'neutral'
  score: number
  qualified_opinion_flag: boolean
}

export interface IngestResult {
  session_id: string
  company_name: string
  cin: string
  extracted_financials: Record<string, FinancialYear>
  bank_metrics: BankMetrics
  gst_reconciliation: GSTReconciliation
  risk_clauses: RiskClause[]
  directors: Director[]
  sentiment: SentimentResult
  processing_time_seconds: number
}

// ─── Research ─────────────────────────────────────────────────────────────────

export interface NewsArticle {
  title: string
  url: string
  source_domain: string
  publication_date: string
  sentiment: string
  risk_type: string
}

export interface NewsReport {
  articles: NewsArticle[]
  news_risk_score: number
  negative_article_count: number
  most_alarming_headline: string | null
  risk_tags: string[]
}

export interface CourtCase {
  case_number: string
  court_name: string
  filing_date: string
  case_type: string
  case_status: string
  severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'
}

export interface ECourtsReport {
  cases: CourtCase[]
  litigation_risk_score: number
  nclt_override: boolean
}

export interface MCACharge {
  charge_holder: string
  amount_inr: number
  status: string
}

export interface MCAReport {
  company_status: string
  last_bs_filing_date: string
  total_open_charges_inr: number
  charges: MCACharge[]
  compliance_flags: Record<string, boolean>
}

export interface RBICheck {
  any_match: boolean
  directors_checked: string[]
  matches: string[]
}

export interface SynthesisReport {
  overall_external_risk_score: number
  promoter_risk_flag: 'HIGH' | 'MEDIUM' | 'LOW' | 'CLEAR'
  litigation_summary: string
  news_summary: string
  regulatory_compliance_summary: string
  key_red_flags: string[]
  positive_signals: string[]
  recommended_action: 'PROCEED' | 'CONDITIONAL' | 'REJECT'
}

export interface ResearchResult {
  news_report: NewsReport
  ecourts_report: ECourtsReport
  mca_report: MCAReport
  rbi_check: RBICheck
  synthesis_report: SynthesisReport
  external_risk_score: number
}

// ─── Qualitative ──────────────────────────────────────────────────────────────

export interface QualitativeResult {
  total_adjustment: number
  breakdown: Record<string, number>
  red_flags_found: string[]
  summary_text: string
  severity: 'HIGH_RISK' | 'MODERATE_RISK' | 'NEUTRAL' | 'POSITIVE'
}

export interface QualitativeFormData {
  company_id?: string
  session_id?: string
  site_visit_observations?: string
  capacity_utilization_pct?: number
  facility_condition?: 'EXCELLENT' | 'GOOD' | 'FAIR' | 'POOR' | 'NOT_VISITED'
  management_interview_notes?: string
  management_transparency?: 'FULLY_TRANSPARENT' | 'MOSTLY_TRANSPARENT' | 'EVASIVE' | 'UNCOOPERATIVE'
  group_company_exposure?: string
  inventory_vs_records?: string
  employee_count_vs_records?: string
  other_key_observations?: string
}

// ─── Scoring ──────────────────────────────────────────────────────────────────

export interface SHAPFactor {
  human_readable_name: string
  shap_value: number
  direction: 'risk' | 'protective'
  /** alternative field names that may arrive from different endpoints */
  feature_name?: string
  feature_value?: number | string | null
}

export interface ScoreResult {
  risk_score: number
  risk_band: 'PRIME' | 'LOW' | 'MEDIUM' | 'HIGH'
  default_probability: number
  recommended_loan_amount: number | null
  recommended_interest_rate: string | null
  recommended_tenure_months: number | null
  shap_explanations: {
    top_risk_factors: SHAPFactor[]
    top_positive_factors: SHAPFactor[]
  }
  decision: 'APPROVE' | 'CONDITIONAL' | 'REJECT'
  decision_rationale: string
}

// ─── EWS ──────────────────────────────────────────────────────────────────────

export type EWSLevel = 'HIGH' | 'MEDIUM' | 'LOW' | 'CLEAR'

export interface EWSFlags {
  gst_itc_fraud_risk: EWSLevel
  circular_trading_risk: EWSLevel
  revenue_inflation_risk: EWSLevel
  cash_stress_risk: EWSLevel
  documentation_risk: EWSLevel
  auditor_concern_risk: EWSLevel
  director_risk: EWSLevel
  compliance_risk: EWSLevel
  ews_score: number
  sma_classification: 'SMA-0' | 'SMA-1' | 'SMA-2'
}

// ─── Five Cs ──────────────────────────────────────────────────────────────────

export interface FiveCsText {
  character?: string
  capacity?: string
  capital?: string
  collateral?: string
  conditions?: string
}

// ─── Pipeline ─────────────────────────────────────────────────────────────────

export interface PipelineStage {
  name: string
  stage_name?: string   // alias
  status: 'pending' | 'running' | 'done' | 'failed' | 'skipped'
  duration_seconds?: number
  duration_s?: number   // alias
  output_snippet?: string
  message?: string      // alias
  started_at?: string
  completed_at?: string
}

export interface StageResult {
  stage: string
  status: 'ok' | 'partial' | 'failed'
  elapsed_ms: number
  error?: string
}

export interface DataQualityReport {
  imputed_features: string[]
  timed_out_tools: string[]
  model_availability: Record<string, boolean>
}

export interface FullPipelineResult {
  session_id: string
  company: Company
  ingest: IngestResult
  research: ResearchResult
  qualitative?: QualitativeResult
  score: ScoreResult
  ews: EWSFlags
  five_cs?: FiveCsText
  cam_download_url: string
  stage_results?: Record<string, StageResult>
  data_quality_report?: DataQualityReport
}

export interface PipelineJob {
  job_id: string
  session_id: string
  status: 'PENDING' | 'RUNNING' | 'DONE' | 'FAILED'
  current_stage: string
  progress_pct: number
  stages: PipelineStage[]
  live_logs?: string[]
  result?: FullPipelineResult
  error?: string
}

// ─── Session Store ────────────────────────────────────────────────────────────

export interface SessionState {
  session_id: string | null
  owner_user_id: string | null
  company: Company | null
  job_id: string | null
  pipeline_status: PipelineJob | null
  results: FullPipelineResult | null
  qualitative_submitted: boolean
  last_appraised_at: string | null
  qualitative_data: QualitativeFormData | null
  setSession: (id: string) => void
  setOwnerUserId: (id: string | null) => void
  setCompany: (c: Company) => void
  setJobId: (id: string) => void
  setPipelineStatus: (s: PipelineJob) => void
  setResults: (r: FullPipelineResult) => void
  setQualitativeSubmitted: (v: boolean) => void
  setQualitativeData: (d: QualitativeFormData) => void
  setLastAppraisedAt: (t: string) => void
  reset: () => void
}

// ─── UI Store ─────────────────────────────────────────────────────────────────

export interface UIState {
  sidebarCollapsed: boolean
  apiOnline: boolean | null
  setSidebarCollapsed: (v: boolean) => void
  setApiOnline: (v: boolean) => void
}

// ─── CAM ──────────────────────────────────────────────────────────────────────

export interface CAMRequest {
  company_id: string
  company_name: string
  cin?: string
  five_cs_text?: FiveCsText
  scoring_result?: unknown
  research_report?: unknown
}

// ─── API response wrappers ────────────────────────────────────────────────────

export interface JobRef {
  job_id: string
  job_type: string
  status: string
  poll_url: string
  created_at: string
}

export interface CompanyListItem {
  company_id: string
  company_name?: string
  has_bronze?: boolean
  has_silver?: boolean
  has_gold?: boolean
  risk_band?: string
  risk_score?: number
  decision?: string
  appraisal_date?: string
}

/**
 * Raw silver-layer record returned by DeltaWriter.read_company_data().
 * Field names mirror what _build_silver_record writes to disk.
 */
export interface SilverRecord {
  fiscal_year?: number
  company_name?: string
  revenue?: number | null
  ebitda?: number | null
  pat?: number | null
  total_debt?: number | null
  net_worth?: number | null
  dscr?: number | null
  current_ratio?: number | null
  ebitda_margin?: number | null
  pat_margin?: number | null
  debt_equity?: number | null
  revenue_growth?: number | null
  risk_clauses?: RiskClause[]
  directors?: Director[]
  [key: string]: unknown
}

/**
 * Shape returned by GET /companies/{id}.
 * Wraps the DeltaWriter delta-lake data.
 * When a full pipeline has been run the response may also include the
 * FullPipelineResult fields (company, score, ews, ingest, research, five_cs).
 */
export interface CompanyDetailData {
  company_id: string
  records: SilverRecord[]
  latest?: SilverRecord
  years_available: number[]
  // Optional full-pipeline fields (present if pipeline result was stored)
  company?: Company
  score?: ScoreResult
  ews?: EWSFlags
  ingest?: IngestResult
  research?: ResearchResult
  five_cs?: FiveCsText
}
