import React, { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { AlertTriangle, ArrowRight } from 'lucide-react'
import { usePipeline } from '../hooks/usePipeline'
import { useSession } from '../hooks/useSession'
import PipelineProgress from '../components/pipeline/PipelineProgress'
import StageCard from '../components/pipeline/StageCard'
import LiveLog from '../components/pipeline/LiveLog'
import Card, { CardHeader, CardTitle, CardBody } from '../components/ui/Card'
import Button from '../components/ui/Button'
import CompanyHeader from '../components/shared/CompanyHeader'

export default function LiveAnalysis() {
  const navigate = useNavigate()
  const { job_id, company, recordResults } = useSession()
  const { job, isComplete, isFailed, isError } = usePipeline(job_id)

  useEffect(() => {
    if (isComplete && job?.result) {
      recordResults(job.result)
      const timer = setTimeout(() => navigate('/results'), 1200)
      return () => clearTimeout(timer)
    }
  }, [isComplete, job, recordResults, navigate])

  if (!job_id) {
    return (
      <div className="max-w-2xl mx-auto mt-12 text-center">
        <AlertTriangle size={40} className="text-gold mx-auto mb-3" />
        <h2 className="text-text-primary font-semibold text-lg mb-2">No active pipeline</h2>
        <p className="text-text-secondary text-sm mb-5">
          Start a new appraisal to run the credit analysis pipeline.
        </p>
        <Button onClick={() => navigate('/new')}>Start New Appraisal</Button>
      </div>
    )
  }

  const logLines: string[] = job?.stages
    ? job.stages.flatMap((s) => {
        const lines: string[] = []
        if (s.started_at) lines.push(`[${new Date(s.started_at).toLocaleTimeString()}] Starting: ${s.stage_name ?? s.name}`)
        if (s.output_snippet ?? s.message) lines.push(`  → ${s.output_snippet ?? s.message}`)
        if (s.status === 'done') lines.push(`  ✓ Done${(s.duration_s ?? s.duration_seconds) ? ` in ${(s.duration_s ?? s.duration_seconds)!.toFixed(1)}s` : ''}`)
        if (s.status === 'failed') lines.push(`  ✗ Failed`)
        return lines
      })
    : []

  return (
    <div className="max-w-4xl mx-auto space-y-5">
      {company && <CompanyHeader company={company} subtitle="Running AI Credit Analysis Pipeline" />}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Progress card */}
        <Card>
          <CardHeader>
            <CardTitle description={`Job: ${job_id}`}>Pipeline Progress</CardTitle>
          </CardHeader>
          <CardBody>
            <PipelineProgress job={job} />

            {isComplete && (
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className="mt-5 p-4 bg-success/10 border border-success/30 rounded-xl text-center"
              >
                <p className="text-success font-semibold mb-2">Pipeline Complete!</p>
                <Button
                  size="sm"
                  iconRight={<ArrowRight size={14} />}
                  onClick={() => navigate('/results')}
                >
                  View Results
                </Button>
              </motion.div>
            )}

            {isFailed && (
              <div className="mt-5 p-4 bg-danger/10 border border-danger/30 rounded-xl">
                <p className="text-danger font-semibold mb-1">Pipeline Failed</p>
                <p className="text-text-secondary text-xs">{job?.error || 'Check logs for details'}</p>
              </div>
            )}

            {isError && (
              <div className="mt-5 p-4 bg-gold/10 border border-gold/30 rounded-xl">
                <p className="text-gold font-semibold text-sm">Connection error — retrying…</p>
              </div>
            )}
          </CardBody>
        </Card>

        {/* Stage cards */}
        <div className="space-y-3">
          <h3 className="text-text-secondary text-sm font-medium px-1">Stage Details</h3>
          {job?.stages && job.stages.length > 0
            ? job.stages.map((stage, i) => (
                <StageCard key={stage.name ?? i} stage={stage} index={i} />
              ))
            : (
              <div className="text-text-muted text-sm p-4 bg-surface2/50 rounded-xl">
                Waiting for stage updates…
              </div>
            )}
        </div>
      </div>

      {/* Live log */}
      <LiveLog lines={logLines} />
    </div>
  )
}
