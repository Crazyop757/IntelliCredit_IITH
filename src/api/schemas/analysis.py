"""
Schemas for the full analysis pipeline endpoint.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.api.schemas.ingest import (
    BankIngestResponse,
    GSTIngestResponse,
    PDFIngestResponse,
)
from src.api.schemas.research import ResearchResponse
from src.api.schemas.scoring import CreditScoreResponse


class PipelineRequest(BaseModel):
    """Trigger a full 5-stage pipeline for a company.

    Files are supplied as UploadFile in the multipart form; this schema
    captures the non-file metadata fields in the same form submit.
    """
    company_name: str
    company_id: Optional[str] = None
    cin: Optional[str] = None
    loan_amount_requested: Optional[float] = Field(None, ge=0)
    loan_tenure_months: Optional[int] = Field(None, ge=1)
    fiscal_year: Optional[int] = Field(None, ge=2000, le=2100)


class FinancialYear(BaseModel):
    year: str
    revenue: Optional[float] = None
    ebitda: Optional[float] = None
    pat: Optional[float] = None
    de_ratio: Optional[float] = None
    current_ratio: Optional[float] = None
    dscr: Optional[float] = None
    pat_margin_pct: Optional[float] = None
    roce_pct: Optional[float] = None


class PipelineDecision(BaseModel):
    decision: str           # APPROVE | CONDITIONAL_APPROVE | REJECT | PENDING
    recommended_amount: Optional[float] = None
    interest_rate: Optional[float] = None
    tenure_months: Optional[int] = None
    decision_rationale: Optional[str] = None


class PipelineResult(BaseModel):
    company_id: str
    company_name: str
    # Stage outputs
    pdf_extraction: Optional[PDFIngestResponse] = None
    bank_analysis: Optional[BankIngestResponse] = None
    gst_analysis: Optional[GSTIngestResponse] = None
    research: Optional[ResearchResponse] = None
    scoring: Optional[CreditScoreResponse] = None
    # Aggregated 3-year financials
    financials_3yr: List[FinancialYear] = []
    # Decision
    decision: PipelineDecision = Field(
        default_factory=lambda: PipelineDecision(decision="PENDING")
    )
    # Five C's text (keys: CHARACTER/CAPACITY/CAPITAL/COLLATERAL/CONDITIONS)
    five_cs_text: Optional[Dict[str, Any]] = None
    # Log of each stage
    pipeline_log: List[str] = []
    errors: List[str] = []
