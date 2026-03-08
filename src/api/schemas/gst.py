"""
Schemas for GST endpoints.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ITCMonthlyEntry(BaseModel):
    period: str
    itc_as_per_2a: Optional[float] = None
    itc_claimed_3b: Optional[float] = None
    gap: Optional[float] = None
    gap_pct: Optional[float] = None
    risk: Optional[str] = None


class ITCReconciliationSummary(BaseModel):
    total_itc_as_per_2a: Optional[float] = None
    total_itc_claimed_3b: Optional[float] = None
    total_gap: Optional[float] = None
    total_gap_percentage: Optional[float] = None
    overall_risk: Optional[str] = None
    high_risk_periods: List[str] = []
    suspicious_periods: List[str] = []
    periods_analysed: int = 0


class ITCReconciliationResult(BaseModel):
    monthly: List[ITCMonthlyEntry] = []
    summary: ITCReconciliationSummary


class TurnoverMonthlyEntry(BaseModel):
    period: str
    gstr1_turnover: Optional[float] = None
    bank_credits: Optional[float] = None
    ratio: Optional[float] = None
    flag: Optional[str] = None


class TurnoverReconciliationSummary(BaseModel):
    total_gstr1_turnover: Optional[float] = None
    total_bank_credits: Optional[float] = None
    overall_bank_to_declared_ratio: Optional[float] = None
    overall_flag: Optional[str] = None
    unexplained_income_periods: List[str] = []
    revenue_inflation_periods: List[str] = []
    periods_analysed: int = 0


class TurnoverReconciliationResult(BaseModel):
    monthly: List[TurnoverMonthlyEntry] = []
    summary: TurnoverReconciliationSummary


class FictitiousVendorResult(BaseModel):
    fictitious_gstins: List[str] = []
    fictitious_vendor_count: int = 0
    risk: Optional[str] = None
    known_2a_supplier_count: int = 0
    details: Optional[List[Dict[str, Any]]] = None


class GSTHealthScore(BaseModel):
    score: float = Field(..., ge=0.0, le=10.0)
    max: float = 10.0
    grade: str  # A | B | C | D
    components: Optional[Dict[str, Any]] = None


class GSTReconcileRequest(BaseModel):
    """Used when GST data is already stored (company_id known)."""
    company_id: str
    bank_credits: Optional[Dict[str, float]] = Field(
        None,
        description="Monthly bank credits dict {YYYY-MM: amount_inr} for turnover cross-check",
    )


class GSTReconcileResponse(BaseModel):
    company_id: str
    itc_reconciliation: Optional[ITCReconciliationResult] = None
    turnover_reconciliation: Optional[TurnoverReconciliationResult] = None
    fictitious_vendors: Optional[FictitiousVendorResult] = None
    health_score: Optional[GSTHealthScore] = None


class EWSRequest(BaseModel):
    company_id: str


class EWSFlag(BaseModel):
    flag_name: str
    level: str       # HIGH | MEDIUM | LOW | CLEAR
    weight: float
    weighted_contribution: float


class EWSResponse(BaseModel):
    company_id: str
    ews_score: float = Field(..., description="0–5 weighted EWS score")
    sma_classification: str  # SMA-0 | SMA-1 | SMA-2
    flags: List[EWSFlag] = []
    summary: Optional[str] = None
    full_report: Optional[Dict[str, Any]] = None


class GNNPrediction(BaseModel):
    gstin: str
    fraud_probability: float
    risk_label: str  # HIGH_RISK | MEDIUM_RISK | LOW_RISK


class GNNPredictResponse(BaseModel):
    company_id: str
    predictions: List[GNNPrediction] = []
    circular_patterns: List[Dict[str, Any]] = []
    suspicious_clusters: List[Dict[str, Any]] = []


class GraphBuildResponse(BaseModel):
    node_count: int
    edge_count: int
    circular_pattern_count: int
    suspicious_cluster_count: int
    node_risk_scores: Optional[Dict[str, float]] = None
    visualization_path: Optional[str] = None
