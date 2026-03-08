"""
Schemas for the research agent endpoints.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ResearchRequest(BaseModel):
    company_name: str
    company_cin: Optional[str] = None
    director_names: List[str] = []


class PromoterRiskFlag(BaseModel):
    level: str    # HIGH | MEDIUM | LOW | CLEAR
    reason: Optional[str] = None


class ResearchResponse(BaseModel):
    company_name: str
    overall_external_risk_score: float = Field(..., ge=0.0, le=10.0)
    promoter_risk_flag: Optional[PromoterRiskFlag] = None
    litigation_summary: Optional[str] = None
    news_summary: Optional[str] = None
    regulatory_compliance_summary: Optional[str] = None
    key_red_flags: List[str] = []
    positive_signals: List[str] = []
    recommended_action: Optional[str] = None  # PROCEED | CAUTION | REJECT
    recommended_rationale: Optional[str] = None
    synthesis_method: Optional[str] = None  # "llm" | "rule_based"
    news_report: Optional[Dict[str, Any]] = None
    ecourts_report: Optional[Dict[str, Any]] = None
    mca_report: Optional[Dict[str, Any]] = None
    rbi_report: Optional[Dict[str, Any]] = None


class SynthesizeRequest(BaseModel):
    """Synthesize already-fetched sub-reports without running the full agent."""
    news_report: Optional[Dict[str, Any]] = None
    ecourts_report: Optional[Dict[str, Any]] = None
    mca_report: Optional[Dict[str, Any]] = None
    rbi_report: Optional[Dict[str, Any]] = None
