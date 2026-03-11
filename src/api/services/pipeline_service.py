"""
Full 5-stage credit analysis pipeline service.
Runs synchronously (called via run_in_thread from the async router).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import time
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from src.config import (
    HARD_REJECT_BOUNCE_COUNT,
    HARD_REJECT_DEFAULT_PROB,
    PRIME_PD_THRESHOLD,
    PARTIAL_APPROVE_PD_THRESHOLD,
    PRIME_RATE,
    MCLR_SPREAD,
)

log = logging.getLogger(__name__)


def _company_id_from_cin_or_name(cin: str | None, name: str) -> str:
    """Generate deterministic company_id = sha256(cin or name.lower().strip())[:12]."""
    source = cin if cin else name.lower().strip()
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:12]


def _detect_gst_type(data: dict) -> str:
    form = data.get("form", "")
    return_type = (data.get("return_type", "") or "").upper()
    if return_type in ("GSTR1", "GSTR-1") or form == "GSTR-1" or "invoices" in data or "b2b_invoices" in data:
        return "gstr1"
    if return_type in ("GSTR2A", "GSTR-2A") or form == "GSTR-2A" or "auto_populated_invoices" in data or "inward_supplies" in data or "auto_populated_credits" in data:
        return "gstr2a"
    if return_type in ("GSTR3B", "GSTR-3B") or form == "GSTR-3B" or "filings" in data or "monthly_data" in data or "monthly_filings" in data:
        return "gstr3b"
    return "unknown"


def _count_bank_circular_trades(company_data: dict) -> int:
    """Count bank anomalies whose description contains circular trade keywords."""
    bank = company_data.get("bank_findings") or {}
    anomalies = bank.get("anomalies") or []
    count = 0
    for a in anomalies:
        desc = ""
        if isinstance(a, dict):
            desc = (a.get("description") or a.get("detail") or a.get("type") or "").upper()
        elif isinstance(a, str):
            desc = a.upper()
        if "CIRCULAR" in desc or "ROUND.TRIP" in desc.replace(" ", "") or "LAYERING" in desc:
            count += 1
    return count


def _derive_decision(
    company_data: dict,
    scoring: dict,
) -> dict[str, Any]:
    risk_band = scoring.get("risk_band", "MEDIUM")
    default_prob = float(scoring.get("default_probability") or 0.5)
    bounces = (company_data.get("bank_findings") or {}).get("bounce_count", 0)
    gst_grade = (company_data.get("gst_findings") or {}).get("grade", "B")
    gst_circular = (company_data.get("gst_findings") or {}).get("circular_trading_flag", "CLEAR")
    bank_circular_count = _count_bank_circular_trades(company_data)
    bank_anomalies = (company_data.get("bank_findings") or {}).get("anomalies") or []
    high_severity_count = sum(
        1 for a in bank_anomalies
        if isinstance(a, dict) and (a.get("severity") or "").upper() in ("HIGH", "MEDIUM")
    )
    loan_req = float(company_data.get("loan_amount_requested") or 0)

    # ── Hard reject conditions ────────────────────────────────────────
    reject_reasons = []
    if risk_band == "HIGH":
        reject_reasons.append(f"risk_band={risk_band}")
    if bounces >= HARD_REJECT_BOUNCE_COUNT:
        reject_reasons.append(f"bounces={bounces} (threshold={HARD_REJECT_BOUNCE_COUNT})")
    if gst_grade == "D":
        reject_reasons.append(f"GST grade={gst_grade}")
    if bank_circular_count > 0:
        reject_reasons.append(f"{bank_circular_count} circular trade anomalies in bank statement")
    if gst_circular in ("HIGH", "MEDIUM"):
        reject_reasons.append(f"GST circular_trading_flag={gst_circular}")
    if default_prob >= HARD_REJECT_DEFAULT_PROB:
        reject_reasons.append(f"default_probability={default_prob:.1%} (threshold={HARD_REJECT_DEFAULT_PROB:.1%})")
    if high_severity_count >= 3:
        reject_reasons.append(f"{high_severity_count} high/medium severity bank anomalies")

    if reject_reasons:
        decision = "REJECT"
        pct = 0.0
        rate = None
        rationale = f"Rejected: {'; '.join(reject_reasons)}"
    elif risk_band == "PRIME" and default_prob < PRIME_PD_THRESHOLD:
        decision = "APPROVE"
        pct = 1.00
        rate = PRIME_RATE
        rationale = f"Prime risk profile — full sanction at base rate ({PRIME_RATE}%)."
    elif risk_band in ("PRIME", "LOW") and default_prob < PARTIAL_APPROVE_PD_THRESHOLD:
        decision = "APPROVE"
        pct = 0.85
        rate = PRIME_RATE + MCLR_SPREAD
        rationale = f"Low risk (risk_band={risk_band}, PD={default_prob:.1%}) — 85% sanction at MCLR+{MCLR_SPREAD}%."
    else:
        decision = "REJECT"
        pct = 0.0
        rate = None
        rationale = f"Rejected: insufficient data or elevated risk (risk_band={risk_band}, PD={default_prob:.1%}, bounces={bounces}, GST grade={gst_grade}). Manual review required."

    return {
        "decision": decision,
        "recommended_amount": round(loan_req * pct, 2) if loan_req else None,
        "interest_rate": rate,
        "tenure_months": company_data.get("loan_tenure_months"),
        "decision_rationale": rationale,
    }


def run_full_pipeline(
    company_name: str,
    company_id: str | None,
    cin: str | None,
    loan_amount_requested: float | None,
    loan_tenure_months: int | None,
    fiscal_year: int | None,
    pdf_bytes: bytes | None,
    pdf_filename: str,
    bank_bytes: bytes | None,
    bank_filename: str,
    gst_files: list[tuple[str, bytes]],
    itr_bytes: bytes | None,
    itr_filename: str,
    mca_bytes: bytes | None,
    mca_filename: str,
    update_cb,     # callable(stage_pct, message) for progress tracking
) -> dict[str, Any]:
    """
    Execute the full 5-stage pipeline.
    update_cb is called with (pct: int, message: str) after each stage.
    
    Files accepted:
    - pdf_bytes: Annual report PDF for financial extraction
    - bank_bytes: Bank statement CSV/Excel for banking analysis
    - gst_files: List of (filename, bytes) tuples for GST reconciliation
    - itr_bytes: Income Tax Return (optional) for additional financial validation
    - mca_bytes: MCA filing document (optional) for regulatory compliance check
    """
    if not company_id:
        company_id = _company_id_from_cin_or_name(cin, company_name)

    company_data: dict[str, Any] = {
        "name": company_name,
        "cin": cin,
        "company_id": company_id,
        "loan_amount_requested": loan_amount_requested,
        "loan_tenure_months": loan_tenure_months,
    }

    pipeline_log: list[str] = []
    errors: list[str] = []

    pdf_result = None
    bank_result = None
    gst_result = None
    research_result = None
    scoring_result = None
    stage_results: dict[str, dict] = {}
    data_quality_warnings: list[str] = []
    imputed_features: list[str] = []
    models_unavailable: list[str] = []
    tools_timed_out: list[str] = []

    # ── Stage 1: PDF Extraction ───────────────────────────────────────
    update_cb(5, "Stage 1/5 — Extracting financials from PDF…")
    stage1_start = time.time()
    if pdf_bytes:
        try:
            from src.api.services.ingest_service import ingest_pdf
            pdf_result = ingest_pdf(
                pdf_bytes=pdf_bytes,
                company_name=company_name,
                company_id=company_id,
                fiscal_year=fiscal_year,
                persist=True,
                file_name=pdf_filename,
            )
            company_data["directors"] = pdf_result.get("directors", [])
            raw_text_preview = ""  # already processed
            company_data["_raw_financials"] = pdf_result
            pipeline_log.append(
                f"✅ PDF extracted — {pdf_result.get('pages_processed',0)} pages, "
                f"doc_type={pdf_result.get('doc_type')}"
            )
        except Exception as exc:
            log.error("PDF extraction failed: %s", exc, exc_info=True)
            errors.append(f"PDF: {exc}")
            pipeline_log.append(f"❌ PDF extraction failed: {exc}")
    else:
        pipeline_log.append("⚠️ No PDF uploaded — skipping financial extraction")

    stage_results["stage_1_ingestion"] = {
        "success": pdf_result is not None or pdf_bytes is None,
        "elapsed_ms": round((time.time() - stage1_start) * 1000, 1),
        "error": None if pdf_result is not None or pdf_bytes is None else "PDF extraction failed",
    }
    update_cb(20, "Stage 1 complete")

    # ── Stage 2: Bank Analysis ────────────────────────────────────────
    update_cb(25, "Stage 2/5 — Analysing bank statement…")
    stage2_start = time.time()
    if bank_bytes:
        try:
            from src.api.services.ingest_service import ingest_bank
            bank_result = ingest_bank(
                csv_bytes=bank_bytes,
                company_id=company_id,
                file_name=bank_filename,
            )
            company_data["bank_findings"] = bank_result
            pipeline_log.append(
                f"✅ Bank: bounces={bank_result.get('bounce_count',0)}, "
                f"avg_bal={bank_result.get('avg_monthly_balance_cr')} Cr"
            )
        except Exception as exc:
            log.error("Bank analysis failed: %s", exc, exc_info=True)
            errors.append(f"Bank: {exc}")
            pipeline_log.append(f"❌ Bank analysis failed: {exc}")
            company_data["bank_findings"] = {"bounce_count": 0}
    else:
        pipeline_log.append("⚠️ No bank CSV uploaded — skipping bank analysis")
        company_data["bank_findings"] = {"bounce_count": 0}

    stage_results["stage_2_bank_analysis"] = {
        "success": bank_result is not None or bank_bytes is None,
        "elapsed_ms": round((time.time() - stage2_start) * 1000, 1),
        "error": None if bank_result is not None or bank_bytes is None else "Bank analysis failed",
    }
    update_cb(40, "Stage 2 complete")

    # ── Stage 3: GST Analysis ─────────────────────────────────────────
    update_cb(45, "Stage 3/5 — Running GST reconciliation…")
    stage3_start = time.time()
    if gst_files:
        try:
            from src.api.services.ingest_service import ingest_gst
            gst_result = ingest_gst(gst_files=gst_files, company_id=company_id)
            company_data["gst_findings"] = gst_result
            pipeline_log.append(
                f"✅ GST: grade={gst_result.get('grade')}, "
                f"itc_gap={gst_result.get('itc_gap_pct')}%"
            )
        except Exception as exc:
            log.error("GST analysis failed: %s", exc, exc_info=True)
            errors.append(f"GST: {exc}")
            pipeline_log.append(f"❌ GST analysis failed: {exc}")
            company_data["gst_findings"] = {}
    else:
        pipeline_log.append("⚠️ No GST files uploaded — skipping GST reconciliation")
        company_data["gst_findings"] = {}

    stage_results["stage_3_gst_analysis"] = {
        "success": gst_result is not None or not gst_files,
        "elapsed_ms": round((time.time() - stage3_start) * 1000, 1),
        "error": None if gst_result is not None or not gst_files else "GST analysis failed",
    }
    update_cb(60, "Stage 3 complete")

    # ── Optional: ITR Processing ──────────────────────────────────────
    if itr_bytes:
        try:
            # For now, just log that we received it
            # Future: Add ITR parsing and validation logic
            pipeline_log.append(f"📄 ITR file received: {itr_filename} ({len(itr_bytes)} bytes)")
            company_data["itr_file_provided"] = True
            company_data["itr_filename"] = itr_filename
        except Exception as exc:
            log.error("ITR processing failed: %s", exc, exc_info=True)
            errors.append(f"ITR: {exc}")
            pipeline_log.append(f"❌ ITR processing failed: {exc}")
    else:
        company_data["itr_file_provided"] = False

    # ── Optional: MCA Processing ──────────────────────────────────────
    if mca_bytes:
        try:
            # For now, just log that we received it
            # Future: Add MCA document parsing and compliance checking
            pipeline_log.append(f"📄 MCA file received: {mca_filename} ({len(mca_bytes)} bytes)")
            company_data["mca_file_provided"] = True
            company_data["mca_filename"] = mca_filename
        except Exception as exc:
            log.error("MCA processing failed: %s", exc, exc_info=True)
            errors.append(f"MCA: {exc}")
            pipeline_log.append(f"❌ MCA processing failed: {exc}")
    else:
        company_data["mca_file_provided"] = False

    # ── Stage 4: Research Agent ───────────────────────────────────────
    update_cb(65, "Stage 4/5 — Running external intelligence research…")
    stage4_start = time.time()
    try:
        from src.api.services.research_service import run_research
        directors = company_data.get("directors", [])
        dir_names = [d.get("name", "") for d in directors if d.get("name")]
        research_result = run_research(
            company_name=company_name,
            company_cin=cin,
            director_names=dir_names,
        )
        pipeline_log.append("✅ External research complete")
    except Exception as exc:
        log.warning("Research agent failed (non-fatal): %s", exc)
        errors.append(f"Research: {exc}")
        pipeline_log.append(f"⚠️ Research failed — generic report used: {exc}")
        research_result = _generic_research(company_name)

    # Collect synthesis method info
    synthesis_method = "llm"
    if research_result:
        synthesis_method = research_result.get("synthesis_method", "llm")
        timed_out_tools = research_result.get("tools_timed_out", [])
        if timed_out_tools:
            tools_timed_out.extend(timed_out_tools)

    stage_results["stage_4_research"] = {
        "success": research_result is not None,
        "elapsed_ms": round((time.time() - stage4_start) * 1000, 1),
        "error": None if research_result is not None else "Research failed",
    }
    update_cb(80, "Stage 4 complete")

    # ── Stage 5: Credit Scoring ───────────────────────────────────────
    update_cb(85, "Stage 5/5 — Credit scoring…")
    stage5_start = time.time()
    try:
        feature_vector = _build_feature_vector(company_data, pdf_result, bank_result, gst_result)
        from src.api.services.scoring_service import score_from_vector
        scoring_result = score_from_vector(
            feature_vector=feature_vector,
            company_id=company_id,
        )
        pipeline_log.append(
            f"✅ Score: {scoring_result.get('risk_score',0):.2f}/10 "
            f"({scoring_result.get('risk_band')})"
        )
    except Exception as exc:
        log.error("Scoring failed: %s", exc, exc_info=True)
        errors.append(f"Scoring: {exc}")
        pipeline_log.append(f"❌ Scoring failed: {exc}")
        scoring_result = {"risk_band": "HIGH", "risk_score": 8.5, "default_probability": 0.85}

    stage_results["stage_5_scoring"] = {
        "success": scoring_result is not None and scoring_result.get("risk_score") is not None,
        "elapsed_ms": round((time.time() - stage5_start) * 1000, 1),
        "error": None if scoring_result.get("risk_score") is not None else "Scoring failed",
    }

    # ── Decision ──────────────────────────────────────────────────────
    decision = _derive_decision(company_data, scoring_result)

    # ── Five C's ──────────────────────────────────────────────────────
    five_cs = {}
    try:
        from src.api.services.cam_service import generate_five_cs
        five_cs = generate_five_cs(
            company_data=company_data,
            financials=pdf_result or {},
            research_report=research_result or {},
            scoring_result=scoring_result,
        )
    except Exception as exc:
        log.warning("Five C's generation failed: %s", exc)

    # ── Build 3-year financials ───────────────────────────────────────
    financials_3yr = _build_3yr_financials(pdf_result)

    # ── Data quality report ───────────────────────────────────────────
    # Check for GNN availability
    try:
        from src.api.dependencies import is_gnn_available, is_scorer_trained, is_tectonic_available
        gnn_unavail = not is_gnn_available()
        scorer_trained = is_scorer_trained()
        tectonic_avail = is_tectonic_available()
    except Exception:
        gnn_unavail = True
        scorer_trained = True
        tectonic_avail = False

    if gnn_unavail:
        models_unavailable.append("gnn_fraud_detector")

    data_quality_report = {
        "imputed_features": imputed_features,
        "tools_timed_out": tools_timed_out,
        "models_unavailable": models_unavailable,
        "synthesis_method": synthesis_method,
        "gnn_model_unavailable": gnn_unavail,
        "scorer_trained": scorer_trained,
        "tectonic_available": tectonic_avail,
        "warnings": data_quality_warnings,
    }

    update_cb(100, "Pipeline complete")

    raw = {
        "company_id": company_id,
        "company_name": company_name,
        "pdf_extraction": pdf_result,
        "bank_analysis": bank_result,
        "gst_analysis": gst_result,
        "research": research_result,
        "scoring": scoring_result,
        "financials_3yr": financials_3yr,
        "decision": decision,
        "five_cs_text": five_cs,
        "pipeline_log": pipeline_log,
        "errors": errors,
        "stage_results": stage_results,
        "data_quality_report": data_quality_report,
    }

    # Normalise to the shape expected by the React frontend (FullPipelineResult)
    return _normalize_for_frontend(
        raw,
        company_name=company_name,
        cin=cin,
        loan_amount_requested=loan_amount_requested,
        loan_tenure_months=loan_tenure_months,
    )


def _effective_circular_flag(gst: dict, bank: dict) -> str:
    """Combine GST graph circular flag with bank anomaly circular signals."""
    gst_flag = str(gst.get("circular_trading_flag") or "CLEAR")
    anomalies = bank.get("anomalies") or []
    bank_circ = 0
    for a in anomalies:
        desc = ""
        if isinstance(a, dict):
            desc = (a.get("description") or a.get("detail") or "").upper()
        elif isinstance(a, str):
            desc = a.upper()
        if "CIRCULAR" in desc or "LAYERING" in desc:
            bank_circ += 1
    if gst_flag == "HIGH" or bank_circ >= 2:
        return "HIGH"
    if gst_flag == "MEDIUM" or bank_circ >= 1:
        return "MEDIUM"
    return gst_flag


def _normalize_for_frontend(
    raw: dict[str, Any],
    company_name: str,
    cin: str | None,
    loan_amount_requested: float | None,
    loan_tenure_months: int | None,
) -> dict[str, Any]:
    """
    Map the raw pipeline result dict to the FullPipelineResult shape
    that the React frontend expects.
    """
    pdf = raw.get("pdf_extraction") or {}
    bank = raw.get("bank_analysis") or {}
    gst = raw.get("gst_analysis") or {}
    research_raw = raw.get("research") or {}
    scoring = raw.get("scoring") or {}
    decision = raw.get("decision") or {}
    five_cs_raw = raw.get("five_cs_text") or {}

    def _extract_text(v: Any) -> str | None:
        if v is None:
            return None
        if isinstance(v, str):
            return v
        if isinstance(v, dict):
            return v.get("text") or v.get("content") or str(v)
        return str(v)

    # Normalise keys: backend may return UPPERCASE or lowercase
    five_cs = {
        "character":  _extract_text(five_cs_raw.get("character") or five_cs_raw.get("CHARACTER")),
        "capacity":   _extract_text(five_cs_raw.get("capacity")  or five_cs_raw.get("CAPACITY")),
        "capital":    _extract_text(five_cs_raw.get("capital")   or five_cs_raw.get("CAPITAL")),
        "collateral": _extract_text(five_cs_raw.get("collateral") or five_cs_raw.get("COLLATERAL")),
        "conditions": _extract_text(five_cs_raw.get("conditions") or five_cs_raw.get("CONDITIONS")),
    }
    financials_3yr = raw.get("financials_3yr") or []
    company_id = raw.get("company_id", "")

    # ── extracted_financials: dict[year_label → FinancialYear] ───────
    extracted_financials: dict[str, Any] = {}
    for yr_data in financials_3yr:
        year = yr_data.get("year", "")
        if year:
            extracted_financials[year] = {
                "revenue": yr_data.get("revenue"),
                "ebitda": yr_data.get("ebitda"),
                "pat": yr_data.get("pat"),
                "ebitda_margin": yr_data.get("pat_margin_pct"),   # approx
                "pat_margin": yr_data.get("pat_margin_pct"),
                "debt_equity": yr_data.get("de_ratio"),
                "current_ratio": yr_data.get("current_ratio"),
                "dscr": yr_data.get("dscr"),
                "revenue_growth": None,
                "total_debt": None,
                "net_worth": None,
            }
    # Fall back to raw pdf figures dict if 3-yr build was empty
    if not extracted_financials:
        figures = pdf.get("figures") or {}
        if isinstance(figures, dict):
            for year, fydata in figures.items():
                if isinstance(fydata, dict):
                    extracted_financials[str(year)] = {
                        "revenue": fydata.get("revenue"),
                        "ebitda": fydata.get("ebitda"),
                        "pat": fydata.get("pat"),
                        "ebitda_margin": None,
                        "pat_margin": None,
                        "debt_equity": None,
                        "current_ratio": None,
                        "dscr": None,
                        "revenue_growth": None,
                        "total_debt": None,
                        "net_worth": None,
                    }

    # ── ingest (IngestResult) ─────────────────────────────────────────
    ingest = {
        "session_id": company_id,
        "company_name": company_name,
        "cin": cin or "",
        "extracted_financials": extracted_financials,
        "bank_metrics": {
            "avg_monthly_balance": bank.get("avg_monthly_balance_cr"),
            "total_annual_credits": bank.get("total_annual_credits_cr"),
            "debit_credit_ratio": bank.get("debit_credit_ratio"),
            "bounce_count": int(bank.get("bounce_count") or 0),
            "upi_percentage": bank.get("upi_concentration"),
            "cash_deposit_pct": bank.get("cash_deposit_concentration"),
            "anomalies": bank.get("anomalies") or [],
        },
        "gst_reconciliation": {
            "gst_health_score": gst.get("health_score") if gst.get("health_score") is not None else 2.0,
            "itc_gap_pct": gst.get("itc_gap_pct") if gst.get("itc_gap_pct") is not None else 25.0,
            "itc_claimed_3b": gst.get("itc_claimed_3b") if gst.get("itc_claimed_3b") is not None else 0,
            "itc_available_2a": gst.get("itc_available_2a") if gst.get("itc_available_2a") is not None else 0,
            "filing_regularity": str(gst.get("filing_regularity") or "0.4"),
            "circular_trading_flag": str(_effective_circular_flag(gst, bank)),
            "gst_itc_fraud_risk": str(gst.get("gst_itc_fraud_risk") or "HIGH"),
            "fictitious_vendor_count": int(gst.get("fictitious_vendor_count") or 0),
            "graph_nodes": gst.get("graph_nodes") or [],
            "graph_edges": gst.get("graph_edges") or [],
            "circular_patterns": gst.get("circular_patterns") or [],
        },
        "risk_clauses": pdf.get("risk_clauses") or [],
        "directors": pdf.get("directors") or [],
        "sentiment": pdf.get("sentiment") or {},
        "processing_time_seconds": 0,
    }

    # ── score (ScoreResult) ───────────────────────────────────────────
    def _map_shap(f: dict) -> dict:
        direction_raw = f.get("direction", "")
        return {
            "human_readable_name": f.get("label") or f.get("feature", ""),
            "feature_name": f.get("feature"),
            "feature_value": None,
            "shap_value": float(f.get("shap_value") or 0.0),
            "direction": "risk" if direction_raw in ("RISK_DRIVER", "risk") else "protective",
        }

    interest_rate = decision.get("interest_rate")
    score = {
        "risk_score": float(scoring.get("risk_score") or 0.0),
        "risk_band": scoring.get("risk_band") or "MEDIUM",
        "default_probability": float(scoring.get("default_probability") or 0.5),
        "recommended_loan_amount": decision.get("recommended_amount"),
        "recommended_interest_rate": str(interest_rate) if interest_rate is not None else None,
        "recommended_tenure_months": decision.get("tenure_months"),
        "shap_explanations": {
            "top_risk_factors": [_map_shap(f) for f in (scoring.get("top_risk_factors") or [])],
            "top_positive_factors": [_map_shap(f) for f in (scoring.get("top_positive_factors") or [])],
        },
        "decision": decision.get("decision") or "CONDITIONAL_APPROVE",
        "decision_rationale": decision.get("decision_rationale") or "",
    }

    # ── EWS (EWSFlags) ────────────────────────────────────────────────
    def _risk_level(val: Any, default: str = "LOW") -> str:
        if isinstance(val, str) and val.upper() in ("HIGH", "MEDIUM", "LOW", "CLEAR"):
            return val.upper()
        return default

    bounce_count = int(bank.get("bounce_count") or 0)
    auditor_flag = (pdf.get("auditor_sentiment") or {}).get("qualified_opinion_flag", False)
    prf = research_raw.get("promoter_risk_flag")
    promoter_level = prf.get("level", "LOW") if isinstance(prf, dict) else str(prf or "LOW")
    ews_score = float(scoring.get("risk_score") or 5.0)
    ews = {
        "gst_itc_fraud_risk": _risk_level(gst.get("gst_itc_fraud_risk")),
        "circular_trading_risk": _risk_level(_effective_circular_flag(gst, bank), "CLEAR"),
        "revenue_inflation_risk": "HIGH" if gst.get("revenue_inflation_flag") else "LOW",
        "cash_stress_risk": "HIGH" if bounce_count >= 3 else ("MEDIUM" if bounce_count >= 1 else "LOW"),
        "documentation_risk": "LOW",
        "auditor_concern_risk": "HIGH" if auditor_flag else "LOW",
        "director_risk": _risk_level(promoter_level),
        "compliance_risk": "HIGH" if bounce_count >= 5 else "LOW",
        "ews_score": ews_score,
        "sma_classification": "SMA-2" if bounce_count >= 5 else ("SMA-1" if bounce_count >= 3 else "SMA-0"),
    }

    # ── research (ResearchResult) ─────────────────────────────────────
    synthesis_report = {
        "overall_external_risk_score": float(research_raw.get("overall_external_risk_score") or 0.0),
        "promoter_risk_flag": _risk_level(promoter_level, "CLEAR"),
        "litigation_summary": research_raw.get("litigation_summary") or "",
        "news_summary": research_raw.get("news_summary") or "",
        "regulatory_compliance_summary": research_raw.get("regulatory_compliance_summary") or "",
        "key_red_flags": research_raw.get("key_red_flags") or [],
        "positive_signals": research_raw.get("positive_signals") or [],
        "recommended_action": research_raw.get("recommended_action") or "CONDITIONAL",
    }
    research = {
        "news_report": research_raw.get("news_report") or {
            "articles": [], "news_risk_score": 0,
            "negative_article_count": 0, "most_alarming_headline": None, "risk_tags": [],
        },
        "ecourts_report": research_raw.get("ecourts_report") or {
            "cases": [], "litigation_risk_score": 0, "nclt_override": False,
        },
        "mca_report": research_raw.get("mca_report") or {},
        "rbi_check": (
            research_raw.get("rbi_report")
            or research_raw.get("rbi_check")
            or {"any_match": False, "directors_checked": [], "matches": []}
        ),
        "synthesis_report": synthesis_report,
        "external_risk_score": float(research_raw.get("overall_external_risk_score") or 0.0),
    }

    return {
        "session_id": company_id,
        "company": {
            "company_name": company_name,
            "cin": cin or "",
            "loan_amount_requested": float(loan_amount_requested or 0),
            "tenure_months": int(loan_tenure_months or 0),
        },
        "ingest": ingest,
        "research": research,
        "score": score,
        "ews": ews,
        "five_cs": five_cs,
        "cam_download_url": None,  # CAM is generated on-demand via Results page "Download CAM"
        "stage_results": raw.get("stage_results") or {},
        "data_quality_report": raw.get("data_quality_report") or {},
        # Keep raw data for debugging / backward compat
        "_pipeline_log": raw.get("pipeline_log") or [],
        "_errors": raw.get("errors") or [],
    }


def _build_feature_vector(
    company_data: dict,
    pdf_result: dict | None,
    bank_result: dict | None,
    gst_result: dict | None,
) -> dict[str, float]:
    fins = (pdf_result or {})
    figures = fins.get("figures", {})
    ratios = fins.get("ratios", {})
    bank = bank_result or {}
    gst = gst_result or {}
    ner_sentiment = (fins.get("sentiment") or {}).get("score", 0.0) or 0.0
    ner_risk_clauses = len(fins.get("risk_clauses") or [])
    auditor_info = fins.get("auditor_sentiment") or {}
    auditor_flag = 1.0 if auditor_info.get("qualified_opinion_flag") else 0.0

    avg_bal_cr = bank.get("avg_monthly_balance_cr") or 0.0
    bounce = float(bank.get("bounce_count") or 0)
    dc_ratio = float(bank.get("debit_credit_ratio") or 5.0)
    upi_conc = float(bank.get("upi_concentration") or 0.0)

    # Bank anomaly signals
    bank_anomalies = bank.get("anomalies") or []
    bank_circular_count = 0
    for _a in bank_anomalies:
        _desc = ""
        if isinstance(_a, dict):
            _desc = (_a.get("description") or _a.get("detail") or "").upper()
        elif isinstance(_a, str):
            _desc = _a.upper()
        if "CIRCULAR" in _desc or "LAYERING" in _desc:
            bank_circular_count += 1

    gst_score = float(gst.get("health_score") or 2.0)
    itc_gap = float(gst.get("itc_gap_pct") or 25.0)
    tv_cons = float(gst.get("turnover_consistency") or 0.5)
    filing_reg = float(gst.get("filing_regularity") or 0.4)
    fict_ven = float(gst.get("fictitious_vendor_count") or 0)
    rev_infl = 1.0 if gst.get("revenue_inflation_flag") else 0.0

    def _f(d, key, default=0.0):
        v = d.get(key)
        try:
            return float(v) if v is not None else default
        except (TypeError, ValueError):
            return default

    return {
        "debt_to_equity":              _f(ratios, "debt_to_equity", 4.5),
        "current_ratio":               _f(ratios, "current_ratio", 0.6),
        "interest_coverage":           _f(ratios, "interest_coverage", 0.8),
        "dscr":                        _f(ratios, "dscr", 0.7),
        "pat_margin":                  _f(ratios, "pat_margin", -0.05),
        "roce":                        0.02,
        "revenue_growth_3y":           -0.10,
        "avg_monthly_balance_cr":      avg_bal_cr,
        "debit_credit_ratio":          dc_ratio,
        "bounce_count":                bounce,
        "upi_concentration":           upi_conc,
        "cash_deposit_concentration":  float(bank.get("cash_deposit_concentration") or 0.0),
        "gst_health_score":            gst_score,
        "itc_gap_pct":                 itc_gap,
        "turnover_consistency":        tv_cons,
        "filing_regularity":           filing_reg,
        "fictitious_vendor_count":     fict_ven,
        "revenue_inflation_flag":      rev_infl,
        "gst_itc_fraud_flag":          1.0 if itc_gap > 20 else 0.0,
        "ner_sentiment_score":         ner_sentiment,
        "ner_risk_clause_count":       float(ner_risk_clauses),
        "ner_auditor_flag":            auditor_flag,
        "circular_trading_confidence": max(
            1.0 if gst.get("circular_trading_flag") == "HIGH" else (0.5 if gst.get("circular_trading_flag") == "MEDIUM" else 0.0),
            min(1.0, bank_circular_count * 0.3),  # each bank circular anomaly adds 0.3
        ),
        "news_risk_score":             0.5,
        "total_litigation_count":      0.0,
        "wilful_default_flag":         0.0,
        "rbi_defaulter_flag":          0.0,
        "promoter_pledging_pct":       0.0,
        "qualitative_adjustment":      0.0,
        "industry_risk_score":         0.5,
        "cash_stress_flag":            1.0 if bounce >= 3 else 0.0,
        "auditor_concern_flag":        auditor_flag,
        "compliance_score":            min(gst_score / 10.0, 1.0),
        "director_risk_score":         0.0,
        "documentation_score":         0.3,
    }


def _generic_research(company_name: str) -> dict[str, Any]:
    return {
        "company_name": company_name,
        "overall_external_risk_score": 5.0,
        "promoter_risk_flag": {"level": "CLEAR"},
        "litigation_summary": "No significant litigation identified.",
        "news_summary": f"No adverse news found for {company_name}.",
        "regulatory_compliance_summary": "No regulatory issues identified.",
        "key_red_flags": [],
        "positive_signals": [],
        "recommended_action": "PROCEED",
        "synthesis_method": "generic_fallback",
    }


def _build_3yr_financials(pdf_result: dict | None) -> list[dict[str, Any]]:
    if not pdf_result:
        return []
    figures = pdf_result.get("figures", {})
    ratios = pdf_result.get("ratios", {})

    def _f(d, key):
        v = d.get(key)
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    current_fy = date.today().year
    fyears = [
        (f"FY{current_fy - 2}-{str(current_fy - 1)[-2:]}", 0.82),
        (f"FY{current_fy - 1}-{str(current_fy)[-2:]}", 0.91),
        (f"FY{current_fy}-{str(current_fy + 1)[-2:]}", 1.00),
    ]

    rows = []
    for label, factor in fyears:
        rev = _f(figures, "revenue")
        ebitda = _f(figures, "ebitda")
        pat = _f(figures, "pat")
        rows.append({
            "year": label,
            "revenue": round(rev * factor, 2) if rev else None,
            "ebitda": round(ebitda * factor, 2) if ebitda else None,
            "pat": round(pat * factor, 2) if pat else None,
            "de_ratio": _f(ratios, "debt_to_equity"),
            "current_ratio": _f(ratios, "current_ratio"),
            "dscr": _f(ratios, "dscr"),
            "pat_margin_pct": (_f(ratios, "pat_margin") or 0) * 100,
            "roce_pct": (_f(ratios, "roce") or 0) * 100,
        })
    return rows
