import { AlertTriangle, CheckCircle, XCircle, Info } from 'lucide-react'
import type { DataQualityReport, StageResult } from '../../store/types'
import Card from '../ui/Card'

interface Props {
  report?: DataQualityReport
  stageResults?: Record<string, StageResult>
}

function StatusIcon({ status }: { status: string }) {
  if (status === 'ok') return <CheckCircle size={14} className="text-emerald-400" />
  if (status === 'partial') return <AlertTriangle size={14} className="text-gold" />
  return <XCircle size={14} className="text-red-400" />
}

export default function DataQualityPanel({ report, stageResults }: Props) {
  if (!report && !stageResults) return null

  const hasIssues =
    (report?.imputed_features?.length ?? 0) > 0 ||
    (report?.timed_out_tools?.length ?? 0) > 0

  return (
    <Card className="border border-border-dark">
      <div className="px-5 py-4">
        <div className="flex items-center gap-2 mb-3">
          <Info size={16} className="text-text-muted" />
          <h3 className="text-text-primary font-semibold text-sm">Data Quality Report</h3>
          {hasIssues && (
            <span className="text-[10px] bg-gold/20 text-gold px-2 py-0.5 rounded-full font-medium">
              Attention
            </span>
          )}
        </div>

        {/* Stage timings */}
        {stageResults && Object.keys(stageResults).length > 0 && (
          <div className="mb-4">
            <p className="text-text-muted text-xs mb-2 uppercase tracking-wider">Pipeline Stages</p>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-2">
              {Object.entries(stageResults).map(([name, sr]) => (
                <div
                  key={name}
                  className="bg-surface2 rounded-lg p-2.5 flex flex-col items-center text-center"
                >
                  <StatusIcon status={sr.status} />
                  <span className="text-text-secondary text-xs mt-1 capitalize">
                    {name.replace(/_/g, ' ')}
                  </span>
                  <span className="text-text-muted text-[10px]">{sr.elapsed_ms}ms</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Imputed features */}
        {report?.imputed_features && report.imputed_features.length > 0 && (
          <div className="mb-3">
            <p className="text-text-muted text-xs mb-1 uppercase tracking-wider">Imputed Features</p>
            <div className="flex flex-wrap gap-1.5">
              {report.imputed_features.map((f) => (
                <span
                  key={f}
                  className="text-[10px] bg-gold/10 text-gold border border-gold/20 px-2 py-0.5 rounded-full"
                >
                  {f}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Timed out tools */}
        {report?.timed_out_tools && report.timed_out_tools.length > 0 && (
          <div className="mb-3">
            <p className="text-text-muted text-xs mb-1 uppercase tracking-wider">Timed-Out Tools</p>
            <div className="flex flex-wrap gap-1.5">
              {report.timed_out_tools.map((t) => (
                <span
                  key={t}
                  className="text-[10px] bg-red-500/10 text-red-400 border border-red-500/20 px-2 py-0.5 rounded-full"
                >
                  {t}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Model availability */}
        {report?.model_availability && Object.keys(report.model_availability).length > 0 && (
          <div>
            <p className="text-text-muted text-xs mb-1 uppercase tracking-wider">Model Availability</p>
            <div className="flex flex-wrap gap-2">
              {Object.entries(report.model_availability).map(([name, available]) => (
                <span
                  key={name}
                  className={`text-[10px] px-2 py-0.5 rounded-full border ${
                    available
                      ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                      : 'bg-red-500/10 text-red-400 border-red-500/20'
                  }`}
                >
                  {name}: {available ? 'Online' : 'Offline'}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </Card>
  )
}
