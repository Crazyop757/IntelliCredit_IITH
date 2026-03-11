import { useCallback } from 'react'
import { useSessionStore } from '../store/sessionStore'
import type { Company, FullPipelineResult, PipelineJob, QualitativeFormData } from '../store/types'

export function useSession() {
  const session_id = useSessionStore((s) => s.session_id)
  const company = useSessionStore((s) => s.company)
  const job_id = useSessionStore((s) => s.job_id)
  const results = useSessionStore((s) => s.results)
  const qualitative_submitted = useSessionStore((s) => s.qualitative_submitted)
  const last_appraised_at = useSessionStore((s) => s.last_appraised_at)

  const setSession = useSessionStore((s) => s.setSession)
  const setCompany = useSessionStore((s) => s.setCompany)
  const setJobId = useSessionStore((s) => s.setJobId)
  const setResults = useSessionStore((s) => s.setResults)
  const setPipelineStatus = useSessionStore((s) => s.setPipelineStatus)
  const setQualitativeSubmitted = useSessionStore((s) => s.setQualitativeSubmitted)
  const setQualitativeData = useSessionStore((s) => s.setQualitativeData)
  const setLastAppraisedAt = useSessionStore((s) => s.setLastAppraisedAt)
  const reset = useSessionStore((s) => s.reset)

  const startSession = useCallback(
    (sessionId: string, companyData: Company) => {
      setSession(sessionId)
      setCompany(companyData)
      setLastAppraisedAt(new Date().toISOString())
    },
    [setSession, setCompany, setLastAppraisedAt],
  )

  const recordJob = useCallback(
    (jobId: string) => {
      setJobId(jobId)
    },
    [setJobId],
  )

  const recordResults = useCallback(
    (res: FullPipelineResult) => {
      setResults(res)
    },
    [setResults],
  )

  const recordQualitative = useCallback(
    (data: QualitativeFormData) => {
      setQualitativeData(data)
      setQualitativeSubmitted(true)
    },
    [setQualitativeData, setQualitativeSubmitted],
  )

  return {
    session_id,
    company,
    job_id,
    results,
    qualitative_submitted,
    last_appraised_at,
    startSession,
    recordJob,
    recordResults,
    recordQualitative,
    setPipelineStatus,
    reset,
  }
}
