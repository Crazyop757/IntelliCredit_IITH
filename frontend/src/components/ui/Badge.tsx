import React from 'react'
import { getRiskBandColor } from '../../utils/formatters'

type RiskBand = 'PRIME' | 'LOW' | 'MEDIUM' | 'HIGH'
type Severity = 'HIGH' | 'MEDIUM' | 'LOW' | 'CLEAR' | 'CRITICAL'
type Decision = 'APPROVE' | 'CONDITIONAL' | 'REJECT'
type SentimentType = 'positive' | 'negative' | 'neutral'
type StatusType = 'PENDING' | 'RUNNING' | 'DONE' | 'FAILED'
type SMAType = 'SMA-0' | 'SMA-1' | 'SMA-2'

interface BadgeProps {
  children: React.ReactNode
  className?: string
  size?: 'xs' | 'sm' | 'md'
}

type RiskBandBadgeProps = BadgeProps & { variant: 'riskBand'; value: RiskBand }
type SeverityBadgeProps = BadgeProps & { variant: 'severity'; value: Severity }
type DecisionBadgeProps = BadgeProps & { variant: 'decision'; value: Decision }
type SentimentBadgeProps = BadgeProps & { variant: 'sentiment'; value: SentimentType }
type StatusBadgeProps = BadgeProps & { variant: 'status'; value: StatusType }
type SMABadgeProps = BadgeProps & { variant: 'sma'; value: SMAType }
type GenericBadgeProps = BadgeProps & { variant?: 'default'; style?: React.CSSProperties }

type AllBadgeProps =
  | RiskBandBadgeProps
  | SeverityBadgeProps
  | DecisionBadgeProps
  | SentimentBadgeProps
  | StatusBadgeProps
  | SMABadgeProps
  | GenericBadgeProps

const sizeClasses = {
  xs: 'px-1.5 py-0.5 text-xs',
  sm: 'px-2 py-0.5 text-xs font-medium',
  md: 'px-3 py-1 text-sm font-semibold',
}

function getRiskBandStyle(value: RiskBand): React.CSSProperties {
  const c = getRiskBandColor(value)
  return { background: c.bg, color: c.text, border: `1px solid ${c.border}` }
}

function getSeverityStyle(value: Severity): React.CSSProperties {
  const map: Record<Severity, { bg: string; text: string; border: string }> = {
    CRITICAL: { bg: 'rgba(220,38,38,0.2)', text: '#DC2626', border: 'rgba(220,38,38,0.4)' },
    HIGH: { bg: 'rgba(220,38,38,0.15)', text: '#DC2626', border: 'rgba(220,38,38,0.3)' },
    MEDIUM: { bg: 'rgba(217,119,6,0.15)', text: '#D97706', border: 'rgba(217,119,6,0.3)' },
    LOW: { bg: 'rgba(234,179,8,0.15)', text: '#EAB308', border: 'rgba(234,179,8,0.3)' },
    CLEAR: { bg: 'rgba(22,163,74,0.15)', text: '#16A34A', border: 'rgba(22,163,74,0.3)' },
  }
  const s = map[value] ?? { bg: 'rgba(71,85,105,0.15)', text: '#94A3B8', border: 'rgba(71,85,105,0.3)' }
  return { background: s.bg, color: s.text, border: `1px solid ${s.border}` }
}

function getDecisionStyle(value: Decision): React.CSSProperties {
  const map: Record<Decision, { bg: string; text: string; border: string }> = {
    APPROVE: { bg: 'rgba(22,163,74,0.15)', text: '#16A34A', border: 'rgba(22,163,74,0.3)' },
    CONDITIONAL: { bg: 'rgba(217,119,6,0.15)', text: '#D97706', border: 'rgba(217,119,6,0.3)' },
    REJECT: { bg: 'rgba(220,38,38,0.15)', text: '#DC2626', border: 'rgba(220,38,38,0.3)' },
  }
  const s = map[value]
  return { background: s.bg, color: s.text, border: `1px solid ${s.border}` }
}

