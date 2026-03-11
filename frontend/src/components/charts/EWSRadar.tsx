import React from 'react'
import {
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  ResponsiveContainer, Tooltip,
} from 'recharts'
import type { EWSFlags } from '../../store/types'
import { ewsFlagLabel } from '../../utils/formatters'
import { EWS_FLAG_WEIGHTS } from '../../utils/constants'

interface EWSRadarProps {
  flags: EWSFlags
  height?: number
}

const CustomTooltip = ({ active, payload }: any) => {
  if (!active || !payload?.length) return null
  const d = payload[0].payload
  return (
    <div className="bg-surface2 border border-border-dark rounded-lg px-3 py-2 text-xs shadow-card">
      <p className="text-text-primary font-medium">{d.subject}</p>
      <p className={d.value > 0 ? 'text-danger' : 'text-success'}>
        {d.value > 0 ? 'FLAGGED' : 'CLEAR'}
      </p>
    </div>
  )
}

export default function EWSRadar({ flags, height = 300 }: EWSRadarProps) {
  const ewsKeys = Object.keys(EWS_FLAG_WEIGHTS) as (keyof EWSFlags)[]

  const data = ewsKeys.map((key) => ({
    subject: ewsFlagLabel(key),
    value: flags[key] && flags[key] !== 'CLEAR' ? 1 : 0,
    fullMark: 1,
  }))

  const flaggedCount = data.filter((d) => d.value > 0).length

  return (
    <div className="flex flex-col items-center">
      <ResponsiveContainer width="100%" height={height}>
        <RadarChart data={data} margin={{ top: 10, right: 30, bottom: 10, left: 30 }}>
          <PolarGrid stroke="#1E2D45" />
          <PolarAngleAxis
            dataKey="subject"
            tick={{ fill: '#94A3B8', fontSize: 10 }}
          />
          <PolarRadiusAxis
            angle={90}
            domain={[0, 1]}
            tick={false}
            axisLine={false}
            tickCount={2}
          />
          <Radar
            name="EWS Flags"
            dataKey="value"
            stroke={flaggedCount >= 4 ? '#DC2626' : flaggedCount >= 2 ? '#D97706' : '#16A34A'}
            fill={flaggedCount >= 4 ? '#DC2626' : flaggedCount >= 2 ? '#D97706' : '#16A34A'}
            fillOpacity={0.25}
            strokeWidth={1.5}
          />
          <Tooltip content={<CustomTooltip />} />
        </RadarChart>
      </ResponsiveContainer>
      <p className="text-text-muted text-xs mt-1">
        {flaggedCount} of {ewsKeys.length} early-warning flags triggered
      </p>
    </div>
  )
}
