// ─── INR Currency Formatting ──────────────────────────────────────────────────

/**
 * Format a number in Indian notation: ₹1,25,00,000
 */
export function formatINR(value: number | null | undefined): string {
  if (value === null || value === undefined || isNaN(value)) return '₹0'
  const absValue = Math.abs(value)
  const sign = value < 0 ? '-' : ''
  const formatted = new Intl.NumberFormat('en-IN').format(absValue)
  return `${sign}₹${formatted}`
}

/**
 * Format a number as crores: ₹37.16 Cr
 */
export function formatCrore(value: number | null | undefined): string {
  if (value === null || value === undefined || isNaN(value)) return '—'
  return `₹${value.toFixed(2)} Cr`
}

/**
 * Format a number as lakhs: ₹371.6 L
 */
export function formatLakh(value: number | null | undefined): string {
  if (value === null || value === undefined || isNaN(value)) return '—'
  return `₹${(value * 100).toFixed(1)} L`
}

/**
 * Smart format: auto-picks Cr or L based on magnitude
 */
export function formatINRSmart(value: number | null | undefined): string {
  if (value === null || value === undefined || isNaN(value)) return '—'
  const absValue = Math.abs(value)
  if (absValue >= 1) return formatCrore(value)
  return `₹${(value * 100).toFixed(2)} L`
}

// ─── Percentage ───────────────────────────────────────────────────────────────

export function formatPct(value: number | null | undefined, decimals = 1): string {
  if (value === null || value === undefined) return '—'
  return `${value.toFixed(decimals)}%`
}

export function formatRatio(value: number | null | undefined, decimals = 2): string {
  if (value === null || value === undefined) return '—'
  return value.toFixed(decimals)
}

// ─── Date ─────────────────────────────────────────────────────────────────────

export function formatDate(date: string | null | undefined): string {
  if (!date) return '—'
  try {
    return new Date(date).toLocaleDateString('en-IN', {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
    })
  } catch {
    return date
  }
}

export function formatDateTime(date: string | null | undefined): string {
  if (!date) return '—'
  try {
    return new Date(date).toLocaleString('en-IN', {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return date
  }
}

export function timeAgo(dateStr: string | null | undefined): string {
  if (!dateStr) return '—'
  const date = new Date(dateStr)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMins / 60)
  const diffDays = Math.floor(diffHours / 24)
  if (diffMins < 1) return 'just now'
  if (diffMins < 60) return `${diffMins}m ago`
  if (diffHours < 24) return `${diffHours}h ago`
  if (diffDays < 7) return `${diffDays}d ago`
  return formatDate(dateStr)
}

// ─── Risk Colors ──────────────────────────────────────────────────────────────

export function getRiskBandColor(band: string): { bg: string; text: string; border: string } {
  switch (band?.toUpperCase()) {
    case 'PRIME':
      return { bg: 'rgba(13,148,136,0.15)', text: '#0D9488', border: 'rgba(13,148,136,0.3)' }
    case 'LOW':
      return { bg: 'rgba(22,163,74,0.15)', text: '#16A34A', border: 'rgba(22,163,74,0.3)' }
    case 'MEDIUM':
      return { bg: 'rgba(217,119,6,0.15)', text: '#D97706', border: 'rgba(217,119,6,0.3)' }
    case 'HIGH':
      return { bg: 'rgba(220,38,38,0.15)', text: '#DC2626', border: 'rgba(220,38,38,0.3)' }
    default:
      return { bg: 'rgba(71,85,105,0.15)', text: '#94A3B8', border: 'rgba(71,85,105,0.3)' }
  }
}

export function getDecisionColor(decision: string): { gradient: string; text: string } {
  switch (decision?.toUpperCase()) {
    case 'APPROVE':
      return { gradient: 'linear-gradient(135deg, #16A34A 0%, #15803D 100%)', text: '#FFFFFF' }
    case 'CONDITIONAL':
      return { gradient: 'linear-gradient(135deg, #D97706 0%, #B45309 100%)', text: '#FFFFFF' }
    case 'REJECT':
      return { gradient: 'linear-gradient(135deg, #DC2626 0%, #B91C1C 100%)', text: '#FFFFFF' }
    default:
      return { gradient: 'linear-gradient(135deg, #475569 0%, #334155 100%)', text: '#FFFFFF' }
  }
}

export function getSeverityColor(severity: string): string {
  switch (severity?.toUpperCase()) {
    case 'HIGH':
    case 'CRITICAL':
      return '#DC2626'
    case 'MEDIUM':
      return '#D97706'
    case 'LOW':
      return '#EAB308'
    case 'CLEAR':
      return '#16A34A'
    default:
      return '#94A3B8'
  }
}

export function getEWSLevelColor(level: string): string {
  switch (level?.toUpperCase()) {
    case 'HIGH': return '#DC2626'
    case 'MEDIUM': return '#D97706'
    case 'LOW': return '#EAB308'
    case 'CLEAR': return '#16A34A'
    default: return '#475569'
  }
}

export function getGaugeColor(score: number): string {
  if (score >= 8) return '#0D9488'
  if (score >= 7) return '#16A34A'
  if (score >= 5) return '#EAB308'
  if (score >= 3) return '#D97706'
  return '#DC2626'
}

// ─── EWS Labels ───────────────────────────────────────────────────────────────

export function ewsFlagLabel(flag: string): string {
  const labels: Record<string, string> = {
    gst_itc_fraud_risk: 'ITC Fraud Risk',
    circular_trading_risk: 'Circular Trading',
    revenue_inflation_risk: 'Revenue Inflation',
    cash_stress_risk: 'Cash Stress',
    documentation_risk: 'Documentation',
    auditor_concern_risk: 'Auditor Concerns',
    director_risk: 'Director Risk',
    compliance_risk: 'Compliance',
  }
  return labels[flag] ?? flag
}

// ─── File size ────────────────────────────────────────────────────────────────

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

// ─── Trend ────────────────────────────────────────────────────────────────────

export function trendArrow(current: number | null, previous: number | null): string {
  if (current === null || previous === null) return '→'
  if (current > previous * 1.02) return '↑'
  if (current < previous * 0.98) return '↓'
  return '→'
}

export function trendColor(current: number | null, previous: number | null, higherIsBetter = true): string {
  if (current === null || previous === null) return '#94A3B8'
  const improved = current > previous * 1.02
  const worsened = current < previous * 0.98
  if (!improved && !worsened) return '#94A3B8'
  return (improved && higherIsBetter) || (worsened && !higherIsBetter) ? '#16A34A' : '#DC2626'
}

// ─── CIN Validation ──────────────────────────────────────────────────────────

/**
 * Validate an Indian Corporate Identification Number (CIN).
 * Format: L/U + 5 digits (section code) + 2 alpha (state) + 4 digits (year) +
 *         3 alpha (ownership) + 6 digits (serial) + 1 alphanumeric (check)
 * Total length: 21 characters.
 */
const CIN_RE = /^[LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}[A-Z0-9]$/

export function isValidCIN(cin: string | null | undefined): boolean {
  if (!cin) return false
  return CIN_RE.test(cin.toUpperCase().trim())
}

export function formatCIN(cin: string | null | undefined): string {
  if (!cin) return '—'
  return cin.toUpperCase().trim()
}
