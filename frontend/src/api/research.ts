import { get, post } from './client'
import type { ResearchResult, JobRef } from '../store/types'

interface ResearchJobStatus {
  job_id: string
  job_type: string
  status: 'PENDING' | 'RUNNING' | 'DONE' | 'FAILED'
  result?: ResearchResult
  error?: string
}

export const runResearch = (body: {
  company_name: string
  company_cin?: string
  director_names?: string[]
}): Promise<JobRef> => post<JobRef>('/research/run', body)

export const getResearchJob = (id: string): Promise<ResearchJobStatus> =>
  get<ResearchJobStatus>(`/research/jobs/${id}`)

export const synthesizeResearch = (body: {
  news_report: unknown
  ecourts_report: unknown
  mca_report: unknown
  rbi_report: unknown
}): Promise<ResearchResult> => post<ResearchResult>('/research/synthesize', body)
