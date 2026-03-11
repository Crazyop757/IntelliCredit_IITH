import { useQuery } from '@tanstack/react-query'
import { checkHealth, type HealthResponse } from '../../api/health'
import { useUIStore } from '../../store/uiStore'
import { useEffect } from 'react'

const STATUS_COLORS: Record<string, string> = {
  ok: 'bg-green-600',
  degraded: 'bg-yellow-500',
  offline: 'bg-red-600',
}

const STATUS_TEXT: Record<string, string> = {
  ok: 'All systems operational',
  degraded: 'Some components degraded',
  offline: 'System offline — critical components unavailable',
}

export function HealthBanner() {
  const setApiOnline = useUIStore((s) => s.setApiOnline)

  const { data, isError } = useQuery<HealthResponse>({
    queryKey: ['health'],
    queryFn: checkHealth,
    refetchInterval: 30_000,
    retry: 1,
  })

  const status = isError ? 'offline' : data?.status ?? 'ok'
  const isHealthy = status === 'ok'

  useEffect(() => {
    setApiOnline(!isError && status !== 'offline')
  }, [isError, status, setApiOnline])

  if (isHealthy && !isError) return null

  const degradedComponents = data?.components
    ? Object.entries(data.components)
        .filter(([, v]) => v !== 'loaded' && v !== 'available' && v !== 'ok' && v !== 'configured' && v !== 'local_fallback')
        .map(([k, v]) => `${k}: ${v}`)
    : []

  return (
    <div
      className={`${STATUS_COLORS[status] ?? 'bg-red-600'} text-white px-4 py-2 text-sm flex items-center justify-between`}
    >
      <span className="font-medium">
        ⚠ {STATUS_TEXT[status] ?? 'System status unknown'}
      </span>
      {degradedComponents.length > 0 && (
        <span className="text-white/80 text-xs">
          {degradedComponents.join(' · ')}
        </span>
      )}
    </div>
  )
}
