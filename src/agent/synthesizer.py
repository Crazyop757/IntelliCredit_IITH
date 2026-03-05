"""
synthesizer.py — External Intelligence Synthesizer for intelli_credit.

Combines the outputs of four intelligence tools (news, eCourts, MCA, RBI) into
a single structured External Intelligence Report using Claude, with a rule-based
fallback and a deterministic score sanity-check.

Public API
----------
    from src.agent.synthesizer import SynthesizerAgent

    agent = SynthesizerAgent()

    synthesis = agent.synthesize(
        news_report    = ...,   # from NewsIntelligenceTool
        ecourts_report = ...,   # from ECourtsTool
        mca_report     = ...,   # from MCATool
        rbi_report     = ...,   # from RBIDefaulterTool
    )
    # synthesis contains all REQUIRED_FIELDS plus synthesis_method

    score, full = agent.compute_external_score(synthesis)
    # score: float  0.0 – 10.0   (LLM score validated against rule-based check)
    # full : dict   synthesis enriched with sanity_check sub-dict
"""

from __future__ import annotations

import json
import logging
import os
import re
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

from dotenv import load_dotenv  # noqa: E402
load_dotenv(_PROJECT_ROOT / ".env")

import anthropic  # noqa: E402

logger = logging.getLogger("intelli_credit.agent.synthesizer")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_CLAUDE_MODEL = "claude-haiku-4-5-20251001"   # fastest model available; update as needed

# Required keys that every synthesis dict must contain
REQUIRED_FIELDS: tuple[str, ...] = (
    "overall_external_risk_score",
    "promoter_risk_flag",
    "litigation_summary",
    "news_summary",
    "regulatory_compliance_summary",
    "key_red_flags",
    "positive_signals",
    "recommended_action",
)

# Valid values for enumerated fields
_VALID_PROMOTER_FLAGS   = {"HIGH", "MEDIUM", "LOW", "CLEAR"}
_VALID_ACTIONS          = {"PROCEED", "CAUTION", "REJECT"}

# ---------------------------------------------------------------------------
# Claude system prompt
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = """\
You are a credit analyst synthesizing external intelligence for a credit appraisal.

Given the following data, produce a structured External Intelligence Report in JSON \
format with EXACTLY these fields (no extras, no omissions):

{
  "overall_external_risk_score": <float, 0.0 to 10.0, where 10 is maximum risk>,
  "promoter_risk_flag": "<HIGH|MEDIUM|LOW|CLEAR>: <one sentence reason>",
  "litigation_summary": "<2-3 sentences summarising litigation exposure>",
  "news_summary": "<2-3 sentences summarising recent news sentiment>",
  "regulatory_compliance_summary": "<2 sentences on RBI/MCA regulatory standing>",
  "key_red_flags": ["<specific issue #1>", ... up to 5 items],
  "positive_signals": ["<positive finding #1>", ...],
  "recommended_action": "<PROCEED|CAUTION|REJECT>: <one sentence rationale>"
}

Rules:
- overall_external_risk_score MUST be a JSON number (not a string).
- promoter_risk_flag MUST start with HIGH, MEDIUM, LOW, or CLEAR followed by a colon.
- recommended_action MUST start with PROCEED, CAUTION, or REJECT followed by a colon.
- key_red_flags: include ONLY issues actually evidenced in the data; max 5 items.
- positive_signals: include ONLY genuine positives; can be an empty list [].
- Output ONLY the JSON object — no preamble, no explanation, no markdown fences.\
"""


# ---------------------------------------------------------------------------
# SynthesizerAgent
# ---------------------------------------------------------------------------

