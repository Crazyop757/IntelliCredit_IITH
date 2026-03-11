import React from 'react'
import {
  ComposedChart, Bar, Line, XAxis, YAxis, Tooltip, Legend,
  ResponsiveContainer, CartesianGrid,
} from 'recharts'
import type { FinancialYear } from '../../store/types'
import { formatCrore } from '../../utils/formatters'

interface FinancialTrendProps {
  years: FinancialYear[]
  height?: number
}

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-surface2 border border-border-dark rounded-lg px-3 py-2 text-xs shadow-card space-y-1">
      <p className="text-text-primary font-semibold mb-1">{label}</p>
      {payload.map((p: any) => (
        <div key={p.dataKey} className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-sm flex-shrink-0" style={{ background: p.color }} />
          <span className="text-text-secondary">{p.name}:</span>
          <span className="text-text-primary font-medium">
            {p.dataKey === 'dscr'
              ? typeof p.value === 'number' ? p.value.toFixed(2) : '—'
              : formatCrore(p.value)}
          </span>
        </div>
      ))}
    </div>
  )
}

export default function FinancialTrend({ years, height = 280 }: FinancialTrendProps) {
  const data = years.map((y) => ({
    year: y.year ?? '',
    revenue: y.total_revenue ?? y.revenue ?? null,
    ebitda: y.ebitda ?? null,
    net_profit: y.net_profit ?? y.pat ?? null,
    dscr: y.dscr ?? null,
  }))

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 4, right: 16, left: 8, bottom: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1E2D45" vertical={false} />
        <XAxis
          dataKey="year"
          tick={{ fill: '#94A3B8', fontSize: 11 }}
          axisLine={{ stroke: '#1E2D45' }}
          tickLine={false}
        />
        <YAxis
          yAxisId="left"
          tick={{ fill: '#94A3B8', fontSize: 10 }}
          axisLine={false}
          tickLine={false}
          tickFormatter={(v) => `₹${(v / 1).toFixed(0)}Cr`}
          width={52}
        />
        <YAxis
          yAxisId="right"
          orientation="right"
          tick={{ fill: '#94A3B8', fontSize: 10 }}
          axisLine={false}
          tickLine={false}
          tickFormatter={(v) => v?.toFixed(1)}
          width={36}
        />
        <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(37,99,235,0.06)' }} />
        <Legend
          wrapperStyle={{ fontSize: 11, color: '#94A3B8', paddingTop: 8 }}
          formatter={(value) => <span style={{ color: '#94A3B8' }}>{value}</span>}
        />
        <Bar yAxisId="left" dataKey="revenue" name="Revenue" fill="#2563EB" opacity={0.7} radius={[3, 3, 0, 0]} maxBarSize={40} />
        <Bar yAxisId="left" dataKey="ebitda" name="EBITDA" fill="#0D9488" opacity={0.7} radius={[3, 3, 0, 0]} maxBarSize={40} />
        <Line yAxisId="right" type="monotone" dataKey="dscr" name="DSCR" stroke="#D97706" strokeWidth={2} dot={{ fill: '#D97706', r: 3 }} connectNulls />
      </ComposedChart>
    </ResponsiveContainer>
  )
}
