"""
feature_builder.py — Gold-layer feature assembly for LightGBM credit scoring.

Assembles a flat 35-feature numeric vector for a given company_id by sourcing
data from four layers:

    1. **Silver layer**     : financial ratios, NER sentiment, bank statement
    2. **EWS Engine**       : GST health sub-metrics, 8 encoded flag levels,
                              EWS composite score, NER and GNN signals
    3. **Research Agent**   : news risk, litigation count, RBI wilful-default
                              flag, MCA charges gap, eCourts severity
    4. **Qualitative Portal**: credit-officer site-visit adjustment score

Categorical encoding convention (applied to all EWS flag features):
    HIGH=3  MEDIUM=2  LOW=1  CLEAR=0

Public API
----------
    from src.scorer.feature_builder import FeatureBuilder

    fb = FeatureBuilder()
    feature_dict, feature_names = fb.build_feature_vector("COMP_C_FRAUD")
    # feature_dict: {name: float, ...}   len == 35
    # feature_names: ordered list, len == 35

The assembled vector is persisted to:
    data/gold/gold_features/{company_id}_features.json
and (best-effort) to the DeltaLakeManager local-Parquet Gold table.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Project-root path resolution
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.config import (  # noqa: E402
    DATA_GOLD, DATA_RAW, DATA_SILVER,
    SAFE_DEFAULT_GST_HEALTH, SAFE_DEFAULT_NEWS_RISK,
)

logger = logging.getLogger("intelli_credit.scorer.feature_builder")

_GOLD_FEATURES_DIR = DATA_GOLD / "gold_features"
_GOLD_FEATURES_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Categorical encoder:  HIGH=3  MEDIUM=2  LOW=1  CLEAR=0
# ---------------------------------------------------------------------------
_LEVEL_CODE: dict[str, int] = {
    "HIGH":   3,
    "MEDIUM": 2,
    "LOW":    1,
    "CLEAR":  0,
}


def _encode_flag(value: str | None) -> int:
    """
    Encode an EWS flag string to an integer.

    Handles values like ``"HIGH"`` or ``"HIGH: …reason…"`` produced by
    ``EWSEngine`` and ``SynthesizerAgent``.  Unknown / missing values default
    to ``0`` (CLEAR).
    """
    if not value:
        return 0
    key = str(value).strip().upper().split(":")[0].strip()
    return _LEVEL_CODE.get(key, 0)


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convert *value* to float, returning *default* on failure."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    """Convert *value* to int, returning *default* on failure."""
    if value is None:
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


# ===========================================================================
# FeatureBuilder
# ===========================================================================

class FeatureBuilder:
    """
    Assembles the Gold-layer 35-feature vector used by LightGBM credit scoring.

    Parameters
    ----------
    run_ews_live : bool
        When ``True`` the EWS engine is invoked live for companies that do not
        yet have a cached ``{company_id}_ews.json`` file.  Default ``False``.
    run_research_live : bool
        When ``True`` the ResearchAgent is invoked live for companies that do
        not yet have a cached ``{company_id}_research.json`` file.
        Default ``False``.
    """

    # ------------------------------------------------------------------
    # Canonical ordered feature names — 35 total
    # Must stay in sync with the assembly dict in build_feature_vector().
    # ------------------------------------------------------------------
    FEATURE_NAMES: list[str] = [
        # ── Silver: Financial Ratios (7) ──────────────────────────────
        "debt_to_equity",           # Total Debt / Net Worth
        "current_ratio",            # Current Assets / Current Liabilities
        "interest_coverage",        # EBIT / Interest Expense
        "dscr",                     # Debt Service Coverage Ratio
        "pat_margin",               # PAT / Revenue
        "roce",                     # EBITDA / (Net Worth + Total Debt)
        "revenue_growth_3y",        # 3-year revenue CAGR (0.10 = 10%)
        # ── Silver: Bank Metrics (4) ──────────────────────────────────
        "avg_monthly_balance",      # Average end-of-month closing balance (INR)
        "debit_credit_ratio",       # Total debits / total credits
        "bounce_count",             # # of cheque/ECS return transactions
        "upi_concentration",        # UPI transactions as % of total txn count
        # ── EWS Engine: GST Health Sub-metrics (4) ────────────────────
        "gst_health_score",         # Composite GST health score (0–10)
        "itc_gap_pct",              # ITC claimed vs GSTR-2A gap %
        "turnover_consistency",     # 1 – (flagged_periods / total_periods)
        "filing_regularity",        # periods_filed / expected_periods
        # ── EWS Engine: Core Flags from spec (3) ─────────────────────
        "circular_trading_confidence",  # encoded circular_trading_risk
        "revenue_inflation_flag",       # encoded revenue_inflation_risk
        "cash_stress_flag",             # encoded cash_stress_risk
        # ── Research Agent (5) ────────────────────────────────────────
        "news_risk_score",              # news risk score 0–10
        "litigation_count",             # total eCourts cases
        "has_wilful_default_flag",      # 1 if RBI defaulter list match
        "mca_charges_vs_declared_debt_gap",  # open charges / declared debt
        "ecourts_severity_score",       # weighted litigation risk 0–10
        # ── Qualitative Portal (1) ────────────────────────────────────
        "qualitative_adjustment",       # credit-officer score −5.0…+2.0
        # ── EWS Engine: Remaining 5 Flags ────────────────────────────
        "gst_itc_fraud_flag",           # encoded gst_itc_fraud_risk
        "documentation_risk_flag",      # encoded documentation_risk
        "auditor_concern_flag",         # encoded auditor_concern_risk
        "director_risk_flag",           # encoded director_risk
        "compliance_risk_flag",         # encoded compliance_risk
        # ── EWS / NER Composite Signals (6) ──────────────────────────
        "ews_score",                    # overall EWS score 0–5
        "ner_sentiment_score",          # NER finBERT sentiment (0 = negative)
        "ner_risk_clause_count",        # # risk clauses in annual report
        "ner_auditor_flag",             # 1 if auditor concern detected
        "nclt_override_flag",           # 1 if NCLT insolvency case present
        "gnn_high_risk_gstin_count",    # # GSTINs with GNN HIGH_RISK flag
    ]

    def __init__(
        self,
        run_ews_live:      bool = False,
        run_research_live: bool = False,
    ) -> None:
        self.run_ews_live      = run_ews_live
        self.run_research_live = run_research_live

    # ==================================================================
    # Public API
    # ==================================================================

    def build_feature_vector(
        self,
        company_id: str,
    ) -> tuple[dict[str, float], list[str]]:
        """
        Assemble the complete 35-feature vector for *company_id*.

        Steps
        -----
        1. Load Silver JSONL (financials + NER).
        2. Load bank metrics (precomputed cache → raw CSV → defaults).
        3. Load EWS gold JSON (or run EWSEngine live if configured).
        4. Load Research Agent synthesis (or run live if configured).
        5. Load qualitative credit-officer adjustment if available.
        6. Encode all categoricals: HIGH=3, MEDIUM=2, LOW=1, CLEAR=0.
        7. Persist the vector to the Gold Delta table.
        8. Return ``(feature_dict, feature_names)``.

        Returns
        -------
        feature_dict : dict[str, float]
            ``{feature_name: numeric_value}``  — exactly 35 keys.
        feature_names : list[str]
            Ordered list of feature names matching ``FEATURE_NAMES`` (len 35).
        """
        cid = company_id.strip().upper()
        logger.info("[%s] Building feature vector …", cid)

        # Track which features are imputed vs extracted
        imputed_flags: dict[str, bool] = {}

        # ── Load data sources ─────────────────────────────────────────
        silver   = self._load_silver(cid)
        bank     = self._load_bank_metrics(cid)
        ews      = self._load_ews(cid)
        research = self._load_research(cid)
        qual     = self._load_qualitative(cid)

        # ── Track source availability ────────────────────────────────
        if not silver.get("_records"):
            for f in ("debt_to_equity", "current_ratio", "interest_coverage",
                      "dscr", "pat_margin", "roce", "revenue_growth_3y"):
                imputed_flags[f] = True
        if bank.get("avg_monthly_balance", 0.0) == 0.0 and bank.get("bounce_count", 0.0) == 0.0:
            for f in ("avg_monthly_balance", "debit_credit_ratio", "bounce_count", "upi_concentration"):
                imputed_flags[f] = True
        if not ews:
            for f in ("gst_health_score", "itc_gap_pct", "turnover_consistency", "filing_regularity",
                      "ews_score", "gnn_high_risk_gstin_count"):
                imputed_flags[f] = True
        if not research:
            for f in ("news_risk_score", "litigation_count", "ecourts_severity_score"):
                imputed_flags[f] = True

        # ── Extract sub-groups ────────────────────────────────────────
        fin   = self._extract_financials(silver)
        gst   = self._extract_gst_health(ews)
        flags = self._extract_ews_flags(ews)
        ra    = self._extract_research(research)
        ner   = self._extract_ner(ews)

        # ── Assemble flat feature dict (exactly 35) ───────────────────
        fv: dict[str, float] = {
            # Silver: Financial Ratios
            "debt_to_equity":                   fin["debt_to_equity"],
            "current_ratio":                    fin["current_ratio"],
            "interest_coverage":                fin["interest_coverage"],
            "dscr":                             fin["dscr"],
            "pat_margin":                       fin["pat_margin"],
            "roce":                             fin["roce"],
            "revenue_growth_3y":                fin["revenue_growth_3y"],
            # Bank Metrics
            "avg_monthly_balance":              bank["avg_monthly_balance"],
            "debit_credit_ratio":               bank["debit_credit_ratio"],
            "bounce_count":                     bank["bounce_count"],
            "upi_concentration":                bank["upi_concentration"],
            # EWS: GST Health
            "gst_health_score":                 gst["gst_health_score"],
            "itc_gap_pct":                      gst["itc_gap_pct"],
            "turnover_consistency":             gst["turnover_consistency"],
            "filing_regularity":                gst["filing_regularity"],
            # EWS: Core Flags (spec §2)
            "circular_trading_confidence":      flags["circular_trading_confidence"],
            "revenue_inflation_flag":           flags["revenue_inflation_flag"],
            "cash_stress_flag":                 flags["cash_stress_flag"],
            # Research Agent (spec §3)
            "news_risk_score":                  ra["news_risk_score"],
            "litigation_count":                 ra["litigation_count"],
            "has_wilful_default_flag":          ra["has_wilful_default_flag"],
            "mca_charges_vs_declared_debt_gap": ra["mca_charges_vs_declared_debt_gap"],
            "ecourts_severity_score":           ra["ecourts_severity_score"],
            # Qualitative Portal (spec §4)
            "qualitative_adjustment":           _safe_float(qual.get("total_adjustment"), 0.0),
            # EWS: Remaining 5 flags
            "gst_itc_fraud_flag":               flags["gst_itc_fraud_flag"],
            "documentation_risk_flag":          flags["documentation_risk_flag"],
            "auditor_concern_flag":             flags["auditor_concern_flag"],
            "director_risk_flag":               flags["director_risk_flag"],
            "compliance_risk_flag":             flags["compliance_risk_flag"],
            # EWS / NER Composite Signals
            "ews_score":                        _safe_float(ews.get("ews_score"), 0.0),
            "ner_sentiment_score":              ner["ner_sentiment_score"],
            "ner_risk_clause_count":            ner["ner_risk_clause_count"],
            "ner_auditor_flag":                 ner["ner_auditor_flag"],
            "nclt_override_flag":               ra["nclt_override_flag"],
            "gnn_high_risk_gstin_count":        float(
                ews.get("signals", {}).get("gnn", {}).get("high_risk_count", 0) or 0
            ),
        }

        assert len(fv) == 35, (
            f"[{cid}] Feature count mismatch: got {len(fv)}, expected 35. "
            f"Keys: {sorted(fv)}"
        )

        # Coerce all values to float (guards against stray ints/bools)
        fv = {k: float(v) for k, v in fv.items()}

        # Log imputed features for audit trail
        if imputed_flags:
            logger.warning(
                "[%s] %d features imputed (source data unavailable): %s",
                cid, len(imputed_flags), sorted(imputed_flags.keys()),
            )

        self._persist_gold(cid, fv)

        logger.info("[%s] Feature vector assembled (%d features, %d imputed).",
                    cid, len(fv), len(imputed_flags))
        return fv, list(self.FEATURE_NAMES)

    # ==================================================================
    # Data loaders
    # ==================================================================

    def _load_silver(self, company_id: str) -> dict[str, Any]:
        """
        Load Silver JSONL records for *company_id*.

        Checks two candidate paths (same strategy as EWSEngine):
          1. ``data/silver/{company_id}/silver_financials.jsonl``
          2. ``data/silver/silver_financials/{company_id}.jsonl``

        Returns a dict with:
          ``_records`` : all matching records sorted by fiscal_year descending.
          All keys from the latest record are merged at the top level.
        """
        candidates = [
            DATA_SILVER / company_id / "silver_financials.jsonl",
            DATA_SILVER / "silver_financials" / f"{company_id}.jsonl",
        ]
        records: list[dict[str, Any]] = []

        for path in candidates:
            if not path.exists():
                continue
            try:
                with path.open(encoding="utf-8") as fh:
                    for raw_line in fh:
                        line = raw_line.strip()
                        if not line:
                            continue
                        rec = json.loads(line)
                        if rec.get("company_id", "").upper() == company_id.upper():
                            records.append(rec)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[%s] Silver read error at %s: %s", company_id, path, exc
                )

        if not records:
            logger.warning(
                "[%s] No Silver records found — financial ratios will default to 0.",
                company_id,
            )
            return {"_records": []}

        records.sort(key=lambda r: r.get("fiscal_year", 0), reverse=True)
        # Merge latest record values at top level for convenience
        return {"_records": records, **records[0]}

    def _load_bank_metrics(self, company_id: str) -> dict[str, float]:
        """
        Load bank metrics, trying sources in order:

        1. Precomputed ``data/silver/{company_id}/bank_metrics.json``
        2. Raw ``data/raw/bank_statement_{company_id}.csv``
        3. Generic ``data/raw/bank_statement_sample.csv``  (demo/fallback)
        4. Zero defaults when no bank data is available.
        """
        # 1. Precomputed cache
        cache_path = DATA_SILVER / company_id / "bank_metrics.json"
        if cache_path.exists():
            try:
                with cache_path.open(encoding="utf-8") as fh:
                    return self._normalise_bank_metrics(json.load(fh))
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[%s] bank_metrics.json read error: %s", company_id, exc
                )

        # 2. Raw bank statement CSV
        raw_candidates = [
            DATA_RAW / f"bank_statement_{company_id}.csv",
            DATA_RAW / f"bank_statement_{company_id.lower()}.csv",
            DATA_RAW / "bank_statement_sample.csv",
        ]
        for csv_path in raw_candidates:
            if not csv_path.exists():
                continue
            try:
                from src.ingestor.bank_analyzer import (  # noqa: PLC0415
                    BankStatementAnalyzer,
                )
                analyzer = BankStatementAnalyzer()
                analyzer.load_transactions(str(csv_path))
                metrics = analyzer.compute_metrics()
                logger.info(
                    "[%s] Bank metrics loaded from %s.", company_id, csv_path.name
                )
                return self._normalise_bank_metrics(metrics)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[%s] BankStatementAnalyzer failed on %s: %s",
                    company_id, csv_path.name, exc,
                )
                break  # don't try next file on unexpected error

        logger.info(
            "[%s] No bank statement found — bank metrics default to 0.", company_id
        )
        return {
            "avg_monthly_balance": 0.0,
            "debit_credit_ratio":  0.0,
            "bounce_count":        0.0,
            "upi_concentration":   0.0,
        }

    @staticmethod
    def _normalise_bank_metrics(raw: dict[str, Any]) -> dict[str, float]:
        """Normalise field names from BankStatementAnalyzer or a pre-saved dict."""
        return {
            "avg_monthly_balance": _safe_float(
                raw.get("avg_monthly_balance")
                or raw.get("average_monthly_balance")
            ),
            "debit_credit_ratio": _safe_float(raw.get("debit_credit_ratio")),
            "bounce_count":       _safe_float(raw.get("bounce_count")),
            "upi_concentration":  _safe_float(
                raw.get("upi_concentration")
                or raw.get("upi_percentage")
            ),
        }

    def _load_ews(self, company_id: str) -> dict[str, Any]:
        """
        Load the EWS report for *company_id*.

        Tries ``data/gold/gold_features/{company_id}_ews.json`` first.
        Falls back to running ``EWSEngine.consolidate_signals()`` when
        ``run_ews_live=True`` and no cached file is found.
        """
        cache_path = _GOLD_FEATURES_DIR / f"{company_id}_ews.json"
        if cache_path.exists():
            try:
                with cache_path.open(encoding="utf-8") as fh:
                    return json.load(fh)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[%s] EWS JSON read error: %s", company_id, exc
                )

        if self.run_ews_live:
            try:
                from src.gst.ews_engine import EWSEngine  # noqa: PLC0415

                engine = EWSEngine()
                return engine.consolidate_signals(company_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[%s] EWSEngine.consolidate_signals failed: %s", company_id, exc
                )

        logger.info("[%s] No EWS data found — EWS features will default.", company_id)
        return {}

    def _load_research(self, company_id: str) -> dict[str, Any]:
        """
        Load the Research Agent synthesis for *company_id*.

        Tries ``data/gold/gold_features/{company_id}_research.json`` first.
        Falls back to running ``ResearchAgent.run_research()`` when
        ``run_research_live=True`` and no cached file is found.

        Expected cached structure::

            {
              "synthesis_report": { overall_external_risk_score, … },
              "news_report":      { news_risk_score, … },
              "ecourts_report":   { total_cases, litigation_risk_score, nclt_override, … },
              "mca_report":       { charges: { hidden_debt_flag, … }, … },
              "rbi_report":       { is_flagged, hit_count, … },
            }
        """
        cache_path = _GOLD_FEATURES_DIR / f"{company_id}_research.json"
        if cache_path.exists():
            try:
                with cache_path.open(encoding="utf-8") as fh:
                    return json.load(fh)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[%s] Research JSON read error: %s", company_id, exc
                )

        if self.run_research_live:
            try:
                from src.agent.research_agent import ResearchAgent  # noqa: PLC0415

                result = ResearchAgent().run_research(company_id)
                full: dict[str, Any] = {
                    "synthesis_report": result.get("synthesis_report") or {},
                    "news_report":      result.get("news_report"),
                    "ecourts_report":   result.get("ecourts_report"),
                    "mca_report":       result.get("mca_report"),
                    "rbi_report":       result.get("rbi_report"),
                }
                self._write_json(cache_path, full)
                logger.info("[%s] Research Agent result cached → %s", company_id, cache_path)
                return full
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[%s] ResearchAgent.run_research failed: %s", company_id, exc
                )

        logger.info(
            "[%s] No research data found — research features will default.", company_id
        )
        return {}

    def _load_qualitative(self, company_id: str) -> dict[str, Any]:
        """
        Load the credit-officer qualitative adjustment for *company_id*.

        Expects a JSON file at::

            data/silver/qualitative_inputs/{company_id}_qualitative.json

        produced by the Credit Officer Portal / ``QualitativeScorer``.
        The key ``total_adjustment`` (float, −5.0…+2.0) is used directly.
        """
        path = (
            DATA_SILVER / "qualitative_inputs"
            / f"{company_id}_qualitative.json"
        )
        if path.exists():
            try:
                with path.open(encoding="utf-8") as fh:
                    return json.load(fh)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[%s] Qualitative JSON read error: %s", company_id, exc
                )
        logger.info(
            "[%s] No qualitative adjustment file found — defaulting to 0.0.", company_id
        )
        return {}

    # ==================================================================
    # Feature-extraction helpers
    # ==================================================================

    @staticmethod
    def _extract_financials(silver: dict[str, Any]) -> dict[str, float]:
        """
        Compute financial ratios from Silver JSONL records.

        ``pat_margin``      = PAT / Revenue  (latest year)
        ``roce``            = EBITDA / (Net Worth + Total Debt)  (latest year)
        ``revenue_growth_3y`` = 2-year CAGR using years[0] and years[2] when
                              ≥ 3 records exist; YoY growth for 2 records.
        """
        records: list[dict] = silver.get("_records", [])
        latest  = records[0] if records else {}

        revenue    = _safe_float(latest.get("revenue"),   0.0)
        ebitda     = _safe_float(latest.get("ebitda"),    0.0)
        pat        = _safe_float(latest.get("pat"),       0.0)
        net_worth  = _safe_float(latest.get("net_worth"), 0.0)
        total_debt = _safe_float(latest.get("total_debt"), 0.0)

        pat_margin = pat / revenue if revenue else 0.0
        capital    = net_worth + total_debt
        roce       = ebitda / capital if capital else 0.0

        # 3-year revenue CAGR
        revenue_growth_3y = 0.0
        if len(records) >= 3:
            rev_new = _safe_float(records[0].get("revenue"), 0.0)
            rev_old = _safe_float(records[2].get("revenue"), 0.0)
            if rev_old > 0 and rev_new >= 0:
                revenue_growth_3y = (rev_new / rev_old) ** (1.0 / 2.0) - 1.0
        elif len(records) == 2:
            rev_new = _safe_float(records[0].get("revenue"), 0.0)
            rev_old = _safe_float(records[1].get("revenue"), 0.0)
            if rev_old > 0:
                revenue_growth_3y = (rev_new - rev_old) / rev_old

        return {
            "debt_to_equity":    _safe_float(latest.get("debt_to_equity"),   0.0),
            "current_ratio":     _safe_float(latest.get("current_ratio"),    0.0),
            "interest_coverage": _safe_float(latest.get("interest_coverage"), 0.0),
            "dscr":              _safe_float(latest.get("dscr"),             0.0),
            "pat_margin":        pat_margin,
            "roce":              roce,
            "revenue_growth_3y": revenue_growth_3y,
        }

    @staticmethod
    def _extract_gst_health(ews: dict[str, Any]) -> dict[str, float]:
        """
        Extract GST health sub-metrics from the EWS gold report.

        Data path inside the EWS JSON::

            ews["signals"]["gst"]["health_score"]["components"]

        ``turnover_consistency`` = 1 − (flagged_periods / total_periods)
        ``filing_regularity``    = periods_filed / expected_periods
        Both are clamped to [0.0, 1.0].
        """
        gst_signals = ews.get("signals", {}).get("gst", {})
        health      = gst_signals.get("health_score", {})
        components  = health.get("components", {})

        gst_health_score = _safe_float(health.get("score"), 0.0)

        # ITC gap %
        itc_comp    = components.get("itc_gap", {})
        itc_gap_pct = _safe_float(itc_comp.get("total_gap_pct"), 0.0)

        # Turnover consistency: 1 − (flagged / total)
        tc_comp   = components.get("turnover_consistency", {})
        flagged   = _safe_float(tc_comp.get("flagged_periods"), 0.0)
        n_periods = _safe_float(tc_comp.get("total_periods"), 1.0) or 1.0
        turnover_consistency = max(0.0, min(1.0, 1.0 - flagged / n_periods))

        # Filing regularity: filed / expected
        fr_comp   = components.get("filing_regularity", {})
        expected  = _safe_float(fr_comp.get("expected"), 1.0) or 1.0
        filed     = _safe_float(fr_comp.get("periods_filed"), expected)
        filing_regularity = max(0.0, min(1.0, filed / expected))

        return {
            "gst_health_score":     gst_health_score,
            "itc_gap_pct":          itc_gap_pct,
            "turnover_consistency": turnover_consistency,
            "filing_regularity":    filing_regularity,
        }

    @staticmethod
    def _extract_ews_flags(ews: dict[str, Any]) -> dict[str, float]:
        """
        Encode all 8 EWS flag strings to integers.

        EWS flag key → encoded feature name mapping:

        ============================  ==============================
        circular_trading_risk         circular_trading_confidence
        revenue_inflation_risk        revenue_inflation_flag
        cash_stress_risk              cash_stress_flag
        gst_itc_fraud_risk            gst_itc_fraud_flag
        documentation_risk            documentation_risk_flag
        auditor_concern_risk          auditor_concern_flag
        director_risk                 director_risk_flag
        compliance_risk               compliance_risk_flag
        ============================  ==============================
        """
        flags = ews.get("flags", {})
        return {
            "circular_trading_confidence": float(_encode_flag(flags.get("circular_trading_risk"))),
            "revenue_inflation_flag":      float(_encode_flag(flags.get("revenue_inflation_risk"))),
            "cash_stress_flag":            float(_encode_flag(flags.get("cash_stress_risk"))),
            "gst_itc_fraud_flag":          float(_encode_flag(flags.get("gst_itc_fraud_risk"))),
            "documentation_risk_flag":     float(_encode_flag(flags.get("documentation_risk"))),
            "auditor_concern_flag":        float(_encode_flag(flags.get("auditor_concern_risk"))),
            "director_risk_flag":          float(_encode_flag(flags.get("director_risk"))),
            "compliance_risk_flag":        float(_encode_flag(flags.get("compliance_risk"))),
        }

    @staticmethod
    def _extract_research(research: dict[str, Any]) -> dict[str, float]:
        """
        Extract Research Agent features from the cached research report.

        Features extracted
        ------------------
        news_risk_score                 : float 0–10  (NewsIntelligenceTool)
        litigation_count                : int   (ECourtsTool total_cases)
        has_wilful_default_flag         : 0/1   (RBIDefaulterTool is_flagged)
        mca_charges_vs_declared_debt_gap: float (open charges / declared debt;
                                            1.0 when hidden_debt_flag is True)
        ecourts_severity_score          : float 0–10  (litigation_risk_score)
        nclt_override_flag              : 0/1   (ECourtsTool nclt_override)
        """
        synthesis   = research.get("synthesis_report") or {}
        news_rep    = research.get("news_report")       or {}
        ecourts_rep = research.get("ecourts_report")    or {}
        mca_rep     = research.get("mca_report")        or {}
        rbi_rep     = research.get("rbi_report")        or {}

        # news_risk_score: prefer news_report, fall back to synthesis score
        news_risk_score = _safe_float(
            news_rep.get("news_risk_score"),
            _safe_float(synthesis.get("overall_external_risk_score"), 0.0),
        )

        # litigation_count
        litigation_count = float(_safe_int(ecourts_rep.get("total_cases"), 0))

        # has_wilful_default_flag — RBIDefaulterTool.check_company_group returns is_flagged
        is_flagged = rbi_rep.get("is_flagged", False)
        if isinstance(is_flagged, str):
            is_flagged = is_flagged.lower() not in ("false", "0", "no", "none", "")
        has_wilful_default_flag = 1.0 if is_flagged else 0.0

        # mca_charges_vs_declared_debt_gap
        charges  = mca_rep.get("charges") or {}
        if charges.get("hidden_debt_flag"):
            mca_charges_gap = 1.0
        else:
            open_amt  = _safe_float(charges.get("total_open_charges_amount"), 0.0)
            declared  = _safe_float(charges.get("declared_debt_inr"),         0.0)
            mca_charges_gap = open_amt / declared if declared > 0.0 else 0.0

        # ecourts_severity_score and nclt_override
        ecourts_severity_score = _safe_float(
            ecourts_rep.get("litigation_risk_score"), 0.0
        )
        nclt_override_flag = 1.0 if ecourts_rep.get("nclt_override") else 0.0

        return {
            "news_risk_score":                  news_risk_score,
            "litigation_count":                 litigation_count,
            "has_wilful_default_flag":          has_wilful_default_flag,
            "mca_charges_vs_declared_debt_gap": mca_charges_gap,
            "ecourts_severity_score":           ecourts_severity_score,
            "nclt_override_flag":               nclt_override_flag,
        }

    @staticmethod
    def _extract_ner(ews: dict[str, Any]) -> dict[str, float]:
        """Extract NER and sentiment signals from ``ews["signals"]["ner"]``."""
        ner = ews.get("signals", {}).get("ner", {})
        return {
            "ner_sentiment_score":  _safe_float(ner.get("sentiment_score"), 0.0),
            "ner_risk_clause_count": float(_safe_int(ner.get("risk_clause_count"), 0)),
            "ner_auditor_flag":     1.0 if ner.get("auditor_flag") else 0.0,
        }

    # ==================================================================
    # Gold persistence
    # ==================================================================

    def _persist_gold(self, company_id: str, fv: dict[str, float]) -> None:
        """
        Write the feature vector to the Gold feature store.

        Always writes a JSON file at::

            data/gold/gold_features/{company_id}_features.json

        Also performs a best-effort write to the local-Parquet Gold Delta
        table via ``DeltaLakeManager``; any failure is logged and silently
        swallowed so the feature vector is always returned to the caller.
        """
        out: dict[str, Any] = {
            "company_id":    company_id,
            "features":      fv,
            "feature_names": self.FEATURE_NAMES,
            "feature_count": len(fv),
            "generated_at":  datetime.now(tz=timezone.utc).isoformat(),
        }

        json_path = _GOLD_FEATURES_DIR / f"{company_id}_features.json"
        self._write_json(json_path, out)

        # Delta / local-Parquet write (best-effort)
        try:
            import pandas as pd  # noqa: PLC0415

            from src.config import DeltaLakeManager  # noqa: PLC0415

            mgr = DeltaLakeManager(force_local=True)
            row = {
                "company_id":   company_id,
                **fv,
                "generated_at": out["generated_at"],
            }
            df = pd.DataFrame([row])
            mgr.write_gold_features(df, mode="append")
            logger.info("[%s] Feature vector written to Gold Delta table.", company_id)
        except Exception as exc:  # noqa: BLE001
            logger.info(
                "[%s] Gold Delta write skipped (%s) — JSON record saved.",
                company_id, exc,
            )

    @staticmethod
    def _write_json(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False, default=str)
        logger.info("Written → %s", path)


# ---------------------------------------------------------------------------
# Module-level convenience wrapper
# ---------------------------------------------------------------------------

def build_features(
    company_id: str,
    **kwargs: Any,
) -> tuple[dict[str, float], list[str]]:
    """
    One-liner wrapper around ``FeatureBuilder.build_feature_vector``.

    Example
    -------
    >>> fv, names = build_features("COMP_C_FRAUD", run_ews_live=True)
    """
    return FeatureBuilder(**kwargs).build_feature_vector(company_id)


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys as _sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    )

    company = _sys.argv[1] if len(_sys.argv) > 1 else "COMP_C_FRAUD"
    run_live = "--live" in _sys.argv

    print(f"\n{'='*64}")
    print(f"  FeatureBuilder smoke-test  |  company: {company}")
    print(f"  run_ews_live={run_live}  run_research_live={run_live}")
    print(f"{'='*64}")

    fb = FeatureBuilder(run_ews_live=run_live, run_research_live=run_live)
    fv, names = fb.build_feature_vector(company)

    print(f"\n  {'Feature':<42} {'Value':>12}")
    print(f"  {'-'*56}")
    for name in names:
        print(f"  {name:<42} {fv[name]:>12.4f}")

    print(f"\n  Total features: {len(fv)}")
    print(f"{'='*64}\n")
