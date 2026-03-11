interface SkeletonProps {
  className?: string
  width?: string | number
  height?: string | number
  rounded?: boolean
  circle?: boolean
  count?: number
}

export default function Skeleton({
  className = '',
  width,
  height,
  rounded = false,
  circle = false,
  count = 1,
}: SkeletonProps) {
  const baseClass = [
    'animate-pulse bg-surface2',
    circle ? 'rounded-full' : rounded ? 'rounded-full' : 'rounded-md',
    className,
  ].join(' ')

  const style: React.CSSProperties = {}
  if (width) style.width = typeof width === 'number' ? `${width}px` : width
  if (height) style.height = typeof height === 'number' ? `${height}px` : height

  if (count > 1) {
    return (
      <div className="flex flex-col gap-2">
        {Array.from({ length: count }).map((_, i) => (
          <div key={i} className={baseClass} style={style} />
        ))}
      </div>
    )
  }

  return <div className={baseClass} style={style} />
}

import React from 'react'

export function CardSkeleton({ className = '' }: { className?: string }) {
  return (
    <div className={`bg-surface border border-border-dark rounded-xl p-5 ${className}`}>
      <div className="flex items-center gap-3 mb-4">
        <Skeleton circle width={40} height={40} />
        <div className="flex-1">
          <Skeleton height={14} className="mb-2 w-1/3" />
          <Skeleton height={12} className="w-1/2" />
        </div>
      </div>
      <Skeleton height={48} className="mb-3" />
      <Skeleton height={12} className="mb-2 w-3/4" />
      <Skeleton height={12} className="w-1/2" />
    </div>
  )
}

export function TableSkeleton({ rows = 5, cols = 5 }: { rows?: number; cols?: number }) {
  return (
    <div className="overflow-hidden rounded-xl border border-border-dark">
      <div className="bg-surface px-4 py-3 border-b border-border-dark">
        <div className="flex gap-6">
          {Array.from({ length: cols }).map((_, i) => (
            <Skeleton key={i} height={12} className="flex-1 max-w-[120px]" />
          ))}
        </div>
      </div>
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className="px-4 py-3 border-b border-border-dark"
          style={{ background: i % 2 === 0 ? '#0D1117' : '#111827' }}
        >
          <div className="flex gap-6">
            {Array.from({ length: cols }).map((_, j) => (
              <Skeleton key={j} height={12} className="flex-1 max-w-[120px]" />
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

export function MetricCardSkeleton() {
  return (
    <div className="bg-surface border border-border-dark rounded-xl p-5">
      <div className="flex items-center justify-between mb-3">
        <Skeleton height={12} className="w-24" />
        <Skeleton circle width={32} height={32} />
      </div>
      <Skeleton height={36} className="w-32 mb-2" />
      <Skeleton height={10} className="w-20" />
    </div>
  )
}
