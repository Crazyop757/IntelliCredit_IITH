/**
 * GST Graph Visualization API client
 */
import api from './client'

export interface GraphNode {
  id: string
  name?: string
  total_sales: number
  total_purchases: number
  net_gst_paid: number
  risk_score: number
  is_circular: boolean
  is_suspicious: boolean
  sector?: string
  state?: string
}

export interface GraphEdge {
  source: string
  target: string
  invoice_value: number
  tax_amount: number
  transaction_count: number
  is_circular: boolean
}

export interface CircularPattern {
  cycle: string[]
  cycle_length: number
  cycle_value: number
  flag: string
  edges: any[]
}

export interface GraphVisualizationData {
  nodes: GraphNode[]
  edges: GraphEdge[]
  circular_patterns: CircularPattern[]
  suspicious_clusters: any[]
  stats: {
    total_nodes: number
    total_edges: number
    circular_trading_nodes: number
    suspicious_nodes: number
    total_transaction_value: number
    avg_risk_score: number
  }
}

/**
 * Fetch complete GST transaction graph data for visualization
 */
export async function fetchGraphVisualization(): Promise<GraphVisualizationData> {
  const response = await api.get<GraphVisualizationData>('/gst/graph/visualization')
  return response.data
}

/**
 * Fetch graph summary statistics
 */
export async function fetchGraphStats() {
  const response = await api.get('/gst/graph')
  return response.data
}
