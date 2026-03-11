interface ProgressProps {
  value: number        // 0–100
  max?: number
  className?: string
  color?: 'primary' | 'success' | 'danger' | 'gold' | 'accent' | 'gradient'
  size?: 'xs' | 'sm' | 'md'
  showLabel?: boolean
  animated?: boolean
  label?: string
}

const colorMap = {
  primary: '#2563EB',
  success: '#16A34A',
  danger: '#DC2626',
  gold: '#D97706',
  accent: '#0D9488',
  gradient: undefined,
}

const sizeMap = {
  xs: 'h-1',
  sm: 'h-1.5',
  md: 'h-2.5',
}

export default function Progress({
  value,
  max = 100,
  className = '',
  color = 'primary',
  size = 'sm',
  showLabel = false,
  animated = false,
  label,
}: ProgressProps) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100))
  const solidColor = colorMap[color]

  const fillStyle: React.CSSProperties =
    color === 'gradient'
      ? {
          width: `${pct}%`,
          background: 'linear-gradient(90deg, #2563EB 0%, #0D9488 100%)',
          borderRadius: '9999px',
          transition: animated ? 'width 0.6s ease' : undefined,
        }
      : {
          width: `${pct}%`,
          background: solidColor,
          borderRadius: '9999px',
          transition: animated ? 'width 0.6s ease' : undefined,
        }

  return (
    <div className={className}>
      {(label || showLabel) && (
        <div className="flex justify-between items-center mb-1">
          {label && <span className="text-xs text-text-secondary">{label}</span>}
          {showLabel && <span className="text-xs text-text-secondary font-mono">{pct.toFixed(0)}%</span>}
        </div>
      )}
      <div className={`w-full bg-surface2 rounded-full overflow-hidden ${sizeMap[size]}`}>
        <div style={fillStyle} />
      </div>
    </div>
  )
}

import React from 'react'
