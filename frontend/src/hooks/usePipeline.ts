import { useQuery } from '@tanstack/react-query'
import { getPipelineJob } from '../api/analysis'
import type { PipelineJob } from '../store/types'

export function usePipeline(jobId: string | null) {
  const query = useQuery<PipelineJob>({
    queryKey: ['pipeline', jobId],
    queryFn: () => getPipelineJob(jobId!),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const data = query.state.data
      if (!data) return 2000
      if (data.status === 'DONE' || data.status === 'FAILED') return false
      return 2000
    },
    staleTime: 0,
    gcTime: 60000,
  })

  return {
    job: query.data,
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isComplete: query.data?.status === 'DONE',
    isFailed: query.data?.status === 'FAILED',
    isRunning: query.data?.status === 'RUNNING',
    progress: query.data?.progress_pct ?? 0,
    currentStage: query.data?.current_stage ?? null,
    refetch: query.refetch,
  }
}
