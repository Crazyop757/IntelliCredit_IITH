import React from 'react'
import { motion } from 'framer-motion'
import { CheckCircle2, Clock, Loader2, XCircle, Circle } from 'lucide-react'
import type { PipelineJob } from '../../store/types'
import { PIPELINE_STAGES } from '../../utils/constants'

interface PipelineProgressProps {
  job: PipelineJob | undefined
}

type StageStatus = 'done' | 'running' | 'pending' | 'failed'

function getStageStatus(job: PipelineJob | undefined, stageKey: string): StageStatus {
  if (!job) return 'pending'
  const stageIndex = PIPELINE_STAGES.findIndex((s) => s.key === stageKey)
  const currentIndex = PIPELINE_STAGES.findIndex((s) => s.key === job.current_stage)

  if (job.status === 'FAILED' && currentIndex === stageIndex) return 'failed'
  if (currentIndex > stageIndex) return 'done'
  if (currentIndex === stageIndex && job.status === 'RUNNING') return 'running'
  if (job.status === 'DONE') return 'done'
  return 'pending'
}

const StatusIcon = ({ status }: { status: StageStatus }) => {
  if (status === 'done') return <CheckCircle2 size={18} className="text-success" />
  if (status === 'running') return <Loader2 size={18} className="text-primary animate-spin" />
  if (status === 'failed') return <XCircle size={18} className="text-danger" />
  return <Circle size={18} className="text-text-muted" />
}

export default function PipelineProgress({ job }: PipelineProgressProps) {
  const progress = job?.progress_pct ?? 0

  return (
    <div className="space-y-4">
      {/* Overall progress bar */}
      <div>
        <div className="flex justify-between items-center mb-2">
          <span className="text-sm text-text-secondary">Overall Progress</span>
          <span className="text-sm font-semibold text-text-primary">{Math.round(progress)}%</span>
        </div>
        <div className="h-2 bg-surface2 rounded-full overflow-hidden">
          <motion.div
            className="h-full rounded-full bg-gradient-to-r from-primary to-accent"
            initial={{ width: 0 }}
            animate={{ width: `${progress}%` }}
            transition={{ duration: 0.5, ease: 'easeOut' }}
          />
        </div>
      </div>

      {/* Stage list */}
      <div className="space-y-2">
        {PIPELINE_STAGES.map((stage, i) => {
          const status = getStageStatus(job, stage.key)
          return (
            <motion.div
              key={stage.key}
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.06 }}
              className={[
                'flex items-center gap-3 px-4 py-3 rounded-xl border transition-all',
                status === 'running' ? 'bg-primary/8 border-primary/30' : '',
                status === 'done' ? 'bg-success/5 border-success/20' : '',
                status === 'failed' ? 'bg-danger/8 border-danger/30' : '',
                status === 'pending' ? 'bg-surface2/40 border-border-dark' : '',
              ].join(' ')}
            >
              <StatusIcon status={status} />
              <div className="flex-1 min-w-0">
                <p className={[
                  'text-sm font-medium',
                  status === 'running' ? 'text-text-primary' : 'text-text-secondary',
                ].join(' ')}>
                  {stage.label}
                </p>
              </div>
              {status === 'running' && (
                <span className="text-xs text-primary font-medium animate-pulse">Processing…</span>
              )}
              {status === 'done' && (
                <span className="text-xs text-success font-medium">Done</span>
              )}
              {status === 'failed' && (
                <span className="text-xs text-danger font-medium">Failed</span>
              )}
            </motion.div>
          )
        })}
      </div>
    </div>
  )
}
