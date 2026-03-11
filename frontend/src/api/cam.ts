import { get, post, downloadFile } from './client'
import type { JobRef, FiveCsText } from '../store/types'

interface CAMJobStatus {
  job_id: string
  job_type: string
  status: 'PENDING' | 'RUNNING' | 'DONE' | 'FAILED'
  result?: { output_path: string; file_size_bytes: number }
  error?: string
}

export const generateCAM = (body: {
  company_id: string
  company_name: string
  cin?: string
  loan_amount_requested?: number
  loan_tenure_months?: number
  decision?: string
  recommended_amount?: number
  interest_rate?: number
  five_cs_text?: FiveCsText
  scoring_result?: unknown
  research_report?: unknown
}): Promise<JobRef> => post<JobRef>('/cam/generate', body)

export const getCAMJob = (id: string): Promise<CAMJobStatus> =>
  get<CAMJobStatus>(`/cam/jobs/${id}`)

export const downloadCAMFile = (id: string, filename?: string): Promise<void> =>
  downloadFile(`/cam/jobs/${id}/download`, filename)

export const generateFiveCs = (body: {
  company_data: Record<string, unknown>
  financials?: Record<string, unknown>
  research_report?: Record<string, unknown>
  scoring_result?: Record<string, unknown>
}): Promise<FiveCsText> => post<FiveCsText>('/cam/five-cs', body)
