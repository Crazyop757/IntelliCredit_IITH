"""
qualitative_scorer.py — Qualitative Due-Diligence Scorer for intelli_credit.

Converts structured Credit-Officer field observations (site visit, management
interview, on-ground verification) into a signed qualitative adjustment
(total_adjustment) to be applied to the overall credit risk score.

Scoring convention
------------------
•  Negative adjustment  →  increases risk  (bad observations).
•  Positive adjustment  →  reduces risk    (good observations).
•  Range is clamped to [−5.0, +2.0].

Text-area fields are also classified by Claude Haiku using the prompt:
  "Classify this credit officer note as: RED_FLAG / NEUTRAL / POSITIVE
   with a one-line reason: {text}"
Each RED_FLAG contributes −1.0 to the total.

Public API
----------
    from src.scorer.qualitative_scorer import QualitativeScorer

    scorer = QualitativeScorer()
    result = scorer.compute_adjustment(form_data)

    # result["total_adjustment"]   float   −5.0 … +2.0
    # result["severity"]           str     HIGH_RISK | MODERATE_RISK | NEUTRAL | POSITIVE
    # result["breakdown"]          dict    {field: adjustment_value}
    # result["red_flags_found"]    list    [{field, reason}, …]
    # result["summary_text"]       str     human-readable 2-sentence summary
    # result["raw_total"]          float   uncapped sum (for audit)
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Project-root path bootstrap (needed to load .env before importing anthropic)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv          # noqa: E402
load_dotenv(_PROJECT_ROOT / ".env")

import anthropic                         # noqa: E402

logger = logging.getLogger("intelli_credit.scorer.qualitative_scorer")

# ---------------------------------------------------------------------------
# Claude model
# ---------------------------------------------------------------------------
_CLAUDE_MODEL = "claude-haiku-4-5-20251001"

# Text-area form fields that receive AI classification
_TEXT_FIELDS = (
    "site_visit_observations",
    "management_interview_notes",
    "group_company_exposure",
    "other_key_observations",
)

# ---------------------------------------------------------------------------
# Lookup tables  (negative = more risk, positive = less risk)
# ---------------------------------------------------------------------------

# Pairs of (upper_bound_exclusive, adjustment) — iterated in order
_CAPACITY_BRACKETS: list[tuple[float, float]] = [
    (40.0,  -2.0),    # pct <  40  → −2.0
    (60.0,  -1.0),    # 40 ≤ pct < 60  → −1.0
    (80.01,  0.0),    # 60 ≤ pct ≤ 80  →  0.0
    (101.0, +0.5),    # pct >  80  → +0.5
]

_FACILITY_CONDITION: dict[str, float] = {
    "Excellent":   +0.5,
    "Good":         0.0,
    "Fair":        -0.5,
    "Poor":        -1.5,
    "Not Visited":  0.0,
}

_MANAGEMENT_TRANSPARENCY: dict[str, float] = {
    "Fully Transparent":      +0.3,
    "Mostly Transparent":     -0.3,
    "Evasive on some topics": -1.5,
    "Uncooperative":          -3.0,
}

_INVENTORY_VS_RECORDS: dict[str, float] = {
    "Matches":             +0.2,
    "Slightly Lower":      -0.7,
    "Significantly Lower": -2.0,
    "Could Not Verify":     0.0,
}

_EMPLOYEE_VS_RECORDS: dict[str, float] = {
    "Matches":          0.0,
    "20% Lower":       -1.0,
    "50%+ Lower":      -2.5,
    "Could Not Verify": 0.0,
}

# ---------------------------------------------------------------------------
# Severity thresholds (lower total = higher risk)
# ---------------------------------------------------------------------------

def _severity(total: float) -> str:
    if total <= -2.0:
        return "HIGH_RISK"
    if total <= -0.5:
        return "MODERATE_RISK"
    if total <= 0.5:
        return "NEUTRAL"
    return "POSITIVE"


# ---------------------------------------------------------------------------
# QualitativeScorer
# ---------------------------------------------------------------------------

class QualitativeScorer:
    """
    Converts Credit Officer form inputs into a signed qualitative risk
    adjustment (total_adjustment).

    Parameters
    ----------
    cap_min : float   Most negative the adjustment can reach.  Default −5.
    cap_max : float   Most positive the adjustment can reach.  Default +2.
    """

    def __init__(self, cap_min: float = -5.0, cap_max: float = 2.0) -> None:
        self._cap_min = cap_min
        self._cap_max = cap_max
        self._api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        self._client  = anthropic.Anthropic(api_key=self._api_key) if self._api_key else None

    # ------------------------------------------------------------------
    # Public entry-point
    # ------------------------------------------------------------------

    def compute_adjustment(self, form_data: dict[str, Any]) -> dict[str, Any]:
        """
        Compute the qualitative risk adjustment from Credit Officer form data.

        form_data keys (all optional; sensible defaults applied):

            capacity_utilization       int   0–100
            facility_condition         str
            management_transparency    str
            inventory_vs_records       str
            employee_count_vs_records  str
            site_visit_observations    str   → AI classified
            management_interview_notes str   → AI classified
            group_company_exposure     str   → AI classified
            other_key_observations     str   → AI classified

        Returns
        -------
        dict:
            total_adjustment   float   clamped [−5, +2]
            severity           str     HIGH_RISK | MODERATE_RISK | NEUTRAL | POSITIVE
            breakdown          dict    {field: adjustment}
            red_flags_found    list    [{field, reason}, …]
            summary_text       str     2-sentence narrative
            raw_total          float   uncapped sum (for audit)
        """
        breakdown:       dict[str, float] = {}
        red_flags_found: list[dict]       = []

        # ---- Structured dropdown fields ----------------------------------
        breakdown["capacity_utilization"] = self._score_capacity(
            form_data.get("capacity_utilization", 70)
        )
        breakdown["facility_condition"] = _FACILITY_CONDITION.get(
            form_data.get("facility_condition", "Good"), 0.0
        )
        breakdown["management_transparency"] = _MANAGEMENT_TRANSPARENCY.get(
            form_data.get("management_transparency", "Fully Transparent"), 0.0
        )
        breakdown["inventory_vs_records"] = _INVENTORY_VS_RECORDS.get(
            form_data.get("inventory_vs_records", "Matches"), 0.0
        )
        breakdown["employee_count_vs_records"] = _EMPLOYEE_VS_RECORDS.get(
            form_data.get("employee_count_vs_records", "Matches"), 0.0
        )

        # ---- Free-text fields (AI classification) -----------------------
        for field in _TEXT_FIELDS:
            text = form_data.get(field, "").strip()
            if not text:
                continue
            label, reason = self._classify_text(field, text)
            if label == "RED_FLAG":
                breakdown[f"{field}_text"] = -1.0
                red_flags_found.append({"field": field, "reason": reason})
            # NEUTRAL and POSITIVE leave the score unchanged per spec

        # ---- Aggregate --------------------------------------------------
        raw_total        = sum(breakdown.values())
        total_adjustment = round(max(self._cap_min, min(self._cap_max, raw_total)), 2)
        severity         = _severity(total_adjustment)

        logger.info(
            "QualitativeScorer: raw=%.2f  adj=%.2f  severity=%s  red_flags=%d",
            raw_total, total_adjustment, severity, len(red_flags_found),
        )

        return {
            "total_adjustment": total_adjustment,
            "severity":         severity,
            "breakdown":        breakdown,
            "red_flags_found":  red_flags_found,
            "summary_text":     self._build_summary(
                total_adjustment, severity, breakdown, red_flags_found
            ),
            "raw_total": round(raw_total, 2),
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _score_capacity(utilization: int | float) -> float:
        """Map capacity utilization % to a risk adjustment."""
        pct = float(utilization)
        for upper, adj in _CAPACITY_BRACKETS:
            if pct < upper:
                return adj
        return +0.5   # pct == 100 edge-case

    def _classify_text(self, field: str, text: str) -> tuple[str, str]:
        """
        Ask Claude Haiku to classify a free-text note as RED_FLAG / NEUTRAL / POSITIVE.

        Returns (label, one_line_reason).  Falls back to ("NEUTRAL", reason) on error.
        """
        if not self._client:
            logger.debug("No API key — skipping text classification for %s.", field)
            return "NEUTRAL", "No API key — classification skipped."

        prompt = (
            f"Classify this credit officer note as: RED_FLAG / NEUTRAL / POSITIVE "
            f"with a one-line reason: {text}"
        )
        try:
            response = self._client.messages.create(
                model=_CLAUDE_MODEL,
                max_tokens=80,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()

            # Expect the response to open with the label
            for label in ("RED_FLAG", "NEUTRAL", "POSITIVE"):
                if raw.upper().startswith(label):
                    reason = raw[len(label):].lstrip(": ").strip()
                    return label, reason or raw

            # Label not at the start — scan the full response
            upper = raw.upper()
            if "RED_FLAG" in upper or "RED FLAG" in upper:
                return "RED_FLAG", raw
            if "POSITIVE" in upper:
                return "POSITIVE", raw
            return "NEUTRAL", raw

        except Exception as exc:  # noqa: BLE001
            logger.warning("Text classification failed for '%s': %s", field, exc)
            return "NEUTRAL", f"Classification error: {exc}"

    @staticmethod
    def _build_summary(
        total: float,
        severity: str,
        breakdown: dict[str, float],
        red_flags: list[dict],
    ) -> str:
        """Compose a concise two-sentence narrative."""
        if total < -0.5:
            direction, verb = "elevated risk", "worsened"
        elif total > 0.5:
            direction, verb = "positive signals", "improved"
        else:
            direction, verb = "neutral indicators", "remained stable"

        worst       = min(breakdown, key=lambda k: breakdown[k]) if breakdown else None
        worst_label = worst.replace("_", " ").replace(" text", " (AI)").title() if worst else "N/A"
        worst_val   = breakdown.get(worst, 0.0) if worst else 0.0

        n = len(red_flags)
        flag_str = f" {n} AI red flag{'s' if n != 1 else ''} detected." if n else ""

        s1 = (
            f"On-ground due diligence indicates {direction} — overall assessment "
            f"{verb} by {abs(total):.2f} pts "
            f"(severity: {severity.replace('_', ' ').title()}, total: {total:+.2f})."
        )
        s2 = (
            f"Largest contributor: {worst_label} at {worst_val:+.2f}.{flag_str}"
        )
        return f"{s1} {s2}"


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import pprint

    scorer = QualitativeScorer()

    # Positive: 90% capacity (+0.5), Excellent (+0.5), Fully (+0.3), Matches (+0.2) → +1.5
    positive = scorer.compute_adjustment({
        "capacity_utilization":    90,
        "facility_condition":      "Excellent",
        "management_transparency": "Fully Transparent",
        "inventory_vs_records":    "Matches",
        "employee_count_vs_records": "Matches",
    })
    print("\n=== POSITIVE ===")
    pprint.pprint(positive)
    assert positive["severity"]         == "POSITIVE",  positive["severity"]
    assert positive["total_adjustment"] >  0,           positive["total_adjustment"]

    # Neutral: 70% cap (0.0), Good (0.0), Mostly (−0.3), Matches (+0.2), Matches (0.0) → −0.1
    neutral = scorer.compute_adjustment({
        "capacity_utilization":    70,
        "facility_condition":      "Good",
        "management_transparency": "Mostly Transparent",
        "inventory_vs_records":    "Matches",
        "employee_count_vs_records": "Matches",
    })
    print("\n=== NEUTRAL ===")
    pprint.pprint(neutral)
    assert neutral["severity"] == "NEUTRAL", neutral["severity"]

    # High-risk (all bad fields, no text) → raw −11.0, clamped to −5.0
    risky = scorer.compute_adjustment({
        "capacity_utilization":    30,
        "facility_condition":      "Poor",
        "management_transparency": "Uncooperative",
        "inventory_vs_records":    "Significantly Lower",
        "employee_count_vs_records": "50%+ Lower",
    })
    print("\n=== HIGH RISK ===")
    pprint.pprint(risky)
    assert risky["severity"]         == "HIGH_RISK", risky["severity"]
    assert risky["total_adjustment"] == -5.0,        risky["total_adjustment"]

    print("\n=== ALL SMOKE-TEST ASSERTIONS PASSED ===")
