import React, { useEffect, useRef } from 'react'
import { Terminal } from 'lucide-react'

interface LiveLogProps {
  lines: string[]
  maxLines?: number
}

export default function LiveLog({ lines, maxLines = 200 }: LiveLogProps) {
  const bottomRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  const visibleLines = lines.slice(-maxLines)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const isNearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 80
    if (isNearBottom) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
    }
  }, [lines.length])

  const getLineColor = (line: string) => {
    const l = line.toLowerCase()
    if (l.includes('error') || l.includes('failed') || l.includes('exception')) return 'text-danger'
    if (l.includes('warn') || l.includes('warning')) return 'text-gold'
    if (l.includes('done') || l.includes('success') || l.includes('complete')) return 'text-success'
    if (l.includes('running') || l.includes('processing') || l.includes('start')) return 'text-primary'
    return 'text-text-secondary'
  }

  return (
    <div className="bg-[#0A0E17] border border-border-dark rounded-xl overflow-hidden shadow-inner">
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border-dark bg-surface2">
        <div className="flex gap-1.5 mr-1">
          <div className="w-2.5 h-2.5 rounded-full bg-red-500/70" />
          <div className="w-2.5 h-2.5 rounded-full bg-yellow-500/70" />
          <div className="w-2.5 h-2.5 rounded-full bg-green-500/70" />
        </div>
        <Terminal size={13} className="text-text-muted" />
        <span className="text-xs text-text-muted font-mono">pipeline.log</span>
        <span className="ml-auto text-xs text-text-muted">{lines.length} entries</span>
      </div>
      <div
        ref={containerRef}
        className="h-52 overflow-y-auto p-4 font-mono text-xs space-y-0.5"
        style={{ scrollbarWidth: 'thin', scrollbarColor: '#1E2D45 transparent' }}
      >
        {visibleLines.length === 0 ? (
          <p className="text-text-muted italic">Waiting for pipeline to start…</p>
        ) : (
          visibleLines.map((line, i) => (
            <div key={i} className={`leading-5 ${getLineColor(line)}`}>
              {line}
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
