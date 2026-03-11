"""
pipeline_models.py — Typed dataclasses for all inter-stage data contracts.

This module is the **single source of truth** for every data shape that
flows between pipeline stages.  All stage functions MUST accept and return
these types rather than raw dicts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


# ══════════════════════════════════════════════════════════════════════════════
# Enums
# ══════════════════════════════════════════════════════════════════════════════

class RiskLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    CLEAR = "CLEAR"


class RiskBand(str, Enum):
    PRIME = "PRIME"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Decision(str, Enum):
    APPROVE = "APPROVE"
    CONDITIONAL_APPROVE = "CONDITIONAL_APPROVE"
    REJECT = "REJECT"


class ConfidenceFlag(str, Enum):
    EXTRACTED = "EXTRACTED"
    ESTIMATED = "ESTIMATED"
    MISSING = "MISSING"


class SMAClassification(str, Enum):
    SMA_0 = "SMA-0"
    SMA_1 = "SMA-1"
    SMA_2 = "SMA-2"


class SynthesisMethod(str, Enum):
    LLM = "llm"
    RULE_BASED = "rule_based"
    GENERIC_FALLBACK = "generic_fallback"


# ══════════════════════════════════════════════════════════════════════════════
# Stage 1 — Document Ingestion
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ParseResult:
    """Output from pdf_parser.py."""
    text: str = ""
    pages_processed: int = 0
    doc_type: str = "unknown"
    doc_type_confidence: float = 0.0
    company_name_guessed: Optional[str] = None
    tables: list[list[list[str]]] = field(default_factory=list)
    ocr_used: bool = False
    extraction_success: bool = False
    text_length: int = 0


@dataclass
class FinancialMetric:
    """A single extracted financial figure with confidence."""
    value: Optional[float] = None
    flag: ConfidenceFlag = ConfidenceFlag.MISSING
    raw_snippet: Optional[str] = None


@dataclass
class RiskClause:
    """A risk clause found in a document."""
    clause_type: str = ""
    raw_text: str = ""
    severity: str = "LOW"


@dataclass
class FinancialExtractionResult:
    """Output from financial_extractor.py."""
    revenue: FinancialMetric = field(default_factory=FinancialMetric)
    ebitda: FinancialMetric = field(default_factory=FinancialMetric)
    pat: FinancialMetric = field(default_factory=FinancialMetric)
    total_debt: FinancialMetric = field(default_factory=FinancialMetric)
    net_worth: FinancialMetric = field(default_factory=FinancialMetric)
    interest_expense: FinancialMetric = field(default_factory=FinancialMetric)
    debt_service: FinancialMetric = field(default_factory=FinancialMetric)
    current_assets: FinancialMetric = field(default_factory=FinancialMetric)
    current_liabilities: FinancialMetric = field(default_factory=FinancialMetric)
    # Computed ratios
    current_ratio: Optional[float] = None
    debt_to_equity: Optional[float] = None
    interest_coverage: Optional[float] = None
    dscr: Optional[float] = None
    pat_margin: Optional[float] = None
    # Risk and directors
    risk_clauses: list[RiskClause] = field(default_factory=list)
    directors: list[dict[str, str]] = field(default_factory=list)
    # Sentiment
    sentiment_score: float = 0.0
    auditor_qualified_opinion: bool = False


@dataclass
class NERResult:
    """Output from ner_extractor.py."""
    entities: list[dict[str, Any]] = field(default_factory=list)
    sentiment_score: float = 0.0
    sentiment_label: str = "neutral"
    auditor_qualified_opinion: bool = False
    money_entities: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class IngestStageResult:
    """Combined result of Stage 1 (PDF parsing + financial extraction + NER)."""
    parse_result: Optional[ParseResult] = None
    financials: Optional[FinancialExtractionResult] = None
    ner_result: Optional[NERResult] = None
    company_name: str = ""
    company_id: str = ""
    directors: list[dict[str, str]] = field(default_factory=list)
    success: bool = False
    error: Optional[str] = None
    elapsed_ms: float = 0.0


# ══════════════════════════════════════════════════════════════════════════════
# Stage 2 — Bank Statement Analysis
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class BankAnomaly:
    """A single anomaly detected in bank statement analysis."""
    anomaly_type: str = ""
    description: str = ""
    severity: str = "LOW"
    evidence_rows: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class BankAnalysisResult:
    """Output from bank_analyzer.py."""
    avg_monthly_balance_cr: float = 0.0
    total_annual_credits_cr: float = 0.0
    total_annual_debits_cr: float = 0.0
    debit_credit_ratio: float = 0.0
    bounce_count: int = 0
    upi_concentration: float = 0.0
    cash_deposit_concentration: float = 0.0
    emi_outflows_cr: float = 0.0
    salary_credits_detected: bool = False
    anomalies: list[BankAnomaly] = field(default_factory=list)
    months_analysed: int = 0
    header_mapping_method: str = "exact"  # "exact" or "fuzzy"
    success: bool = False
    error: Optional[str] = None
    elapsed_ms: float = 0.0


# ══════════════════════════════════════════════════════════════════════════════
# Stage 3 — GST Analysis + Fraud Detection
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class GSTReconciliationResult:
    """Output from reconciler.py."""
    health_score: float = 5.0
    grade: str = "B"
    itc_gap_pct: float = 0.0
    itc_claimed_3b: float = 0.0
    itc_available_2a: float = 0.0
    turnover_consistency: float = 0.5
    filing_regularity: float = 0.5
    fictitious_vendor_count: int = 0
    revenue_inflation_flag: bool = False
    circular_trading_flag: str = "CLEAR"
    gst_itc_fraud_risk: str = "LOW"
    graph_nodes: list[dict[str, Any]] = field(default_factory=list)
    graph_edges: list[dict[str, Any]] = field(default_factory=list)
    circular_patterns: list[dict[str, Any]] = field(default_factory=list)
    gnn_model_unavailable: bool = False
    gnn_high_risk_count: int = 0
    success: bool = False
    error: Optional[str] = None
    elapsed_ms: float = 0.0


@dataclass
class EWSFlags:
    """Output from ews_engine.py."""
    gst_itc_fraud_risk: str = "LOW"
    circular_trading_risk: str = "CLEAR"
    revenue_inflation_risk: str = "LOW"
    cash_stress_risk: str = "LOW"
    documentation_risk: str = "LOW"
    auditor_concern_risk: str = "LOW"
    director_risk: str = "LOW"
    compliance_risk: str = "LOW"
    ews_score: float = 0.0
    sma_classification: str = "SMA-0"


# ══════════════════════════════════════════════════════════════════════════════
# Stage 4 — External Intelligence (Research Agent)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class NewsReport:
    """Output from news_tool.py."""
    articles: list[dict[str, Any]] = field(default_factory=list)
    news_risk_score: float = 0.0
    negative_article_count: int = 0
    most_alarming_headline: Optional[str] = None
    risk_tags: list[str] = field(default_factory=list)
    timed_out: bool = False
    api_key_missing: bool = False


@dataclass
class ECourtsReport:
    """Output from ecourts_tool.py."""
    cases: list[dict[str, Any]] = field(default_factory=list)
    litigation_risk_score: float = 0.0
    nclt_override: bool = False
    total_case_count: int = 0
    timed_out: bool = False
    using_mock_data: bool = False


@dataclass
class MCAReport:
    """Output from mca_tool.py."""
    company_name: str = ""
    cin: str = ""
    status: str = ""
    date_of_incorporation: Optional[str] = None
    authorized_capital: Optional[float] = None
    paid_up_capital: Optional[float] = None
    charges_count: int = 0
    compliance_flags: list[str] = field(default_factory=list)
    timed_out: bool = False
    company_not_found: bool = False


@dataclass
class RBICheck:
    """Output from rbi_tool.py."""
    any_match: bool = False
    directors_checked: list[str] = field(default_factory=list)
    matches: list[dict[str, Any]] = field(default_factory=list)
    timed_out: bool = False
    rbi_data_unavailable: bool = False


@dataclass
class SynthesisReport:
    """Output from synthesizer.py."""
    overall_external_risk_score: float = 5.0
    promoter_risk_flag: str = "CLEAR"
    litigation_summary: str = ""
    news_summary: str = ""
    regulatory_compliance_summary: str = ""
    key_red_flags: list[str] = field(default_factory=list)
    positive_signals: list[str] = field(default_factory=list)
    recommended_action: str = "CONDITIONAL"
    synthesis_method: str = "rule_based"  # "llm" | "rule_based"
    tools_timed_out: list[str] = field(default_factory=list)


@dataclass
class ResearchResult:
    """Combined result of Stage 4 (all 4 research tools + synthesis)."""
    news_report: NewsReport = field(default_factory=NewsReport)
    ecourts_report: ECourtsReport = field(default_factory=ECourtsReport)
    mca_report: MCAReport = field(default_factory=MCAReport)
    rbi_check: RBICheck = field(default_factory=RBICheck)
    synthesis_report: SynthesisReport = field(default_factory=SynthesisReport)
    overall_external_risk_score: float = 5.0
    success: bool = False
    error: Optional[str] = None
    elapsed_ms: float = 0.0


# ══════════════════════════════════════════════════════════════════════════════
# Stage 5 — Credit Scoring
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class FeatureVector:
    """Output from feature_builder.py — the Gold-layer ML input."""
    values: list[float] = field(default_factory=list)  # shape [35]
    feature_names: list[str] = field(default_factory=list)  # len 35
    imputed_flags: dict[str, bool] = field(default_factory=dict)

    def to_numpy(self):
        import numpy as np
        return np.array(self.values, dtype=np.float64)

    def to_dict(self) -> dict[str, float]:
        return dict(zip(self.feature_names, self.values))


@dataclass
class SHAPExplanation:
    """A single SHAP factor explanation."""
    feature_name: str = ""
    human_readable_name: str = ""
    feature_value: Optional[float] = None
    shap_value: float = 0.0
    direction: str = "risk"  # "risk" | "protective"


@dataclass
class ScoreResult:
    """Output from credit_scorer.py."""
    default_probability: Optional[float] = None
    risk_score: Optional[float] = None
    risk_band: str = "UNSCORED"
    top_risk_factors: list[SHAPExplanation] = field(default_factory=list)
    top_positive_factors: list[SHAPExplanation] = field(default_factory=list)
    scorer_trained: bool = True
    error: Optional[str] = None


@dataclass
class LoanDecision:
    """Final loan decision output."""
    decision: str = "REJECT"
    recommended_amount: Optional[float] = None
    interest_rate: Optional[float] = None
    tenure_months: Optional[int] = None
    decision_rationale: str = ""
    reject_reasons: list[str] = field(default_factory=list)


@dataclass
class QualitativeResult:
    """Output from qualitative_scorer.py."""
    total_adjustment: float = 0.0
    breakdown: dict[str, float] = field(default_factory=dict)
    classification_method: str = "rule_based"  # "llm" | "rule_based"


# ══════════════════════════════════════════════════════════════════════════════
# CAM Generation
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class FiveCsText:
    """Output from five_cs_writer.py."""
    character: str = ""
    capacity: str = ""
    capital: str = ""
    collateral: str = ""
    conditions: str = ""
    generation_method: str = "rule_based"  # "llm" | "rule_based"


# ══════════════════════════════════════════════════════════════════════════════
# Stage Tracking
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class StageResult:
    """Tracking info for a single pipeline stage."""
    stage_name: str = ""
    success: bool = False
    elapsed_ms: float = 0.0
    error: Optional[str] = None


@dataclass
class DataQualityReport:
    """Aggregated data quality information across all stages."""
    imputed_features: list[str] = field(default_factory=list)
    tools_timed_out: list[str] = field(default_factory=list)
    models_unavailable: list[str] = field(default_factory=list)
    synthesis_method: str = "llm"
    gnn_model_unavailable: bool = False
    scorer_trained: bool = True
    tectonic_available: bool = True
    warnings: list[str] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════════
# Pipeline Result — the top-level output
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class PipelineResult:
    """
    The complete output of run_full_pipeline().

    Every value shown in the UI MUST trace back to a field in this object
    or be clearly labelled as imputed.
    """
    company_id: str = ""
    company_name: str = ""
    cin: Optional[str] = None
    loan_amount_requested: Optional[float] = None
    loan_tenure_months: Optional[int] = None

    # Stage outputs
    ingest: Optional[IngestStageResult] = None
    bank_analysis: Optional[BankAnalysisResult] = None
    gst_analysis: Optional[GSTReconciliationResult] = None
    research: Optional[ResearchResult] = None
    score_result: Optional[ScoreResult] = None
    ews_flags: Optional[EWSFlags] = None
    loan_decision: Optional[LoanDecision] = None
    five_cs: Optional[FiveCsText] = None
    qualitative: Optional[QualitativeResult] = None

    # Financials
    financials_3yr: list[dict[str, Any]] = field(default_factory=list)

    # Tracking
    stage_results: dict[str, StageResult] = field(default_factory=dict)
    data_quality_report: Optional[DataQualityReport] = None
    pipeline_log: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    # Feature audit trail
    feature_vector: Optional[FeatureVector] = None

    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
