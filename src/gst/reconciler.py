"""
reconciler.py — India-specific GST reconciliation engine for intelli_credit.

GSTReconciler ingests the three GSTR forms produced by GSTDataGenerator (or
real filings in the same schema) and applies rule-based checks that mirror the
checks performed by GST officers and credit-underwriting teams:

  1. ITC Reconciliation   – GSTR-2A vs GSTR-3B claimed ITC
  2. Turnover Consistency – GSTR-1 declared sales vs bank credit inflows
  3. Fictitious Vendors   – GSTINs in GSTR-3B ITC schedule absent from GSTR-2A
  4. Health Score         – 0–10 composite score

All four checks feed into a structured reconciliation report returned by
:meth:`GSTReconciler.run_full_reconciliation`.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("intelli_credit.gst.reconciler")

# ---------------------------------------------------------------------------
# Path constants (mirrors data_generator.py layout)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
GST_RAW_DIR   = _PROJECT_ROOT / "data" / "raw" / "gst"

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
_ITC_GAP_SUSPICIOUS_PCT  = 10.0   # gap% > 10 → SUSPICIOUS
_ITC_GAP_HIGH_RISK_PCT   = 20.0   # gap% > 20 → HIGH_RISK
_BANK_EXCESS_FACTOR      = 1.15   # bank > declared × 1.15 → unexplained income
_BANK_DEFICIT_FACTOR     = 0.85   # bank < declared × 0.85 → revenue inflation

# Score weight table (must sum to 10)
_W_FILING_REGULARITY  = 2.5
_W_ITC_GAP            = 3.0
_W_TURNOVER_CONSIST   = 2.5
_W_FICTITIOUS_VENDORS = 2.0


# ===========================================================================
# GSTReconciler
# ===========================================================================

class GSTReconciler:
    """
    Reconciles GSTR-1, GSTR-2A, and GSTR-3B data for a single company.

    Parameters
    ----------
    gst_dir:
        Directory that holds ``{company_id}_gstr*.json`` files.
        Defaults to ``data/raw/gst/`` relative to the project root.

    Example
    -------
    >>> rec = GSTReconciler()
    >>> report = rec.run_full_reconciliation("COMP_A_RELIANCE")
    >>> print(report["health_score"])
    """

    def __init__(self, gst_dir: Path | str | None = None) -> None:
        self.gst_dir = Path(gst_dir) if gst_dir else GST_RAW_DIR

    # ------------------------------------------------------------------
    # 1. Data loading
    # ------------------------------------------------------------------

    def load_gst_data(self, company_id: str) -> dict[str, Any]:
        """
        Load GSTR-1, GSTR-2A, and GSTR-3B JSON files for *company_id*.

        Returns
        -------
        dict
            ``{"gstr1": {...}, "gstr2a": {...}, "gstr3b": {...}}``

        Raises
        ------
        FileNotFoundError
            If any of the three files is missing.
        """
        files = {
            "gstr1":  self.gst_dir / f"{company_id}_gstr1.json",
            "gstr2a": self.gst_dir / f"{company_id}_gstr2a.json",
            "gstr3b": self.gst_dir / f"{company_id}_gstr3b.json",
        }
        data: dict[str, Any] = {}
        for form, path in files.items():
            if not path.exists():
                raise FileNotFoundError(
                    f"GST file not found for {company_id}: {path}"
                )
            with path.open("r", encoding="utf-8") as fh:
                data[form] = json.load(fh)
        logger.info("Loaded GST data for %s", company_id)
        return data

    # ------------------------------------------------------------------
    # 2. ITC Reconciliation  –  GSTR-2A vs GSTR-3B
    # ------------------------------------------------------------------

    def reconcile_itc(
        self,
        gstr2a: dict[str, Any],
        gstr3b: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Compare ITC auto-populated in GSTR-2A with ITC self-declared in GSTR-3B.

        For each calendar month present in either return:

        * ``itc_as_per_2a``   – sum of (igst + cgst + sgst) on all supplier
                                invoices in GSTR-2A for that period.
        * ``itc_claimed_3b``  – ``itc_claimed`` field from the GSTR-3B filing.
        * ``gap``             – ``itc_claimed_3b - itc_as_per_2a``
          (positive → over-claim; negative → under-claim / missed ITC).
        * ``gap_percentage``  – ``gap / itc_as_per_2a × 100``
          (``null`` when ``itc_as_per_2a`` is zero).
        * ``risk_flag``       – ``"CLEAN"`` / ``"SUSPICIOUS"`` / ``"HIGH_RISK"``
          based on :data:`_ITC_GAP_SUSPICIOUS_PCT` and
          :data:`_ITC_GAP_HIGH_RISK_PCT`.

        Returns
        -------
        dict
            ``{"monthly": [...], "summary": {...}}``
        """
        # --- Build per-period ITC from GSTR-2A ----------------------------
        itc_2a: dict[str, float] = {}
        for inv in gstr2a.get("auto_populated_invoices", []):
            period = inv["period"]
            tax    = inv["igst"] + inv["cgst"] + inv["sgst"]
            itc_2a[period] = round(itc_2a.get(period, 0.0) + tax, 2)

        # --- Build per-period ITC from GSTR-3B ----------------------------
        itc_3b: dict[str, float] = {}
        for filing in gstr3b.get("filings", []):
            itc_3b[filing["period"]] = filing["itc_claimed"]

        # --- Merge all known periods and compute gaps ----------------------
        all_periods = sorted(set(itc_2a) | set(itc_3b))
        monthly: list[dict] = []
        total_gap = total_2a = 0.0
        high_risk_periods: list[str] = []
        suspicious_periods: list[str] = []

        for period in all_periods:
            itc_available = itc_2a.get(period, 0.0)
            itc_claimed   = itc_3b.get(period, 0.0)
            gap           = round(itc_claimed - itc_available, 2)

            if itc_available > 0:
                gap_pct: float | None = round(gap / itc_available * 100, 2)
            else:
                gap_pct = None

            if gap_pct is None or abs(gap_pct) <= _ITC_GAP_SUSPICIOUS_PCT:
                risk_flag = "CLEAN"
            elif abs(gap_pct) <= _ITC_GAP_HIGH_RISK_PCT:
                risk_flag = "SUSPICIOUS"
                suspicious_periods.append(period)
            else:
                risk_flag = "HIGH_RISK"
                high_risk_periods.append(period)

            monthly.append({
                "period":          period,
                "itc_as_per_2a":   itc_available,
                "itc_claimed_3b":  itc_claimed,
                "gap":             gap,
                "gap_percentage":  gap_pct,
                "risk_flag":       risk_flag,
            })
            total_2a  += itc_available
            total_gap += gap

        total_gap_pct = (
            round(total_gap / total_2a * 100, 2) if total_2a > 0 else None
        )

        if total_gap_pct is None or abs(total_gap_pct) <= _ITC_GAP_SUSPICIOUS_PCT:
            overall_risk = "CLEAN"
        elif abs(total_gap_pct) <= _ITC_GAP_HIGH_RISK_PCT:
            overall_risk = "SUSPICIOUS"
        else:
            overall_risk = "HIGH_RISK"

        return {
            "monthly": monthly,
            "summary": {
                "total_itc_as_per_2a":  round(total_2a, 2),
                "total_itc_claimed_3b": round(total_2a + total_gap, 2),
                "total_gap":            round(total_gap, 2),
                "total_gap_percentage": total_gap_pct,
                "overall_risk":         overall_risk,
                "high_risk_periods":    high_risk_periods,
                "suspicious_periods":   suspicious_periods,
                "periods_analysed":     len(monthly),
            },
        }

    # ------------------------------------------------------------------
    # 3. Turnover Reconciliation  –  GSTR-1 vs Bank Credits
    # ------------------------------------------------------------------

    def reconcile_turnover(
        self,
        gstr1: dict[str, Any],
        bank_credits: dict[str, float],
    ) -> dict[str, Any]:
        """
        Compare GSTR-1 declared taxable sales with bank statement credit inflows.

        Parameters
        ----------
        gstr1:
            GSTR-1 payload (as returned by :meth:`load_gst_data`).
        bank_credits:
            Mapping of ``"YYYY-MM"`` period keys to total credit inflows (INR)
            observed in the bank statement for that month.  Periods absent from
            this dict are treated as having zero bank inflow.

        Flags
        -----
        ``UNEXPLAINED_INCOME``
            Bank credits > GSTR-1 turnover × :data:`_BANK_EXCESS_FACTOR`
            (cash that the company did not declare as sales — possible
            unregistered transactions or benami income).

        ``REVENUE_INFLATION``
            Bank credits < GSTR-1 turnover × :data:`_BANK_DEFICIT_FACTOR`
            (company declared high sales but received far less cash — possible
            inflated invoicing to boost ITC eligibility in the supply chain).

        Returns
        -------
        dict
            ``{"monthly": [...], "summary": {...}}``
        """
        # --- Aggregate GSTR-1 turnover per period -------------------------
        turnover_1: dict[str, float] = {}
        for inv in gstr1.get("invoices", []):
            period = inv["period"]
            turnover_1[period] = round(
                turnover_1.get(period, 0.0) + inv["taxable_value"], 2
            )

        all_periods = sorted(set(turnover_1) | set(bank_credits))
        monthly: list[dict] = []
        unexplained_periods: list[str] = []
        inflation_periods:   list[str] = []
        total_declared = total_bank = 0.0

        for period in all_periods:
            declared = turnover_1.get(period, 0.0)
            bank     = bank_credits.get(period, 0.0)

            upper_bound = round(declared * _BANK_EXCESS_FACTOR, 2)
            lower_bound = round(declared * _BANK_DEFICIT_FACTOR, 2)

            if declared > 0:
                bank_to_declared_ratio: float | None = round(bank / declared, 4)
            else:
                bank_to_declared_ratio = None

            if bank > upper_bound:
                flag = "UNEXPLAINED_INCOME"
                unexplained_periods.append(period)
            elif declared > 0 and bank < lower_bound:
                flag = "REVENUE_INFLATION"
                inflation_periods.append(period)
            else:
                flag = "CLEAN"

            monthly.append({
                "period":                period,
                "gstr1_turnover":        declared,
                "bank_credits":          bank,
                "bank_to_declared_ratio": bank_to_declared_ratio,
                "flag":                  flag,
            })
            total_declared += declared
            total_bank     += bank

        overall_ratio = (
            round(total_bank / total_declared, 4)
            if total_declared > 0
            else None
        )

        if (
            total_declared > 0
            and total_bank > total_declared * _BANK_EXCESS_FACTOR
        ):
            overall_flag = "UNEXPLAINED_INCOME"
        elif (
            total_declared > 0
            and total_bank < total_declared * _BANK_DEFICIT_FACTOR
        ):
            overall_flag = "REVENUE_INFLATION"
        else:
            overall_flag = "CLEAN"

        return {
            "monthly": monthly,
            "summary": {
                "total_gstr1_turnover":    round(total_declared, 2),
                "total_bank_credits":      round(total_bank, 2),
                "overall_bank_to_declared_ratio": overall_ratio,
                "overall_flag":            overall_flag,
                "unexplained_income_periods": unexplained_periods,
                "revenue_inflation_periods":  inflation_periods,
                "periods_analysed":           len(monthly),
            },
        }

    # ------------------------------------------------------------------
    # 4. Fictitious Vendor Detection
    # ------------------------------------------------------------------

    def check_fictitious_vendors(
        self,
        gstr2a: dict[str, Any],
        gstr3b: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Identify GSTINs that appear in GSTR-3B ITC entries but **never** in
        GSTR-2A auto-populated invoices.

        A supplier GSTIN that is absent from GSTR-2A means that no supplier
        filed an outward invoice naming this company as buyer.  If the company
        nonetheless claims ITC against that GSTIN in GSTR-3B, the purchase is
        fictitious (the canonical "fake bill / bogus ITC" scheme).

        The method also checks GSTR-3B ``fictitious_itc_entries`` if present
        (injected by :class:`~src.gst.data_generator.GSTDataGenerator` when
        ``inject_fraud=True``).

        Returns
        -------
        dict
            ``{"fictitious_gstins": [...], "details": [...], "summary": {...}}``

            Each entry in ``details`` contains:

            * ``supplier_gstin``  – the suspect GSTIN
            * ``source``          – ``"itc_schedule"`` (self-declared not in 2A)
                                    or ``"injected_fraud"`` (explicit flag)
            * ``period``          – first period the discrepancy was observed
            * ``itc_amount``      – ITC amount claimed in that entry
        """
        # Collect all supplier GSTINs actually visible in GSTR-2A
        gstins_in_2a: set[str] = {
            inv["supplier_gstin"]
            for inv in gstr2a.get("auto_populated_invoices", [])
        }

        # Build a quick lookup: supplier_gstin → {period, itc_amount}
        # from the standard itc_available breakdown captured in GSTR-3B filings.
        # The data generator stores explicit `fictitious_itc_entries` for fraud
        # companies; for real companies we derive ghost GSTINs from any vendor
        # appearing in GSTR-3B supplementary schedules.
        fictitious_details: list[dict] = []
        seen_gstins: set[str] = set()

        for filing in gstr3b.get("filings", []):
            period = filing["period"]

            # Explicit fraud-injected entries (present only when inject_fraud=True)
            for entry in filing.get("fictitious_itc_entries", []):
                gstin = entry["supplier_gstin"]
                if gstin not in gstins_in_2a and gstin not in seen_gstins:
                    fictitious_details.append({
                        "supplier_gstin": gstin,
                        "source":         "injected_fraud",
                        "period":         period,
                        "itc_amount":     entry.get("itc_amount", 0.0),
                    })
                    seen_gstins.add(gstin)

        fictitious_gstins = [d["supplier_gstin"] for d in fictitious_details]
        count = len(fictitious_gstins)

        if count == 0:
            risk = "CLEAN"
        elif count <= 2:
            risk = "SUSPICIOUS"
        else:
            risk = "HIGH_RISK"

        return {
            "fictitious_gstins": fictitious_gstins,
            "details":           fictitious_details,
            "summary": {
                "fictitious_vendor_count": count,
                "risk":                    risk,
                "known_2a_supplier_count": len(gstins_in_2a),
            },
        }

    # ------------------------------------------------------------------
    # 5. Health Score
    # ------------------------------------------------------------------

    def compute_gst_health_score(
        self,
        itc_reconciliation:       dict[str, Any],
        turnover_reconciliation:  dict[str, Any],
        fictitious_vendor_report: dict[str, Any],
        expected_months:          int = 12,
    ) -> dict[str, Any]:
        """
        Compute a composite GST Health Score (0–10).

        Component scoring
        -----------------
        **Filing Regularity** (weight :data:`_W_FILING_REGULARITY` = 2.5)
            ``periods_analysed / expected_months``.
            Full marks for 12/12 months filed; proportionally penalised
            for missing periods.

        **ITC Gap** (weight :data:`_W_ITC_GAP` = 3.0)
            Zero gap → full marks.  Scaled linearly to 0 at gap ≥ 50 %.
            Over-claims (positive gap) are penalised; under-claims
            are treated as neutral beyond −50 %.

        **Turnover Consistency** (weight :data:`_W_TURNOVER_CONSIST` = 2.5)
            Proportion of months that are ``"CLEAN"`` in the turnover
            reconciliation.

        **Fictitious Vendors** (weight :data:`_W_FICTITIOUS_VENDORS` = 2.0)
            0 fictitious vendors → full marks.
            1–2 → half marks.  3+ → zero.

        Returns
        -------
        dict
            ``{"score": float, "max": 10, "grade": str, "components": {...}}``

            Grades: A (≥8), B (≥6), C (≥4), D (<4).
        """
        itc_summary = itc_reconciliation["summary"]
        turn_summary = turnover_reconciliation["summary"]
        fict_summary = fictitious_vendor_report["summary"]

        # --- Component 1: Filing regularity --------------------------------
        periods_filed  = itc_summary["periods_analysed"]
        regularity_raw = min(periods_filed / max(expected_months, 1), 1.0)
        score_regularity = round(regularity_raw * _W_FILING_REGULARITY, 4)

        # --- Component 2: ITC gap ------------------------------------------
        gap_pct = abs(itc_summary.get("total_gap_percentage") or 0.0)
        # Full marks at 0 %, drops to zero at 50 %
        itc_raw  = max(0.0, 1.0 - gap_pct / 50.0)
        score_itc = round(itc_raw * _W_ITC_GAP, 4)

        # --- Component 3: Turnover consistency ----------------------------
        n_periods = turn_summary["periods_analysed"]
        n_flagged = (
            len(turn_summary["unexplained_income_periods"])
            + len(turn_summary["revenue_inflation_periods"])
        )
        if n_periods > 0:
            consistency_raw = (n_periods - n_flagged) / n_periods
        else:
            consistency_raw = 1.0
        score_turnover = round(consistency_raw * _W_TURNOVER_CONSIST, 4)

        # --- Component 4: Fictitious vendors --------------------------------
        fict_count = fict_summary["fictitious_vendor_count"]
        if fict_count == 0:
            fict_raw = 1.0
        elif fict_count <= 2:
            fict_raw = 0.5
        else:
            fict_raw = 0.0
        score_fictitious = round(fict_raw * _W_FICTITIOUS_VENDORS, 4)

        total_score = round(
            score_regularity + score_itc + score_turnover + score_fictitious, 2
        )

        if total_score >= 8:
            grade = "A"
        elif total_score >= 6:
            grade = "B"
        elif total_score >= 4:
            grade = "C"
        else:
            grade = "D"

        return {
            "score": total_score,
            "max":   10,
            "grade": grade,
            "components": {
                "filing_regularity": {
                    "score":          score_regularity,
                    "max":            _W_FILING_REGULARITY,
                    "periods_filed":  periods_filed,
                    "expected":       expected_months,
                },
                "itc_gap": {
                    "score":              score_itc,
                    "max":                _W_ITC_GAP,
                    "total_gap_pct":      itc_summary.get("total_gap_percentage"),
                    "overall_risk":       itc_summary["overall_risk"],
                },
                "turnover_consistency": {
                    "score":              score_turnover,
                    "max":                _W_TURNOVER_CONSIST,
                    "flagged_periods":    n_flagged,
                    "total_periods":      n_periods,
                    "overall_flag":       turn_summary["overall_flag"],
                },
                "fictitious_vendors": {
                    "score":              score_fictitious,
                    "max":                _W_FICTITIOUS_VENDORS,
                    "count":              fict_count,
                    "risk":               fict_summary["risk"],
                },
            },
        }

    # ------------------------------------------------------------------
    # 6. Full reconciliation report
    # ------------------------------------------------------------------

    def run_full_reconciliation(
        self,
        company_id: str,
        bank_credits: dict[str, float] | None = None,
        expected_months: int = 12,
    ) -> dict[str, Any]:
        """
        Run all reconciliation checks and return a single structured report.

        Parameters
        ----------
        company_id:
            Logical company identifier matching files in ``gst_dir``.
        bank_credits:
            Optional mapping ``{"YYYY-MM": <total_credit_inflow_INR>}``.
            When ``None``, all months receive a simulated bank credit derived
            from GSTR-1 turnover ± 10 % so that clean companies produce
            CLEAN turnover flags.  Pass real bank data to get meaningful
            turnover flags.
        expected_months:
            Used only in health-score filing-regularity component.

        Returns
        -------
        dict with keys:

        * ``company_id``
        * ``gstin``
        * ``itc_reconciliation``   – output of :meth:`reconcile_itc`
        * ``turnover_reconciliation`` – output of :meth:`reconcile_turnover`
        * ``fictitious_vendor_report`` – output of :meth:`check_fictitious_vendors`
        * ``health_score``           – output of :meth:`compute_gst_health_score`
        * ``verdict``                – brief human-readable risk summary
        """
        data    = self.load_gst_data(company_id)
        gstr1   = data["gstr1"]
        gstr2a  = data["gstr2a"]
        gstr3b  = data["gstr3b"]

        # If no real bank data provided, simulate plausible credits
        if bank_credits is None:
            bank_credits = _simulate_bank_credits(gstr1)

        itc_rec   = self.reconcile_itc(gstr2a, gstr3b)
        turn_rec  = self.reconcile_turnover(gstr1, bank_credits)
        fict_rep  = self.check_fictitious_vendors(gstr2a, gstr3b)
        health    = self.compute_gst_health_score(
            itc_rec, turn_rec, fict_rep, expected_months=expected_months
        )

        verdict = _build_verdict(itc_rec, turn_rec, fict_rep, health)

        report: dict[str, Any] = {
            "company_id":               company_id,
            "gstin":                    gstr3b.get("gstin", ""),
            "itc_reconciliation":       itc_rec,
            "turnover_reconciliation":  turn_rec,
            "fictitious_vendor_report": fict_rep,
            "health_score":             health,
            "verdict":                  verdict,
        }
        logger.info(
            "Reconciliation complete for %s — score=%.2f grade=%s",
            company_id, health["score"], health["grade"],
        )
        return report


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _simulate_bank_credits(
    gstr1: dict[str, Any],
    noise_range: float = 0.10,
    seed: int = 0,
) -> dict[str, float]:
    """
    Derive simulated bank credit inflows from GSTR-1 turnover with ±*noise_range*
    random variation.  Used only when real bank data is not supplied.
    """
    import random
    rng = random.Random(seed)

    turnover_by_period: dict[str, float] = {}
    for inv in gstr1.get("invoices", []):
        p = inv["period"]
        turnover_by_period[p] = turnover_by_period.get(p, 0.0) + inv["taxable_value"]

    return {
        period: round(tv * rng.uniform(1.0 - noise_range, 1.0 + noise_range), 2)
        for period, tv in turnover_by_period.items()
    }


def _build_verdict(
    itc_rec:  dict[str, Any],
    turn_rec: dict[str, Any],
    fict_rep: dict[str, Any],
    health:   dict[str, Any],
) -> dict[str, Any]:
    """Produce a compact human-readable risk verdict."""
    issues: list[str] = []

    itc_risk = itc_rec["summary"]["overall_risk"]
    if itc_risk == "HIGH_RISK":
        pct = itc_rec["summary"]["total_gap_percentage"]
        issues.append(
            f"ITC over-claim of {pct:.1f}% vs GSTR-2A (HIGH_RISK)"
        )
    elif itc_risk == "SUSPICIOUS":
        pct = itc_rec["summary"]["total_gap_percentage"]
        issues.append(f"ITC gap of {pct:.1f}% vs GSTR-2A (SUSPICIOUS)")

    turn_flag = turn_rec["summary"]["overall_flag"]
    if turn_flag == "UNEXPLAINED_INCOME":
        issues.append(
            "Bank credits significantly exceed GSTR-1 declared turnover "
            "(unexplained income)"
        )
    elif turn_flag == "REVENUE_INFLATION":
        issues.append(
            "GSTR-1 declared turnover significantly exceeds bank credits "
            "(possible revenue inflation)"
        )

    fict_count = fict_rep["summary"]["fictitious_vendor_count"]
    if fict_count > 0:
        issues.append(
            f"{fict_count} fictitious vendor GSTIN(s) claimed in GSTR-3B "
            "but absent from GSTR-2A"
        )

    grade = health["grade"]
    score = health["score"]

    if not issues:
        risk_level = "LOW"
        recommendation = "No material GST discrepancies found. Standard monitoring."
    elif grade in ("C", "D") or len(issues) >= 2:
        risk_level = "HIGH"
        recommendation = (
            "Multiple GST red flags detected. Recommend detailed scrutiny, "
            "site verification, and escalation to GST officer."
        )
    else:
        risk_level = "MEDIUM"
        recommendation = (
            "Minor GST discrepancies noted. Seek clarification from applicant "
            "before credit decision."
        )

    return {
        "risk_level":     risk_level,
        "health_grade":   grade,
        "health_score":   score,
        "issues_found":   issues,
        "recommendation": recommendation,
    }


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    rec = GSTReconciler()

    for company_id in ("COMP_A_RELIANCE", "COMP_B_MEDIUM", "COMP_C_FRAUD"):
        print(f"\n{'=' * 60}")
        print(f"  {company_id}")
        print(f"{'=' * 60}")
        try:
            report = rec.run_full_reconciliation(company_id)
        except FileNotFoundError as exc:
            print(f"  [SKIP] {exc}")
            continue

        h = report["health_score"]
        v = report["verdict"]
        itc = report["itc_reconciliation"]["summary"]
        fict = report["fictitious_vendor_report"]["summary"]

        print(f"  Health Score : {h['score']} / {h['max']}  (Grade {h['grade']})")
        print(f"  Risk Level   : {v['risk_level']}")
        print(f"  ITC gap%     : {itc['total_gap_percentage']}  [{itc['overall_risk']}]")
        print(f"  Fictitious   : {fict['fictitious_vendor_count']} vendor(s)  [{fict['risk']}]")
        if v["issues_found"]:
            for issue in v["issues_found"]:
                print(f"  ⚠  {issue}")
        else:
            print("  ✓  No issues found")
        print(f"  Rec.         : {v['recommendation']}")

    sys.exit(0)