function getSentimentStyle(value: SentimentType): React.CSSProperties {
  const map: Record<SentimentType, { bg: string; text: string; border: string }> = {
    positive: { bg: 'rgba(22,163,74,0.15)', text: '#16A34A', border: 'rgba(22,163,74,0.3)' },
    negative: { bg: 'rgba(220,38,38,0.15)', text: '#DC2626', border: 'rgba(220,38,38,0.3)' },
    neutral: { bg: 'rgba(71,85,105,0.15)', text: '#94A3B8', border: 'rgba(71,85,105,0.3)' },
  }
  const s = map[value]
  return { background: s.bg, color: s.text, border: `1px solid ${s.border}` }
}

function getStatusStyle(value: StatusType): React.CSSProperties {
  const map: Record<StatusType, { bg: string; text: string; border: string }> = {
    DONE: { bg: 'rgba(22,163,74,0.15)', text: '#16A34A', border: 'rgba(22,163,74,0.3)' },
    RUNNING: { bg: 'rgba(37,99,235,0.15)', text: '#60A5FA', border: 'rgba(37,99,235,0.3)' },
    PENDING: { bg: 'rgba(71,85,105,0.15)', text: '#94A3B8', border: 'rgba(71,85,105,0.3)' },
    FAILED: { bg: 'rgba(220,38,38,0.15)', text: '#DC2626', border: 'rgba(220,38,38,0.3)' },
  }
  const s = map[value]
  return { background: s.bg, color: s.text, border: `1px solid ${s.border}` }
}

function getSMAStyle(value: SMAType): React.CSSProperties {
  const map: Record<SMAType, { bg: string; text: string; border: string }> = {
    'SMA-0': { bg: 'rgba(22,163,74,0.15)', text: '#16A34A', border: 'rgba(22,163,74,0.3)' },
    'SMA-1': { bg: 'rgba(217,119,6,0.15)', text: '#D97706', border: 'rgba(217,119,6,0.3)' },
    'SMA-2': { bg: 'rgba(220,38,38,0.15)', text: '#DC2626', border: 'rgba(220,38,38,0.3)' },
  }
  const s = map[value]
  return { background: s.bg, color: s.text, border: `1px solid ${s.border}` }
}

export default function Badge(props: AllBadgeProps) {
  const { children, className = '', size = 'sm' } = props

  let style: React.CSSProperties = {}

  if (props.variant === 'riskBand') style = getRiskBandStyle(props.value)
  else if (props.variant === 'severity') style = getSeverityStyle(props.value)
  else if (props.variant === 'decision') style = getDecisionStyle(props.value)
  else if (props.variant === 'sentiment') style = getSentimentStyle(props.value)
  else if (props.variant === 'status') style = getStatusStyle(props.value)
  else if (props.variant === 'sma') style = getSMAStyle(props.value)
  else if ('style' in props && props.style) style = props.style

  return (
    <span
      className={`inline-flex items-center rounded-full ${sizeClasses[size]} ${className}`}
      style={style}
    >
      {children}
    </span>
  )
}

// Convenience exports
export function RiskBandBadge({ band, size = 'sm', className }: { band: string; size?: 'xs' | 'sm' | 'md'; className?: string }) {
  const normalized = band?.toUpperCase() as RiskBand
  return (
    <Badge variant="riskBand" value={normalized} size={size} className={className}>
      {normalized}
    </Badge>
  )
}

export function SeverityBadge({ severity, size = 'sm', className }: { severity: string; size?: 'xs' | 'sm' | 'md'; className?: string }) {
  const normalized = severity?.toUpperCase() as Severity
  return (
    <Badge variant="severity" value={normalized} size={size} className={className}>
      {normalized}
    </Badge>
  )
}

export function DecisionBadge({ decision, size = 'sm', className }: { decision: string; size?: 'xs' | 'sm' | 'md'; className?: string }) {
  const normalized = decision?.toUpperCase() as Decision
  const icons: Record<string, string> = { APPROVE: '✓', CONDITIONAL: '⚠', REJECT: '✗' }
  return (
    <Badge variant="decision" value={normalized} size={size} className={className}>
      {icons[normalized] && <span className="mr-1">{icons[normalized]}</span>}
      {normalized}
    </Badge>
  )
}
