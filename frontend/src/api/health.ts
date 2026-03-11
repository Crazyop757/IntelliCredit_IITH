import { get } from './client'

export interface HealthResponse {
  status: 'ok' | 'degraded' | 'offline'
  service: string
  components: Record<string, string>
}

export function checkHealth(): Promise<HealthResponse> {
  return get<HealthResponse>('/health')
}
