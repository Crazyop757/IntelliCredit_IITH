"""
Schemas for CAM (Credit Assessment Memorandum) generation.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Union

from pydantic import BaseModel, Field, field_validator


class FiveCsSection(BaseModel):
    section: str
    text: str
    word_count: int
    meets_min_length: bool


class FiveCsText(BaseModel):
    CHARACTER: Optional[FiveCsSection] = None
    CAPACITY: Optional[FiveCsSection] = None
    CAPITAL: Optional[FiveCsSection] = None
    COLLATERAL: Optional[FiveCsSection] = None
    CONDITIONS: Optional[FiveCsSection] = None


class CAMGenerateRequest(BaseModel):
    company_id: str
    company_name: str
    cin: Optional[str] = None
    loan_amount_requested: Optional[float] = Field(
        None, description="Loan amount in INR crores"
    )
    loan_tenure_months: Optional[int] = None
    decision: Optional[str] = None
    recommended_amount: Optional[float] = None
    interest_rate: Optional[float] = None
    # Scoring input (if already computed; will be re-computed if omitted)
    scoring_result: Optional[Dict[str, Any]] = None
    # Research input (if already run; will be re-run if omitted)
    research_report: Optional[Dict[str, Any]] = None
    # Five Cs (if already generated; will be auto-generated if omitted)
    five_cs_text: Optional[FiveCsText] = None


class CAMStatusResponse(BaseModel):
    job_id: str
    status: str
    download_url: Optional[str] = Field(
        None, description="Available when status=DONE"
    )
    file_name: Optional[str] = None
    error: Optional[str] = None


class FiveCsWriteRequest(BaseModel):
    """Generate Five C's narrative sections via LLM writer."""
    company_data: Dict[str, Any]
    financials: Optional[Dict[str, Any]] = None
    # Accept either a pre-parsed dict or a raw text string
    research_report: Optional[Union[Dict[str, Any], str]] = None
    scoring_result: Optional[Dict[str, Any]] = None

    @field_validator("research_report", mode="before")
    @classmethod
    def _normalise_report(cls, v):
        # If a raw string is supplied, wrap it in a simple dict
        if isinstance(v, str):
            return {"summary": v}
        return v
