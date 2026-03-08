"""
run_ril_pipeline.py
===================
Runs the full 10-step IntelliCredit pipeline against the real
Reliance Industries annual report PDF that lives at:

    data/raw/ril_annual_report.pdf

All other inputs (bank statement, GST files, EWS signals, feature
vector) are sourced from the existing RIL fixtures already present in
the repo.

Usage (from project root):

    python tests/run_ril_pipeline.py

Steps
-----
  [01] PDFParser           — parses ril_annual_report.pdf
  [02] FinancialExtractor  — extracts revenue / EBITDA / PAT / debt etc.
  [03] BankStatementAnalyzer — uses data/raw/bank_statement_sample.csv
  [04] GSTReconciler       — uses data/raw/gst/RIL_gstr*.json
  [05] GraphBuilder + GNN  — runs circular-trading detection
  [06] EWSEngine           — loads / builds RIL EWS signals
  [07] ResearchAgent       — online research for "Reliance Industries"
  [08] FeatureBuilder      — assembles 35-feature gold vector for RIL
  [09] CreditScorer        — scores the feature vector
  [10] CAMGenerator        — writes outputs/CAM_RIL.docx
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ── project-root path bootstrap ───────────────────────────────────────────
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Enable ANSI colours on Windows
if sys.platform == "win32":
    os.system("")

# ── Import the shared E2ETest harness ─────────────────────────────────────
from tests.test_end_to_end import E2ETest  # noqa: E402

# ── Paths ─────────────────────────────────────────────────────────────────
_PDF        = _ROOT / "data" / "raw" / "ril_annual_report.pdf"
_BANK_CSV   = _ROOT / "data" / "raw" / "bank_statement_sample.csv"
_GST_DIR    = _ROOT / "data" / "raw" / "gst"
_COMPANY_ID = "RIL"
_COMPANY_NAME = "Reliance Industries Limited"


def main() -> int:
    if not _PDF.exists():
        print(f"[ERROR] PDF not found: {_PDF}")
        print("  Please ensure data/raw/ril_annual_report.pdf is present.")
        return 1

    print(f"\n  PDF        : {_PDF.name}  ({_PDF.stat().st_size / 1024:.0f} KB)")
    print(f"  Company ID : {_COMPANY_ID}")
    print(f"  GST dir    : {_GST_DIR.relative_to(_ROOT)}")
    print(f"  Bank CSV   : {_BANK_CSV.relative_to(_ROOT)}")

    test   = E2ETest()
    passed = test.run_full_pipeline(
        company_name  = _COMPANY_NAME,
        pdf_path      = _PDF,
        bank_csv_path = _BANK_CSV,
        gst_dir       = _GST_DIR,
        company_id    = _COMPANY_ID,
    )
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
