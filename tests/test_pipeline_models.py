"""
test_pipeline_models.py — Unit tests for models/pipeline_models.py.

Validates all enums, dataclass defaults, serialisation, and factory fields.

Usage:
    python tests/test_pipeline_models.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ── ANSI helpers ──────────────────────────────────────────────────────────────
_GREEN = "\033[92m"
_RED   = "\033[91m"
_CYAN  = "\033[96m"
_RESET = "\033[0m"
_BOLD  = "\033[1m"

_results: list[tuple[str, bool, str]] = []


def check(name: str, expr: bool, detail: str = ""):
    tag = f"{_GREEN}PASS{_RESET}" if expr else f"{_RED}FAIL{_RESET}"
    _results.append((name, expr, detail))
    print(f"  [{tag}] {name}" + (f"  ({detail})" if detail and not expr else ""))


def report():
    passed = sum(1 for _, ok, _ in _results if ok)
    failed = sum(1 for _, ok, _ in _results if not ok)
    print(f"\n{_BOLD}{'='*60}")
    print(f"  {_GREEN}{passed} passed{_RESET}, {_RED}{failed} failed{_RESET}")
    print(f"{'='*60}{_RESET}")
    return 0 if failed == 0 else 1


# ── Import ────────────────────────────────────────────────────────────────────
from models.pipeline_models import (
    RiskLevel, RiskBand, Decision, ConfidenceFlag, SMAClassification,
    SynthesisMethod, ParseResult, FinancialMetric, RiskClause,
    FinancialExtractionResult, NERResult, IngestStageResult,
    BankAnomaly, BankAnalysisResult, GSTReconciliationResult, EWSFlags,
    NewsReport, ECourtsReport, MCAReport, RBICheck, SynthesisReport,
    ResearchResult, FeatureVector, SHAPExplanation, ScoreResult,
    LoanDecision, QualitativeResult, FiveCsText,
    StageResult, DataQualityReport, PipelineResult,
)


def test_enums():
    print(f"\n{_CYAN}{_BOLD}── Enum tests ──{_RESET}")
    # RiskLevel
    check("RiskLevel members count", len(RiskLevel) == 4)
    check("RiskLevel.HIGH value", RiskLevel.HIGH == "HIGH")
    check("RiskLevel from string", RiskLevel("MEDIUM") == RiskLevel.MEDIUM)

    # RiskBand
    check("RiskBand members count", len(RiskBand) == 4)
    check("RiskBand.PRIME value", RiskBand.PRIME == "PRIME")

    # Decision
    check("Decision members count", len(Decision) == 3)
    check("Decision.REJECT value", Decision.REJECT == "REJECT")
    check("Decision.CONDITIONAL_APPROVE value", Decision.CONDITIONAL_APPROVE == "CONDITIONAL_APPROVE")

    # ConfidenceFlag
    check("ConfidenceFlag members", len(ConfidenceFlag) == 3)
    check("ConfidenceFlag.EXTRACTED", ConfidenceFlag.EXTRACTED == "EXTRACTED")

    # SMAClassification
    check("SMAClassification members", len(SMAClassification) == 3)
    check("SMA-0 value", SMAClassification.SMA_0 == "SMA-0")

    # SynthesisMethod
    check("SynthesisMethod members", len(SynthesisMethod) == 3)
    check("SynthesisMethod.LLM", SynthesisMethod.LLM == "llm")


def test_stage1_dataclasses():
    print(f"\n{_CYAN}{_BOLD}── Stage 1 dataclasses ──{_RESET}")
    # ParseResult defaults
    pr = ParseResult()
    check("ParseResult default text is empty", pr.text == "")
    check("ParseResult default pages_processed", pr.pages_processed == 0)
    check("ParseResult default doc_type", pr.doc_type == "unknown")

    # FinancialMetric
    fm = FinancialMetric(value=100.5, flag=ConfidenceFlag.EXTRACTED)
    check("FinancialMetric value", fm.value == 100.5)
    check("FinancialMetric flag", fm.flag == ConfidenceFlag.EXTRACTED)
    check("FinancialMetric default flag is MISSING", FinancialMetric().flag == ConfidenceFlag.MISSING)

    # RiskClause
    rc = RiskClause(clause_type="going_concern", raw_text="doubt about...", severity="HIGH")
    check("RiskClause severity", rc.severity == "HIGH")

    # FinancialExtractionResult
    fer = FinancialExtractionResult()
    check("FinancialExtractionResult default revenue is MISSING", fer.revenue.flag == ConfidenceFlag.MISSING)
    check("FinancialExtractionResult default risk_clauses empty", fer.risk_clauses == [])

    # NERResult
    ner = NERResult()
    check("NERResult default sentiment neutral", ner.sentiment_label == "neutral")

    # IngestStageResult
    isr = IngestStageResult(company_name="Test Corp", company_id="COMP_TEST", success=True)
    check("IngestStageResult company_name", isr.company_name == "Test Corp")
    check("IngestStageResult success", isr.success is True)


def test_stage2_dataclasses():
    print(f"\n{_CYAN}{_BOLD}── Stage 2 dataclasses ──{_RESET}")
    ba = BankAnalysisResult()
    check("BankAnalysisResult default bounce_count", ba.bounce_count == 0)
    check("BankAnalysisResult default anomalies empty", ba.anomalies == [])
    check("BankAnalysisResult default success", ba.success is False)

    anomaly = BankAnomaly(anomaly_type="round_tripping", severity="HIGH")
    check("BankAnomaly type", anomaly.anomaly_type == "round_tripping")


def test_stage3_dataclasses():
    print(f"\n{_CYAN}{_BOLD}── Stage 3 dataclasses ──{_RESET}")
    gst = GSTReconciliationResult()
    check("GST default health_score", gst.health_score == 5.0)
    check("GST default grade", gst.grade == "B")
    check("GST default circular_trading_flag", gst.circular_trading_flag == "CLEAR")

    ews = EWSFlags()
    check("EWSFlags default ews_score", ews.ews_score == 0.0)
    check("EWSFlags default sma_classification", ews.sma_classification == "SMA-0")


def test_stage4_dataclasses():
    print(f"\n{_CYAN}{_BOLD}── Stage 4 dataclasses ──{_RESET}")
    news = NewsReport()
    check("NewsReport default timed_out", news.timed_out is False)
    check("NewsReport default risk_score", news.news_risk_score == 0.0)

    ecourts = ECourtsReport()
    check("ECourtsReport default nclt_override", ecourts.nclt_override is False)

    mca = MCAReport()
    check("MCAReport default cin empty", mca.cin == "")

    rbi = RBICheck()
    check("RBICheck default any_match", rbi.any_match is False)

    synth = SynthesisReport()
    check("SynthesisReport default method", synth.synthesis_method == "rule_based")

    research = ResearchResult(success=True)
    check("ResearchResult success", research.success is True)
    check("ResearchResult default elapsed_ms", research.elapsed_ms == 0.0)


def test_stage5_dataclasses():
    print(f"\n{_CYAN}{_BOLD}── Stage 5 dataclasses ──{_RESET}")
    # FeatureVector
    fv = FeatureVector(
        values=[1.0, 2.0, 3.0],
        feature_names=["a", "b", "c"],
    )
    check("FeatureVector to_dict", fv.to_dict() == {"a": 1.0, "b": 2.0, "c": 3.0})
    np_arr = fv.to_numpy()
    check("FeatureVector to_numpy shape", np_arr.shape == (3,))
    check("FeatureVector to_numpy dtype", str(np_arr.dtype) == "float64")

    # ScoreResult
    sr = ScoreResult(default_probability=0.08, risk_score=9.2, risk_band="PRIME")
    check("ScoreResult default_probability", sr.default_probability == 0.08)
    check("ScoreResult scorer_trained default", ScoreResult().scorer_trained is True)

    # LoanDecision
    ld = LoanDecision()
    check("LoanDecision default REJECT", ld.decision == "REJECT")
    check("LoanDecision default reject_reasons empty", ld.reject_reasons == [])


def test_cam_dataclasses():
    print(f"\n{_CYAN}{_BOLD}── CAM dataclasses ──{_RESET}")
    fc = FiveCsText(character="Good", capacity="Adequate")
    check("FiveCsText character", fc.character == "Good")
    check("FiveCsText default generation_method", fc.generation_method == "rule_based")

    qa = QualitativeResult(total_adjustment=-1.5)
    check("QualitativeResult adjustment", qa.total_adjustment == -1.5)


def test_tracking_dataclasses():
    print(f"\n{_CYAN}{_BOLD}── Tracking dataclasses ──{_RESET}")
    sr = StageResult(stage_name="ingest", success=True, elapsed_ms=1234.5)
    check("StageResult name", sr.stage_name == "ingest")
    check("StageResult elapsed_ms", sr.elapsed_ms == 1234.5)

    dq = DataQualityReport(
        imputed_features=["gst_health_score", "news_risk_score"],
        tools_timed_out=["tavily"],
    )
    check("DataQualityReport imputed count", len(dq.imputed_features) == 2)
    check("DataQualityReport timed_out count", len(dq.tools_timed_out) == 1)
    check("DataQualityReport default scorer_trained", dq.scorer_trained is True)


def test_pipeline_result():
    print(f"\n{_CYAN}{_BOLD}── PipelineResult ──{_RESET}")
    pr = PipelineResult(
        company_id="TEST_001",
        company_name="Test Corp",
    )
    check("PipelineResult company_id", pr.company_id == "TEST_001")
    check("PipelineResult default errors empty", pr.errors == [])
    check("PipelineResult default stage_results empty", pr.stage_results == {})
    check("PipelineResult created_at is ISO string", "T" in pr.created_at)
    check("PipelineResult ingest is None by default", pr.ingest is None)

    # Verify mutable defaults are independent
    pr2 = PipelineResult(company_id="TEST_002")
    pr.errors.append("test error")
    check("PipelineResult mutable default independence", len(pr2.errors) == 0)


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n{_BOLD}{'='*60}")
    print(f"  Pipeline Models Unit Tests")
    print(f"{'='*60}{_RESET}")

    test_enums()
    test_stage1_dataclasses()
    test_stage2_dataclasses()
    test_stage3_dataclasses()
    test_stage4_dataclasses()
    test_stage5_dataclasses()
    test_cam_dataclasses()
    test_tracking_dataclasses()
    test_pipeline_result()

    exit_code = report()
    sys.exit(exit_code)
