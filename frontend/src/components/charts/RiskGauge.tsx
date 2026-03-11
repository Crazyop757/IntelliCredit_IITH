import React, { useEffect, useRef } from 'react'
import { motion, useMotionValue, useSpring } from 'framer-motion'

interface RiskGaugeProps {
  score: number
  size?: number
  showLabel?: boolean
  className?: string
}

const polarToXY = (cx: number, cy: number, r: number, deg: number) => {
  const rad = (deg * Math.PI) / 180
  return { x: cx + r * Math.cos(rad), y: cy - r * Math.sin(rad) }
}

const arcPath = (cx: number, cy: number, r: number, startDeg: number, endDeg: number) => {
  const s = polarToXY(cx, cy, r, startDeg)
  const e = polarToXY(cx, cy, r, endDeg)
  const large = startDeg - endDeg > 180 ? 1 : 0
  return `M ${s.x.toFixed(2)} ${s.y.toFixed(2)} A ${r} ${r} 0 ${large} 0 ${e.x.toFixed(2)} ${e.y.toFixed(2)}`
}

// 5 equal zones of 36° each across a 180° semicircle
const zones = [
  { from: 180, to: 144, color: '#DC2626', label: 'High Risk' },
  { from: 144, to: 108, color: '#F97316', label: 'Elevated' },
  { from: 108, to: 72,  color: '#EAB308', label: 'Moderate' },
  { from: 72,  to: 36,  color: '#22C55E', label: 'Low Risk' },
  { from: 36,  to: 0,   color: '#0D9488', label: 'Prime' },
]

const scoreToAngle = (s: number) => 180 - Math.min(Math.max(s, 0), 10) * 18

const getRiskLabel = (score: number) => {
  if (score < 3)  return { label: 'PRIME',     color: '#0D9488' }
  if (score < 5)  return { label: 'LOW RISK',  color: '#22C55E' }
  if (score < 6.5) return { label: 'MEDIUM',   color: '#EAB308' }
  if (score < 8)  return { label: 'ELEVATED',  color: '#F97316' }
  return                  { label: 'HIGH RISK', color: '#DC2626' }
}

export default function RiskGauge({ score, size = 200, showLabel = true, className = '' }: RiskGaugeProps) {
  const cx = 100
  const cy = 100
  const R = 78
  const r = 62
  const strokeW = R - r
  const midR = (R + r) / 2

  const needleAngle = useMotionValue(180)
  const smoothAngle = useSpring(needleAngle, { stiffness: 55, damping: 14 })

  useEffect(() => {
    needleAngle.set(scoreToAngle(score))
  }, [score, needleAngle])

  const { label: riskLabel, color: riskColor } = getRiskLabel(score)

  return (
    <div className={`flex flex-col items-center ${className}`}>
      <svg
        viewBox="0 0 200 120"
        width={size}
        height={size * 0.6}
        aria-label={`Risk score ${score.toFixed(1)}`}
      >
        {/* Background track */}
        <path
          d={arcPath(cx, cy, midR, 180, 0)}
          fill="none"
          stroke="#1E293B"
          strokeWidth={strokeW}
          strokeLinecap="butt"
        />

        {/* Colored zones */}
        {zones.map((zone) => (
          <path
            key={zone.from}
            d={arcPath(cx, cy, midR, zone.from, zone.to)}
            fill="none"
            stroke={zone.color}
            strokeWidth={strokeW}
            strokeLinecap="butt"
            opacity={0.85}
          />
        ))}

        {/* Needle shadow */}
        <motion.g style={{ originX: `${cx}px`, originY: `${cy}px` }} animate={{ rotate: scoreToAngle(score) - 180 }} initial={{ rotate: 0 }} transition={{ type: 'spring', stiffness: 55, damping: 14 }}>
          <line
            x1={cx}
            y1={cy}
            x2={cx + 62}
            y2={cy}
            stroke="rgba(0,0,0,0.4)"
            strokeWidth={3.5}
            strokeLinecap="round"
            transform="translate(1,2)"
          />
        </motion.g>

        {/* Needle */}
        <motion.g
          style={{ originX: `${cx}px`, originY: `${cy}px` }}
          animate={{ rotate: scoreToAngle(score) - 180 }}
          initial={{ rotate: 0 }}
          transition={{ type: 'spring', stiffness: 55, damping: 14 }}
        >
          <line
            x1={cx}
            y1={cy}
            x2={cx + 62}
            y2={cy}
            stroke="#334155"
            strokeWidth={3}
            strokeLinecap="round"
          />
          <line
            x1={cx}
            y1={cy}
            x2={cx - 14}
            y2={cy}
            stroke="#334155"
            strokeWidth={3}
            strokeLinecap="round"
            opacity={0.4}
          />
        </motion.g>

        {/* Center dot */}
        <circle cx={cx} cy={cy} r={6} fill="#0D1117" stroke="#334155" strokeWidth={2} />

        {/* Score text — rendered below the arc baseline in the added viewBox space */}
        {showLabel && (
          <>
            <text
              x={cx}
              y={112}
              textAnchor="middle"
              fill="#FFFFFF"
              fontSize="20"
              fontWeight="700"
              fontFamily="Inter, sans-serif"
            >
              {score.toFixed(1)}
            </text>
            <text
              x={cx}
              y={120}
              textAnchor="middle"
              fill={riskColor}
              fontSize="7.5"
              fontWeight="600"
              fontFamily="Inter, sans-serif"
              letterSpacing="0.1em"
            >
              {riskLabel}
            </text>
          </>
        )}

        {/* Scale labels: left=risky(10), right=safe(0) */}
        <text x="10" y="103" fill="#94A3B8" fontSize="7.5" fontFamily="Inter, sans-serif">10</text>
        <text x="184" y="103" fill="#94A3B8" fontSize="7.5" fontFamily="Inter, sans-serif">0</text>
        <text x="96" y="18" fill="#94A3B8" fontSize="7.5" fontFamily="Inter, sans-serif">5</text>
      </svg>
    </div>
  )
}
