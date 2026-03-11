import React from 'react'
import { motion } from 'framer-motion'
import { CheckCircle2, Loader2, XCircle, Circle, Clock } from 'lucide-react'
import type { PipelineStage } from '../../store/types'

interface StageCardProps {
  stage: PipelineStage
  index: number
}

const statusConfig = {
  done: {
    icon: CheckCircle2,
    iconClass: 'text-success',
    badge: 'Done',
    badgeClass: 'text-success bg-success/10',
    border: 'border-success/20',
    bg: 'bg-success/5',
  },
  running: {
    icon: Loader2,
    iconClass: 'text-primary animate-spin',
    badge: 'Running',
    badgeClass: 'text-primary bg-primary/10',
    border: 'border-primary/30',
    bg: 'bg-primary/5',
  },
  pending: {
    icon: Circle,
    iconClass: 'text-text-muted',
    badge: 'Pending',
    badgeClass: 'text-text-muted bg-surface2',
    border: 'border-border-dark',
    bg: 'bg-surface2/30',
  },
  failed: {
    icon: XCircle,
    iconClass: 'text-danger',
    badge: 'Failed',
    badgeClass: 'text-danger bg-danger/10',
    border: 'border-danger/30',
    bg: 'bg-danger/5',
  },
  skipped: {
    icon: Clock,
    iconClass: 'text-text-muted',
    badge: 'Skipped',
    badgeClass: 'text-text-muted bg-surface2',
    border: 'border-border-dark',
    bg: 'bg-surface2/30',
  },
}

export default function StageCard({ stage, index }: StageCardProps) {
  const config = statusConfig[stage.status as keyof typeof statusConfig] || statusConfig.pending
  const Icon = config.icon

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.08, duration: 0.3 }}
      className={[
        'flex items-start gap-4 p-4 rounded-xl border',
        config.bg,
        config.border,
      ].join(' ')}
    >
      <div className="flex-shrink-0 mt-0.5">
        <Icon size={20} className={config.iconClass} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2 mb-0.5">
          <h4 className="text-sm font-semibold text-text-primary">{stage.stage_name ?? stage.name}</h4>
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium flex-shrink-0 ${config.badgeClass}`}>
            {config.badge}
          </span>
        </div>
        {(stage.message ?? stage.output_snippet) && (
          <p className="text-xs text-text-secondary truncate">{stage.message ?? stage.output_snippet}</p>
        )}
        {stage.started_at && (
          <p className="text-xs text-text-muted mt-1">
            Started {new Date(stage.started_at).toLocaleTimeString()}
            {(stage.duration_s ?? stage.duration_seconds) != null &&
              ` · ${(stage.duration_s ?? stage.duration_seconds)!.toFixed(1)}s`}
          </p>
        )}
      </div>
    </motion.div>
  )
}
