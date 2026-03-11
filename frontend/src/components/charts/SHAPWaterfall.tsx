import React from 'react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, ReferenceLine,
} from 'recharts'
import type { SHAPFactor } from '../../store/types'

interface SHAPWaterfallProps {
  factors: SHAPFactor[]
  height?: number
}

const CustomTooltip = ({ active, payload }: any) => {
  if (!active || !payload?.length) return null
  const d = payload[0].payload
  return (
    <div className="bg-surface2 border border-border-dark rounded-lg px-3 py-2 text-xs shadow-card">
      <p className="text-text-primary font-medium mb-0.5">{d.feature}</p>
      <p className={d.value >= 0 ? 'text-danger' : 'text-success'}>
        SHAP: {d.value >= 0 ? '+' : ''}{d.value.toFixed(4)}
      </p>
      <p className="text-text-secondary">Feature value: {d.raw_value}</p>
    </div>
  )
}

const formatFeatureName = (name: string) =>
  name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()).slice(0, 28)

export default function SHAPWaterfall({ factors, height = 320 }: SHAPWaterfallProps) {
  const sorted = [...factors]
    .sort((a, b) => Math.abs(b.shap_value) - Math.abs(a.shap_value))
    .slice(0, 12)

  const data = sorted.map((f) => ({
    feature: formatFeatureName(f.feature_name ?? f.human_readable_name),
    value: f.shap_value,
    raw_value: typeof f.feature_value === 'number'
      ? Number(f.feature_value).toFixed(3)
      : String(f.feature_value ?? '—'),
    fill: f.shap_value >= 0 ? '#DC2626' : '#16A34A',
  }))

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart
        data={data}
        layout="vertical"
        margin={{ top: 4, right: 24, left: 8, bottom: 4 }}
        barCategoryGap="20%"
      >
        <XAxis
          type="number"
          tick={{ fill: '#94A3B8', fontSize: 10 }}
          axisLine={{ stroke: '#1E2D45' }}
          tickLine={false}
          tickFormatter={(v) => v.toFixed(2)}
        />
        <YAxis
          type="category"
          dataKey="feature"
          width={160}
          tick={{ fill: '#94A3B8', fontSize: 11 }}
          axisLine={false}
          tickLine={false}
        />
        <ReferenceLine x={0} stroke="#1E2D45" strokeWidth={1.5} />
        <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(37,99,235,0.06)' }} />
        <Bar dataKey="value" radius={[0, 3, 3, 0]} maxBarSize={20}>
          {data.map((entry, index) => (
            <Cell key={`cell-${index}`} fill={entry.fill} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
