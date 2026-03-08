"""
Schemas for credit scoring and qualitative scoring.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── Feature vector ────────────────────────────────────────────────────────────
class FeatureVectorRequest(BaseModel):
    """Build and optionally score a 35-feature vector for a stored company."""
    company_id: str
    run_ews_live: bool = False
    run_research_live: bool = False


class FeatureVectorResponse(BaseModel):
    company_id: str
    feature_vector: Dict[str, float]
    feature_names: List[str]


# ── Credit scoring ────────────────────────────────────────────────────────────
class CreditScoreRequest(BaseModel):
    """Either supply a raw feature_vector or a company_id (will build vector from data lake)."""
    company_id: Optional[str] = None
    feature_vector: Optional[Dict[str, float]] = Field(
        None,
        description="35-key feature dict.  Required if company_id is omitted.",
    )
    qualitative_delta: Optional[float] = Field(
        None,
        ge=-5.0,
        le=2.0,
        description="Qualitative adjustment to apply after ML scoring",
    )


class SHAPFactor(BaseModel):
    feature: str
    label: str
    shap_value: float
    direction: str   # RISK_DRIVER | PROTECTIVE


class CreditScoreResponse(BaseModel):
    company_id: Optional[str] = None
    default_probability: float = Field(..., ge=0.0, le=1.0)
    risk_score: float = Field(..., ge=0.0, le=10.0)
    risk_band: str          # PRIME | LOW | MEDIUM | HIGH
    raw_lgbm_proba: Optional[float] = None
    qualitative_adjusted: bool = False
    qualitative_delta: Optional[float] = None
    top_risk_factors: List[SHAPFactor] = []
    top_positive_factors: List[SHAPFactor] = []
    shap_base_value: Optional[float] = None


# ── Qualitative scoring ───────────────────────────────────────────────────────
class QualitativeFormData(BaseModel):
    # All fields mirror the qualitative_scorer FormData keys
    management_quality: Optional[str] = Field(
        None, description="EXCELLENT | GOOD | AVERAGE | POOR"
    )
    credit_utilization_pct: Optional[float] = Field(None, ge=0, le=200)
    industry_outlook: Optional[str] = None
    collateral_coverage: Optional[str] = None
    repayment_track_record: Optional[str] = None
    related_party_transactions: Optional[str] = None
    auditor_qualification: Optional[str] = None
    promoter_pledging_pct: Optional[float] = Field(None, ge=0, le=100)
    litigation_status: Optional[str] = None
    regulatory_compliance: Optional[str] = None
    # Allow arbitrary extra fields (open-ended form)
    model_config = {"extra": "allow"}


class QualitativeScoreResponse(BaseModel):
    total_adjustment: float = Field(description="Clamped to [-5.0, +2.0]")
    severity: str            # HIGH_RISK | MODERATE_RISK | NEUTRAL | POSITIVE
    red_flags_found: List[str] = []
    breakdown: Dict[str, Any]
    summary_text: str


class ApplyQualitativeRequest(BaseModel):
    """Apply qualitative delta to an existing credit score result."""
    scoring_result: CreditScoreResponse
    qualitative_adjustment: float = Field(..., ge=-5.0, le=2.0)
