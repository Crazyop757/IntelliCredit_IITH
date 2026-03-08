"""
Ingest service — orchestrates PDF, bank, and GST ingestion into the delta layers.
All heavy I/O and ML calls happen synchronously here (run via ThreadPoolExecutor
from the async routers).
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _company_id_from_name(name: str) -> str:
    """Derive a filesystem-safe company_id from a human name."""
    slug = re.sub(r"[^a-zA-Z0-9]", "_", name).upper()
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug[:40]


def _detect_gst_type(data: dict) -> str:
    """Detect GSTR type from JSON content."""
    form = data.get("form", "")
    if form == "GSTR-1" or "invoices" in data:
        return "gstr1"
    if form == "GSTR-2A" or "auto_populated_invoices" in data:
        return "gstr2a"
    if form == "GSTR-3B" or "filings" in data:
        return "gstr3b"
    return "unknown"


# ── PDF Ingestion ─────────────────────────────────────────────────────────────

def ingest_pdf(
    pdf_bytes: bytes,
    company_name: str,
    company_id: str,
    fiscal_year: int | None,
    persist: bool,
    file_name: str = "upload.pdf",
) -> dict[str, Any]:
    """
    Parse PDF → extract financials + NER → optionally write Delta layers.
    Returns a dict matching PDFIngestResponse fields.
    """
    from src.ingestor.pdf_parser import PDFParser
    from src.ingestor.financial_extractor import FinancialExtractor
    from src.ingestor.ner_extractor import NERExtractor

    # Write bytes to a temp file (parsers expect a path)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = Path(tmp.name)

    try:
        parser = PDFParser()
        pdf_result = parser.parse(tmp_path)
        raw_text: str = pdf_result.get("raw_text", "")
        tables: list = pdf_result.get("tables", [])
        doc_type: str = pdf_result.get("doc_type", "UNKNOWN")
        pages: int = pdf_result.get("pages_processed", 0)

        extractor = FinancialExtractor()
        fin_result = extractor.extract(raw_text, tables, doc_type)
        figures = fin_result.get("figures", {})
        ratios = fin_result.get("ratios", {})
        directors_raw = fin_result.get("directors", [])
        risk_clauses_raw = fin_result.get("risk_clauses", [])

        # NER (may be heavy — catch failures gracefully)
        ner_result: dict = {}
        try:
            ner = NERExtractor()
            ner_result = ner.analyze(raw_text[:8000])  # cap at 8k chars to keep it fast
        except Exception as exc:
            log.warning("NER failed: %s", exc)

        # Persist to Delta Lake if requested
        bronze_id = None
        quality_flag = None
        if persist:
            try:
                from src.ingestor.delta_writer import DeltaWriter
                import datetime
                fy = fiscal_year or datetime.date.today().year
                writer = DeltaWriter()
                ids = writer.write(
                    pdf_result,
                    fin_result,
                    ner_result or None,
                    company_id=company_id,
                    file_name=file_name,
                    fiscal_year=fy,
                )
                bronze_id = ids.get("bronze_id")
                quality_flag = ids.get("quality_flag")
            except Exception as exc:
                log.warning("Delta write failed: %s", exc)

        # Parse risk clauses to dicts
        def _rc(rc) -> dict:
            if hasattr(rc, "__dict__"):
                return rc.__dict__
            return rc if isinstance(rc, dict) else {}

        return {
            "company_id": company_id,
            "company_name": company_name,
            "doc_type": doc_type,
            "pages_processed": pages,
            "fiscal_year": fiscal_year,
            "figures": figures,
            "ratios": ratios,
            "directors": directors_raw,
            "risk_clauses": [_rc(r) for r in risk_clauses_raw],
            "sentiment": (ner_result.get("sentiment") if ner_result else None),
            "auditor_sentiment": (ner_result.get("auditor_sentiment") if ner_result else None),
            "entities": (ner_result.get("entities") if ner_result else None),
            "bronze_id": bronze_id,
            "quality_flag": quality_flag,
        }
    finally:
        os.unlink(tmp_path)


# ── Bank Ingestion ────────────────────────────────────────────────────────────

def ingest_bank(
    csv_bytes: bytes,
    company_id: str,
    file_name: str = "bank.csv",
) -> dict[str, Any]:
    """
    Analyse bank statement CSV/Excel.
    Returns a dict matching BankIngestResponse fields.
    """
    from src.ingestor.bank_analyzer import BankStatementAnalyzer

    suffix = Path(file_name).suffix or ".csv"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(csv_bytes)
        tmp_path = Path(tmp.name)

    try:
        analyzer = BankStatementAnalyzer()
        result = analyzer.analyze(tmp_path)

        metrics = result.get("metrics", result)  # some versions return nested
        avg_bal_inr = metrics.get("average_monthly_balance", 0) or 0
        avg_bal_cr = round(avg_bal_inr / 1e7, 4) if avg_bal_inr else None

        total_credits_inr = metrics.get("total_annual_credits", 0) or 0
        total_credits_cr = round(total_credits_inr / 1e7, 4) if total_credits_inr else None

        anomalies = result.get("anomalies", {})
        anomaly_list = []
        if isinstance(anomalies, dict):
            for k, v in anomalies.items():
                if v:
                    anomaly_list.append(str(k))
        elif isinstance(anomalies, list):
            anomaly_list = [str(a) for a in anomalies]

        row_count = int(metrics.get("transaction_count", 0) or 0)

        return {
            "company_id": company_id,
            "avg_monthly_balance_cr": avg_bal_cr,
            "debit_credit_ratio": metrics.get("debit_credit_ratio"),
            "bounce_count": int(metrics.get("bounce_count", 0) or 0),
            "upi_concentration": metrics.get("upi_percentage") or metrics.get("upi_concentration"),
            "cash_deposit_concentration": metrics.get("cash_deposit_concentration"),
            "total_annual_credits_cr": total_credits_cr,
            "anomalies": anomaly_list,
            "monthly_breakdown": metrics.get("monthly_breakdown"),
            "row_count": row_count,
        }
    finally:
        os.unlink(tmp_path)


# ── GST Ingestion ─────────────────────────────────────────────────────────────

def ingest_gst(
    gst_files: list[tuple[str, bytes]],   # [(filename, content), ...]
    company_id: str,
) -> dict[str, Any]:
    """
    Run GSTReconciler on uploaded JSON files.
    Returns a dict matching GSTIngestResponse fields.
    """
    from src.gst.reconciler import GSTReconciler

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        found_types: set[str] = set()

        for fname, content in gst_files:
            try:
                data = json.loads(content.decode("utf-8"))
            except Exception:
                log.warning("Could not parse GST file %s as JSON", fname)
                continue

            gst_type = _detect_gst_type(data)
            if gst_type == "unknown":
                log.warning("Could not detect GST type for %s", fname)
                continue

            out_name = f"{company_id}_{gst_type}.json"
            (tmp_path / out_name).write_text(json.dumps(data), encoding="utf-8")
            found_types.add(gst_type)

        if not found_types:
            return {
                "company_id": company_id,
                "health_score": None,
                "grade": None,
                "verdict": "No valid GST files detected",
                "full_report": None,
            }

        reconciler = GSTReconciler(gst_dir=tmp_path)
        report = reconciler.run_full_reconciliation(company_id)

        hs = report.get("health_score", {})
        itc = (report.get("itc_reconciliation") or {}).get("summary", {})
        tv = (report.get("turnover_reconciliation") or {}).get("summary", {})
        fv = (report.get("fictitious_vendors") or {}).get("summary", {})

        return {
            "company_id": company_id,
            "health_score": hs.get("score"),
            "grade": hs.get("grade"),
            "itc_gap_pct": itc.get("total_gap_percentage"),
            "turnover_consistency": tv.get("overall_bank_to_declared_ratio"),
            "filing_regularity": hs.get("components", {}).get("filing_regularity"),
            "fictitious_vendor_count": fv.get("fictitious_vendor_count", 0),
            "revenue_inflation_flag": bool(tv.get("revenue_inflation_periods")),
            "verdict": hs.get("grade"),
            "full_report": report,
        }
