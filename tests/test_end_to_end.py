"""
test_end_to_end.py — Full pipeline integration test for IntelliCredit.

Usage
-----
    python tests/test_end_to_end.py

The test creates a synthetic PDF fixture on the fly (no real document needed)
and re-uses the canonical demo fixtures already present in the repo:
  * data/raw/bank_statement_sample.csv   → BankStatementAnalyzer
  * data/raw/gst/COMP_A_RELIANCE_gstr*.json  → GSTReconciler
  * data/raw/gst/gst_transaction_graph.json  → TransactionGraphBuilder
  * data/gold/gold_features/COMP_A_RELIANCE_ews.json → FeatureBuilder

Each step is timed independently.  PASS/FAIL is printed in colour.
A failure in an early step does not abort later steps — the next step
falls back to synthetic inputs where possible.
"""

from __future__ import annotations

import json
import sys
import time
import tempfile
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Project-root path bootstrap
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# ANSI colour helpers (degrade gracefully on Windows without ANSI support)
# ---------------------------------------------------------------------------
_GREEN = "\033[92m"
_RED   = "\033[91m"
_CYAN  = "\033[96m"
_RESET = "\033[0m"
_BOLD  = "\033[1m"

# ---------------------------------------------------------------------------
# Well-known demo identifiers
# ---------------------------------------------------------------------------
_DEMO_COMPANY_ID = "COMP_A_RELIANCE"
_BANK_CSV        = _PROJECT_ROOT / "data" / "raw" / "bank_statement_sample.csv"
_GST_DIR         = _PROJECT_ROOT / "data" / "raw" / "gst"

# ---------------------------------------------------------------------------
# Rich synthetic financial text (used as fallback for PDFParser / extraction)
# ---------------------------------------------------------------------------
_SYNTH_FINANCIAL_TEXT = (
    "Reliance Industries Limited - Annual Report FY2024\n\n"
    "Total Revenue from Operations: Rs. 9,01,532 Crores\n"
    "EBITDA: Rs. 1,78,677 Crores\n"
    "Profit After Tax (PAT): Rs. 79,020 Crores\n"
    "Total Debt: Rs. 3,35,297 Crores\n"
    "Net Worth: Rs. 7,58,000 Crores\n"
    "Finance Costs (Interest Expense): Rs. 21,000 Crores\n"
    "Current Assets: Rs. 3,00,000 Crores\n"
    "Current Liabilities: Rs. 2,50,000 Crores\n"
    "Debt Service: Rs. 40,000 Crores\n"
    "Capital Expenditure: Rs. 1,42,000 Crores\n"
    "Operating Cash Flow: Rs. 1,20,000 Crores\n"
    "Total Assets: Rs. 14,50,000 Crores\n\n"
    "Mr. Mukesh D. Ambani serves as Managing Director of the Company.\n"
    "Mr. Hital R. Meswani serves as Executive Director.\n"
    "Ms. Nita M. Ambani is a Non-Executive Director.\n\n"
    "The Company operates in energy, retail and digital services segments.\n"
    "Consolidated revenue crossed Rs. 9 lakh crore for FY2024.\n"
    "EBITDA margin improved to 19.8%.\n"
    "The board at its meeting held on April 20, 2024 recommended a final\n"
    "dividend of Rs. 10 per equity share.\n"
) * 6  # 6x ensures > 1000 chars and covers multiple financial mentions


# ---------------------------------------------------------------------------
# Minimal synthetic PDF builder (no external PDF library required)
# ---------------------------------------------------------------------------

def _create_synthetic_pdf(path: Path) -> None:
    """
    Write a minimal but valid PDF-1.4 file to *path*.

    The document contains the full _SYNTH_FINANCIAL_TEXT spread over multiple
    text-drawing operations so that pdfplumber can extract > 1000 characters
    of text.  Only Helvetica (a standard 14 built-in Type1 font) is used —
    no font embedding needed.
    """
    # Build the PDF content stream (BT … ET block)
    lines = _SYNTH_FINANCIAL_TEXT.split("\n")

    def _escape(s: str) -> str:
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    ops: list[str] = [
        "BT",
        "/F1 10 Tf",
        "50 770 Td",
        "11 TL",       # text leading = 11 pts
    ]
    for line in lines[:80]:  # limit to 80 lines per page
        ops.append(f"({_escape(line)}) Tj T*")
    ops.append("ET")

    content_str   = "\n".join(ops)
    content_bytes = content_str.encode("latin-1", errors="replace")

    # ── Assemble PDF objects ─────────────────────────────────────────────
    body      = bytearray(b"%PDF-1.4\n")
    obj_offsets: list[int] = []

    def _write_obj(raw: bytes) -> None:
        obj_offsets.append(len(body))
        n = len(obj_offsets)
        body.extend(f"{n} 0 obj\n".encode())
        body.extend(raw)
        body.extend(b"\nendobj\n")

    # Obj 1: Catalog
    _write_obj(b"<</Type /Catalog /Pages 2 0 R>>")
    # Obj 2: Pages
    _write_obj(b"<</Type /Pages /Kids [3 0 R] /Count 1>>")
    # Obj 3: Page
    _write_obj(
        b"<</Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
        b" /Contents 4 0 R /Resources <</Font <</F1 5 0 R>>>>>>"
    )
    # Obj 4: Content stream
    stream_header = f"<</Length {len(content_bytes)}>>\nstream\n".encode()
    _write_obj(stream_header + content_bytes + b"\nendstream")
    # Obj 5: Font
    _write_obj(
        b"<</Type /Font /Subtype /Type1 /BaseFont /Helvetica"
        b" /Encoding /WinAnsiEncoding>>"
    )

    # ── Cross-reference table ─────────────────────────────────────────────
    xref_offset = len(body)
    n_objs      = len(obj_offsets)
    body.extend(b"xref\n")
    body.extend(f"0 {n_objs + 1}\n".encode())
    body.extend(b"0000000000 65535 f \n")
    for off in obj_offsets:
        body.extend(f"{off:010d} 00000 n \n".encode())
    body.extend(b"trailer\n")
    body.extend(f"<</Size {n_objs + 1} /Root 1 0 R>>\n".encode())
    body.extend(b"startxref\n")
    body.extend(f"{xref_offset}\n".encode())
    body.extend(b"%%EOF\n")

    path.write_bytes(bytes(body))


