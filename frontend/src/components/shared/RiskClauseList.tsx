import React, { useState } from 'react'
import { AlertTriangle, ChevronDown, ChevronUp } from 'lucide-react'
import type { RiskClause } from '../../store/types'
import { SeverityBadge } from '../ui/Badge'

interface RiskClauseListProps {
  clauses: RiskClause[]
  title?: string
  maxVisible?: number
}

const severityOrder: Record<string, number> = {
  CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3,
}

export default function RiskClauseList({
  clauses,
  title = 'Risk Clauses',
  maxVisible = 5,
}: RiskClauseListProps) {
  const [expanded, setExpanded] = useState(false)

  const sorted = [...clauses].sort(
    (a, b) => (severityOrder[a.severity] ?? 9) - (severityOrder[b.severity] ?? 9),
  )

  const visible = expanded ? sorted : sorted.slice(0, maxVisible)
  const hasMore = sorted.length > maxVisible

  if (clauses.length === 0) {
    return (
      <div className="flex items-center gap-2 text-success text-sm py-3">
        <span className="w-4 h-4 rounded-full bg-success/20 flex items-center justify-center text-xs">✓</span>
        No risk clauses identified
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {title && (
        <div className="flex items-center gap-2 mb-3">
          <AlertTriangle size={15} className="text-gold" />
          <h4 className="text-sm font-semibold text-text-primary">{title}</h4>
          <span className="text-xs text-text-muted ml-auto">{clauses.length} items</span>
        </div>
      )}
      {visible.map((clause, i) => (
        <div
          key={i}
          className="flex items-start gap-3 p-3 bg-surface2/60 border border-border-dark rounded-lg"
        >
          <SeverityBadge severity={clause.severity} className="flex-shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <p className="text-text-primary text-xs font-medium leading-relaxed">{clause.clause_text ?? clause.clause}</p>
            {clause.source && (
              <p className="text-text-muted text-xs mt-0.5 truncate">Source: {clause.source}</p>
            )}
          </div>
        </div>
      ))}
      {hasMore && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-1.5 text-xs text-text-secondary hover:text-primary transition-colors mt-1 px-1"
        >
          {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
          {expanded ? 'Show less' : `Show ${sorted.length - maxVisible} more`}
        </button>
      )}
    </div>
  )
}
