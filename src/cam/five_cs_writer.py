"""
five_cs_writer.py — LLM-powered 5 C's Credit Appraisal Memo writer.

Uses Claude to draft the five standard sections of an Indian bank Credit Appraisal
Memo (CAM): Character, Capacity, Capital, Collateral, and Conditions.

Each section is written in formal third-person banking language, referencing
the specific data points supplied by the caller.  A ``regenerate_if_short``
guard ensures every section meets a minimum word count.

Public API
----------
    from src.cam.five_cs_writer import FiveCsWriter

    writer = FiveCsWriter()

    char = writer.write_character(
        company_data     = {"name": "Acme Ltd", "directors": [...], ...},
        research_report  = {...},   # from ResearchAgent / SynthesizerAgent
    )
    cap  = writer.write_capacity(financials)
    capl = writer.write_capital(balance_sheet_data)
    coll = writer.write_collateral(site_visit, mca_charges)
    cond = writer.write_conditions(research_report, sector_data)

    # Each method returns:
    # {
    #   "section"          : str   — e.g. "CHARACTER"
    #   "text"             : str   — the written CAM section
    #   "word_count"       : int
    #   "meets_min_length" : bool
    #   "regenerated"      : bool  — True if regenerate_if_short was triggered
    #   "generation_method": str   — "llm" | "fallback"
    #   "model"            : str
    # }

Fallback
--------
When ``ANTHROPIC_API_KEY`` is absent, all methods return clearly-marked
placeholder templates so downstream code always receives a well-formed response.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Project-root path bootstrap
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv          # noqa: E402
load_dotenv(_PROJECT_ROOT / ".env")

import anthropic                         # noqa: E402

logger = logging.getLogger("intelli_credit.cam.five_cs_writer")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# Use the same model as the rest of the project.  Override via constructor.
_CLAUDE_MODEL = "claude-haiku-4-5-20251001"

# CAM sections require at least 150 words (2-3 paragraphs, 150-200 target).
_CAM_MIN_WORDS = 150

# Expansion prompt reused by regenerate_if_short
_EXPAND_SYSTEM = (
    "You are a senior Indian bank credit analyst. "
    "The following Credit Appraisal Memo section is too short. "
    "Expand it to at least {min_words} words while preserving the exact "
    "third-person, professional banking tone and all specific facts already mentioned. "
    "Do NOT add fictional data — expand only on implications and industry context."
)

# ---------------------------------------------------------------------------
# Base system-prompt template shared by all 5 C write methods
# ---------------------------------------------------------------------------
_BASE_SYSTEM = (
    "You are an experienced Indian bank credit analyst writing a formal "
    "Credit Appraisal Memo. "
    "Write the {section_upper} section (2-3 paragraphs, 150-200 words) "
    "assessing {assessment_focus}. "
    "You MUST reference the specific data points provided. "
    "Write in third person, professional banking language, no jargon. "
    "Include specific facts."
)

# ---------------------------------------------------------------------------
# Section-level system-prompt fragments
# ---------------------------------------------------------------------------
_SECTION_FOCUS: dict[str, str] = {
    "CHARACTER":  (
        "management integrity, promoter trustworthiness, and track record "
        "of meeting financial obligations"
    ),
    "CAPACITY":   (
        "the borrower's ability to service debt from operating cash flows, "
        "including DSCR trends, liquidity position, and repayment track record"
    ),
    "CAPITAL":    (
        "the borrower's net worth, capital adequacy, and promoter equity "
        "contribution as a buffer against credit losses"
    ),
    "COLLATERAL": (
        "the quality, liquidity, legal enforceability, and adequacy of "
        "security offered against the proposed credit facility"
    ),
    "CONDITIONS": (
        "the current macroeconomic environment, sector-specific risks, "
        "and regulatory factors that affect the borrower and the proposed credit"
    ),
}


# ===========================================================================
# FiveCsWriter
# ===========================================================================

class FiveCsWriter:
    """
    LLM-powered writer for the five sections of a Credit Appraisal Memo.

    Parameters
    ----------
    model : str
        Claude model identifier.  Defaults to ``claude-haiku-4-5-20251001``
        (same as the rest of the project).
    max_tokens : int
        Maximum tokens for the primary generation call.
    """

    def __init__(
        self,
        model:      str = _CLAUDE_MODEL,
        max_tokens: int = 700,
    ) -> None:
        self._api_key   = os.environ.get("ANTHROPIC_API_KEY", "")
        self._client    = (
            anthropic.Anthropic(api_key=self._api_key) if self._api_key else None
        )
        self._model     = model
        self._max_tokens = max_tokens

    # ==================================================================
    # 1. Character
    # ==================================================================

    def write_character(
        self,
        company_data:    dict[str, Any],
        research_report: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Write the CHARACTER section of the CAM.

        Assesses management integrity, promoter background, litigation
        exposure, and reputational signals drawn from external intelligence.

        Parameters
        ----------
        company_data : dict
            Keys used (all optional with sensible defaults):

            ==================  =============================================
            name                Company / borrower legal name
            directors           list[str] or str of director names
            wilful_default_flag bool / int / str — RBI wilful-defaulter flag
            ecourts_cases       int / str — number of active eCourts cases
            management_notes    str — credit-officer interview notes
            ==================  =============================================

        research_report : dict
            Should contain ``news_summary`` and / or ``promoter_risk_flag``
            from ``SynthesizerAgent``.

        Returns
        -------
        dict — structured CAM section (see module docstring).
        """
        name      = company_data.get("name", "the borrower")
        directors = company_data.get("directors", [])
        if isinstance(directors, (list, tuple)):
            directors = ", ".join(str(d) for d in directors) if directors else "not disclosed"
        flag      = company_data.get("wilful_default_flag", "No")
        flag_str  = "YES — listed as an RBI wilful defaulter" if flag and str(flag) not in ("0", "False", "No", "false", "no") else "No"
        cases     = company_data.get("ecourts_cases", 0)
        notes     = company_data.get("management_notes", "No formal interview notes recorded.")

        news_summary = (
            research_report.get("news_summary")
            or research_report.get("synthesis_report", {}).get("news_summary")
            or "No recent news intelligence available."
        )
        promoter_flag = (
            research_report.get("promoter_risk_flag")
            or research_report.get("synthesis_report", {}).get("promoter_risk_flag")
            or "Not assessed."
        )

        system_prompt = _BASE_SYSTEM.format(
            section_upper    = "CHARACTER",
            assessment_focus = _SECTION_FOCUS["CHARACTER"],
        )

        user_prompt = (
            f"Company: {name}.\n\n"
            f"Key data:\n"
            f"  Directors: {directors}.\n"
            f"  Wilful default flag: {flag_str}.\n"
            f"  eCourts cases (active): {cases}.\n"
            f"  Promoter risk flag: {promoter_flag}.\n"
            f"  News findings: {news_summary}.\n"
            f"  Management interview notes: {notes}.\n\n"
            f"Write the Character assessment."
        )

        return self._generate_section("CHARACTER", system_prompt, user_prompt)

    # ==================================================================
    # 2. Capacity
    # ==================================================================

    def write_capacity(self, financials: dict[str, Any]) -> dict[str, Any]:
        """
        Write the CAPACITY section of the CAM.

        Assesses the borrower's ability to repay from operating cash flows,
        drawing on income statement and cash-flow metrics.

        Parameters
        ----------
        financials : dict
            Keys used (all optional):

            ======================  =========================================
            name                    Company name
            revenue                 Total revenue / turnover (₹ Cr or absolute)
            revenue_growth_pct      YoY revenue growth (%)
            ebitda                  EBITDA amount
            ebitda_margin_pct       EBITDA margin (%)
            pat                     Profit After Tax
            pat_margin_pct          PAT margin (%)
            dscr                    Debt Service Coverage Ratio
            current_ratio           Current Ratio
            interest_coverage       Interest Coverage Ratio
            cfo                     Cash Flow from Operations
            proposed_emi            Proposed monthly / annual debt service
            existing_obligations    Existing loan repayment obligations
            ======================  =========================================

        Returns
        -------
        dict — structured CAM section.
        """
        name     = financials.get("name", "the borrower")
        revenue  = financials.get("revenue", "not provided")
        rev_gr   = financials.get("revenue_growth_pct", "N/A")
        ebitda   = financials.get("ebitda", "not provided")
        ebitda_m = financials.get("ebitda_margin_pct", "N/A")
        pat      = financials.get("pat", "not provided")
        pat_m    = financials.get("pat_margin_pct", "N/A")
        dscr     = financials.get("dscr", "N/A")
        curr_r   = financials.get("current_ratio", "N/A")
        icr      = financials.get("interest_coverage", "N/A")
        cfo      = financials.get("cfo", "not provided")
        emi      = financials.get("proposed_emi", "not specified")
        existing = financials.get("existing_obligations", "none disclosed")

        system_prompt = _BASE_SYSTEM.format(
            section_upper    = "CAPACITY",
            assessment_focus = _SECTION_FOCUS["CAPACITY"],
        )

        user_prompt = (
            f"Company: {name}.\n\n"
            f"Key financial metrics:\n"
            f"  Revenue: {revenue}  (YoY growth: {rev_gr}%).\n"
            f"  EBITDA: {ebitda}  (margin: {ebitda_m}%).\n"
            f"  Profit After Tax (PAT): {pat}  (PAT margin: {pat_m}%).\n"
            f"  Debt Service Coverage Ratio (DSCR): {dscr}.\n"
            f"  Current Ratio: {curr_r}.\n"
            f"  Interest Coverage Ratio: {icr}.\n"
            f"  Cash Flow from Operations (CFO): {cfo}.\n"
            f"  Proposed debt service obligation: {emi}.\n"
            f"  Existing loan obligations: {existing}.\n\n"
            f"Write the Capacity assessment."
        )

        return self._generate_section("CAPACITY", system_prompt, user_prompt)

    # ==================================================================
    # 3. Capital
    # ==================================================================

    def write_capital(self, balance_sheet_data: dict[str, Any]) -> dict[str, Any]:
        """
        Write the CAPITAL section of the CAM.

        Assesses the borrower's equity base, net worth, and the promoter's
        financial commitment as a loss-absorption buffer.

        Parameters
        ----------
        balance_sheet_data : dict
            Keys used (all optional):

            ========================  =======================================
            name                      Company name
            net_worth                 Net worth / shareholders' equity
            total_debt                Total outstanding borrowings
            debt_to_equity            Debt-to-Equity ratio
            paid_up_capital           Paid-up share capital
            reserves_and_surplus      Accumulated reserves
            promoter_contribution     Promoter equity stake / infusion amount
            promoter_holding_pct      Promoter shareholding (%)
            retained_earnings         Retained earnings (current year)
            tangible_net_worth        TNW after adjusting intangibles
            ========================  =======================================

        Returns
        -------
        dict — structured CAM section.
        """
        name     = balance_sheet_data.get("name", "the borrower")
        nw       = balance_sheet_data.get("net_worth", "not provided")
        debt     = balance_sheet_data.get("total_debt", "not provided")
        dte      = balance_sheet_data.get("debt_to_equity", "N/A")
        puc      = balance_sheet_data.get("paid_up_capital", "not provided")
        reserves = balance_sheet_data.get("reserves_and_surplus", "not provided")
        promo_c  = balance_sheet_data.get("promoter_contribution", "not disclosed")
        promo_h  = balance_sheet_data.get("promoter_holding_pct", "N/A")
        ret_earn = balance_sheet_data.get("retained_earnings", "not provided")
        tnw      = balance_sheet_data.get("tangible_net_worth", "not provided")

        system_prompt = _BASE_SYSTEM.format(
            section_upper    = "CAPITAL",
            assessment_focus = _SECTION_FOCUS["CAPITAL"],
        )

        user_prompt = (
            f"Company: {name}.\n\n"
            f"Balance sheet highlights:\n"
            f"  Net Worth: {nw}.\n"
            f"  Tangible Net Worth (TNW): {tnw}.\n"
            f"  Total Debt: {debt}.\n"
            f"  Debt-to-Equity Ratio: {dte}.\n"
            f"  Paid-up Capital: {puc}.\n"
            f"  Reserves & Surplus: {reserves}.\n"
            f"  Retained Earnings (current year): {ret_earn}.\n"
            f"  Promoter equity contribution: {promo_c}.\n"
            f"  Promoter shareholding: {promo_h}%.\n\n"
            f"Write the Capital assessment."
        )

        return self._generate_section("CAPITAL", system_prompt, user_prompt)

    # ==================================================================
    # 4. Collateral
    # ==================================================================

    def write_collateral(
        self,
        site_visit:  dict[str, Any],
        mca_charges: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Write the COLLATERAL section of the CAM.

        Assesses the nature, quality, and sufficiency of the security
        offered, drawing on physical site-visit findings and MCA charge data.

        Parameters
        ----------
        site_visit : dict
            Keys used (all optional):

            ========================  =======================================
            name                      Company name
            observations              Str — key site-visit notes
            property_type             Type of primary security asset
            property_location         Location (district / state)
            estimated_value           Market / distress valuation (₹)
            valuation_date            Date of last independent valuation
            loan_amount               Proposed exposure (₹)
            security_coverage_ratio   Collateral value / loan amount
            secondary_security        Personal guarantee / pledge details
            ========================  =======================================

        mca_charges : dict
            Typically from ``MCATool``.  Keys used:

            ====================  ============================================
            total_charges         Total registered charges count
            open_charges          Unsatisfied / active charge count
            open_charge_amount    Aggregate amount of open charges (₹)
            charge_holders        list[str] — lenders holding open charges
            ====================  ============================================

        Returns
        -------
        dict — structured CAM section.
        """
        name       = site_visit.get("name", mca_charges.get("company_name", "the borrower"))
        obs        = site_visit.get("observations", "No site-visit observations recorded.")
        prop_type  = site_visit.get("property_type", "not specified")
        prop_loc   = site_visit.get("property_location", "not specified")
        est_val    = site_visit.get("estimated_value", "not provided")
        val_date   = site_visit.get("valuation_date", "not provided")
        loan_amt   = site_visit.get("loan_amount", "not specified")
        scr        = site_visit.get("security_coverage_ratio", "N/A")
        secondary  = site_visit.get("secondary_security", "none offered")

        total_ch   = mca_charges.get("total_charges", 0)
        open_ch    = mca_charges.get("open_charges", 0)
        open_amt   = mca_charges.get("open_charge_amount", "not disclosed")
        ch_holders = mca_charges.get("charge_holders", [])
        if isinstance(ch_holders, (list, tuple)):
            ch_holders = ", ".join(str(c) for c in ch_holders) if ch_holders else "none on record"

        system_prompt = _BASE_SYSTEM.format(
            section_upper    = "COLLATERAL",
            assessment_focus = _SECTION_FOCUS["COLLATERAL"],
        )

        user_prompt = (
            f"Company: {name}.\n\n"
            f"Site visit findings:\n"
            f"  Observations: {obs}\n"
            f"  Primary security type: {prop_type}.\n"
            f"  Location: {prop_loc}.\n"
            f"  Estimated market value: {est_val}  (Valuation date: {val_date}).\n"
            f"  Proposed loan exposure: {loan_amt}.\n"
            f"  Security Coverage Ratio (SCR): {scr}.\n"
            f"  Secondary security / guarantees: {secondary}.\n\n"
            f"MCA charge details:\n"
            f"  Total registered charges: {total_ch}.\n"
            f"  Open (unsatisfied) charges: {open_ch}  (aggregate: {open_amt}).\n"
            f"  Existing charge holders: {ch_holders}.\n\n"
            f"Write the Collateral assessment."
        )

        return self._generate_section("COLLATERAL", system_prompt, user_prompt)

    # ==================================================================
    # 5. Conditions
    # ==================================================================

    def write_conditions(
        self,
        research_report: dict[str, Any],
        sector_data:     dict[str, Any],
    ) -> dict[str, Any]:
        """
        Write the CONDITIONS section of the CAM.

        Assesses the external environment — macroeconomic conditions,
        sector outlook, competitive dynamics, and regulatory developments —
        in the context of the proposed credit.

        Parameters
        ----------
        research_report : dict
            Output from ``ResearchAgent`` / ``SynthesizerAgent``.  Keys used:
            ``news_summary``, ``regulatory_compliance_summary``,
            ``recommended_action``, ``overall_external_risk_score``.

        sector_data : dict
            Keys used (all optional):

            ======================  =========================================
            name                    Company / borrower name
            sector                  Broad sector (e.g. "Steel", "NBFC")
            industry_growth_pct     Sector growth rate (%)
            macro_risks             list[str] or str — key macro headwinds
            regulatory_notes        RBI / SEBI / sectoral regulation summary
            competitive_landscape   Brief description of competitive dynamics
            gdp_growth_pct          India GDP growth (current fiscal, %)
            interest_rate_env       Rate environment note (e.g. "tightening")
            commodity_exposure      Raw-material / commodity price sensitivity
            ======================  =========================================

        Returns
        -------
        dict — structured CAM section.
        """
        name        = sector_data.get("name", "the borrower")
        sector      = sector_data.get("sector", "not specified")
        ind_growth  = sector_data.get("industry_growth_pct", "N/A")
        macro_risks = sector_data.get("macro_risks", [])
        if isinstance(macro_risks, (list, tuple)):
            macro_risks = "; ".join(str(r) for r in macro_risks) if macro_risks else "none highlighted"
        reg_notes   = sector_data.get("regulatory_notes", "No specific regulatory concerns flagged.")
        comp        = sector_data.get("competitive_landscape", "not assessed")
        gdp         = sector_data.get("gdp_growth_pct", "N/A")
        rate_env    = sector_data.get("interest_rate_env", "N/A")
        commodity   = sector_data.get("commodity_exposure", "not material")

        news_summary   = (
            research_report.get("news_summary")
            or research_report.get("synthesis_report", {}).get("news_summary")
            or "No recent news available."
        )
        reg_summary    = (
            research_report.get("regulatory_compliance_summary")
            or research_report.get("synthesis_report", {}).get("regulatory_compliance_summary")
            or "No regulatory findings."
        )
        ext_risk_score = (
            research_report.get("overall_external_risk_score")
            or research_report.get("synthesis_report", {}).get("overall_external_risk_score")
            or "N/A"
        )
        rec_action     = (
            research_report.get("recommended_action")
            or research_report.get("synthesis_report", {}).get("recommended_action")
            or "N/A"
        )

        system_prompt = _BASE_SYSTEM.format(
            section_upper    = "CONDITIONS",
            assessment_focus = _SECTION_FOCUS["CONDITIONS"],
        )

        user_prompt = (
            f"Company: {name}.\n\n"
            f"Sector & macro context:\n"
            f"  Sector: {sector}.\n"
            f"  Industry growth rate: {ind_growth}%.\n"
            f"  India GDP growth (current fiscal): {gdp}%.\n"
            f"  Interest rate environment: {rate_env}.\n"
            f"  Key macro risks: {macro_risks}.\n"
            f"  Competitive landscape: {comp}.\n"
            f"  Commodity / input-cost exposure: {commodity}.\n\n"
            f"Research intelligence:\n"
            f"  News summary: {news_summary}\n"
            f"  Regulatory compliance summary: {reg_summary}\n"
            f"  External risk score (0–10): {ext_risk_score}.\n"
            f"  Recommended action: {rec_action}.\n"
            f"  Regulatory notes: {reg_notes}\n\n"
            f"Write the Conditions assessment."
        )

        return self._generate_section("CONDITIONS", system_prompt, user_prompt)

    # ==================================================================
    # regenerate_if_short
    # ==================================================================

    def regenerate_if_short(self, text: str, min_words: int = 100) -> str:
        """
        Check if *text* meets the minimum word count.  If not, ask Claude to
        expand it while preserving all existing facts and banking tone.

        This method can be called stand-alone or is invoked automatically
        by every ``write_*`` method.

        Parameters
        ----------
        text : str
            The section text to evaluate.
        min_words : int
            Minimum acceptable word count (default 100).

        Returns
        -------
        str — original text if it already meets the requirement; otherwise the
        Claude-expanded version (or original text if the API is unavailable).
        """
        word_count = len(text.split())
        if word_count >= min_words:
            return text

        logger.info(
            "Section has only %d words (min %d) — requesting expansion …",
            word_count, min_words,
        )

        if not self._client:
            logger.warning(
                "ANTHROPIC_API_KEY not set — cannot expand short section (%d words).",
                word_count,
            )
            return text  # return as-is; caller's responsibility

        system = _EXPAND_SYSTEM.format(min_words=min_words)
        user   = (
            f"Expand this credit memo section (currently {word_count} words; "
            f"target: at least {min_words} words):\n\n{text}"
        )

        try:
            response = self._client.messages.create(
                model     = self._model,
                max_tokens= self._max_tokens,
                system    = system,
                messages  = [{"role": "user", "content": user}],
            )
            expanded = response.content[0].text.strip()
            new_count = len(expanded.split())
            logger.info(
                "Section expanded from %d → %d words.", word_count, new_count
            )
            return expanded
        except Exception as exc:    # noqa: BLE001
            logger.warning(
                "regenerate_if_short — Claude call failed: %s — returning original.",
                exc,
            )
            return text

    # ==================================================================
    # Private helpers
    # ==================================================================

    def _call_claude(
        self, system_prompt: str, user_prompt: str, max_tokens: int | None = None
    ) -> str:
        """
        Make a single Claude API call.  Returns the response text.
        Raises ``RuntimeError`` when the API key is not configured
        (caller must handle and fall back).
        """
        if not self._client:
            raise RuntimeError("ANTHROPIC_API_KEY not set.")

        response = self._client.messages.create(
            model     = self._model,
            max_tokens= max_tokens or self._max_tokens,
            system    = system_prompt,
            messages  = [{"role": "user", "content": user_prompt}],
        )
        return response.content[0].text.strip()

    def _fallback_text(self, section: str) -> str:
        """
        Return a clearly-labelled placeholder when the LLM is unavailable.
        The text is intentionally minimal so it is obvious to reviewers that
        it must be replaced before the CAM is submitted.
        """
        templates: dict[str, str] = {
            "CHARACTER": (
                "[AUTO-GENERATED PLACEHOLDER — REPLACE BEFORE SUBMISSION]\n\n"
                "The management of the borrower comprises experienced professionals. "
                "No adverse findings have been recorded in the absence of intelligence "
                "data. A full character assessment requires manual completion by the "
                "relationship manager referencing director KYC, eCourts records, "
                "RBI defaulter status, and news intelligence."
            ),
            "CAPACITY": (
                "[AUTO-GENERATED PLACEHOLDER — REPLACE BEFORE SUBMISSION]\n\n"
                "The borrower's repayment capacity is pending assessment. "
                "Key metrics including DSCR, current ratio, interest coverage, "
                "and cash flow from operations must be verified from audited "
                "financials before this section is completed."
            ),
            "CAPITAL": (
                "[AUTO-GENERATED PLACEHOLDER — REPLACE BEFORE SUBMISSION]\n\n"
                "The capital adequacy of the borrower is pending assessment. "
                "Net worth, debt-to-equity position, and promoter equity "
                "contribution are to be verified from the latest audited "
                "balance sheet before this section is completed."
            ),
            "COLLATERAL": (
                "[AUTO-GENERATED PLACEHOLDER — REPLACE BEFORE SUBMISSION]\n\n"
                "The collateral assessment is pending completion. "
                "Site visit observations, independent valuation report, "
                "and MCA charge search results must be reviewed to assess "
                "security coverage and lien priority."
            ),
            "CONDITIONS": (
                "[AUTO-GENERATED PLACEHOLDER — REPLACE BEFORE SUBMISSION]\n\n"
                "The external conditions analysis is pending completion. "
                "Macro-economic outlook, sector growth trends, regulatory "
                "developments, and competitive dynamics relevant to the "
                "borrower's industry must be incorporated by the analyst."
            ),
        }
        return templates.get(section, f"[{section} — no content generated]")

    def _generate_section(
        self,
        section:       str,
        system_prompt: str,
        user_prompt:   str,
    ) -> dict[str, Any]:
        """
        Internal dispatcher: call Claude → run regenerate_if_short guard →
        build and return the structured result dict.
        """
        regenerated = False
        method      = "llm"
        text        = ""

        try:
            text = self._call_claude(system_prompt, user_prompt)
            logger.info(
                "[%s] Initial generation: %d words.", section, len(text.split())
            )
        except RuntimeError as exc:
            logger.warning(
                "[%s] API unavailable (%s) — using fallback template.", section, exc
            )
            text   = self._fallback_text(section)
            method = "fallback"
        except Exception as exc:    # noqa: BLE001
            logger.error(
                "[%s] Unexpected error during generation: %s — using fallback.",
                section, exc,
            )
            text   = self._fallback_text(section)
            method = "fallback"

        # ── Length guard ──────────────────────────────────────────────
        if method == "llm":
            expanded = self.regenerate_if_short(text, min_words=_CAM_MIN_WORDS)
            if expanded != text:
                text        = expanded
                regenerated = True

        word_count = len(text.split())

        return {
            "section":           section,
            "text":              text,
            "word_count":        word_count,
            "meets_min_length":  word_count >= _CAM_MIN_WORDS,
            "regenerated":       regenerated,
            "generation_method": method,
            "model":             self._model if method == "llm" else "none",
        }


# ---------------------------------------------------------------------------
# Module-level convenience wrappers
# ---------------------------------------------------------------------------

def write_five_cs(
    company_data:      dict[str, Any],
    financials:        dict[str, Any],
    balance_sheet:     dict[str, Any],
    site_visit:        dict[str, Any],
    mca_charges:       dict[str, Any],
    research_report:   dict[str, Any],
    sector_data:       dict[str, Any],
    model:             str = _CLAUDE_MODEL,
) -> dict[str, dict[str, Any]]:
    """
    Write all five CAM sections in one call.

    Returns a dict keyed by section name:
    ``{"CHARACTER": ..., "CAPACITY": ..., "CAPITAL": ...,
       "COLLATERAL": ..., "CONDITIONS": ...}``
    """
    writer = FiveCsWriter(model=model)
    return {
        "CHARACTER":  writer.write_character(company_data, research_report),
        "CAPACITY":   writer.write_capacity(financials),
        "CAPITAL":    writer.write_capital(balance_sheet),
        "COLLATERAL": writer.write_collateral(site_visit, mca_charges),
        "CONDITIONS": writer.write_conditions(research_report, sector_data),
    }


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys as _sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    )

    print("\n" + "=" * 65)
    print("  FiveCsWriter — CAM Section Smoke-test")
    print("=" * 65)

    # ── Synthetic demo data ────────────────────────────────────────────
    company_data = {
        "name":                "Acme Manufacturing Private Limited",
        "directors":           ["Rajesh Mehta", "Supriya Mehta"],
        "wilful_default_flag": False,
        "ecourts_cases":       2,
        "management_notes":    (
            "Promoters have 15 years in the sector. "
            "No hostile regulatory inquiries. "
            "Second-generation management; succession planning in place."
        ),
    }
    research_report = {
        "news_summary":                  "No significant adverse news in the last 24 months.",
        "regulatory_compliance_summary": "MCA filings up to date; no SEBI notices.",
        "promoter_risk_flag":            "LOW: No RBI defaulter matches found.",
        "overall_external_risk_score":   2.5,
        "recommended_action":            "PROCEED: External intelligence is broadly clean.",
    }
    financials = {
        "name":                 "Acme Manufacturing Private Limited",
        "revenue":              "₹148 Crore",
        "revenue_growth_pct":   12.4,
        "ebitda":               "₹22 Crore",
        "ebitda_margin_pct":    14.9,
        "pat":                  "₹8.6 Crore",
        "pat_margin_pct":       5.8,
        "dscr":                 1.42,
        "current_ratio":        1.18,
        "interest_coverage":    3.1,
        "cfo":                  "₹14 Crore",
        "proposed_emi":         "₹1.2 Crore per month",
        "existing_obligations": "₹0.4 Crore per month (vehicle loans)",
    }
    balance_sheet = {
        "name":                  "Acme Manufacturing Private Limited",
        "net_worth":             "₹42 Crore",
        "tangible_net_worth":    "₹39 Crore",
        "total_debt":            "₹58 Crore",
        "debt_to_equity":        1.38,
        "paid_up_capital":       "₹5 Crore",
        "reserves_and_surplus":  "₹37 Crore",
        "retained_earnings":     "₹6.2 Crore",
        "promoter_contribution": "₹12 Crore (own funds)",
        "promoter_holding_pct":  74,
    }
    site_visit = {
        "name":                    "Acme Manufacturing Private Limited",
        "observations":            (
            "Plant operational, modern CNC machinery observed, "
            "adequate raw-material stock on floor. No visible distress signs."
        ),
        "property_type":           "Industrial land & factory building",
        "property_location":       "Chakan Industrial Area, Pune, Maharashtra",
        "estimated_value":         "₹85 Crore",
        "valuation_date":          "January 2026",
        "loan_amount":             "₹50 Crore",
        "security_coverage_ratio": 1.7,
        "secondary_security":      "Personal guarantee of Rajesh Mehta (NW ₹28 Cr)",
    }
    mca_charges = {
        "total_charges":      3,
        "open_charges":       1,
        "open_charge_amount": "₹22 Crore",
        "charge_holders":     ["State Bank of India"],
    }
    sector_data = {
        "name":                  "Acme Manufacturing Private Limited",
        "sector":                "Auto-Components Manufacturing",
        "industry_growth_pct":   8.5,
        "gdp_growth_pct":        6.9,
        "interest_rate_env":     "Stable — RBI repo at 6.5%",
        "macro_risks":           [
            "Input-cost inflation (steel, aluminium)",
            "EV transition risk for ICE component suppliers",
        ],
        "regulatory_notes":      "PLI scheme benefits available; no sector-specific RBI restrictions.",
        "competitive_landscape": "Fragmented mid-size OEM supplier market; company holds 3 OEM certifications.",
        "commodity_exposure":    "High — 60% COGS is steel and aluminium",
    }

    writer = FiveCsWriter()

    sections = [
        ("CHARACTER",  lambda: writer.write_character(company_data, research_report)),
        ("CAPACITY",   lambda: writer.write_capacity(financials)),
        ("CAPITAL",    lambda: writer.write_capital(balance_sheet)),
        ("COLLATERAL", lambda: writer.write_collateral(site_visit, mca_charges)),
        ("CONDITIONS", lambda: writer.write_conditions(research_report, sector_data)),
    ]

    for sec_name, fn in sections:
        print(f"\n{'─' * 65}")
        print(f"  [{sec_name}]")
        print(f"{'─' * 65}")
        result = fn()
        print(f"  Method   : {result['generation_method']}")
        print(f"  Words    : {result['word_count']}  (min {_CAM_MIN_WORDS})")
        print(f"  Meets min: {result['meets_min_length']}")
        print(f"  Regen'd  : {result['regenerated']}")
        print(f"\n{result['text']}")

    print("\n" + "=" * 65)
    print("  Smoke-test complete.")
    print("=" * 65 + "\n")
