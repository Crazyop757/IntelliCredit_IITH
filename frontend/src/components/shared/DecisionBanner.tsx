import React from 'react'
import { motion } from 'framer-motion'
import { CheckCircle2, XCircle, AlertTriangle, TrendingUp } from 'lucide-react'
import type { ScoreResult } from '../../store/types'
import { formatINR } from '../../utils/formatters'

interface DecisionBannerProps {
  score: ScoreResult
}

const configs = {
  APPROVE: {
    bg: 'from-success/15 to-success/5',
    border: 'border-success/30',
    icon: CheckCircle2,
    iconColor: 'text-success',
    badge: 'bg-success/15 text-success border border-success/30',
    title: 'Recommended for Approval',
  },
  CONDITIONAL: {
    bg: 'from-gold/15 to-gold/5',
    border: 'border-gold/30',
    icon: AlertTriangle,
    iconColor: 'text-gold',
    badge: 'bg-gold/15 text-gold border border-gold/30',
    title: 'Conditional Approval',
  },
  REJECT: {
    bg: 'from-danger/15 to-danger/5',
    border: 'border-danger/30',
    icon: XCircle,
    iconColor: 'text-danger',
    badge: 'bg-danger/15 text-danger border border-danger/30',
    title: 'Not Recommended',
  },
}

export default function DecisionBanner({ score }: DecisionBannerProps) {
  const decision = (score.decision || 'CONDITIONAL') as keyof typeof configs
  const cfg = configs[decision] || configs.CONDITIONAL
  const Icon = cfg.icon

  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className={[
        'rounded-2xl border bg-gradient-to-br p-6',
        cfg.bg,
        cfg.border,
      ].join(' ')}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-4">
          <div className="w-12 h-12 rounded-xl bg-black/20 flex items-center justify-center flex-shrink-0">
            <Icon size={24} className={cfg.iconColor} />
          </div>
          <div>
            <div className="flex items-center gap-2 mb-1">
              <h3 className="text-text-primary text-lg font-bold">{cfg.title}</h3>
              <span className={`text-xs font-semibold px-2.5 py-1 rounded-full ${cfg.badge}`}>
                {decision}
              </span>
            </div>
            {score.decision_rationale && (
              <p className="text-text-secondary text-sm max-w-xl leading-relaxed">
                {score.decision_rationale}
              </p>
            )}
          </div>
        </div>

        {/* Key metrics */}
        <div className="flex items-center gap-6 flex-shrink-0">
          <div className="text-center">
            <p className="text-text-muted text-xs mb-0.5">Risk Score</p>
            <p className="text-text-primary text-2xl font-bold">{score.risk_score.toFixed(1)}</p>
            <p className="text-text-muted text-xs">/ 10.0</p>
          </div>
          {score.recommended_loan_amount != null && (
            <div className="text-center">
              <p className="text-text-muted text-xs mb-0.5">Loan Limit</p>
              <p className="text-text-primary text-2xl font-bold">
                {formatINR(score.recommended_loan_amount)}
              </p>
              <div className="flex items-center gap-1 justify-center">
                <TrendingUp size={10} className="text-text-muted" />
                <p className="text-text-muted text-xs">
                  {score.recommended_interest_rate
                    ? `${score.recommended_interest_rate} p.a.`
                    : ''}
                </p>
              </div>
            </div>
          )}
          {score.default_probability != null && (
            <div className="text-center">
              <p className="text-text-muted text-xs mb-0.5">Prob. of Default</p>
              <p className="text-text-primary text-2xl font-bold">
                {(score.default_probability * 100).toFixed(1)}%
              </p>
            </div>
          )}
        </div>
      </div>
    </motion.div>
  )
}
