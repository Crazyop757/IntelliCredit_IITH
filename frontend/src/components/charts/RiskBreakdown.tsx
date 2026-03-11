import { PieChart, Pie, Cell, ResponsiveContainer, Legend, Tooltip } from 'recharts'
import { AlertTriangle, CheckCircle, AlertCircle, XCircle } from 'lucide-react'
import { motion } from 'framer-motion'

interface RiskCategory {
  name: string
  value: number
  color: string
  icon: React.ReactNode
  description: string
}

interface RiskBreakdownProps {
  riskFactors: {
    high: number
    medium: number
    low: number
    minimal: number
  }
  totalScore: number
}

export default function RiskBreakdown({ riskFactors, totalScore }: RiskBreakdownProps) {
  const categories: RiskCategory[] = [
    {
      name: 'High Risk',
      value: riskFactors.high,
      color: '#EF4444',
      icon: <XCircle size={16} />,
      description: 'Critical issues requiring immediate attention'
    },
    {
      name: 'Medium Risk',
      value: riskFactors.medium,
      color: '#F97316',
      icon: <AlertTriangle size={16} />,
      description: 'Moderate concerns needing review'
    },
    {
      name: 'Low Risk',
      value: riskFactors.low,
      color: '#F59E0B',
      icon: <AlertCircle size={16} />,
      description: 'Minor issues with low impact'
    },
    {
      name: 'Clean',
      value: riskFactors.minimal,
      color: '#10B981',
      icon: <CheckCircle size={16} />,
      description: 'No significant risks detected'
    }
  ]

  const data = categories.map(cat => ({
    name: cat.name,
    value: cat.value,
    color: cat.color
  }))

  const total = data.reduce((sum, item) => sum + item.value, 0)

  const CustomTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length) {
      const data = payload[0]
      const percentage = total > 0 ? ((data.value / total) * 100).toFixed(1) : '0.0'
      return (
        <div className="bg-surface rounded-lg shadow-xl p-3 border border-border-dark">
          <div className="text-sm font-semibold text-text-primary mb-1">{data.name}</div>
          <div className="text-xs text-text-secondary">
            {data.value} factors ({percentage}%)
          </div>
        </div>
      )
    }
    return null
  }

  const renderCustomLabel = (entry: any) => {
    const percentage = total > 0 ? ((entry.value / total) * 100).toFixed(0) : '0'
    return `${percentage}%`
  }

  return (
    <div className="bg-surface rounded-xl border border-border-dark p-6">
      <div className="flex items-center justify-between mb-6">
        <h3 className="text-lg font-semibold text-text-primary">Risk Factor Breakdown</h3>
        <div className="text-right">
          <div className="text-xs text-text-muted mb-0.5">Overall Score</div>
          <div className={`text-2xl font-bold ${
            totalScore >= 7 ? 'text-green-600' :
            totalScore >= 5 ? 'text-blue-600' :
            totalScore >= 3 ? 'text-orange-600' :
            'text-red-600'
          }`}>
            {totalScore.toFixed(1)}/10
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Donut Chart */}
        <div className="relative">
          {total > 0 ? (
            <ResponsiveContainer width="100%" height={240}>
              <PieChart>
                <Pie
                  data={data}
                  cx="50%"
                  cy="50%"
                  labelLine={false}
                  label={renderCustomLabel}
                  outerRadius={90}
                  innerRadius={50}
                  fill="#8884d8"
                  dataKey="value"
                  animationBegin={0}
                  animationDuration={800}
                >
                  {data.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip content={<CustomTooltip />} />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-60 flex items-center justify-center text-text-muted">
              <div className="text-center">
                <AlertCircle size={48} className="mx-auto mb-2 opacity-50" />
                <div className="text-sm">No risk data available</div>
              </div>
            </div>
          )}

          {/* Center Label */}
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <div className="text-center">
              <div className="text-3xl font-bold text-text-primary">{total}</div>
              <div className="text-xs text-text-muted">Factors</div>
            </div>
          </div>
        </div>

        {/* Category List */}
        <div className="space-y-3">
          {categories.map((category, idx) => (
            <motion.div
              key={category.name}
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: idx * 0.1 }}
              className="flex items-start gap-3 p-3 rounded-lg hover:bg-surface2 transition-colors"
            >
              <div 
                className="mt-0.5 p-2 rounded-lg"
                style={{ backgroundColor: `${category.color}15` }}
              >
                <div style={{ color: category.color }}>
                  {category.icon}
                </div>
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between mb-1">
                  <div className="text-sm font-semibold text-text-primary">{category.name}</div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-text-secondary">{category.value}</span>
                    <div className="w-16 h-1.5 bg-border-dark rounded-full overflow-hidden">
                      <motion.div
                        initial={{ width: 0 }}
                        animate={{ width: total > 0 ? `${(category.value / total) * 100}%` : '0%' }}
                        transition={{ delay: idx * 0.1 + 0.3, duration: 0.6 }}
                        className="h-full rounded-full"
                        style={{ backgroundColor: category.color }}
                      />
                    </div>
                  </div>
                </div>
                <div className="text-xs text-text-muted">{category.description}</div>
              </div>
            </motion.div>
          ))}
        </div>
      </div>

      {/* Summary Stats */}
      <div className="mt-6 pt-6 border-t border-border-dark grid grid-cols-3 gap-4">
        <div className="text-center">
          <div className="text-xs text-text-muted mb-1">Critical Issues</div>
          <div className="text-lg font-bold text-red-600">{riskFactors.high}</div>
        </div>
        <div className="text-center">
          <div className="text-xs text-text-muted mb-1">Needs Review</div>
          <div className="text-lg font-bold text-orange-600">{riskFactors.medium + riskFactors.low}</div>
        </div>
        <div className="text-center">
          <div className="text-xs text-text-muted mb-1">Clean Signals</div>
          <div className="text-lg font-bold text-green-600">{riskFactors.minimal}</div>
        </div>
      </div>
    </div>
  )
}
