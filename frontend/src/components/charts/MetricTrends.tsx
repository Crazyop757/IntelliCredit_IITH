import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, Area, AreaChart } from 'recharts'
import { TrendingUp, TrendingDown, Minus } from 'lucide-react' 
import { motion } from 'framer-motion'

interface MetricPoint {
  period: string
  value: number
}

interface MetricTrendsProps {
  metrics: {
    label: string
    data: MetricPoint[]
    color: string
    trend?: 'up' | 'down' | 'stable'
    unit?: string
  }[]
}

export default function MetricTrends({ metrics }: MetricTrendsProps) {
  const formatValue = (value: number, unit?: string) => {
    if (!unit) return value.toFixed(2)
    if (unit === '%') return `${value.toFixed(1)}%`
    if (unit === '₹') {
      if (value >= 10000000) return `₹${(value / 10000000).toFixed(2)}Cr`
      if (value >= 100000) return `₹${(value / 100000).toFixed(2)}L`
      return `₹${value.toFixed(0)}`
    }
    return `${value.toFixed(2)} ${unit}`
  }

  const getTrendIcon = (trend?: 'up' | 'down' | 'stable') => {
    if (trend === 'up') return <TrendingUp size={14} className="text-green-600" />
    if (trend === 'down') return <TrendingDown size={14} className="text-red-600" />
    return <Minus size={14} className="text-text-muted" />
  }

  const getTrendColor = (trend?: 'up' | 'down' | 'stable') => {
    if (trend === 'up') return 'text-green-600 bg-green-500/10'
    if (trend === 'down') return 'text-red-600 bg-red-500/10'
    return 'text-text-secondary bg-surface2'
  }

  return (
    <div className="bg-surface rounded-xl border border-border-dark p-6">
      <div className="mb-6">
        <h3 className="text-lg font-semibold text-text-primary mb-1">Key Metrics Trends</h3>
        <p className="text-xs text-text-muted">Performance indicators over time</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {metrics.map((metric, idx) => {
          const latestValue = metric.data[metric.data.length - 1]?.value || 0
          const previousValue = metric.data[metric.data.length - 2]?.value || latestValue
          const changePercent = previousValue !== 0 
            ? ((latestValue - previousValue) / previousValue * 100)
            : 0

          return (
            <motion.div
              key={metric.label}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: idx * 0.1 }}
              className="border border-border-dark rounded-lg p-4"
            >
              {/* Metric Header */}
              <div className="flex items-start justify-between mb-4">
                <div>
                  <div className="text-sm font-semibold text-text-primary mb-1">{metric.label}</div>
                  <div className="text-2xl font-bold" style={{ color: metric.color }}>
                    {formatValue(latestValue, metric.unit)}
                  </div>
                </div>
                <div className={`flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-medium ${getTrendColor(metric.trend)}`}>
                  {getTrendIcon(metric.trend)}
                  {changePercent >= 0 ? '+' : ''}{changePercent.toFixed(1)}%
                </div>
              </div>

              {/* Mini Chart */}
              <ResponsiveContainer width="100%" height={100}>
                <AreaChart data={metric.data} margin={{ top: 5, right: 0, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id={`gradient-${idx}`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor={metric.color} stopOpacity={0.3}/>
                      <stop offset="95%" stopColor={metric.color} stopOpacity={0}/>
                    </linearGradient>
                  </defs>
                  <Area
                    type="monotone"
                    dataKey="value"
                    stroke={metric.color}
                    strokeWidth={2}
                    fill={`url(#gradient-${idx})`}
                    animationDuration={800}
                  />
                  <Tooltip
                    content={({ active, payload }) => {
                      if (active && payload && payload.length) {
                        return (
                          <div className="bg-surface rounded-lg shadow-lg p-2 border border-border-dark">
                            <div className="text-xs font-semibold text-text-primary">
                              {formatValue(payload[0].value as number, metric.unit)}
                            </div>
                          </div>
                        )
                      }
                      return null
                    }}
                  />
                </AreaChart>
              </ResponsiveContainer>

              {/* Period Range */}
              <div className="mt-2 flex items-center justify-between text-xs text-text-muted">
                <span>{metric.data[0]?.period || ''}</span>
                <span>{metric.data[metric.data.length - 1]?.period || ''}</span>
              </div>
            </motion.div>
          )
        })}
      </div>
    </div>
  )
}