class SynthesizerAgent:
    """
    Synthesizes four intelligence-tool reports into one External Intelligence Report.

    Workflow
    --------
    1. ``synthesize()``     — LLM path (Claude) → validates output → falls back to
                              rule-based engine on failure / missing API key.
    2. ``compute_external_score()`` — extracts the LLM score, recomputes it
                              deterministically from raw signals as a sanity check,
                              and returns ``(final_score, enriched_synthesis)``.
    """

    def __init__(self) -> None:
        self._api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    # ------------------------------------------------------------------
    # 1. synthesize
    # ------------------------------------------------------------------

    def synthesize(
        self,
        news_report:    dict[str, Any] | None = None,
        ecourts_report: dict[str, Any] | None = None,
        mca_report:     dict[str, Any] | None = None,
        rbi_report:     dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Combine four tool reports into a structured External Intelligence Report.

        Parameters
        ----------
        news_report :
            Output of ``NewsIntelligenceTool.search_company_news()``.
        ecourts_report :
            Output of ``ECourtsTool.search_cases()``.
        mca_report :
            Output of ``MCATool.get_company_master()`` (may include ``"charges"``).
        rbi_report :
            Output of ``RBIDefaulterTool.check_company_group()``.

        Returns
        -------
        dict — validated synthesis containing all ``REQUIRED_FIELDS`` plus:
            ``synthesis_method``: ``"llm"`` | ``"rule_based"``
            ``synthesized_at``  : ISO-8601 UTC timestamp
        """
        result: dict[str, Any] | None = None

        if self._api_key:
            try:
                result = self._llm_synthesize(
                    news_report, ecourts_report, mca_report, rbi_report,
                )
                if result:
                    result = self._validate(result)
                    result["synthesis_method"] = "llm"
            except Exception as exc:
                logger.warning("SynthesizerAgent LLM call failed: %s", exc)
                result = None

        if result is None:
            result = self._rule_based_synthesis(
                news_report, ecourts_report, mca_report, rbi_report,
            )
            result["synthesis_method"] = "rule_based"

        result["synthesized_at"] = datetime.now(tz=timezone.utc).isoformat()
        return result

    # ------------------------------------------------------------------
    # 2. compute_external_score
    # ------------------------------------------------------------------

    def compute_external_score(
        self,
        synthesis: dict[str, Any],
    ) -> tuple[float, dict[str, Any]]:
        """
        Extract and validate the ``overall_external_risk_score`` from *synthesis*.

        Steps
        -----
        1. Parse the LLM-provided score (may be embedded in ``synthesis``).
        2. Recompute a deterministic score from ``key_red_flags``,
           ``promoter_risk_flag``, and ``recommended_action`` as a sanity check.
        3. If the two scores diverge by more than 2.5 points, log a warning
           and average them.
        4. Clamp the final score to ``[0.0, 10.0]``.

        Parameters
        ----------
        synthesis :
            The dict returned by ``synthesize()``.

        Returns
        -------
        (final_score, enriched_synthesis)
            * ``final_score``       : float, 0.0 – 10.0
            * ``enriched_synthesis``: the input dict enriched with a
              ``"sanity_check"`` sub-dict containing both scores and the
              method used to resolve a divergence.
        """
        # ── LLM score ────────────────────────────────────────────────────
        llm_score = self._extract_llm_score(synthesis)

        # ── Rule-based score ─────────────────────────────────────────────
        rb_score = self._compute_rule_score(synthesis)

        # ── Divergence check ─────────────────────────────────────────────
        divergence = abs(llm_score - rb_score)
        if divergence > 2.5:
            logger.warning(
                "compute_external_score: LLM score %.1f diverges from rule-based "
                "score %.1f by %.1f — averaging.",
                llm_score, rb_score, divergence,
            )
            final_score = (llm_score + rb_score) / 2.0
            resolution  = "averaged_due_to_divergence"
        elif synthesis.get("synthesis_method") == "rule_based":
            final_score = rb_score
            resolution  = "rule_based_primary"
        else:
            final_score = llm_score
            resolution  = "llm_primary"

        final_score = max(0.0, min(10.0, final_score))

        enriched = dict(synthesis)
        enriched["sanity_check"] = {
            "llm_score":      llm_score,
            "rule_based_score": rb_score,
            "divergence":     round(divergence, 2),
            "resolution":     resolution,
            "final_score":    round(final_score, 2),
        }
        enriched["overall_external_risk_score"] = round(final_score, 2)

        return round(final_score, 2), enriched

    # ===================================================================
    # Private helpers — LLM path
    # ===================================================================

    def _llm_synthesize(
        self,
        news_report:    dict[str, Any] | None,
        ecourts_report: dict[str, Any] | None,
        mca_report:     dict[str, Any] | None,
        rbi_report:     dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        reports_json = json.dumps(
            {
                "news_intelligence":   news_report,
                "ecourts_litigation":  ecourts_report,
                "mca_corporate":       mca_report,
                "rbi_defaulter":       rbi_report,
            },
            indent=2,
            default=str,
        )

        user_msg = f"Intelligence data:\n\n{reports_json}"

        client   = anthropic.Anthropic(api_key=self._api_key)
        response = client.messages.create(
            model=_CLAUDE_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": user_msg}],
            system=_SYSTEM_PROMPT,
        )
        raw_text = response.content[0].text.strip()

        # Strip accidental markdown code fences
        raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
        raw_text = re.sub(r"\s*```$", "", raw_text)

        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if not match:
            logger.warning("LLM response contained no JSON object:\n%s", raw_text[:400])
            return None

        return json.loads(match.group())

    # ------------------------------------------------------------------
    def _validate(self, raw: dict[str, Any]) -> dict[str, Any]:
        """
        Ensure all REQUIRED_FIELDS are present and that enum fields are valid.
        Raises ``ValueError`` on unrecoverable issues (triggers rule-based fallback).
        """
        missing = [f for f in REQUIRED_FIELDS if f not in raw]
        if missing:
            raise ValueError(f"LLM response missing fields: {missing}")

        # overall_external_risk_score must be numeric
        score = raw["overall_external_risk_score"]
        if not isinstance(score, (int, float)):
            try:
                raw["overall_external_risk_score"] = float(str(score).split("/")[0].strip())
            except (ValueError, IndexError):
                raise ValueError(f"Cannot parse overall_external_risk_score: {score!r}")

        # promoter_risk_flag must start with a known level
        pflag = str(raw["promoter_risk_flag"]).upper()
        if not any(pflag.startswith(v) for v in _VALID_PROMOTER_FLAGS):
            raise ValueError(f"Invalid promoter_risk_flag: {raw['promoter_risk_flag']!r}")

        # recommended_action must start with a known action
        action = str(raw["recommended_action"]).upper()
        if not any(action.startswith(v) for v in _VALID_ACTIONS):
            raise ValueError(f"Invalid recommended_action: {raw['recommended_action']!r}")

        # Ensure list fields are actually lists
        for key in ("key_red_flags", "positive_signals"):
            if not isinstance(raw[key], list):
                raw[key] = [str(raw[key])] if raw[key] else []

        # Truncate red flags to max 5
        raw["key_red_flags"] = raw["key_red_flags"][:5]

        return raw

    # ===================================================================
    # Private helpers — rule-based fallback
    # ===================================================================

    def _rule_based_synthesis(
        self,
        news_report:    dict[str, Any] | None,
        ecourts_report: dict[str, Any] | None,
        mca_report:     dict[str, Any] | None,
        rbi_report:     dict[str, Any] | None,
    ) -> dict[str, Any]:
        """
        Deterministic credit opinion built entirely from signal rules.
        No LLM involved — guarantees a valid response under any conditions.
        """
        red_flags:        list[str] = []
        positive_signals: list[str] = []
        score: float = 0.0

        # ── RBI (weight: up to 4 pts) ─────────────────────────────────
        promoter_risk   = "CLEAR"
        promoter_reason = "No RBI wilful-defaulter matches found."
        if rbi_report:
            if rbi_report.get("is_flagged"):
                hits = rbi_report.get("hit_count", 1)
                red_flags.append(
                    f"RBI wilful-defaulter: {hits} match(es) — "
                    + (rbi_report.get("summary") or "")
                )
                score         += 4.0
                promoter_risk  = "HIGH"
                first_hit      = (rbi_report.get("hits") or [{}])[0]
                promoter_reason = (
                    f"Matched as RBI wilful defaulter: {first_hit.get('matched_name', 'unknown')} "
                    f"(confidence {first_hit.get('match_confidence', 0):.0%})."
                )
            else:
                positive_signals.append("No RBI wilful-defaulter matches found.")

        # ── eCourts (weight: up to 3 pts) ─────────────────────────────
        lit_score = 0.0
        lit_detail = "No litigation data available."
        if ecourts_report and not ecourts_report.get("error"):
            lit_score = float(ecourts_report.get("litigation_risk_score", 0))
            cases     = ecourts_report.get("cases") or []
            nclt      = ecourts_report.get("nclt_override", False)
            cnt       = len(cases)
            severity  = ecourts_report.get("severity_breakdown") or {}

            if nclt:
                red_flags.append("Active NCLT / insolvency proceeding detected.")
                score += 3.0
            elif lit_score >= 7:
                red_flags.append(f"High litigation risk score: {lit_score:.1f}/10 ({cnt} case(s)).")
                score += 2.5
            elif lit_score >= 4:
                red_flags.append(f"Moderate litigation risk score: {lit_score:.1f}/10 ({cnt} case(s)).")
                score += 1.5
            elif cnt == 0:
                positive_signals.append("No active court cases on record.")
                score += 0.0

            if nclt:
                lit_detail = (
                    f"Company has an active NCLT / insolvency proceeding. "
                    f"Litigation risk score is {lit_score:.1f}/10 across {cnt} case(s). "
                    "This represents a severe financial-stress signal."
                )
            elif cnt > 0:
                crit  = severity.get("CRITICAL", 0)
                high  = severity.get("HIGH", 0)
                lit_detail = (
                    f"Company has {cnt} active court case(s) with a litigation risk "
                    f"score of {lit_score:.1f}/10 "
                    f"({crit} critical, {high} high severity). "
                    "Significant exposure warrants detailed legal due-diligence."
                )
            else:
                lit_detail = "No active court cases found across major Indian courts."
        elif ecourts_report and ecourts_report.get("error"):
            lit_detail = "eCourts data unavailable due to an access error; manual verification recommended."

        # ── MCA (weight: up to 2 pts) ──────────────────────────────────
        mca_lines: list[str] = []
        if mca_report and not mca_report.get("error"):
            active = mca_report.get("company_active", True)
            if not active:
                red_flags.append(
                    f"Company status is '{mca_report.get('company_status', 'unknown')}' per MCA records."
                )
                score += 2.0
                mca_lines.append("Company is struck off or dormant per MCA records.")
            else:
                positive_signals.append("Company is active per MCA.")
                mca_lines.append("Company is active per MCA records.")

            if mca_report.get("bs_filing_overdue"):
                red_flags.append("Balance-sheet filing overdue (> 2 years).")
                score += 0.5
                mca_lines.append("Balance-sheet filing is overdue.")
            if mca_report.get("agm_overdue"):
                red_flags.append("AGM overdue (> 15 months).")
                mca_lines.append("Last AGM is overdue.")
            charges = mca_report.get("charges") or {}
            if isinstance(charges, dict) and charges.get("hidden_debt_flag"):
                red_flags.append(
                    "Potential hidden debt: open MCA charges exceed declared debt by > 25 %."
                )
                score += 0.5
            elif isinstance(charges, dict) and charges.get("open_charges", 0) == 0:
                positive_signals.append("No open charges against the company.")
        elif mca_report and mca_report.get("error"):
            mca_lines.append("MCA data unavailable due to an access error.")

        reg_summary = (
            " ".join(mca_lines[:2]) if mca_lines
            else "MCA regulatory data was not available for this entity."
        )

        # ── News (weight: up to 2 pts) ─────────────────────────────────
        news_score  = 0.0
        news_detail = "No recent news data available."
        if news_report and not news_report.get("error"):
            news_score  = float(news_report.get("news_risk_score", 0))
            neg_count   = news_report.get("negative_article_count", 0)
            headline    = news_report.get("most_alarming_headline", "")
            risk_tags   = news_report.get("risk_tags") or []
            cred_score  = news_report.get("source_credibility_score", 0.5)

            if news_score >= 7:
                red_flags.append(
                    f"High negative news sentiment (score {news_score:.1f}/10, "
                    f"{neg_count} negative article(s))."
                )
                score += 2.0
            elif news_score >= 4:
                red_flags.append(
                    f"Moderate negative news sentiment (score {news_score:.1f}/10)."
                )
                score += 1.0
            elif neg_count == 0:
                positive_signals.append("No negative news articles found in the lookback window.")
                score += 0.0

            tag_str = ", ".join(risk_tags[:3]) if risk_tags else "none identified"
            source_txt = (
                f"Coverage from {'high' if cred_score >= 0.8 else 'moderate'}-credibility "
                f"sources (average score {cred_score:.2f})."
            )
            if neg_count > 0:
                news_detail = (
                    f"{neg_count} negative article(s) found with a risk score of "
                    f"{news_score:.1f}/10. Primary risk themes: {tag_str}. "
                    f"Most alarming headline: \"{headline}\". {source_txt}"
                )
            else:
                news_detail = (
                    f"No negative articles identified in the lookback window "
                    f"(risk score {news_score:.1f}/10). {source_txt}"
                )

        # ── Cap and determine action ───────────────────────────────────
        score = min(10.0, score)

        if score >= 7.5 or "CRITICAL" in promoter_risk:
            action = "REJECT"
            rationale = (
                "Multiple critical risk signals (RBI defaulter / NCLT / struck-off) "
                "make credit extension unjustifiable."
            )
        elif score >= 4.5:
            action = "CAUTION"
            rationale = (
                "Elevated risk signals require enhanced due-diligence and senior "
                "credit-committee approval before proceeding."
            )
        else:
            action = "PROCEED"
            rationale = (
                "External intelligence checks returned low-risk signals; "
                "proceed to financial due-diligence."
            )

        # Limit red flags to 5
        red_flags = red_flags[:5]

        return {
            "overall_external_risk_score":  round(score, 2),
            "promoter_risk_flag":           f"{promoter_risk}: {promoter_reason}",
            "litigation_summary":           lit_detail,
            "news_summary":                 news_detail,
            "regulatory_compliance_summary": reg_summary,
            "key_red_flags":                red_flags,
            "positive_signals":             positive_signals,
            "recommended_action":           f"{action}: {rationale}",
        }

    # ===================================================================
    # Private helpers — score computation
    # ===================================================================

    def _extract_llm_score(self, synthesis: dict[str, Any]) -> float:
        """Parse ``overall_external_risk_score`` from synthesis; return 5.0 on failure."""
        raw = synthesis.get("overall_external_risk_score", None)
        if raw is None:
            return 5.0
        try:
            return float(str(raw).split("/")[0].strip())
        except (ValueError, TypeError):
            return 5.0

    def _compute_rule_score(self, synthesis: dict[str, Any]) -> float:
        """
        Compute a deterministic score from synthesis fields as a sanity check.

        Scoring
        -------
        * ``recommended_action`` prefix:  REJECT → 8.5 | CAUTION → 5.5 | PROCEED → 2.0
        * ``promoter_risk_flag``  prefix: HIGH    → +1.5 | MEDIUM → +0.5 | LOW/CLEAR → 0
        * ``key_red_flags`` count:        each flag → +0.3, capped at 1.5
        """
        # Base score from recommended action
        action = str(synthesis.get("recommended_action", "")).upper()
        if action.startswith("REJECT"):
            base = 8.5
        elif action.startswith("CAUTION"):
            base = 5.5
        else:
            base = 2.0

        # Promoter-risk adjustment
        pflag = str(synthesis.get("promoter_risk_flag", "")).upper()
        if pflag.startswith("HIGH"):
            base += 1.5
        elif pflag.startswith("MEDIUM"):
            base += 0.5

        # Red-flag count adjustment
        n_flags = len(synthesis.get("key_red_flags") or [])
        base += min(1.5, n_flags * 0.3)

        return round(min(10.0, base), 2)


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    )

    # ---------- sample mock reports from existing tool fixtures ----------
    MOCK_NEWS = {
        "company_name":           "Kingfisher Airlines",
        "news_risk_score":        8.5,
        "negative_article_count": 12,
        "most_alarming_headline": "Kingfisher Airlines owes banks ₹9000 Cr",
        "source_credibility_score": 0.88,
        "risk_tags":              ["NPA", "fraud", "wilful default"],
        "data_source":            "mock",
    }
    MOCK_ECOURTS = {
        "party_name":             "Kingfisher Airlines",
        "cases":                  [{"case_type": "Winding Up", "severity": "CRITICAL"}],
        "litigation_risk_score":  8.0,
        "nclt_override":          True,
        "severity_breakdown":     {"CRITICAL": 1},
        "data_source":            "mock",
    }
    MOCK_MCA = {
        "cin":            "U62200KA2003PLC032420",
        "company_name":   "KINGFISHER AIRLINES LIMITED",
        "company_active": False,
        "company_status": "Strike off",
        "bs_filing_overdue": True,
        "agm_overdue":    True,
        "charges": {
            "open_charges":           2,
            "open_charge_total_inr":  90_000_000_000,
            "hidden_debt_flag":       False,
        },
        "data_source": "mock",
    }
    MOCK_RBI = {
        "company_name": "Kingfisher Airlines",
        "is_flagged":   True,
        "risk_level":   "CRITICAL",
        "hit_count":    2,
        "hits": [
            {"screened_as": "company",  "matched_name": "KINGFISHER AIRLINES LIMITED",
             "match_confidence": 1.0},
            {"screened_as": "director", "matched_name": "VIJAY MALLYA",
             "match_confidence": 1.0},
        ],
        "summary":     "2 defaulter match(es) found for 'Kingfisher Airlines' group.",
        "data_source": "mock",
    }

    agent = SynthesizerAgent()

    print("\n" + "=" * 66)
    print("  SynthesizerAgent — smoke test")
    print("=" * 66)

    syn = agent.synthesize(
        news_report=MOCK_NEWS,
        ecourts_report=MOCK_ECOURTS,
        mca_report=MOCK_MCA,
        rbi_report=MOCK_RBI,
    )

    score, enriched = agent.compute_external_score(syn)

    print(f"\nSynthesis method      : {syn['synthesis_method']}")
    print(f"overall_risk_score    : {score:.1f}/10")
    print(f"promoter_risk_flag    : {syn['promoter_risk_flag']}")
    print(f"recommended_action    : {syn['recommended_action']}")
    print(f"\nlitigation_summary    :\n  {syn['litigation_summary']}")
    print(f"\nnews_summary          :\n  {syn['news_summary']}")
    print(f"\nregulatory_summary    :\n  {syn['regulatory_compliance_summary']}")

    print("\nkey_red_flags:")
    for f in syn["key_red_flags"]:
        print(f"  • {f}")

    print("\npositive_signals:")
    for s in syn["positive_signals"]:
        print(f"  ✓ {s}")

    sc = enriched["sanity_check"]
    print(f"\nsanity_check:")
    print(f"  llm_score        : {sc['llm_score']:.1f}")
    print(f"  rule_based_score : {sc['rule_based_score']:.1f}")
    print(f"  divergence       : {sc['divergence']:.2f}")
    print(f"  resolution       : {sc['resolution']}")
    print(f"  final_score      : {sc['final_score']:.1f}")

    # ── Assertions ──────────────────────────────────────────────────────
    assert all(f in syn for f in REQUIRED_FIELDS), "Missing required fields"
    assert 0.0 <= score <= 10.0,                    "Score out of range"
    assert isinstance(syn["key_red_flags"], list),  "key_red_flags not a list"
    assert len(syn["key_red_flags"]) <= 5,          "key_red_flags exceeds 5"
    action_val = str(syn["recommended_action"]).upper()
    assert any(action_val.startswith(v) for v in _VALID_ACTIONS), \
        "Invalid recommended_action"
    pflag_val = str(syn["promoter_risk_flag"]).upper()
    assert any(pflag_val.startswith(v) for v in _VALID_PROMOTER_FLAGS), \
        "Invalid promoter_risk_flag"

    print("\n" + "=" * 66)
    print("  ALL ASSERTIONS PASSED")
    print("=" * 66 + "\n")
