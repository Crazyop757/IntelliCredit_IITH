import { apiClient } from './client';

export interface AppraisalSummary {
  id: string;
  job_id: string;
  company_name: string;
  company_id: string | null;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  decision: string | null;
  risk_band: string | null;
  default_probability: number | null;
  credit_limit: number | null;
  interest_rate: number | null;
  created_at: string;
  updated_at: string;
}

export interface HistoryResponse {
  appraisals: AppraisalSummary[];
  count: number;
  limit: number;
  offset: number;
}

export interface StatsResponse {
  total: number;
  completed: number;
  approved: number;
  rejected: number;
  avg_default_probability: number | null;
}

export interface HistoryParams {
  limit?: number;
  offset?: number;
  status?: string;
  company_id?: string;
}

export async function fetchHistory(params: HistoryParams = {}): Promise<HistoryResponse> {
  const { data } = await apiClient.get<HistoryResponse>('/analysis/history', { params });
  return data;
}

export async function fetchStats(): Promise<StatsResponse> {
  const { data } = await apiClient.get<StatsResponse>('/analysis/stats');
  return data;
}

export async function fetchAppraisalDetail(id: string): Promise<AppraisalSummary & { result_json: Record<string, unknown> | null }> {
  const { data } = await apiClient.get(`/analysis/appraisals/${id}`);
  return data;
}
