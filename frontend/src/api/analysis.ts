import { get, postForm } from './client'
import type { PipelineJob, JobRef } from '../store/types'

export const runFullPipeline = (formData: FormData): Promise<JobRef> =>
  postForm<JobRef>('/analysis/pipeline', formData)

export const getPipelineJob = (id: string): Promise<PipelineJob> =>
  get<PipelineJob>(`/analysis/jobs/${id}`)

export const getLatestPipelineResult = (companyId: string): Promise<PipelineJob> =>
  get<PipelineJob>(`/analysis/${companyId}/latest`)
