"""
Schemas for document ingestion endpoints.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── Request extras (form fields alongside UploadFile) ─────────────────────────
class IngestPDFRequest(BaseModel):
    company_name: str = Field(..., description="Legal company name")
    company_id: Optional[str] = Field(
        None,
        description="Unique company identifier (auto-derived from name if omitted)",
    )
    fiscal_year: Optional[int] = Field(
        None, ge=2000, le=2100, description="Fiscal year of the document"
    )
    persist: bool = Field(True, description="Write extracted data to Delta Lake layers")


# ── Financial figures ─────────────────────────────────────────────────────────
class FinancialFigures(BaseModel):
    revenue: Optional[float] = Field(None, description="Revenue in INR crores")
    ebitda: Optional[float] = None
    pat: Optional[float] = Field(None, description="Profit after tax in INR crores")
    total_debt: Optional[float] = None
    net_worth: Optional[float] = None
    interest_expense: Optional[float] = None
    debt_service: Optional[float] = None
    current_assets: Optional[float] = None
    current_liabilities: Optional[float] = None


class FinancialRatios(BaseModel):
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None
    interest_coverage: Optional[float] = None
    dscr: Optional[float] = Field(None, description="Debt service coverage ratio")
    pat_margin: Optional[float] = None
    roce: Optional[float] = None


class Director(BaseModel):
    name: str
    designation: Optional[str] = None
    din: Optional[str] = None


class RiskClause(BaseModel):
    clause_text: str
    matched_phrase: str
    severity: str  # HIGH | MEDIUM | LOW
    context_snippet: str


# ── PDF ingest response ───────────────────────────────────────────────────────
class PDFIngestResponse(BaseModel):
    company_id: str
    company_name: str
    doc_type: str
    pages_processed: int
    fiscal_year: Optional[int] = None
    figures: FinancialFigures
    ratios: FinancialRatios
    directors: List[Director] = []
    risk_clauses: List[RiskClause] = []
    sentiment: Optional[Dict[str, Any]] = None
    auditor_sentiment: Optional[Dict[str, Any]] = None
    entities: Optional[Dict[str, Any]] = None
    bronze_id: Optional[str] = Field(None, description="Delta Lake bronze record id")
    quality_flag: Optional[str] = None


# ── Bank ingest response ──────────────────────────────────────────────────────
class BankIngestResponse(BaseModel):
    company_id: str
    avg_monthly_balance_cr: Optional[float] = Field(
        None, description="Average monthly balance in INR crores"
    )
    debit_credit_ratio: Optional[float] = None
    bounce_count: int = 0
    upi_concentration: Optional[float] = None
    cash_deposit_concentration: Optional[float] = None
    total_annual_credits_cr: Optional[float] = None
    anomalies: List[str] = []
    monthly_breakdown: Optional[List[Dict[str, Any]]] = None
    row_count: int = 0


# ── GST ingest response (quick health) ───────────────────────────────────────
class GSTIngestResponse(BaseModel):
    company_id: str
    health_score: Optional[float] = Field(None, description="0–10 GST health score")
    grade: Optional[str] = Field(None, description="A / B / C / D")
    itc_gap_pct: Optional[float] = None
    turnover_consistency: Optional[float] = None
    filing_regularity: Optional[float] = None
    fictitious_vendor_count: int = 0
    revenue_inflation_flag: bool = False
    verdict: Optional[str] = None
    full_report: Optional[Dict[str, Any]] = None


# ── Full ingest (all files at once) ──────────────────────────────────────────
class FullIngestResponse(BaseModel):
    company_id: str
    company_name: str
    pdf: Optional[PDFIngestResponse] = None
    bank: Optional[BankIngestResponse] = None
    gst: Optional[GSTIngestResponse] = None
    errors: List[str] = []
