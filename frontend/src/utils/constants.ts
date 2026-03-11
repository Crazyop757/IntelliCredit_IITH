export const PIPELINE_STAGE_KEYS = ['ingest', 'gst', 'research', 'scoring', 'cam'] as const

export const PIPELINE_STAGE_LABELS: Record<string, string> = {
  ingest: 'Document Ingestion',
  gst: 'GST Analysis',
  research: 'Research Agent',
  scoring: 'Credit Scoring',
  cam: 'CAM Generation',
}

export const PIPELINE_POLL_INTERVAL_MS = 2000

export const EWS_FLAG_KEYS = [
  'gst_itc_fraud_risk',
  'circular_trading_risk',
  'revenue_inflation_risk',
  'cash_stress_risk',
  'documentation_risk',
  'auditor_concern_risk',
  'director_risk',
  'compliance_risk',
] as const

export const EWS_FLAG_WEIGHTS: Record<string, number> = {
  circular_trading_risk: 0.25,
  gst_itc_fraud_risk: 0.20,
  revenue_inflation_risk: 0.20,
  auditor_concern_risk: 0.15,
  cash_stress_risk: 0.10,
  documentation_risk: 0.033,
  director_risk: 0.033,
  compliance_risk: 0.034,
}

export const RISK_BAND_ORDER = ['PRIME', 'LOW', 'MEDIUM', 'HIGH'] as const

export const COMPANY_TYPES = [
  { value: 'PRIVATE_LIMITED', label: 'Private Limited' },
  { value: 'PUBLIC_LIMITED', label: 'Public Limited' },
  { value: 'LLP', label: 'LLP' },
  { value: 'PARTNERSHIP', label: 'Partnership' },
  { value: 'PROPRIETORSHIP', label: 'Proprietorship' },
] as const

export const INDUSTRY_SECTORS = [
  { value: 'TEXTILE', label: 'Textile' },
  { value: 'MANUFACTURING', label: 'Manufacturing' },
  { value: 'REAL_ESTATE', label: 'Real Estate' },
  { value: 'NBFC', label: 'NBFC' },
  { value: 'TRADING', label: 'Trading' },
  { value: 'IT_SERVICES', label: 'IT Services' },
  { value: 'PHARMA', label: 'Pharma' },
  { value: 'INFRASTRUCTURE', label: 'Infrastructure' },
  { value: 'AGRICULTURE', label: 'Agriculture' },
  { value: 'OTHER', label: 'Other' },
] as const

export const PIPELINE_STAGES = PIPELINE_STAGE_KEYS.map((key) => ({
  key,
  label: PIPELINE_STAGE_LABELS[key],
}))

export const COMPANY_TYPES_LIST = COMPANY_TYPES.map((t) => t.value)
export const SECTORS = INDUSTRY_SECTORS.map((s) => s.value)


export const MAX_FILE_SIZES = {
  pdf: 50 * 1024 * 1024,   // 50 MB
  bank: 20 * 1024 * 1024,  // 20 MB
  gst: 10 * 1024 * 1024,   // 10 MB per file
}

export const QUALITATIVE_CAPACITY_BRACKETS = [
  { threshold: 40, adjustment: -2.0, label: 'Below 40% — Very Low' },
  { threshold: 60, adjustment: -1.0, label: '40–60% — Low' },
  { threshold: 80, adjustment: 0.0, label: '60–80% — Adequate' },
  { threshold: 101, adjustment: 0.5, label: 'Above 80% — Strong' },
]

export const FACILITY_CONDITION_ADJUSTMENTS: Record<string, number> = {
  EXCELLENT: 0.5,
  GOOD: 0.0,
  FAIR: -0.5,
  POOR: -1.5,
  NOT_VISITED: 0.0,
}

export const MANAGEMENT_TRANSPARENCY_ADJUSTMENTS: Record<string, number> = {
  FULLY_TRANSPARENT: 0.5,
  MOSTLY_TRANSPARENT: 0.0,
  EVASIVE: -1.0,
  UNCOOPERATIVE: -2.0,
}
