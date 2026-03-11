import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts'
import { TrendingUp, TrendingDown, Activity } from 'lucide-react'
import { motion } from 'framer-motion'

interface TimelineDataPoint {
  period: string
  inflow: number
  outflow: number
  balance: number
  transactions: number
}

interface BankTransactionTimelineProps {
  data: TimelineDataPoint[]
  currency?: string
}

export default function BankTransactionTimeline({ 
  data, 
  currency = '₹' 
}: BankTransactionTimelineProps) {
  const formatCurrency = (value: number) => {
    if (Math.abs(value) >= 10000000) return `${currency}${(value / 10000000).toFixed(1)}Cr`
    if (Math.abs(value) >= 100000) return `${currency}${(value / 100000).toFixed(1)}L`
    if (Math.abs(value) >= 1000) return `${currency}${(value / 1000).toFixed(0)}K`
    return `${currency}${value.toFixed(0)}`
  }

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      return (
        <div className="bg-surface rounded-lg shadow-xl p-4 border border-border-dark">
          <div className="font-semibold text-text-primary mb-3">{label}</div>
          <div className="space-y-2 text-sm">
            {payload.map((entry: any, index: number) => (
              <div key={index} className="flex items-center justify-between gap-4">
                <div className="flex items-center gap-2">
                  <div 
                    className="w-3 h-3 rounded-full" 
                    style={{ backgroundColor: entry.color }}
                  />
                  <span className="text-text-secondary">{entry.name}:</span>
                </div>
                <span className="font-semibold text-text-primary">
                  {formatCurrency(entry.value)}
                </span>
              </div>
            ))}
            {payload[0]?.payload?.transactions && (
              <div className="pt-2 mt-2 border-t border-border-dark flex items-center justify-between">
                <span className="text-text-secondary text-xs">Transactions:</span>
                <span className="font-semibold text-text-primary text-xs">
                  {payload[0].payload.transactions}
                </span>
              </div>
            )}
          </div>
        </div>
      )
    }
    return null
  }

  // Calculate summary statistics
  const totalInflow = data.reduce((sum, d) => sum + d.inflow, 0)
  const totalOutflow = data.reduce((sum, d) => sum + d.outflow, 0)
  const avgBalance = data.reduce((sum, d) => sum + d.balance, 0) / data.length
  const netFlow = totalInflow - totalOutflow

  const stats = [
    {
      label: 'Total Inflow',
      value: totalInflow,
      icon: <TrendingUp size={16} />,
      color: 'text-green-600',
      bgColor: 'bg-green-500/10'
    },
    {
      label: 'Total Outflow',
      value: totalOutflow,
      icon: <TrendingDown size={16} />,
      color: 'text-red-600',
      bgColor: 'bg-red-500/10'
    },
    {
      label: 'Net Flow',
      value: netFlow,
      icon: <Activity size={16} />,
      color: netFlow >= 0 ? 'text-blue-600' : 'text-orange-600',
      bgColor: netFlow >= 0 ? 'bg-blue-500/10' : 'bg-orange-500/10'
    }
  ]

  return (
    <div className="bg-surface rounded-xl border border-border-dark p-6">
      <div className="mb-6">
        <h3 className="text-lg font-semibold text-text-primary mb-1">Bank Transaction Timeline</h3>
        <p className="text-xs text-text-muted">Cash flow analysis over time</p>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        {stats.map((stat, idx) => (
          <motion.div
            key={stat.label}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: idx * 0.1 }}
            className={`${stat.bgColor} rounded-lg p-4`}
          >
            <div className="flex items-center justify-between mb-2">
              <div className={`${stat.color}`}>
                {stat.icon}
              </div>
              <div className="text-xs text-text-secondary">{stat.label}</div>
            </div>
            <div className={`text-xl font-bold ${stat.color}`}>
              {formatCurrency(stat.value)}
            </div>
          </motion.div>
        ))}
      </div>

      {/* Area Chart */}
      <div className="relative">
        <ResponsiveContainer width="100%" height={300}>
          <AreaChart
            data={data}
            margin={{ top: 10, right: 10, left: 0, bottom: 0 }}
          >
            <defs>
              <linearGradient id="colorInflow" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#10B981" stopOpacity={0.3}/>
                <stop offset="95%" stopColor="#10B981" stopOpacity={0}/>
              </linearGradient>
              <linearGradient id="colorOutflow" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#EF4444" stopOpacity={0.3}/>
                <stop offset="95%" stopColor="#EF4444" stopOpacity={0}/>
              </linearGradient>
              <linearGradient id="colorBalance" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#3B82F6" stopOpacity={0.3}/>
                <stop offset="95%" stopColor="#3B82F6" stopOpacity={0}/>
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#1E293B" />
            <XAxis 
              dataKey="period" 
              tick={{ fontSize: 12, fill: '#94A3B8' }}
              stroke="#334155"
            />
            <YAxis 
              tick={{ fontSize: 12, fill: '#94A3B8' }}
              stroke="#334155"
              tickFormatter={(value) => formatCurrency(value)}
            />
            <Tooltip content={<CustomTooltip />} />
            <Legend 
              wrapperStyle={{ fontSize: '12px', paddingTop: '10px' }}
              iconType="circle"
            />
            <Area
              type="monotone"
              dataKey="inflow"
              name="Inflow"
              stroke="#10B981"
              strokeWidth={2}
              fill="url(#colorInflow)"
              animationDuration={1000}
            />
            <Area
              type="monotone"
              dataKey="outflow"
              name="Outflow"
              stroke="#EF4444"
              strokeWidth={2}
              fill="url(#colorOutflow)"
              animationDuration={1000}
            />
            <Area
              type="monotone"
              dataKey="balance"
              name="Balance"
              stroke="#3B82F6"
              strokeWidth={2}
              fill="url(#colorBalance)"
              animationDuration={1000}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Additional Insights */}
      <div className="mt-6 pt-6 border-t border-border-dark">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-center">
          <div>
            <div className="text-xs text-text-muted mb-1">Periods Analyzed</div>
            <div className="text-lg font-bold text-text-primary">{data.length}</div>
          </div>
          <div>
            <div className="text-xs text-text-muted mb-1">Avg Balance</div>
            <div className="text-lg font-bold text-blue-600">{formatCurrency(avgBalance)}</div>
          </div>
          <div>
            <div className="text-xs text-text-muted mb-1">Max Inflow</div>
            <div className="text-lg font-bold text-green-600">
              {formatCurrency(Math.max(...data.map(d => d.inflow)))}
            </div>
          </div>
          <div>
            <div className="text-xs text-text-muted mb-1">Max Outflow</div>
            <div className="text-lg font-bold text-red-600">
              {formatCurrency(Math.max(...data.map(d => d.outflow)))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