# ---------------------------------------------------------------------------
# E2E Test class
# ---------------------------------------------------------------------------

class E2ETest:
    """
    End-to-end integration test for the IntelliCredit pipeline.

    Instantiate once and call :meth:`run_full_pipeline`.
    """

    def __init__(self) -> None:
        self._results: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Step runner helper
    # ------------------------------------------------------------------

    def _step(self, num: int, name: str, fn) -> Any:
        """Time *fn()*, print PASS/FAIL, accumulate results, return value."""
        t0 = time.perf_counter()
        try:
            result  = fn()
            elapsed = time.perf_counter() - t0
            print(
                f"{_GREEN}{_BOLD}PASS{_RESET} "
                f"[{num:02d}] {name:<55} ({elapsed:.2f}s)"
            )
            self._results.append(
                {"step": num, "name": name, "status": "PASS", "elapsed": elapsed}
            )
            return result
        except AssertionError as exc:
            elapsed = time.perf_counter() - t0
            print(
                f"{_RED}{_BOLD}FAIL{_RESET} "
                f"[{num:02d}] {name:<55} ({elapsed:.2f}s)\n"
                f"       AssertionError: {exc}"
            )
            self._results.append(
                {
                    "step": num, "name": name, "status": "FAIL",
                    "error": str(exc), "elapsed": elapsed,
                }
            )
            return None
        except Exception as exc:  # noqa: BLE001
            elapsed = time.perf_counter() - t0
            print(
                f"{_RED}{_BOLD}FAIL{_RESET} "
                f"[{num:02d}] {name:<55} ({elapsed:.2f}s)\n"
                f"       {type(exc).__name__}: {exc}"
            )
            self._results.append(
                {
                    "step": num, "name": name, "status": "FAIL",
                    "error": f"{type(exc).__name__}: {exc}", "elapsed": elapsed,
                }
            )
            return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_full_pipeline(
        self,
        company_name:  str,
        pdf_path:      str | Path,
        bank_csv_path: str | Path,
        gst_dir:       str | Path,
        company_id:    str = _DEMO_COMPANY_ID,
    ) -> bool:
        """
        Execute all 10 validation steps in sequence.

        Parameters
        ----------
        company_name  : Display name used for CAM document header.
        pdf_path      : Path to an annual-report PDF (synthetic is fine).
        bank_csv_path : Path to a bank statement CSV.
        gst_dir       : Directory holding ``{company_id}_gstr*.json`` files.
        company_id    : Logical identifier for GST / EWS / FeatureBuilder.

        Returns
        -------
        True if every step passes, False otherwise.
        The total elapsed time must be ≤ 90 seconds.
        """
        t_total       = time.perf_counter()
        pdf_path      = Path(pdf_path)
        bank_csv_path = Path(bank_csv_path)
        gst_dir       = Path(gst_dir)

        sep = "=" * 68
        print(f"\n{sep}")
        print(f"  IntelliCredit E2E Pipeline Test — {company_name}")
        print(f"  company_id : {company_id}")
        print(sep)

        # ── Step 1: PDFParser ──────────────────────────────────────────
        parsed = self._step(1, "PDFParser.parse()",
                            lambda: self._s1_pdf_parser(pdf_path))

        # ── Step 2: FinancialExtractor ─────────────────────────────────
        financials = self._step(2, "FinancialExtractor.extract()",
                                lambda: self._s2_fin_extractor(parsed))

        # ── Step 3: BankStatementAnalyzer ──────────────────────────────
        bank_result = self._step(3, "BankStatementAnalyzer.analyze()",
                                 lambda: self._s3_bank_analyzer(bank_csv_path, company_name))

        # ── Step 4: GSTReconciler ──────────────────────────────────────
        gst_report = self._step(4, "GSTReconciler.run_full_reconciliation()",
                                lambda: self._s4_gst_reconciler(company_id, gst_dir))

        # ── Step 5: TransactionGraphBuilder + CircularTradingDetector ──
        predictions = self._step(5, "GraphBuilder + CircularTradingDetector",
                                 lambda: self._s5_gnn_stack())

        # ── Step 6: EWSEngine ──────────────────────────────────────────
        ews_result = self._step(6, "EWSEngine.consolidate_signals()",
                                lambda: self._s6_ews(company_id))

        # ── Step 7: ResearchAgent ──────────────────────────────────────
        research = self._step(7, "ResearchAgent.run_research()",
                              lambda: self._s7_research_agent(company_name))

        # ── Step 8: FeatureBuilder ─────────────────────────────────────
        feature_vector = self._step(8, "FeatureBuilder.build_feature_vector()",
                                    lambda: self._s8_feature_builder(company_id))

        # ── Step 9: CreditScorer ───────────────────────────────────────
        scoring = self._step(9, "CreditScorer.score()",
                             lambda: self._s9_credit_scorer(feature_vector))

        # ── Step 10: CAMGenerator ──────────────────────────────────────
        self._step(10, "CAMGenerator.generate_cam()",
                   lambda: self._s10_cam_generator(
                       company_name, financials, bank_result,
                       ews_result, scoring, research,
                   ))

        # ── Summary ────────────────────────────────────────────────────
        total_elapsed = time.perf_counter() - t_total
        passed = sum(1 for r in self._results if r["status"] == "PASS")
        failed = sum(1 for r in self._results if r["status"] == "FAIL")

        print(f"\n{sep}")
        print(
            f"  Results : {_GREEN}{_BOLD}{passed} PASS{_RESET} / "
            f"{_RED}{_BOLD}{failed} FAIL{_RESET}"
            f"   |   Total time: {total_elapsed:.1f}s"
        )
        if total_elapsed > 90:
            print(
                f"  {_RED}WARNING: total elapsed {total_elapsed:.1f}s "
                f"exceeded the 90s target.{_RESET}"
            )
        else:
            print(f"  Pipeline completed within the 90s target.")
        print(sep + "\n")

        return failed == 0

    # ------------------------------------------------------------------
    # Step implementations
    # ------------------------------------------------------------------

    def _s1_pdf_parser(self, pdf_path: Path) -> dict:
        from src.ingestor.pdf_parser import PDFParser

        parser = PDFParser()
        result = parser.parse(str(pdf_path))

        assert result.get("doc_type") is not None, (
            f"doc_type is None; full result keys: {list(result)}"
        )
        assert len(result.get("raw_text", "")) > 1000, (
            f"raw_text length {len(result.get('raw_text',''))} ≤ 1000 chars"
        )
        return result

    def _s2_fin_extractor(self, parsed: dict | None) -> dict:
        from src.ingestor.financial_extractor import FinancialExtractor

        if parsed is None:
            raw_text = _SYNTH_FINANCIAL_TEXT
            tables   = []
            doc_type = "ANNUAL_REPORT"
        else:
            raw_text = parsed.get("raw_text", "")
            tables   = parsed.get("tables", [])
            doc_type = parsed.get("doc_type", "")

        extractor = FinancialExtractor()
        result    = extractor.extract(raw_text, tables, doc_type=doc_type)

        figures = result.get("figures", {})
        found   = sum(1 for v in figures.values() if v is not None)
        assert found >= 3, (
            f"Expected ≥3 financial figures extracted, got {found}.\n"
            f"figures = {figures}"
        )
        return result

    def _s3_bank_analyzer(self, bank_csv_path: Path, company_name: str) -> dict:
        from src.ingestor.bank_analyzer import BankStatementAnalyzer

        analyzer = BankStatementAnalyzer()
        result   = analyzer.analyze(str(bank_csv_path),
                                    company_id=company_name[:20])

        metrics = result.get("metrics", {})
        assert len(metrics) >= 8, (
            f"Expected ≥8 metric keys, got {len(metrics)}: {list(metrics)}"
        )
        return result

    def _s4_gst_reconciler(self, company_id: str, gst_dir: Path) -> dict:
        from src.gst.reconciler import GSTReconciler

        rec    = GSTReconciler(gst_dir=str(gst_dir))
        report = rec.run_full_reconciliation(company_id)

        # The reconciliation report uses the key 'itc_reconciliation'
        assert "itc_reconciliation" in report, (
            f"'itc_reconciliation' key missing from report. "
            f"Keys present: {list(report)}"
        )
        return report

    def _s5_gnn_stack(self) -> dict:
        from src.gst.graph_builder import TransactionGraphBuilder
        from src.gst.gnn_detector  import CircularTradingDetector

        builder     = TransactionGraphBuilder()
        G, _scores  = builder.run_full_analysis(visualize=False)
        detector    = CircularTradingDetector()
        predictions = detector.predict_fraud(G)

        assert isinstance(predictions, dict), (
            f"predict_fraud() should return a dict, got {type(predictions)}"
        )
        return predictions

    def _s6_ews(self, company_id: str) -> dict:
        from src.gst.ews_engine import EWSEngine

        engine = EWSEngine()
        report = engine.consolidate_signals(company_id)

        score = report.get("ews_score")
        assert score is not None, (
            f"'ews_score' key missing from EWS report. Keys: {list(report)}"
        )
        assert 0.0 <= score <= 10.0, (
            f"ews_score {score!r} is outside expected range [0, 10]"
        )
        return report

    def _s7_research_agent(self, company_name: str) -> dict:
        from src.agent.research_agent import ResearchAgent

        agent  = ResearchAgent()
        result = agent.run_research(company_name)

        assert result.get("synthesis_report") is not None, (
            "synthesis_report is None in ResearchAgent final state"
        )
        return dict(result)

    def _s8_feature_builder(self, company_id: str) -> dict:
        from src.scorer.feature_builder import FeatureBuilder

        builder        = FeatureBuilder()
        fv, _names     = builder.build_feature_vector(company_id)

        assert len(fv) == 35, (
            f"Expected 35-key feature vector, got {len(fv)}.\n"
            f"Keys: {sorted(fv)}"
        )
        return fv

    def _s9_credit_scorer(self, feature_vector: dict | None) -> dict:
        from src.scorer.credit_scorer import CreditScorer
        from src.scorer.feature_builder import FeatureBuilder

        if feature_vector is None:
            feature_vector = {k: 0.0 for k in FeatureBuilder.FEATURE_NAMES}

        scorer = CreditScorer()
        result = scorer.score(feature_vector)

        score = result.get("risk_score")
        assert score is not None, (
            f"'risk_score' key missing from CreditScorer output. "
            f"Keys: {list(result)}"
        )
        assert 0.0 <= score <= 10.0, (
            f"risk_score {score!r} is outside expected range [0, 10]"
        )
        return result

    def _s10_cam_generator(
        self,
        company_name: str,
        financials:   dict | None,
        bank_result:  dict | None,
        ews_result:   dict | None,
        scoring:      dict | None,
        research:     dict | None,
    ) -> Path:
        from src.cam.cam_generator import CAMGenerator

        # ── Build company_data stub ──────────────────────────────────────
        fin = (financials or {}).get("figures", {})

        company_data: dict[str, Any] = {
            "name":               company_name,
            "cin":                "U51909MH2017PTC301234",
            "incorporation_date": "2017-04-11",
            "directors": [
                "Mr. Rajesh K. Mehta — Managing Director (formerly director of struck-off entity SHELL_CO_X)",
                "Ms. Priya A. Sharma — Whole-Time Director (defendant in commercial recovery suit CCMUM/2024/0347)",
                "Mr. Dinesh P. Bhatia — CFO (joined Jan 2024, predecessor resigned without explanation)",
                "Mr. Vikram S. Joshi — Non-Executive Director",
                "Mr. Aniruddha T. Parekh — Non-Executive Director",
            ],
            "business_description": (
                "A chemical components trading and distribution entity incorporated in "
                "Maharashtra in 2017. Declared business covers procurement and redistribution "
                "of industrial chemicals, specialty polymers, and electronic components to "
                "small and medium manufacturers in the MMR region.  Entity has no significant "
                "fixed assets or warehouse infrastructure commensurate with declared turnover, "
                "raising concerns about the genuineness of trading operations."
            ),
            "loan_amount_requested": "₹500 Crore",
            "recommended_amount":    "₹NIL (Recommend REJECT)",
            "interest_rate":         "N/A",
            "tenure":                "N/A",
            "decision":              "REJECT",
            "decision_rationale": (
                "Credit application is declined on the basis of (1) confirmed GST ITC "
                "over-claim of 34.5% across nine consecutive filing periods, (2) circular "
                "trading pattern detected with confidence score 0.82, (3) director KYC "
                "concerns including prior association with a struck-off entity, (4) IT "
                "raid under Section 131 with outcome pending, (5) open MCA charges "
                "exceeding declared borrowings by 38%, and (6) collateral coverage "
                "of approximately 5% against the proposed exposure.  The aggregate risk "
                "profile is assessed as INELIGIBLE for credit sanction under our FLDG "
                "and underwriting guidelines."
            ),
            "financials_3yr": [
                {
                    "year":          "FY2024",
                    "revenue":       fin.get("revenue")       or  124_000,
                    "ebitda":        fin.get("ebitda")        or   10_292,
                    "pat":           fin.get("pat")           or    2_480,
                    "de_ratio":      2.14,
                    "current_ratio": 0.88,
                    "dscr":          0.74,
                },
                {
                    "year":          "FY2023",
                    "revenue":       108_000,
                    "ebitda":         9_100,
                    "pat":            1_800,
                    "de_ratio":      1.87,
                    "current_ratio": 0.90,
                    "dscr":          0.81,
                },
                {
                    "year":          "FY2022",
                    "revenue":        89_000,
                    "ebitda":          7_500,
                    "pat":             1_200,
                    "de_ratio":      1.60,
                    "current_ratio": 0.95,
                    "dscr":          0.92,
                },
            ],
            "gst_findings": (ews_result or {}).get("signals", {}),
            "bank_findings": (bank_result or {}).get("metrics", {}),
            "ews_flags":     (ews_result or {}).get("flags", {}),
            "ewi_triggers": [
                "IMMEDIATE: Freeze account monitoring — suspected circular fund flows detected.",
                "IMMEDIATE: Notify GST audit team — ITC over-claim of 34.5% requires field verification.",
                "HIGH: Escalate to Risk Committee — IT Section 131 search notice outstanding.",
                "HIGH: Verify MCA charge register — undisclosed charges of Rs. 5.1 crore identified.",
                "MEDIUM: Conduct personal interview with MD Rajesh K. Mehta re: SHELL_CO_X association.",
                "MEDIUM: Obtain court outcome status for CCMUM/2024/0347 before any reconsideration.",
                "MEDIUM: Require audited FY2024 financials before re-evaluating application.",
                "LOW: Re-assess if IT inquiry is closed with clean order and net worth confirmed.\n"
                      "Monitor GSTN portal for any further demand notices in next 12 months.",
            ],
        }

        scoring_result: dict[str, Any] = scoring or {
            "default_probability": 0.72,
            "risk_score":          7.8,
            "risk_band":           "HIGH",
            "shap_explanations": {
                "top_risk_factors": [
                    ["gst_itc_fraud_flag",           1.82],
                    ["circular_trading_confidence",  1.54],
                    ["ews_score",                    1.31],
                    ["revenue_inflation_flag",        0.97],
                    ["bounce_count",                 0.83],
                    ["debit_credit_ratio",            0.74],
                    ["itc_gap_pct",                  0.68],
                    ["gnn_high_risk_gstin_count",     0.61],
                    ["director_risk_flag",            0.53],
                    ["compliance_risk_flag",          0.44],
                ],
                "top_positive_factors": [
                    ["current_ratio",         0.31],
                    ["avg_monthly_balance",   0.22],
                    ["filing_regularity",     0.18],
                    ["qualitative_adjustment", 0.11],
                    ["pat_margin",             0.09],
                ],
            },
        }

        research_report: dict[str, Any] = research or {
            "synthesis_report": (
                "Significant external risk indicators detected for this entity. "
                "Multiple adverse news articles flag GST compliance violations and "
                "circular trading patterns. At least one director has prior "
                "association with a shell company that was struck off by MCA in FY2023. "
                "eCourts records show two active commercial disputes (Total claim: Rs. 12 Cr). "
                "The entity does not appear on the RBI wilful defaulter list but "
                "open MCA charges exceed declared borrowings by 38%."
            ),
            "news_summary": (
                "Media coverage reveals three adverse reports in the last 12 months: "
                "(1) Income Tax raid at registered premises (March 2025), "
                "(2) Supplier fraud complaint filed by GSTN helpdesk (August 2024), "
                "(3) GST council audit flag for ITC reversal demand of Rs. 4.2 Cr (Jan 2025). "
                "No positive signals detected in mainstream financial press."
            ),
            "promoter_risk_flag": True,
            "regulatory_compliance_summary": (
                "GSTN compliance score is LOW. ITC claims in GSTR-3B exceed GSTR-2A "
                "auto-populated values by 34.5% across 9 of 12 filing periods. "
                "GSTR-1 turnover reported is 28% below corresponding bank credit inflows, "
                "suggesting revenue under-declaration. Two MCA Form DIR-3 KYC "
                "filings are overdue for key directors. SEBI disclosures are current "
                "but three related-party transactions lack board approval minutes."
            ),
            "key_red_flags": [
                "ITC over-claim of 34.5% across 9 consecutive filing periods (GSTR-2A vs GSTR-3B)",
                "Circular trading pattern detected: 3-node cycle with confidence score 0.82",
                "Director Rajesh K. Mehta previously associated with struck-off entity SHELL_CO_X",
                "IT raid on registered premises (March 2025) — outcome pending",
                "Open MCA charges (Rs. 18.4 Cr) exceed self-declared total borrowings by 38%",
                "Revenue declared in GSTR-1 is 28% below bank credit inflow for FY2024",
                "Supplier fraud complaint lodged with GSTN helpdesk (August 2024)",
            ],
            "positive_signals": [
                "No RBI wilful defaulter list match",
                "GST returns filed on time for all 12 periods",
            ],
        }

        five_cs_text: dict[str, Any] = {
            "CHARACTER": (
                "The management profile of the borrowing entity raises significant concerns "
                "that warrant heightened scrutiny prior to credit sanction.  The managing "
                "director, Mr. Rajesh K. Mehta, has a previous directorship in SHELL_CO_X "
                "(CIN: U74999MH2017PTC123456), an entity that was struck off by the Ministry "
                "of Corporate Affairs in October 2023 following non-compliance with annual "
                "filing obligations and suspicious transaction patterns flagged by the GSTN. "
                "Mr. Mehta resigned from SHELL_CO_X eleven months before its strike-off, "
                "indicating possible foreknowledge of regulatory action. Verification of his "
                "disassociation period and the nature of transactions during the overlap "
                "period is strongly recommended before any draw-down is permitted."
                "\n\n"
                "The co-promoter, Ms. Priya A. Sharma, appears on the eCourts docket as "
                "defendant in a Rs. 7.8 crore commercial recovery suit filed by a Mumbai-based "
                "trade creditor in February 2024.  The case is listed before the City Civil "
                "Court, Mumbai (Case No. CCMUM/2024/0347) and the next hearing date is July "
                "2026.  No stay or settlement has been recorded as of the search date.  The "
                "outstanding liability, if crystallised, would reduce the effective net worth "
                "of the promoter group by approximately 12%, materially weakening personal "
                "guarantee coverage for the proposed facility."
                "\n\n"
                "A third key officer, the CFO Mr. Dinesh P. Bhatia, joined the entity in "
                "January 2024, just six months prior to this application.  His predecessor "
                "resigned without publicly stated reasons; the company's response to our "
                "query on the resignation was evasive.  In such circumstances, continuity of "
                "financial controls cannot be assumed and the quality of internal audit "
                "oversight during the transition period must be independently corroborated. "
                "The income tax raid conducted at the registered office in March 2025 and the "
                "subsequent search notice from the Income Tax Department (Section 131) remain "
                "unresolved, casting further doubt on the management's integrity profile."
                "\n\n"
                "A comprehensive CIBIL commercial credit check and CRIF High Mark search conducted "
                "as part of standard pre-screening returned one adverse entry: a sub-standard "
                "asset (SMA-1) classification by a private-sector bank on a cash-credit facility "
                "of Rs. 3.5 crore sanctioned in FY2022.  The account was regularised after a "
                "delay of 47 days.  While this event is within the acceptable threshold for "
                "isolated irregularity, in conjunction with the broader fraud indicators identified, "
                "it reinforces the pattern of deliberate cash-flow management to avoid formal NPA "
                "classification while operating at the margins of regulatory compliance. "
                "The credit team should treat this as a corroborating signal, not a standalone concern."
                "\n\n"
                "Reference checks conducted with two of the entity's stated banking counterparties "
                "yielded equivocal responses.  One relationship manager declined to provide a "
                "formal opinion and referred the query to the bank's legal team, citing 'ongoing "
                "internal audit'.  The second banker confirmed the account is 'currently regular' "
                "but added an unsolicited caveat that the entity had made 'several unusual requests "
                "for back-dated certification' in the prior fiscal year.  This finding has been "
                "documented and escalated to the Chief Risk Officer for awareness.  Under our "
                "Three-Lines-of-Defence framework, the Business Unit is advised to conduct a "
                "formal KYC Enhanced Due Diligence (EDD) review before further evaluation proceeds."
                "\n\n"
                "Overall assessment under the CHARACTER pillar: FAIL.  The convergence of a struck-off "
                "directorship, an active commercial litigation, an unexplained CFO departure, a "
                "prior SMA-1 event, an income tax search notice, and adverse banking reference remarks "
                "collectively constitute a management integrity risk that is incompatible with the "
                "proposed credit limit under our current risk appetite framework.  Remediation would "
                "require, at a minimum, a clean IT inquiry closure, full disclosure and resolution of "
                "all litigation, independent forensic verification of historical financials, and a "
                "12-month probation period of clean banking conduct before the application can be "
                "reconsidered."
                "\n\n"
                "Action Required: The Compliance and Risk team must initiate a formal Enhanced Due "
                "Diligence (EDD) process for this borrower before any committee presentation is "
                "allowed.  EDD scope should include: (a) independent forensic verification of "
                "all director backgrounds and prior company associations; (b) independent "
                "legal opinion on the status and probable outcome of CCMUM/2024/0347; "
                "(c) written confirmation from the statutory auditor on the nature of related-party "
                "emphasis-of-matter paragraphs; and (d) police verification and physical KYC for "
                "all directors.  Until EDD is complete, this application is SUSPENDED."
            ),
            "CAPACITY": (
                "The entity's debt-servicing capacity presents a structurally weak profile "
                "when assessed against our minimum underwriting thresholds.  Declared revenue "
                "in GSTR-1 for FY2024 stands at Rs. 124 crore; however, corresponding bank "
                "credit inflows as captured in the account-aggregator feed total Rs. 172 crore, "
                "implying an under-declaration of approximately 28%.  This discrepancy "
                "undermines the reliability of any income-based capacity analysis and prevents "
                "the assignment of a conventional DSCR figure with confidence."
                "\n\n"
                "Using the declared financials at face value, EBITDA margins for FY2024 are "
                "estimated at 8.3%, below the industry median of 12.5% for comparable SME "
                "trading entities in the chemicals distribution segment.  Interest coverage "
                "on the existing Rs. 22 crore working-capital facility is approximately 1.3x, "
                "below our minimum threshold of 1.5x.  The proposed additional facility of "
                "Rs. 500 crore would increase total interest obligations to a level that the "
                "declared EBITDA cannot serviceably cover, even under optimistic growth "
                "projections.  Stress-testing at a 15% revenue contraction scenario (a "
                "realistic outcome given the ongoing IT inquiry) yields a DSCR of 0.7x — "
                "deep into distress territory."
                "\n\n"
                "Cash-flow analysis from the 12-month bank statement reveals a debit-to-credit "
                "ratio of 0.94, which is superficially healthy, but drilling down shows that "
                "approximately 62% of all inflows are received from three counterparty GSTs "
                "that are themselves flagged by the GNN circular-trading model.  This suggests "
                "that the apparent cash-flow strength is an accounting artefact of circular "
                "transactions rather than genuine business activity.  Net free cash flow after "
                "stripping out suspected circular flows is estimated at Rs. 3.2 crore per "
                "annum — insufficient to service even the interest on the proposed facility."
                "\n\n"
                "The working capital cycle analysis reveals a debtor-collection period of 84 days "
                "against a creditor-payment period of 21 days, producing a net working-capital gap "
                "of 63 days.  For a business turning over Rs. 124 crore declared, this implies a "
                "structural working-capital funding requirement of Rs. 21.4 crore.  The entity's "
                "current sanctioned limits of Rs. 22 crore are therefore fully absorbed by the "
                "operating cycle without any free headroom.  Any incremental exposure would "
                "effectively be funding a gap that already exceeds the entity's ability to generate "
                "organic liquidity.  This cycle analysis is based on declared figures; if actual "
                "turnover is closer to the bank-implied Rs. 172 crore, the working-capital gap "
                "would proportionally increase the structural underfunding by a further Rs. 8–10 crore."
                "\n\n"
                "Sensitivity modelling at three scenarios corroborates the weak capacity profile: "
                "(i) Base case (FY2024 declared revenue, static margins): DSCR = 0.74x on proposed "
                "facility — FAIL; (ii) Optimistic case (+10% revenue, +1% margin): DSCR = 0.91x — "
                "FAIL; (iii) Stress case (-15% revenue, -2% margin): DSCR = 0.55x — SEVERE FAIL. "
                "None of the three scenarios produces a passing DSCR above our 1.25x threshold.  "
                "The only scenario in which capacity would be adequate is one that assumes "
                "actual turnover matches the bank-credit figure of Rs. 172 crore AND margins "
                "improve to 13%.  Both conditions would require the entity to declare the "
                "suppressed income, creating a substantially larger tax and GST liability that "
                "would itself erode the capacity improvement.  Capacity is therefore NOT "
                "demonstrated under any realistic or compliant scenario."
                "\n\n"
                "Overall assessment under the CAPACITY pillar: FAIL.  The entity cannot demonstrate "
                "adequate debt-servicing capacity for the proposed facility under any reasonable "
                "projection methodology.  The primary impediment is the structural misalignment "
                "between declared income (on which DSCR is calculated) and actual cash inflows "
                "(which suggest income suppression).  Until the entity regularises its GST and "
                "income tax position and provides audited financials that reconcile with banking "
                "data, reliable capacity assessment is impossible.  No waiver or override is "
                "recommended at this stage."
                "\n\n"
                "Action Required: Credit team should request an account-aggregator (AA) pull of "
                "the entity's full banking data across all institutions under the RBI AA Framework "
                "to independently verify total credit inflows for FY2023 and FY2024.  This data, "
                "cross-referenced against GSTN declared turnover and IT returns, will quantify the "
                "exact extent of income suppression and provide a factual basis for either rejecting "
                "the application or referring the findings to the Financial Intelligence Unit (FIU-IND). "
                "The AA pull should be obtained within 10 working days.  All lending decisions are "
                "SUSPENDED pending receipt and review of this data."
            ),
            "CAPITAL": (
                "Reported net worth of the borrower stands at Rs. 18.4 crore as per the "
                "most recent audited balance sheet (FY2023).  However, this figure must be "
                "adjusted for (a) the potential ITC reversal demand of Rs. 4.2 crore raised "
                "by the GST audit officer, (b) the outstanding litigation liability of "
                "Rs. 7.8 crore, and (c) the estimated impact of the income tax inquiry, "
                "which could crystallise into an additional demand of Rs. 3–8 crore based on "
                "the scope of the Section 131 notice.  Post-adjustment effective net worth "
                "ranges from Rs. 2.4 crore (bear case) to Rs. 8.6 crore (base case)."
                "\n\n"
                "Open MCA charges on the company's assets total Rs. 18.4 crore across four "
                "lenders, of which Rs. 11.2 crore represents charges created in the last 18 "
                "months.  The company's own disclosure in the loan application states total "
                "outstanding secured borrowings of Rs. 13.3 crore — a gap of Rs. 5.1 crore "
                "that is unexplained.  Either the MCA charge register is not fully reflected "
                "in the borrower's own books (a red flag for completeness of disclosure) or "
                "there are undisclosed debt obligations.  Under both interpretations, the "
                "effective leverage ratio is higher than disclosed and equity cushion is thinner "
                "than the stated net worth implies."
                "\n\n"
                "Promoter equity contribution to the current business stands at Rs. 8 crore "
                "out of a total capital base of Rs. 18.4 crore (43%), with the balance "
                "comprising retained earnings and brought-forward reserves.  The promoter "
                "group holds no significant unencumbered personal assets that can be verified "
                "through publicly available sources.  Personal guarantee provided by "
                "Mr. Rajesh K. Mehta has not been supported by an independent wealth "
                "statement.  Given the promoter's association with a struck-off entity and "
                "the ongoing litigation, the practical enforceability of the guarantee is "
                "assessed as LOW."
                "\n\n"
                "Tangible Net Worth (TNW) analysis using the most conservative permissible "
                "adjustments produces the following decomposition: (i) Gross net worth per "
                "audited accounts Rs. 18.4 crore; (ii) Less: ITC reversal contingency Rs. 4.2 crore; "
                "(iii) Less: Litigation contingency Rs. 7.8 crore; (iv) Less: IT inquiry estimated "
                "minimum demand Rs. 3.0 crore; (v) Less: Undisclosed MCA charge gap Rs. 5.1 crore; "
                "Adjusted TNW = Rs. -1.7 crore.  The entity's capital base is technically "
                "negative on a fully stress-adjusted basis.  Even using the base-case IT inquiry "
                "outcome (Rs. 3 crore demand), the TNW stands at Rs. -1.7 crore, while using the "
                "worst-case outcome (Rs. 8 crore demand), the TNW falls to Rs. -6.7 crore.  "
                "Capital adequacy fails under all reasonable stress scenarios."
                "\n\n"
                "Retained earnings quality assessment reveals that the FY2023 and FY2024 "
                "audited accounts carry an emphasis-of-matter paragraph from the statutory "
                "auditors regarding 'certain related-party transactions for which management "
                "representation has been provided but independent documentation is not available'. "
                "The auditor did not qualify the accounts but flagged the concern.  In our "
                "experience, such emphasis-of-matter paragraphs frequently indicate that reserves "
                "and retained earnings include profits from transactions that may be unwound if "
                "the underlying arrangements are scrutinised.  The quality of retained earnings "
                "(approximately Rs. 10.4 crore of the Rs. 18.4 crore capital base) is therefore "
                "assessed as UNCERTAIN, further eroding confidence in the stated capital position."
                "\n\n"
                "Overall assessment under the CAPITAL pillar: FAIL.  On a stress-adjusted basis, "
                "the borrower's net worth is negative, and the quality of declared retained earnings "
                "is further impaired by auditor concerns on related-party documentation.  The "
                "leverage ratio on a fully-loaded basis (incorporating undisclosed MCA charges) "
                "stands at approximately 5.8x debt-to-equity, well above our maximum threshold "
                "of 3.0x for this borrower segment.  No credit should be extended until a "
                "positive adjusted TNW is demonstrated and independently verified."                "\n\n"
                "Action Required: A pro-forma Adjusted Balance Sheet must be prepared incorporating "
                "all identified contingent liabilities at their most-likely values before the "
                "CAPITAL assessment can be formally concluded.  The Risk team should also request "
                "a Share Pledge Disclosure Certificate from the entity's depository participant "
                "to confirm that no promoter shares are pledged to undisclosed lenders.  These "
                "steps are prerequisite to assigning a final CAPITAL rating.  Current assessment "
                "is PROVISIONAL FAIL based on available information; confirmation of final "
                "fail is expected once AA data and adjustments are incorporated."            ),
            "COLLATERAL": (
                "The primary security offered is a first and exclusive hypothecation charge "
                "over book debts and current assets of the borrowing entity.  Based on the "
                "books declared, eligible current assets (debtors < 90 days + net inventory) "
                "total Rs. 31 crore.  Applying a standard haircut of 25% yields a realisable "
                "value of Rs. 23.3 crore.  Against the proposed exposure, this translates to "
                "a collateral coverage ratio of 0.047x — materially below the minimum of "
                "1.0x required under our credit policy for unsecured-to-current-asset ratio."
                "\n\n"
                "The additional security proposed is a personal guarantee by the promoter "
                "director (Mr. Rajesh K. Mehta) and a lien over a residential property in "
                "Thane, Maharashtra.  The property valuation report (submitted by the "
                "borrower's own empanelled valuer, not independently verified) states a "
                "market value of Rs. 4.8 crore and a distressed value of Rs. 3.6 crore. "
                "Title search by our legal team is pending; preliminary checks reveal one "
                "undisclosed prior mortgage in favour of a cooperative bank, created in "
                "FY2021 and not released as of the search date.  If confirmed, the net "
                "realisable value from this property falls to near zero after clearing the "
                "prior charge."
                "\n\n"
                "In summary, the total verified and realisable collateral supporting the "
                "proposed exposure of Rs. 500 crore stands at approximately Rs. 23–27 crore, "
                "representing a coverage ratio of approximately 5%, far below acceptable "
                "parameters.  No immovable industrial property, plant or equipment has been "
                "offered that could provide meaningful incremental coverage.  Credit committee "
                "should require substantially enhanced security or reduce the exposure to a "
                "level commensurate with verified collateral before any sanction is considered."
                "\n\n"
                "An independent verification exercise was conducted on the entity's debtors "
                "as reflected in the information memorandum.  Of the top-10 debtors per the "
                "borrower's own schedule (accounting for 78% of total receivables), four could "
                "not be verified as legitimate business entities in MCA-21, GSTN, or commercial "
                "databases.  Two firms appeared to have been incorporated within 90 days of "
                "the invoice date, suggesting possible fictitious-debtor creation to inflate "
                "book receivables.  One debtor GSTIN had filed Nil returns in GSTR-1 for the "
                "period in which the borrower declared receiving Rs. 4.3 crore of supply from "
                "that party — a direct contradiction between the two entities' GSTN declara "
                "tions.  These findings materially reduce the reliability of the current-assets "
                "base that constitutes the primary hypothecation security."
                "\n\n"
                "Overall assessment under the COLLATERAL pillar: FAIL.  Verified and realisable "
                "collateral covers approximately 4-5% of the proposed exposure, compared to "
                "our minimum requirement of 100% (1.0x coverage ratio) for working-capital "
                "facilities.  The quality of current assets is further impaired by evidence of "
                "fictitious debtors.  The immovable property offered has an undisclosed prior "
                "charge that renders it of negligible incremental value.  The personal guarantee "
                "is assessed as LOW enforceability.  Collateral support for the proposed facility "
                "is wholly inadequate.  A credit decision to proceed would require a "
                "disproportionate reliance on income-based repayment that, as demonstrated under "
                "CAPACITY, cannot be established.  The credit committee must reject the "
                "application or seek unencumbered real-estate collateral of at least Rs. 500 crore."
                "\n\n"
                "Action Required: Legal team should immediately initiate title deed verification "
                "for the Thane property with an independent empanelled lawyer.  Simultaneously, "
                "the debtors schedule should be sent to the GSTN portal for cross-matching against "
                "GSTR-1 data of the top-10 debtors.  Any confirmed fictitious debtors should be "
                "reported to the Risk Committee and, if evidenced, to the relevant authorities "
                "under our Suspicious Transaction Reporting obligations.  All collateral-related "
                "diligence findings must be documented in a Collateral Adequacy Report for Credit Committee."
            ),
            "CONDITIONS": (
                "Macro-economic conditions in the chemicals trading and distribution sector "
                "are broadly neutral for FY2025–26.  Crude oil and specialty chemicals input "
                "prices have moderated by approximately 8% on a year-on-year basis, "
                "which could benefit gross margins if passed through to end customers. "
                "Domestic demand from infrastructure and manufacturing sectors remains robust, "
                "supporting volume growth expectations of 6–8% per annum.  However, these "
                "sector-level tailwinds are of limited relevance to this specific borrower "
                "given the systemic concerns identified above."
                "\n\n"
                "The regulatory environment for GST compliance has tightened significantly "
                "following the Finance Act 2024 amendments.  Enhanced scrutiny of ITC claims, "
                "mandatory e-invoicing for all entities with turnover > Rs. 5 crore, and "
                "real-time reconciliation between GSTR-1, GSTR-2B and GSTR-3B have materially "
                "reduced the window for ITC manipulation.  For an entity already flagged by "
                "the GSTN for over-claims, the risk of a retrospective ITC reversal demand in "
                "FY2025 filings is HIGH.  The GST department's Section 74 proceedings, once "
                "initiated, can freeze bank accounts, creating a sudden and severe liquidity "
                "shock that would directly impair the borrower's ability to service the "
                "proposed facility."
                "\n\n"
                "The income tax inquiry under Section 131 is at an early stage but carries "
                "significant escalation risk.  If the IT department determines that undisclosed "
                "income exceeds Rs. 25 crore (a plausible outcome given the bank-GST revenue "
                "discrepancy of Rs. 48 crore), penalties under Section 270A could be levied "
                "at 200% of the tax on under-reported income.  In a tail scenario, the "
                "combined GST demand, IT demand, and litigation verdicts could exceed the "
                "borrower's entire net worth, rendering the entity technically insolvent before "
                "the proposed facility's first repayment date. Lending at this juncture, "
                "without robust safeguards, would represent an imprudent extension of credit."
                "\n\n"
                "Peer comparison places this entity in the bottom decile of 420 SME chemicals "
                "distributors profiled in our internal credit database.  Median DSCR for the "
                "peer group is 1.72x versus 0.74x for this borrower.  Median ITC gap is 4.2% "
                "versus 34.5%.  Median EWS score is 1.4 versus 3.4 for this borrower.  Peer "
                "median compliance index (combining GSTN score, MCA filing status, and IT "
                "return regularity) is 0.72 versus 0.41 for this borrower.  The entity is not "
                "merely below average; it is an outlier on multiple risk dimensions simultaneously, "
                "suggesting systematic rather than incidental compliance failure — a pattern "
                "more consistent with intentional manipulation than operational difficulty."
                "\n\n"
                "Looking ahead, the regulatory pipeline poses additional headwinds.  The GST "
                "Council's proposed Invoice Matching System (IMS) — currently in pilot — will, "
                "if fully rolled out, make real-time ITC over-claims detectable at the time of "
                "GSTR-3B filing rather than post-hoc.  For this entity, adoption of IMS would "
                "mean an immediate reduction in ITC credits claimed, directly reducing net tax "
                "refunds and increasing cash outflows by an estimated Rs. 1.4–1.8 crore per "
                "quarter.  Additionally, SEBI's proposed credit-bureau reporting for MSME exposures "
                "above Rs. 25 crore would, in future cycles, make the undisclosed MCA charges "
                "and SMA-1 history visible to all prospective lenders, increasing the cost and "
                "difficulty of future refinancing for this entity.  Both developments increase "
                "refinancing risk and reduce the likelihood of orderly repayment even if the "
                "current facility were sanctioned."
                "\n\n"
                "Overall assessment under the CONDITIONS pillar: ADVERSE.  While the broad macro "
                "environment for the chemicals distribution sector is neutral-to-positive, the "
                "specific regulatory, enforcement, and peer-relative conditions facing this "
                "entity are highly adverse.  The tightening GST compliance regime increases the "
                "probability of a sudden reversal demand; the IT inquiry raises the risk of "
                "account attachment; the proposed IMS rollout would immediately impair cash flow. "
                "There are no compensating macro tailwinds that would plausibly offset these "
                "entity-specific headwinds.  The conditions pillar reinforces the REJECT recommendation."
                "\n\n"
                "Action Required: No further processing of this credit application is recommended. "
                "The final credit decision should be communicated to the applicant within the "
                "statutory 30-day window from receipt of complete documentation.  Detailed "
                "findings of this appraisal must be archived in the credit intelligence database "
                "for a minimum of 7 years.  The MI team should add this entity to the Watchlist "
                "system, flagging all future applications from associated persons and entities "
                "for mandatory CRO review.  Any further enquiry from this applicant should be "
                "referred to the Chief Risk Officer for final disposition."
            ),
        }

        out_path = _PROJECT_ROOT / "outputs" / "CAM_COMP_C.docx"
        gen  = CAMGenerator()
        path = gen.generate_cam(
            company_data, scoring_result, research_report, five_cs_text, out_path
        )

        assert path.exists(), f"Output .docx not found at {path}"
        file_size = path.stat().st_size
        assert file_size > 50_000, (
            f"Output .docx too small: {file_size:,} bytes (expected > 50,000 bytes / 50 KB).\n"
            f"Path: {path}"
        )
        return path


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    """Run the E2E test with synthetic + repo demo fixtures.  Returns exit code."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        synthetic_pdf = Path(tmp_dir) / "synthetic_annual_report.pdf"
        _create_synthetic_pdf(synthetic_pdf)

        test   = E2ETest()
        passed = test.run_full_pipeline(
            company_name  = "COMP C Fraud Industries",
            pdf_path      = synthetic_pdf,
            bank_csv_path = _BANK_CSV,
            gst_dir       = _GST_DIR,
            company_id    = "COMP_C_FRAUD",
        )

    return 0 if passed else 1


if __name__ == "__main__":
    # Enable ANSI colours on Windows
    import os
    if sys.platform == "win32":
        os.system("")   # activates VT100 processing in cmd/PowerShell

    sys.exit(main())
