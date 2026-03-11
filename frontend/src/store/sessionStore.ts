import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { SessionState, Company, PipelineJob, FullPipelineResult, QualitativeFormData } from './types'

export const useSessionStore = create<SessionState>()(
  persist(
    (set) => ({
      session_id: null,
      owner_user_id: null,
      company: null,
      job_id: null,
      pipeline_status: null,
      results: null,
      qualitative_submitted: false,
      last_appraised_at: null,
      qualitative_data: null,

      setSession: (id: string) => set({ session_id: id }),
      setOwnerUserId: (id: string | null) => set({ owner_user_id: id }),
      setCompany: (c: Company) => set({ company: c }),
      setJobId: (id: string) => set({ job_id: id }),
      setPipelineStatus: (s: PipelineJob) => set({ pipeline_status: s }),
      setResults: (r: FullPipelineResult) => set({ results: r }),
      setQualitativeSubmitted: (v: boolean) => set({ qualitative_submitted: v }),
      setQualitativeData: (d: QualitativeFormData) => set({ qualitative_data: d }),
      setLastAppraisedAt: (t: string) => set({ last_appraised_at: t }),

      reset: () =>
        set({
          session_id: null,
          owner_user_id: null,
          company: null,
          job_id: null,
          pipeline_status: null,
          results: null,
          qualitative_submitted: false,
          last_appraised_at: null,
          qualitative_data: null,
        }),
    }),
    {
      name: 'finsight_session',
      partialize: (state) => ({
        session_id: state.session_id,
        owner_user_id: state.owner_user_id,
        company: state.company,
        job_id: state.job_id,
        results: state.results,
        qualitative_submitted: state.qualitative_submitted,
        last_appraised_at: state.last_appraised_at,
        qualitative_data: state.qualitative_data,
      }),
    }
  )
)
