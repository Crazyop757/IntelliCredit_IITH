"""
ews_engine.py — Early Warning Score (EWS) engine for intelli_credit.

Aggregates ALL signals produced by Day-1 and Day-2 modules into a single
unified EWS report and persists it to the Gold feature store.

Signal sources
--------------
1. **Bank metrics**       — BankStatementAnalyzer via Silver JSONL
2. **GST reconciliation** — GSTReconciler.run_full_reconciliation()
3. **GNN fraud score**    — CircularTradingDetector.predict_fraud()
4. **NER / PDF signals**  — FinancialExtractor + NERExtractor via Silver JSONL

8 EWS flags (each: HIGH / MEDIUM / LOW / CLEAR)
------------------------------------------------
1. gst_itc_fraud_risk       — ITC over-claim detected by reconciler + GNN
2. circular_trading_risk    — Circular transaction rings in GNN graph
3. revenue_inflation_risk   — GST turnover vs bank credit mismatch
4. cash_stress_risk         — Liquidity / bounce / DSCR stress
5. documentation_risk       — Risk clauses in annual report / filings
6. auditor_concern_risk     — Qualified opinion or negative auditor sentiment
7. director_risk            — Director-linked fraud / SFIO mentions
8. compliance_risk          — Fictitious vendors, GST grade, filing gaps

Weighted EWS score (0 – 5 scale)
---------------------------------
  circular_trading  × 0.250
  gst_itc_fraud     × 0.200
  revenue_inflation × 0.200
  auditor_concern   × 0.150
  cash_stress       × 0.100
  documentation     × 0.033  ⌐
  director          × 0.033   ├─ "others" total weight 0.100
  compliance        × 0.034  ┘

SMA classification (score is normalised to the available data sources)
----------------------------------------------------------------------
  SMA-0 (Standard)  : normalised EWS < 1.0
  SMA-1 (Watch)     : 1.0 ≤ normalised EWS ≤ 3.0
  SMA-2 (Stressed)  : normalised EWS > 3.0
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Project-root path resolution (works whether run as script or import)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.config import DATA_GOLD, DATA_SILVER

logger = logging.getLogger("intelli_credit.gst.ews_engine")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_GST_RAW_DIR   = _PROJECT_ROOT / "data" / "raw" / "gst"
_GOLD_DIR      = DATA_GOLD / "gold_features"
_GOLD_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Flag levels and their numeric weights for score computation
# ---------------------------------------------------------------------------
_FLAG_LEVELS   = ("HIGH", "MEDIUM", "LOW", "CLEAR")
_LEVEL_VALUE: dict[str, float] = {
    "HIGH":   5.0,
    "MEDIUM": 2.5,
    "LOW":    1.0,
    "CLEAR":  0.0,
}
_FLAG_WEIGHTS: dict[str, float] = {
    "circular_trading_risk":  0.250,
    "gst_itc_fraud_risk":     0.200,
    "revenue_inflation_risk": 0.200,
    "auditor_concern_risk":   0.150,
    "cash_stress_risk":       0.100,
    "documentation_risk":     0.033,
    "director_risk":          0.033,
    "compliance_risk":        0.034,   # 0.100 / 3 rounded
}

# ---------------------------------------------------------------------------
# SMA thresholds
# ---------------------------------------------------------------------------
_SMA_THRESHOLDS = [
    ("SMA-2", 3.0),   # normalised score > 3.0
    ("SMA-1", 1.0),   # normalised score >= 1.0
    ("SMA-0", 0.0),   # normalised score < 1.0
]


# ===========================================================================
# EWSEngine
# ===========================================================================

class EWSEngine:
    """
    Aggregate multi-source credit risk signals into a unified Early Warning
    Score report.

    Parameters
    ----------
    gst_dir : str | Path | None
        Directory containing ``{company_id}_gstr*.json`` files.
        Defaults to ``data/raw/gst/``.
    model_path : str | Path | None
        Path to a pre-trained GNN model checkpoint
        (``models/gnn_fraud_detector.pt``).  Will be used if it exists;
        falls back to rule-based graph analysis otherwise.
    """

    def __init__(
        self,
        gst_dir:    str | Path | None = None,
        model_path: str | Path | None = None,
    ) -> None:
        self.gst_dir    = Path(gst_dir) if gst_dir else _GST_RAW_DIR
        self.model_path = (
            Path(model_path) if model_path
            else _PROJECT_ROOT / "models" / "gnn_fraud_detector.pt"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def consolidate_signals(self, company_id: str) -> dict[str, Any]:
        """
        Run the full EWS pipeline for *company_id*.

        Steps
        -----
        1. Load bank-level metrics from the Silver JSONL layer.
        2. Run (or reload cached) GST reconciliation.
        3. Obtain GNN fraud predictions for the company GSTIN.
        4. Load NER / PDF risk signals from the Silver JSONL layer.
        5. Compute the 8 individual EWS flag levels.
        6. Compute the weighted EWS score.
        7. Classify the SMA band.
        8. Persist the full EWS report to Gold feature store and return it.

        Returns
        -------
        dict — complete EWS report including flags, score, SMA band, and all
               intermediate signal values.
        """
        logger.info("EWS consolidation started for %s", company_id)

        # ── 1. Bank metrics ──────────────────────────────────────────────
        bank_metrics = self._load_bank_metrics(company_id)

        # ── 2. GST reconciliation ─────────────────────────────────────────
        gst_report = self._load_gst_reconciliation(company_id)

        # ── 3. GNN fraud predictions ──────────────────────────────────────
        gnn_preds = self._load_gnn_predictions(company_id)

        # ── 4. NER / PDF signals ──────────────────────────────────────────
        ner_signals = self._load_ner_signals(company_id)

        # ── 5. Compute 8 EWS flag levels ──────────────────────────────────
        flags = self._compute_flags(bank_metrics, gst_report, gnn_preds, ner_signals)

        # ── 6. Weighted EWS score ─────────────────────────────────────────
        ews_score = self._compute_score(flags, bank_metrics, gst_report, gnn_preds, ner_signals)

        # ── 7. SMA classification ─────────────────────────────────────────
        sma_class = self._classify_sma(ews_score)

        # ── 8. Build and persist report ───────────────────────────────────
        report = self._build_report(
            company_id  = company_id,
            flags       = flags,
            ews_score   = ews_score,
            sma_class   = sma_class,
            bank_metrics = bank_metrics,
            gst_report  = gst_report,
            gnn_preds   = gnn_preds,
            ner_signals = ner_signals,
        )
        self._persist_gold(company_id, report)

        logger.info(
            "EWS complete for %s — score=%.3f  SMA=%s",
            company_id, ews_score, sma_class,
        )
        return report

    # ------------------------------------------------------------------
    # Step 1: Load bank metrics
    # ------------------------------------------------------------------

    def _load_bank_metrics(self, company_id: str) -> dict[str, Any]:
        """
        Load bank + financial-ratio metrics from the Silver JSONL layer.

        Returns a normalised dict with keys:
            bounce_count, debit_credit_ratio, avg_monthly_balance,
            current_ratio, dscr, debt_to_equity, revenue (INR cr)
        """
        silver = self._read_latest_silver_record(company_id)
        if silver is None:
            logger.warning("[%s] No Silver record found — bank metrics unavailable.", company_id)
            return {}

        return {
            "avg_monthly_balance": None,            # not in silver; rely on ratios
            "bounce_count":        None,
            "debit_credit_ratio":  None,
            "current_ratio":       silver.get("current_ratio"),
            "dscr":                silver.get("dscr"),
            "debt_to_equity":      silver.get("debt_to_equity"),
            "revenue_crore":       silver.get("revenue"),
            "ebitda_crore":        silver.get("ebitda"),
            "interest_coverage":   silver.get("interest_coverage"),
        }

    # ------------------------------------------------------------------
    # Step 2: GST reconciliation
    # ------------------------------------------------------------------

    def _load_gst_reconciliation(self, company_id: str) -> dict[str, Any]:
        """
        Run GSTReconciler.run_full_reconciliation() for *company_id*.

        Returns the full reconciliation report dict, or an empty dict
        when GST data does not exist for the company.
        """
        gstr1_path = self.gst_dir / f"{company_id}_gstr1.json"
        if not gstr1_path.exists():
            logger.info("[%s] No GST data found — skipping reconciliation.", company_id)
            return {}

        try:
            from src.gst.reconciler import GSTReconciler  # noqa: PLC0415
            reconciler = GSTReconciler(gst_dir=str(self.gst_dir))
            return reconciler.run_full_reconciliation(company_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[%s] GST reconciliation failed: %s", company_id, exc)
            return {}

    # ------------------------------------------------------------------
    # Step 3: GNN fraud predictions
    # ------------------------------------------------------------------

    def _load_gnn_predictions(self, company_id: str) -> dict[str, Any]:
        """
        Build the GST transaction graph and obtain per-GSTIN fraud scores.

        If fewer than 5 labelled fraud nodes are available, the detector
        automatically falls back to rule-based PageRank scoring.

        Returns a dict keyed by GSTIN:
            {gstin: {"fraud_probability": float, "risk_flag": str, "method": str}}
        """
        if not list(self.gst_dir.glob("*_gstr1.json")):
            logger.info("[%s] No GST files found — skipping GNN predictions.", company_id)
            return {}

        try:
            from src.gst.graph_builder import TransactionGraphBuilder    # noqa: PLC0415
            from src.gst.gnn_detector  import (                          # noqa: PLC0415
                CircularTradingDetector, collect_fraud_gstins,
            )

            builder = TransactionGraphBuilder(gst_dir=str(self.gst_dir))
            G, _    = builder.run_full_analysis(visualize=False)

            detector = CircularTradingDetector(
                model_path=self.model_path if self.model_path.exists() else None
            )

            # If a trained model exists, load it; otherwise train on the fly
            if self.model_path.exists():
                detector.load_model(self.model_path)
            else:
                fraud_gstins      = collect_fraud_gstins(self.gst_dir)
                data, node_index  = detector.convert_to_pyg_data(G)
                labels            = detector.make_labels(node_index, fraud_gstins)
                detector.train_model(data, labels, epochs=100)

            all_preds = detector.predict_fraud(G)

            # Scope predictions to only this company's own GSTINs so that
            # a fraudulent ring in another company does not infect COMP_A.
            company_gstins = self._get_company_gstins(company_id)
            if company_gstins:
                scoped = {g: v for g, v in all_preds.items() if g in company_gstins}
                return scoped if scoped else all_preds
            return all_preds

        except Exception as exc:  # noqa: BLE001
            logger.warning("[%s] GNN prediction failed: %s", company_id, exc)
            return {}

    def _get_company_gstins(self, company_id: str) -> set[str]:
        """
        Collect supplier GSTINs from the company's GSTR-2A file.

        We scope GNN fraud predictions to these GSTINs only, because our goal
        is to detect whether this company **bought from** fictitious/ring
        vendors.  Using the company's own GSTIN or buyer GSTINs from GSTR-1
        can introduce false positives when another company's fraudulent ring
        lists a legitimate company as a supplier in its circular invoices.
        """
        gstins: set[str] = set()
        gstr2a_path = self.gst_dir / f"{company_id}_gstr2a.json"
        if not gstr2a_path.exists():
            return gstins
        try:
            with gstr2a_path.open(encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:  # noqa: BLE001
            return gstins
        for inv in data.get("auto_populated_invoices", []):
            if inv.get("supplier_gstin"):
                gstins.add(inv["supplier_gstin"])
        gstins.discard("")
        return gstins

    # ------------------------------------------------------------------
    # Step 4: NER / PDF signals
    # ------------------------------------------------------------------

    def _load_ner_signals(self, company_id: str) -> dict[str, Any]:
        """
        Load NER, auditor sentiment, risk clauses, and director data
        from the Silver JSONL layer.

        Returns a dict with:
            risk_clauses (list), directors (list),
            auditor_flag (bool), sentiment_score (float|None),
            high_risk_clause_count, medium_risk_clause_count
        """
        silver = self._read_latest_silver_record(company_id)
        if silver is None:
            return {
                "risk_clauses":           [],
                "directors":              [],
                "auditor_flag":           False,
                "sentiment_score":        None,
                "high_risk_clause_count": 0,
                "medium_risk_clause_count": 0,
            }

        risk_clauses: list[dict] = json.loads(silver.get("risk_clauses_json") or "[]")
        directors:    list[dict] = json.loads(silver.get("directors_json")    or "[]")

        high_count   = sum(1 for c in risk_clauses if c.get("severity") == "HIGH")
        medium_count = sum(1 for c in risk_clauses if c.get("severity") == "MEDIUM")

        return {
            "risk_clauses":             risk_clauses,
            "directors":                directors,
            "auditor_flag":             bool(silver.get("auditor_flag", False)),
            "sentiment_score":          silver.get("sentiment_score"),
            "high_risk_clause_count":   high_count,
            "medium_risk_clause_count": medium_count,
        }

    # ------------------------------------------------------------------
    # Step 5: Compute the 8 EWS flags
    # ------------------------------------------------------------------

    def _compute_flags(
        self,
        bank:  dict[str, Any],
        gst:   dict[str, Any],
        gnn:   dict[str, Any],
        ner:   dict[str, Any],
    ) -> dict[str, str]:
        """Return the 8 EWS flag levels (HIGH/MEDIUM/LOW/CLEAR)."""
        return {
            "gst_itc_fraud_risk":      self._flag_gst_itc_fraud(gst, gnn),
            "circular_trading_risk":   self._flag_circular_trading(gnn, gst),
            "revenue_inflation_risk":  self._flag_revenue_inflation(gst, bank),
            "cash_stress_risk":        self._flag_cash_stress(bank),
            "documentation_risk":      self._flag_documentation(ner),
            "auditor_concern_risk":    self._flag_auditor_concern(ner),
            "director_risk":           self._flag_director_risk(ner),
            "compliance_risk":         self._flag_compliance(gst),
        }

    # ── Individual flag methods ──────────────────────────────────────────

    def _flag_gst_itc_fraud(
        self, gst: dict[str, Any], gnn: dict[str, Any]
    ) -> str:
        """
        ITC over-claim risk.

        HIGH   — ITC gap > 20 %  OR  any GSTIN with GNN P ≥ 0.70
        MEDIUM — ITC gap 10–20 % OR  any GSTIN with GNN P ≥ 0.40
        LOW    — ITC gap  5–10 % OR  any GSTIN with GNN P ≥ 0.20
        CLEAR  — otherwise
        """
        # GST reconciler signal
        itc_risk = "CLEAR"
        itc_rec = gst.get("itc_reconciliation", {})
        overall_risk = itc_rec.get("summary", {}).get("overall_risk", "CLEAR")
        if overall_risk == "HIGH_RISK":
            itc_risk = "HIGH"
        elif overall_risk == "SUSPICIOUS":
            itc_risk = "MEDIUM"
        else:
            gap_pct = itc_rec.get("summary", {}).get("gap_percentage", 0.0) or 0.0
            if gap_pct >= 5.0:
                itc_risk = "LOW"

        # GNN signal — pick the highest-probability GSTIN
        max_prob = max((v["fraud_probability"] for v in gnn.values()), default=0.0)
        if max_prob >= 0.70:
            gnn_risk = "HIGH"
        elif max_prob >= 0.40:
            gnn_risk = "MEDIUM"
        elif max_prob >= 0.20:
            gnn_risk = "LOW"
        else:
            gnn_risk = "CLEAR"

        return _max_flag(itc_risk, gnn_risk)

    def _flag_circular_trading(
        self, gnn: dict[str, Any], gst: dict[str, Any]
    ) -> str:
        """
        Circular-trading risk.

        HIGH   — fictitious vendor risk = HIGH_RISK (≥ 3 fake vendors)
                 OR ≥ 1 supplier GSTIN with GNN HIGH_RISK flag
        MEDIUM — fictitious vendor risk = SUSPICIOUS (1–2 fake vendors)
                 OR ≥ 1 supplier GSTIN with GNN MEDIUM_RISK flag
        LOW    — fictitious vendor count > 0 (unclassified risk)
        CLEAR  — otherwise
        """
        # Primary signal: fictitious-vendor risk from reconciler
        fict_risk = (
            gst.get("fictitious_vendor_report", {})
               .get("summary", {})
               .get("risk", "CLEAN")
        )
        if fict_risk == "HIGH_RISK":
            return "HIGH"
        if fict_risk == "SUSPICIOUS":
            return "MEDIUM"

        # GNN supplement: any scoped GSTIN with HIGH/MEDIUM risk
        high_risk_gstins   = [g for g, v in gnn.items() if v.get("risk_flag") == "HIGH_RISK"]
        medium_risk_gstins = [g for g, v in gnn.items() if v.get("risk_flag") == "MEDIUM_RISK"]
        if high_risk_gstins:
            return "HIGH"
        if medium_risk_gstins:
            return "MEDIUM"

        # Fallback: any fictitious vendor present but below threshold
        fict_count = (
            gst.get("fictitious_vendor_report", {})
               .get("summary", {})
               .get("fictitious_vendor_count", 0) or 0
        )
        if fict_count > 0:
            return "LOW"
        return "CLEAR"

    def _flag_revenue_inflation(
        self, gst: dict[str, Any], bank: dict[str, Any]
    ) -> str:
        """
        Revenue inflation / suppression risk.

        HIGH   — GST turnover flag is REVENUE_INFLATION or UNEXPLAINED_INCOME
        MEDIUM — absolute turnover delta > 15 %
        LOW    — any turnover discrepancy flag present
        CLEAR  — CLEAN or no data
        """
        turnover_rec  = gst.get("turnover_reconciliation", {})
        turnover_flag = turnover_rec.get("turnover_flag", "CLEAN")
        delta_pct     = abs(turnover_rec.get("delta_percentage", 0.0) or 0.0)

        if turnover_flag in ("REVENUE_INFLATION", "UNEXPLAINED_INCOME"):
            return "HIGH" if delta_pct >= 15 else "MEDIUM"
        if delta_pct >= 15:
            return "MEDIUM"
        if turnover_flag not in ("CLEAN", ""):
            return "LOW"
        return "CLEAR"

    def _flag_cash_stress(self, bank: dict[str, Any]) -> str:
        """
        Liquidity / cash stress.

        HIGH   — current_ratio < 1.0  OR  DSCR < 1.0  OR  bounce_count > 5
        MEDIUM — current_ratio 1.0–1.5  OR  DSCR 1.0–1.2  OR  bounce_count 2–5
        LOW    — current_ratio 1.5–2.0  OR  debit_credit_ratio ≥ 0.90
                 OR bounce_count 1
        CLEAR  — otherwise / no data
        """
        cr    = bank.get("current_ratio")
        dscr  = bank.get("dscr")
        bc    = bank.get("bounce_count") or 0
        dcr   = bank.get("debit_credit_ratio")

        high_triggers = [
            cr   is not None and cr   < 1.0,
            dscr is not None and dscr < 1.0,
            bc > 5,
        ]
        medium_triggers = [
            cr   is not None and 1.0 <= cr   < 1.5,
            dscr is not None and 1.0 <= dscr < 1.2,
            bc >= 2,
        ]
        low_triggers = [
            cr   is not None and 1.5 <= cr   < 2.0,
            dcr  is not None and dcr  >= 0.90,
            bc == 1,
        ]

        if any(high_triggers):
            return "HIGH"
        if any(medium_triggers):
            return "MEDIUM"
        if any(low_triggers):
            return "LOW"
        return "CLEAR"

    def _flag_documentation(self, ner: dict[str, Any]) -> str:
        """
        Documentation risk from PDF risk-clause extraction.

        HIGH   — ≥ 1 HIGH-severity clause (fraud, SARFAESI, money laundering …)
        MEDIUM — ≥ 2 MEDIUM-severity clauses (NPA, restructuring, forensic audit …)
        LOW    — ≥ 1 LOW-severity clause (tax demand, pending litigation …)
        CLEAR  — no risk clauses detected
        """
        h = ner.get("high_risk_clause_count",   0)
        m = ner.get("medium_risk_clause_count",  0)
        total = len(ner.get("risk_clauses", []))

        if h >= 1:
            return "HIGH"
        if m >= 2:
            return "MEDIUM"
        if total >= 1:
            return "LOW"
        return "CLEAR"

    def _flag_auditor_concern(self, ner: dict[str, Any]) -> str:
        """
        Auditor concern risk.

        HIGH   — auditor_flag = True (qualified opinion)
                 OR any risk clause matching "going concern", "qualified opinion"
        MEDIUM — overall_sentiment < −0.30 (negative auditor language)
        LOW    — sentiment_score slightly negative (< 0)
        CLEAR  — clean
        """
        if ner.get("auditor_flag", False):
            return "HIGH"

        # Check for auditor-related HIGH risk clauses
        auditor_keywords = {
            "going concern", "qualified opinion", "except for",
            "fraud", "sarfaesi", "money laundering",
        }
        for clause in ner.get("risk_clauses", []):
            if clause.get("severity") == "HIGH":
                phrase = clause.get("matched_phrase", "").lower()
                if any(kw in phrase for kw in auditor_keywords):
                    return "HIGH"

        score = ner.get("sentiment_score")
        if score is not None:
            if score < -0.30:
                return "MEDIUM"
            if score < 0.0:
                return "LOW"

        return "CLEAR"

    def _flag_director_risk(self, ner: dict[str, Any]) -> str:
        """
        Director / promoter risk.

        HIGH   — any risk clause tied to director-fraud / SFIO / arrest
        MEDIUM — very few directors identified (< 2) in a non-trivial company
        LOW    — director-linked LOW-severity clauses present
        CLEAR  — otherwise
        """
        director_risk_keywords = {
            "fraud", "sfio", "nclt", "insolvency", "arrest",
            "money laundering", "ed notice",
        }
        low_keywords = {"regulatory action", "regulatory notice", "tax demand", "law enforcement"}

        for clause in ner.get("risk_clauses", []):
            phrase = clause.get("matched_phrase", "").lower()
            if any(kw in phrase for kw in director_risk_keywords):
                if clause.get("severity") in ("HIGH", "MEDIUM"):
                    return "HIGH"
            if any(kw in phrase for kw in low_keywords):
                return "LOW"

        directors = ner.get("directors", [])
        # Flag a medium concern only if silver had real text (risk clauses > 0)
        # but almost no directors were found (suggests a thin/fraudulent shell)
        if len(directors) == 0 and len(ner.get("risk_clauses", [])) > 2:
            return "MEDIUM"

        return "CLEAR"

    def _flag_compliance(self, gst: dict[str, Any]) -> str:
        """
        GST compliance risk.

        HIGH   — fictitious vendors > 3  OR  health score grade "D"
        MEDIUM — fictitious vendors 1–3  OR  health score grade "C"
        LOW    — GST health score grade "B"
        CLEAR  — grade "A" or no GST data
        """
        if not gst:
            return "CLEAR"

        fict_vendors = (
            gst.get("fictitious_vendor_report", {})
               .get("summary", {})
               .get("fictitious_vendor_count", 0) or 0
        )
        grade = (
            gst.get("health_score", {}).get("grade", "A") or "A"
        )

        if fict_vendors > 3 or grade == "D":
            return "HIGH"
        if 1 <= fict_vendors <= 3 or grade == "C":
            return "MEDIUM"
        if grade == "B":
            return "LOW"
        return "CLEAR"

    # ------------------------------------------------------------------
    # Step 6: Weighted EWS score
    # ------------------------------------------------------------------

    def _compute_score(
        self,
        flags: dict[str, str],
        bank:  dict[str, Any],
        gst:   dict[str, Any],
        gnn:   dict[str, Any],
        ner:   dict[str, Any],
    ) -> float:
        """
        Compute the weighted EWS score normalised to [0, 5].

        The score is normalised against only the weights of data sources that
        actually have data (bank, GST/GNN, NER).  This prevents a fraud company
        from appearing safer simply because bank or PDF data is absent.
        """
        has_gst  = bool(gst)
        has_gnn  = bool(gnn)
        has_bank = any(
            bank.get(k) is not None
            for k in ("current_ratio", "dscr", "bounce_count")
        )
        has_ner = bool(
            ner.get("risk_clauses")
            or ner.get("auditor_flag")
            or ner.get("sentiment_score") is not None
        )

        # Map each flag to the data source(s) it requires
        _flag_data_available: dict[str, bool] = {
            "gst_itc_fraud_risk":      has_gst or has_gnn,
            "circular_trading_risk":   has_gst or has_gnn,
            "revenue_inflation_risk":  has_gst,
            "compliance_risk":         has_gst,
            "cash_stress_risk":        has_bank,
            "documentation_risk":      has_ner,
            "auditor_concern_risk":    has_ner,
            "director_risk":           has_ner,
        }

        raw_score     = 0.0
        available_max = 0.0
        for flag_name, level in flags.items():
            if not _flag_data_available.get(flag_name, False):
                continue
            weight         = _FLAG_WEIGHTS.get(flag_name, 0.0)
            raw_score     += _LEVEL_VALUE.get(level, 0.0) * weight
            available_max += 5.0 * weight

        if available_max == 0.0:
            return 0.0
        return round((raw_score / available_max) * 5.0, 4)

    # ------------------------------------------------------------------
    # Step 7: SMA classification
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_sma(ews_score: float) -> str:
        """
        Map normalised EWS score to SMA band.

        SMA-0 : score < 1.0  (standard / performing)
        SMA-1 : 1.0 ≤ score ≤ 3.0  (special mention / watch)
        SMA-2 : score > 3.0  (sub-standard / stressed)
        """
        if ews_score > 3.0:
            return "SMA-2"
        if ews_score >= 1.0:
            return "SMA-1"
        return "SMA-0"

    # ------------------------------------------------------------------
    # Step 8: Build and persist the report
    # ------------------------------------------------------------------

    def _build_report(
        self,
        company_id:  str,
        flags:       dict[str, str],
        ews_score:   float,
        sma_class:   str,
        bank_metrics: dict[str, Any],
        gst_report:  dict[str, Any],
        gnn_preds:   dict[str, Any],
        ner_signals: dict[str, Any],
    ) -> dict[str, Any]:
        """Assemble the complete EWS report dict."""

        # Top-N highest-risk GSTINs from GNN
        top_gnn = sorted(
            gnn_preds.items(),
            key=lambda kv: kv[1].get("fraud_probability", 0.0),
            reverse=True,
        )[:5]

        # Compute flag-level summary
        flag_counts: dict[str, int] = {level: 0 for level in _FLAG_LEVELS}
        for lvl in flags.values():
            flag_counts[lvl] = flag_counts.get(lvl, 0) + 1

        return {
            # ── Identity ──────────────────────────────────────────────────
            "company_id":        company_id,
            "processed_at":      datetime.now(tz=timezone.utc).isoformat(),

            # ── Core output ───────────────────────────────────────────────
            "ews_score":         ews_score,
            "sma_classification": sma_class,

            # ── 8 EWS flags ───────────────────────────────────────────────
            "flags":             flags,
            "flag_summary":      flag_counts,

            # ── Intermediate signal values ────────────────────────────────
            "signals": {
                "gst": {
                    "health_score":       gst_report.get("health_score", {}),
                    "itc_overall_risk":   (
                        gst_report.get("itc_reconciliation", {})
                                  .get("summary", {})
                                  .get("overall_risk", "N/A")
                    ),
                    "turnover_flag":      (
                        gst_report.get("turnover_reconciliation", {})
                                  .get("turnover_flag", "N/A")
                    ),
                    "fictitious_vendors": (
                        gst_report.get("fictitious_vendor_report", {})
                                  .get("summary", {})
                                  .get("fictitious_vendor_count", 0)
                    ),
                    "verdict":            gst_report.get("verdict", {}),
                },
                "gnn": {
                    "total_nodes_scored": len(gnn_preds),
                    "high_risk_count":    sum(
                        1 for v in gnn_preds.values()
                        if v.get("risk_flag") == "HIGH_RISK"
                    ),
                    "top_fraud_gstins": [
                        {
                            "gstin":             gstin,
                            "fraud_probability": info["fraud_probability"],
                            "risk_flag":         info["risk_flag"],
                            "method":            info.get("method", "unknown"),
                        }
                        for gstin, info in top_gnn
                    ],
                },
                "bank": {
                    "current_ratio":    bank_metrics.get("current_ratio"),
                    "dscr":             bank_metrics.get("dscr"),
                    "debt_to_equity":   bank_metrics.get("debt_to_equity"),
                    "bounce_count":     bank_metrics.get("bounce_count"),
                },
                "ner": {
                    "risk_clause_count":  len(ner_signals.get("risk_clauses", [])),
                    "high_clauses":       ner_signals.get("high_risk_clause_count", 0),
                    "medium_clauses":     ner_signals.get("medium_risk_clause_count", 0),
                    "auditor_flag":       ner_signals.get("auditor_flag", False),
                    "sentiment_score":    ner_signals.get("sentiment_score"),
                    "director_count":     len(ner_signals.get("directors", [])),
                },
            },

            # ── Analyst narrative ──────────────────────────────────────────
            "narrative": self._build_narrative(flags, ews_score, sma_class),
        }

    @staticmethod
    def _build_narrative(
        flags: dict[str, str],
        ews_score: float,
        sma_class: str,
    ) -> str:
        """Generate a one-paragraph human-readable risk narrative."""
        high_flags   = [k for k, v in flags.items() if v == "HIGH"]
        medium_flags = [k for k, v in flags.items() if v == "MEDIUM"]
        low_flags    = [k for k, v in flags.items() if v == "LOW"]

        def _fmt(flag_list: list[str]) -> str:
            return ", ".join(f.replace("_", " ") for f in flag_list)

        parts: list[str] = [
            f"EWS score {ews_score:.2f} → {sma_class}."
        ]
        if high_flags:
            parts.append(f"HIGH risk detected in: {_fmt(high_flags)}.")
        if medium_flags:
            parts.append(f"MEDIUM risk in: {_fmt(medium_flags)}.")
        if low_flags:
            parts.append(f"LOW risk noted in: {_fmt(low_flags)}.")
        if not high_flags and not medium_flags and not low_flags:
            parts.append("No significant risk signals identified.")

        return "  ".join(parts)

    # ------------------------------------------------------------------
    # Gold feature store persistence
    # ------------------------------------------------------------------

    def _persist_gold(self, company_id: str, report: dict[str, Any]) -> None:
        """
        Write the EWS report as a JSON line to the Gold feature store.

        Path: ``data/gold/gold_features/{company_id}_ews.json``

        Overwrites any previous entry for the same company_id (one record
        per company is kept — the latest run).
        """
        out_path = _GOLD_DIR / f"{company_id}_ews.json"
        with out_path.open("w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False, default=str)
        logger.info("[%s] EWS report written → %s", company_id, out_path)

    # ------------------------------------------------------------------
    # Silver JSONL reader
    # ------------------------------------------------------------------

    def _read_latest_silver_record(
        self, company_id: str
    ) -> dict[str, Any] | None:
        """
        Return the most-recent Silver JSONL record for *company_id*.

        Checks two candidate paths:
        1. ``data/silver/{company_id}/silver_financials.jsonl``
        2. ``data/silver/silver_financials/{company_id}.jsonl``

        Returns the record with the latest ``extracted_at`` timestamp,
        or ``None`` if no file exists.
        """
        candidates = [
            DATA_SILVER / company_id     / "silver_financials.jsonl",
            DATA_SILVER / "silver_financials" / f"{company_id}.jsonl",
            DATA_SILVER / "RIL"          / "silver_financials.jsonl"  # demo fallback
            if company_id == "RIL" else None,
        ]
        # filter None
        candidates = [p for p in candidates if p is not None]

        records: list[dict[str, Any]] = []
        for path in candidates:
            if path.exists():
                try:
                    with path.open(encoding="utf-8") as fh:
                        for line in fh:
                            line = line.strip()
                            if not line:
                                continue
                            rec = json.loads(line)
                            if rec.get("company_id", "").upper() == company_id.upper():
                                records.append(rec)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[%s] Failed to read Silver at %s: %s", company_id, path, exc)

        if not records:
            return None

        # Return the record with the latest fiscal_year (or extracted_at)
        records.sort(key=lambda r: r.get("fiscal_year", 0), reverse=True)
        return records[0]


# ===========================================================================
# Module-level helpers
# ===========================================================================

def _max_flag(*flags: str) -> str:
    """Return the most severe flag level among the inputs."""
    order = {level: i for i, level in enumerate(_FLAG_LEVELS)}  # HIGH=0 is worst
    return min(flags, key=lambda f: order.get(f, len(_FLAG_LEVELS)))


# ===========================================================================
# CLI smoke-test
# ===========================================================================

if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    )

    company = sys.argv[1] if len(sys.argv) > 1 else "RIL"
    print(f"\n{'='*60}")
    print(f"EWS Engine — smoke test for company: {company}")
    print(f"{'='*60}\n")

    engine = EWSEngine()
    report = engine.consolidate_signals(company)

    print(f"  EWS Score         : {report['ews_score']:.3f}")
    print(f"  SMA Classification: {report['sma_classification']}")
    print(f"\n  Flags:")
    for flag, level in report["flags"].items():
        bar = "█" * {"HIGH": 4, "MEDIUM": 3, "LOW": 2, "CLEAR": 1}[level]
        print(f"    {flag:<30s}  {level:<8s} {bar}")

    print(f"\n  Flag summary: {report['flag_summary']}")
    print(f"\n  Narrative:\n  {report['narrative']}")

    top = report["signals"]["gnn"]["top_fraud_gstins"]
    if top:
        print(f"\n  Top GNN fraud predictions:")
        for item in top:
            print(f"    {item['gstin']}  P={item['fraud_probability']:.4f}  [{item['risk_flag']}]")

    print(f"\n  Gold report written to: data/gold/gold_features/{company}_ews.json")
    print(f"\n{'='*60}")
