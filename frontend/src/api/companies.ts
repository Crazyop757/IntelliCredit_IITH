import { get } from './client'
import type { CompanyDetailData, CompanyListItem } from '../store/types'

interface CompaniesListResponse {
  companies: CompanyListItem[]
  total: number
}

interface CompanyBronzeRecord {
  doc_id: string
  company_id: string
  ingested_at: string
  doc_type: string
  file_name: string
  quality_flag: string
}

interface CompanySilverRecord {
  company_id: string
  fiscal_year: string
  revenue?: number
  pat?: number
  [key: string]: unknown
}

interface CompanyGoldRecord {
  company_id: string
  created_at: string
  features: Record<string, number>
}

export const listCompanies = (): Promise<CompaniesListResponse> =>
  get<CompaniesListResponse>('/companies')

export const getCompany = (id: string): Promise<CompanyDetailData> =>
  get<CompanyDetailData>(`/companies/${id}`)

export const getCompanyBronze = (id: string): Promise<CompanyBronzeRecord[]> =>
  get<CompanyBronzeRecord[]>(`/companies/${id}/bronze`)

export const getCompanySilver = (id: string): Promise<CompanySilverRecord[]> =>
  get<CompanySilverRecord[]>(`/companies/${id}/silver`)

export const getCompanyGold = (id: string): Promise<CompanyGoldRecord[]> =>
  get<CompanyGoldRecord[]>(`/companies/${id}/gold`)
