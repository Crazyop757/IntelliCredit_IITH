import { useState, useCallback } from 'react'
import toast from 'react-hot-toast'
import { generateCAM, getCAMJob, downloadCAMFile } from '../api/cam'
import type { FiveCsText } from '../store/types'

interface CAMRequest {
  company_id: string
  company_name: string
  cin?: string
  five_cs_text?: FiveCsText
  scoring_result?: unknown
  research_report?: unknown
}

interface DownloadState {
  loading: boolean
  jobId: string | null
  error: string | null
}

export function useDownload() {
  const [state, setState] = useState<DownloadState>({ loading: false, jobId: null, error: null })

  const download = useCallback(async (req: CAMRequest) => {
    setState({ loading: true, jobId: null, error: null })
    const toastId = toast.loading('Generating CAM report…')

    try {
      const { job_id } = await generateCAM(req)
      setState((s) => ({ ...s, jobId: job_id }))

      // Poll until done
      let attempts = 0
      const maxAttempts = 60 // 2 minutes
      while (attempts < maxAttempts) {
        await new Promise((res) => setTimeout(res, 2000))
        attempts++

        const jobStatus = await getCAMJob(job_id)

        if (jobStatus.status === 'DONE') {
          toast.success('CAM report ready — downloading!', { id: toastId })
          await downloadCAMFile(job_id)
          setState({ loading: false, jobId: job_id, error: null })
          return
        }

        if (jobStatus.status === 'FAILED') {
          const msg = jobStatus.error || 'CAM generation failed'
          toast.error(msg, { id: toastId })
          setState({ loading: false, jobId: job_id, error: msg })
          return
        }
      }

      // Timeout
      toast.error('CAM generation timed out', { id: toastId })
      setState({ loading: false, jobId: job_id, error: 'Timed out' })
    } catch (err: any) {
      const msg = err?.response?.data?.detail || err?.message || 'Download failed'
      toast.error(msg, { id: toastId })
      setState({ loading: false, jobId: null, error: msg })
    }
  }, [])

  return { ...state, download }
}
