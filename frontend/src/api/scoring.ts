import { get, post } from './client'
import type { ScoreResult, QualitativeResult, QualitativeFormData } from '../store/types'

interface FeatureVectorResponse {
  company_id: string
  feature_vector: Record<string, number>
  feature_names: string[]
}

export const computeScore = (body: {
  company_id?: string
  feature_vector?: Record<string, number>
  qualitative_delta?: number
}): Promise<ScoreResult> => post<ScoreResult>('/scoring/credit', body)

export const submitQualitative = (body: QualitativeFormData): Promise<QualitativeResult> =>
  post<QualitativeResult>('/scoring/qualitative', body)

export const applyQualitative = (body: {
  scoring_result: ScoreResult
  qualitative_delta: number
}): Promise<ScoreResult> => post<ScoreResult>('/scoring/qualitative/apply', body)

export const buildFeatureVector = (body: {
  company_id: string
}): Promise<FeatureVectorResponse> =>
  post<FeatureVectorResponse>('/scoring/feature-vector', body)

export const getFeatureVector = (companyId: string): Promise<FeatureVectorResponse> =>
  get<FeatureVectorResponse>(`/scoring/feature-vector/${companyId}`)
