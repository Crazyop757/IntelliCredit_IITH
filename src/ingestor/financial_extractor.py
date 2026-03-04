"""
financial_extractor.py — Structured financial data extractor for intelli_credit.

Consumes the ``raw_text`` and ``tables`` output of :class:`PDFParser` and
returns normalised financial figures, computed ratios, flagged risk clauses,
and identified directors/officers.

No external dependencies beyond the standard library.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("intelli_credit.ingestor.financial_extractor")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Conversion multipliers → everything stored in INR crores
_CRORE      = 1.0
_LAKH       = 0.01          # 1 lakh  = 0.01 crore
_BILLION    = 666.67        # 1 USD Bn ≈ 666.67 Cr  (rough; override via fx_usd_inr)
_MILLION    = 0.66667       # 1 USD Mn ≈ 0.66667 Cr
_INR_BILLION= 100.0         # 1 INR Bn = 100 crore
_INR_MILLION= 0.1           # 1 INR Mn = 0.1 crore
_THOUSAND   = 0.0001        # 1 thousand INR = 0.0001 crore (rarely seen)

# Char budget per "page" when estimating page numbers from char offsets
_CHARS_PER_PAGE = 2500

# ---------------------------------------------------------------------------
# Risk-clause definitions
# ---------------------------------------------------------------------------

@dataclass
class RiskClause:
    clause_text:        str
    matched_phrase:     str
    severity:           str          # "HIGH" | "MEDIUM" | "LOW"
    page_number_estimate: int
    context_snippet:    str          # ±120 chars around the match

# Each entry: (phrase_pattern, severity)
# Phrases are matched case-insensitively.
_RISK_PHRASES: list[tuple[str, str]] = [
    # ── HIGH severity ──────────────────────────────────────────────
    (r"going\s+concern",                            "HIGH"),
    (r"qualified\s+opinion",                        "HIGH"),
    (r"wilful\s+default",                           "HIGH"),
    (r"wilful\s+defaulter",                         "HIGH"),
    (r"insolvency",                                 "HIGH"),
    (r"nclt",                                       "HIGH"),
    (r"national\s+company\s+law\s+tribunal",        "HIGH"),
    (r"sarfaesi",                                   "HIGH"),
    (r"unable\s+to\s+independently\s+verify",       "HIGH"),
    (r"fraud",                                      "HIGH"),
    (r"money\s+laundering",                         "HIGH"),
    # ── MEDIUM severity ────────────────────────────────────────────
    (r"debt\s+covenant",                            "MEDIUM"),
    (r"covenant\s+breach",                          "MEDIUM"),
    (r"restructur(?:ed|ing)\s+(?:debt|loan|facility)", "MEDIUM"),
    (r"overdue",                                    "MEDIUM"),
    (r"non[-\s]performing\s+asset",                 "MEDIUM"),
    (r"\bnpa\b",                                    "MEDIUM"),
    (r"one[-\s]time\s+settlement",                  "MEDIUM"),
    (r"\bots\b",                                    "MEDIUM"),
    (r"forensic\s+audit",                           "MEDIUM"),
    (r"material\s+uncertainty",                     "MEDIUM"),
    (r"emphasis\s+of\s+matter",                     "MEDIUM"),
    (r"contingent\s+liabilit(?:y|ies)",             "MEDIUM"),
    (r"legal\s+proceedings?\s+pending",             "MEDIUM"),
    # ── LOW severity ───────────────────────────────────────────────
    (r"adverse\s+(?:remark|observation)",           "LOW"),
    (r"significant\s+doubt",                        "LOW"),
    (r"regulatory\s+(?:action|penalty|notice)",     "LOW"),
    (r"tax\s+demand",                               "LOW"),
    (r"pending\s+litigation",                       "LOW"),
    (r"negative\s+(?:net\s+worth|networth)",        "LOW"),
]

# Pre-compile for speed
_COMPILED_RISK: list[tuple[re.Pattern, str]] = [
    (re.compile(p, re.IGNORECASE), sev)
    for p, sev in _RISK_PHRASES
]

# ---------------------------------------------------------------------------
# Director / officer title patterns
# ---------------------------------------------------------------------------

_TITLE_PREFIX = (
    r"(?:Mr\.|Mrs\.|Ms\.|Dr\.|Prof\.|Shri|Smt\.|Shrimati|Er\.)[^\S\n]+"
)
_NAME_PATTERN = (
    r"[A-Z][a-zA-Z'-]{1,20}"           # First name  (e.g. "Mukesh")
    r"(?:[^\S\n]+[A-Z]\.){0,2}"        # 0–2 initials  (e.g. " D.")
    r"[^\S\n]+[A-Z][a-zA-Z'-]{1,20}"  # Surname (required, e.g. "Ambani")
)
_DESIGNATION_KEYWORDS = [
    "Managing Director", "Whole.Time Director", "Independent Director",
    "Non.Executive Director", "Executive Director", "Director",
    "Chairman", "Vice.Chairman", "Chief Executive Officer",
    r"\bCEO\b", "Chief Financial Officer", r"\bCFO\b",
    "Chief Operating Officer", r"\bCOO\b",
    "Company Secretary", r"\bCS\b",
    "Chief Technology Officer", r"\bCTO\b",
]

_TITLE_RE    = re.compile(_TITLE_PREFIX + r"(" + _NAME_PATTERN + r")", re.UNICODE)
_DESIG_RE    = re.compile(
    r"(?:" + "|".join(_DESIGNATION_KEYWORDS) + r")",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Number-parsing helpers
# ---------------------------------------------------------------------------

def _clean_number(raw: str) -> float:
    """Strip commas and whitespace, return float."""
    return float(re.sub(r"[,\s]", "", raw))


def _parse_amount_to_crores(amount_str: str, unit_str: str) -> float | None:
    """
    Convert a matched (amount, unit) pair to INR crores.

    Handles: crore/cr, lakh/lac, billion/bn, million/mn, thousand/k
    and the special "INR Bn / INR Mn" forms.
    """
    try:
        value = _clean_number(amount_str)
    except (ValueError, TypeError):
        return None

    u = unit_str.lower().strip() if unit_str else ""

    if re.search(r"crore|cr\b", u):
        return value * _CRORE
    if re.search(r"lakh|lac\b", u):
        return value * _LAKH
    if re.search(r"inr\s*bn|inr\s*billion", u):
        return value * _INR_BILLION
    if re.search(r"inr\s*mn|inr\s*million", u):
        return value * _INR_MILLION
    if re.search(r"\bbn\b|billion", u):
        return value * _BILLION
    if re.search(r"\bmn\b|million", u):
        return value * _MILLION
    if re.search(r"thousand|'000|,000\b|\bk\b", u):
        return value * _THOUSAND
    # no unit — return raw (callers decide if useful)
    return value


# ---------------------------------------------------------------------------
# Core regex patterns for financial figures
# ---------------------------------------------------------------------------

# Generic currency prefix: Rs., INR, ₹, USD, $
_CCY      = r"(?:Rs\.?\s*|INR\s*|₹\s*|USD\s*|\$\s*)?"
# Number: handles 1,23,456.78  /  12.3  /  12,345
_NUM      = r"([\d,]+(?:\.\d+)?)"
# Unit (mandatory capture group): crore/cr, lakh/lac, billion/bn, million/mn, etc.
_UNIT     = (
    r"\s*((?:INR\s*)?(?:crore?s?|cr|lakh?s?|lac|billion|bn|million|mn"
    r"|thousand|'000)(?:\s+(?:crore?s?|cr|lakh?s?|lac|billion|bn|million|mn))?)"
)
# Alternative: plain number with optional unit (may be absent)
_UNIT_OPT = (
    r"\s*((?:INR\s*)?(?:crore?s?|cr|lakh?s?|lac|billion|bn|million|mn"
    r"|thousand|'000)(?:\s+(?:crore?s?|cr|lakh?s?|lac|billion|bn|million|mn))?)?"
)

def _build_pattern(label_re: str) -> re.Pattern:
    """
    Build a compiled regex that matches: <label> ... <ccy> <amount> <unit>
    within a window of up to 120 characters.

    The label_re is always wrapped in a non-capturing group so that any
    top-level alternation (``|``) in the label does not swallow the
    capturing groups for amount and unit.
    """
    return re.compile(
        r"(?:" + label_re + r")"
        + r"[^₹\d\n]{0,120}?"
        + _CCY
        + _NUM
        + _UNIT,
        re.IGNORECASE | re.DOTALL,
    )


# ── Revenue / Turnover ──────────────────────────────────────────────────────
_PAT_REVENUE = _build_pattern(
    r"(?:total\s+)?(?:revenue|turnover|net\s+sales?|gross\s+sales?|total\s+income)"
    r"(?:\s+from\s+operations)?"
)

# ── EBITDA ──────────────────────────────────────────────────────────────────
_PAT_EBITDA = _build_pattern(
    r"(?:ebitda"
    r"|earnings?\s+before\s+interest[,\s]+tax(?:es?|ation)?[,\s]+depreciation)"
)

# ── PAT / Net Profit ─────────────────────────────────────────────────────────
_PAT_PAT = _build_pattern(
    r"(?:profit\s+after\s+tax"
    r"|net\s+profit"
    r"|profit\s+for\s+the\s+(?:year|period)"
    r"|\bpat\b)"
)

# ── Total Debt ───────────────────────────────────────────────────────────────
_PAT_DEBT = _build_pattern(
    r"(?:total\s+(?:outstanding\s+)?(?:debt|borrowings?|indebtedness)"
    r"|long[- ]term\s+borrowings?\s*\+\s*short[- ]term\s+borrowings?"
    r"|total\s+(?:financial\s+)?liabilit(?:y|ies))"
)

# ── Net Worth ────────────────────────────────────────────────────────────────
_PAT_NETWORTH = _build_pattern(
    r"(?:total\s+)?(?:net\s+worth"
    r"|shareholders[''s]*\s+(?:equity|funds?)"
    r"|stockholders[''s]*\s+equity"
    r"|equity\s+share\s+capital\s*\+\s*reserves)"
)

# ── Interest Expense ─────────────────────────────────────────────────────────
_PAT_INTEREST = _build_pattern(
    r"(?:finance\s+cost|interest\s+(?:expense|cost|paid|charged)"
    r"|borrowing\s+cost)"
)

# ── Debt Service (principal + interest repaid in year) ───────────────────────
_PAT_DEBT_SERVICE = _build_pattern(
    r"(?:total\s+)?debt\s+service"
    r"|repayment\s+of\s+(?:loans?|borrowings?)"
)

# ── Current Assets / Current Liabilities ─────────────────────────────────────
_PAT_CURRENT_ASSETS = _build_pattern(r"total\s+current\s+assets?")
_PAT_CURRENT_LIAB   = _build_pattern(
    r"total\s+current\s+liabilit(?:y|ies)"
    r"|current\s+liabilit(?:y|ies)\s*(?:&|and)\s+provisions?"
)

# ── "INR X Bn/Mn" standalone form ────────────────────────────────────────────
_PAT_INR_BN = re.compile(
    r"INR\s+" + _NUM + r"\s+(Bn|Billion|Mn|Million)\b",
    re.IGNORECASE,
)


def _first_match_crores(pattern: re.Pattern, text: str) -> float | None:
    """
    Return the first match of *pattern* in *text*, converted to crores.

    The compiled pattern is built by ``_build_pattern`` and always has exactly
    two capturing groups: group 1 = amount, group 2 = unit.
    """
    for m in pattern.finditer(text):
        amount_str = m.group(1)   # NUM group
        unit_str   = m.group(2)   # UNIT group
        val = _parse_amount_to_crores(amount_str, unit_str or "crore")
        if val is not None and val > 0:
            return round(val, 2)
    return None


def _all_matches_crores(pattern: re.Pattern, text: str) -> list[float]:
    """Return all positive matches of *pattern*, deduplicated, sorted descending."""
    results: set[float] = set()
    for m in pattern.finditer(text):
        amount_str = m.group(1)
        unit_str   = m.group(2)
        val = _parse_amount_to_crores(amount_str, unit_str or "crore")
        if val is not None and val > 0:
            results.add(round(val, 2))
    return sorted(results, reverse=True)


# ---------------------------------------------------------------------------
# Table scanning helpers
# ---------------------------------------------------------------------------

def _scan_tables_for_figure(
    tables: list[dict[str, Any]],
    label_patterns: list[str],
) -> float | None:
    """
    Search the structured table list for a row whose first cell matches any of
    *label_patterns* and return the numeric value in a subsequent cell.
    """
    label_re = re.compile(
        "|".join(label_patterns), re.IGNORECASE
    )
    for table in tables:
        for row in table.get("rows", []):
            values = list(row.values())
            if not values:
                continue
            row_label = str(values[0])
            if label_re.search(row_label):
                # Walk through remaining cells looking for first non-empty number
                for cell in values[1:]:
                    cell_str = str(cell).strip()
                    # Strip common characters
                    cleaned = re.sub(r"[₹Rs.,\s]", "", cell_str)
                    try:
                        val = float(cleaned)
                        if val != 0:
                            return round(val, 2)
                    except ValueError:
                        continue
    return None


# ---------------------------------------------------------------------------
# FinancialExtractor
# ---------------------------------------------------------------------------

class FinancialExtractor:
    """
    Extract structured financial data from PDFParser output.

    Parameters
    ----------
    fx_usd_inr : float
        USD → INR exchange rate used to convert USD-denominated figures.
        Default 83.5.
    """

    def __init__(self, fx_usd_inr: float = 83.5) -> None:
        self.fx_usd_inr = fx_usd_inr
        # Recalculate USD multipliers with provided FX rate
        self._bn_multiplier = fx_usd_inr / 1e7   # 1 USD Bn → crores
        self._mn_multiplier = fx_usd_inr / 1e5   # 1 USD Mn → crores

    # ------------------------------------------------------------------
    # Public: main entry point
    # ------------------------------------------------------------------

    def extract(
        self,
        raw_text: str,
        tables: list[dict[str, Any]],
        doc_type: str = "",
    ) -> dict[str, Any]:
        """
        Full extraction pipeline.

        Parameters
        ----------
        raw_text : str
            Full text output from PDFParser.
        tables : list[dict]
            Tables output from PDFParser.
        doc_type : str
            PDFParser document classification (informational only).

        Returns
        -------
        dict with keys:
            figures, ratios, risk_clauses, directors, metadata
        """
        figures     = self.extract_key_figures(raw_text, tables)
        ratios      = self.extract_ratios(figures)
        risk_clauses = self.extract_risk_clauses(raw_text)
        directors   = self.extract_directors(raw_text)

        return {
            "figures":      figures,
            "ratios":       ratios,
            "risk_clauses": risk_clauses,
            "directors":    directors,
            "metadata": {
                "doc_type":       doc_type,
                "risk_clause_count": len(risk_clauses),
                "director_count":    len(directors),
                "figures_found":     sum(1 for v in figures.values() if v is not None),
                "ratios_computed":   sum(1 for v in ratios.values() if v is not None),
            },
        }

    # ------------------------------------------------------------------
    # 1. Key financial figures
    # ------------------------------------------------------------------

    def extract_key_figures(
        self,
        text: str,
        tables: list[dict[str, Any]] | None = None,
    ) -> dict[str, float | None]:
        """
        Extract key financial figures from *text* (and optionally *tables*).

        All values returned in **INR crores**.

        Returns
        -------
        dict with keys:
            revenue, ebitda, pat, total_debt, net_worth,
            interest_expense, debt_service,
            current_assets, current_liabilities
        """
        tables = tables or []

        def _get(pattern: re.Pattern, table_labels: list[str]) -> float | None:
            # 1) regex on raw text
            val = _first_match_crores(pattern, text)
            if val is not None:
                return val
            # 2) scan tables
            return _scan_tables_for_figure(tables, table_labels)

        # Also check "INR X Bn" forms for revenue / EBITDA (common in annual reports)
        revenue = _get(
            _PAT_REVENUE,
            ["revenue", "turnover", "net sales", "gross sales", "total income"],
        )
        if revenue is None:
            revenue = self._extract_inr_bn_form(text, "revenue|turnover|total income")

        ebitda = _get(
            _PAT_EBITDA,
            ["ebitda", "earnings before interest"],
        )
        if ebitda is None:
            ebitda = self._extract_inr_bn_form(text, r"ebitda")

        pat = _get(
            _PAT_PAT,
            ["profit after tax", "net profit", "profit for the year", "pat"],
        )

        total_debt = _get(
            _PAT_DEBT,
            ["total debt", "total borrowings", "borrowings"],
        )

        net_worth = _get(
            _PAT_NETWORTH,
            ["net worth", "networth", "shareholders equity",
             "shareholders funds", "stockholders equity"],
        )

        interest_expense = _get(
            _PAT_INTEREST,
            ["finance cost", "interest expense", "borrowing cost"],
        )

        debt_service = _get(
            _PAT_DEBT_SERVICE,
            ["debt service", "repayment of loans", "repayment of borrowings"],
        )

        current_assets = _get(
            _PAT_CURRENT_ASSETS,
            ["total current assets", "current assets"],
        )

        current_liabilities = _get(
            _PAT_CURRENT_LIAB,
            ["total current liabilities", "current liabilities",
             "current liabilities and provisions"],
        )

        figures = {
            "revenue":              revenue,
            "ebitda":               ebitda,
            "pat":                  pat,
            "total_debt":           total_debt,
            "net_worth":            net_worth,
            "interest_expense":     interest_expense,
            "debt_service":         debt_service,
            "current_assets":       current_assets,
            "current_liabilities":  current_liabilities,
        }

        found = sum(1 for v in figures.values() if v is not None)
        logger.info("extract_key_figures: %d / %d figures found.", found, len(figures))
        return figures

    def _extract_inr_bn_form(self, text: str, label_re: str) -> float | None:
        """
        Handle patterns like "revenue of INR 9.7 Bn" that appear in investor
        presentations and annual report summaries.

        Uses named groups so the group count of the label_re doesn't matter.
        """
        combined = re.compile(
            r"(?:" + label_re + r")"
            + r"[^₹\d\n]{0,80}?"
            + r"INR\s+(?P<inrbn_num>[\d,]+(?:\.\d+)?)\s+(?P<inrbn_unit>Bn|Billion|Mn|Million)\b",
            re.IGNORECASE | re.DOTALL,
        )
        for m in combined.finditer(text):
            raw_num  = m.group("inrbn_num")
            unit_str = m.group("inrbn_unit")
            val = self._inr_bn_to_crores(raw_num, unit_str)
            if val:
                return val
        return None

    def _inr_bn_to_crores(self, num_str: str, unit: str) -> float | None:
        try:
            v = _clean_number(num_str)
        except (ValueError, TypeError):
            return None
        u = unit.lower()
        if "bn" in u or "billion" in u:
            return round(v * _INR_BILLION, 2)
        if "mn" in u or "million" in u:
            return round(v * _INR_MILLION, 2)
        return None

    # ------------------------------------------------------------------
    # 2. Ratio calculation
    # ------------------------------------------------------------------

    def extract_ratios(
        self, figures: dict[str, float | None]
    ) -> dict[str, float | None]:
        """
        Compute standard credit ratios from *figures*.

        Returns None for a ratio when insufficient inputs are available.

        Ratios
        ------
        current_ratio       = current_assets / current_liabilities
        debt_to_equity      = total_debt / net_worth
        interest_coverage   = ebitda / interest_expense  (times)
        dscr                = ebitda / debt_service       (times)
                              (falls back to ebitda / (interest + est. principal))
        """
        def _safe_div(a: float | None, b: float | None) -> float | None:
            if a is None or b is None:
                return None
            if b == 0:
                return None
            return round(a / b, 4)

        current_ratio = _safe_div(
            figures.get("current_assets"),
            figures.get("current_liabilities"),
        )

        debt_to_equity = _safe_div(
            figures.get("total_debt"),
            figures.get("net_worth"),
        )

        interest_coverage = _safe_div(
            figures.get("ebitda"),
            figures.get("interest_expense"),
        )

        # DSCR: prefer explicit debt_service; fall back to interest alone
        dscr: float | None = None
        ebitda = figures.get("ebitda")
        ds     = figures.get("debt_service")
        if ebitda is not None and ds is not None and ds > 0:
            dscr = round(ebitda / ds, 4)
        elif ebitda is not None and figures.get("interest_expense"):
            # Rough DSCR approximation when only interest is known
            interest = figures["interest_expense"]
            dscr = round(ebitda / interest, 4)

        ratios = {
            "current_ratio":      current_ratio,
            "debt_to_equity":     debt_to_equity,
            "interest_coverage":  interest_coverage,
            "dscr":               dscr,
        }

        computed = sum(1 for v in ratios.values() if v is not None)
        logger.info("extract_ratios: %d / %d ratios computed.", computed, len(ratios))
        return ratios

    # ------------------------------------------------------------------
    # 3. Risk clause detection
    # ------------------------------------------------------------------

    def extract_risk_clauses(self, text: str) -> list[dict[str, Any]]:
        """
        Scan *text* for pre-defined risk phrases.

        Returns
        -------
        list of dicts, each with:
            clause_text          — the full sentence containing the match
            matched_phrase       — the exact substring that triggered the flag
            severity             — "HIGH" | "MEDIUM" | "LOW"
            page_number_estimate — estimated page (from [PAGE N] markers or
                                   character offset)
            context_snippet      — ±120 chars around the match
        """
        results: list[dict[str, Any]] = []

        # Build a page-offset mapping from [PAGE N] markers
        page_offsets = self._build_page_offsets(text)

        # Deduplicate: (phrase, page) pairs already emitted
        seen: set[tuple[str, int]] = set()

        for compiled_re, severity in _COMPILED_RISK:
            for m in compiled_re.finditer(text):
                matched_phrase = m.group(0)
                start          = m.start()
                page_est       = self._estimate_page(start, page_offsets)

                dedup_key = (matched_phrase.lower().strip(), page_est)
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                # Extract surrounding sentence (split on . ? ! or newlines)
                clause = self._extract_sentence(text, start)
                snippet_start = max(0, start - 120)
                snippet_end   = min(len(text), m.end() + 120)
                context       = text[snippet_start:snippet_end].replace("\n", " ")

                results.append({
                    "clause_text":           clause,
                    "matched_phrase":        matched_phrase,
                    "severity":              severity,
                    "page_number_estimate":  page_est,
                    "context_snippet":       context,
                })

        # Sort: HIGH first, then MEDIUM, LOW; then by page
        _sev_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        results.sort(key=lambda x: (_sev_order[x["severity"]], x["page_number_estimate"]))

        logger.info(
            "extract_risk_clauses: %d clause(s) found (%d HIGH, %d MEDIUM, %d LOW).",
            len(results),
            sum(1 for r in results if r["severity"] == "HIGH"),
            sum(1 for r in results if r["severity"] == "MEDIUM"),
            sum(1 for r in results if r["severity"] == "LOW"),
        )
        return results

    # ------------------------------------------------------------------
    # 4. Director / officer extraction
    # ------------------------------------------------------------------

    def extract_directors(self, text: str) -> list[dict[str, Any]]:
        """
        Identify names of directors and key officers from *text*.

        Detection strategy:
        1. Find all "Title Firstname Lastname" patterns.
        2. Keep only those that appear within a 300-character window of a
           recognised designation keyword.

        Returns
        -------
        list of dicts:
            name, title, designation, page_number_estimate
        """
        page_offsets = self._build_page_offsets(text)
        seen_names: dict[str, dict[str, Any]] = {}

        # Find all title+name occurrences
        for name_m in _TITLE_RE.finditer(text):
            full_match = name_m.group(0)
            name       = name_m.group(1).strip()
            title      = full_match.replace(name, "").strip()
            start      = name_m.start()

            # Search ±300 chars for a designation keyword
            window_start = max(0, start - 300)
            window_end   = min(len(text), name_m.end() + 300)
            window       = text[window_start:window_end]

            desig_match = _DESIG_RE.search(window)
            if desig_match is None:
                continue

            designation = desig_match.group(0).strip()
            page_est    = self._estimate_page(start, page_offsets)

            # If the same name appears multiple times with different designations,
            # prefer the more senior designation (lower index in the keyword list).
            if name in seen_names:
                existing_desig = seen_names[name]["designation"]
                existing_rank  = self._designation_rank(existing_desig)
                new_rank       = self._designation_rank(designation)
                if new_rank >= existing_rank:
                    continue

            seen_names[name] = {
                "name":                 name,
                "title":                title,
                "designation":          designation,
                "page_number_estimate": page_est,
            }

        directors = sorted(seen_names.values(), key=lambda x: x["page_number_estimate"])
        logger.info("extract_directors: %d director(s) / officer(s) found.", len(directors))
        return directors

    @staticmethod
    def _designation_rank(desig: str) -> int:
        """Lower rank = more senior. Used for deduplication."""
        _order = [
            "Managing Director", "CEO", "Chief Executive",
            "CFO", "Chief Financial",
            "COO", "Chief Operating",
            "CTO", "Chief Technology",
            "Whole", "Executive Director",
            "Non-Executive", "Independent",
            "Chairman", "Director",
            "Company Secretary", "CS",
        ]
        d = desig.upper()
        for i, keyword in enumerate(_order):
            if keyword.upper() in d:
                return i
        return 99

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_page_offsets(text: str) -> list[tuple[int, int]]:
        """
        Return a list of (char_offset, page_number) pairs extracted from
        the [PAGE N] markers inserted by PDFParser.
        Returns an empty list for texts without markers.
        """
        offsets: list[tuple[int, int]] = []
        for m in re.finditer(r"\[PAGE\s+(\d+)\]", text):
            offsets.append((m.start(), int(m.group(1))))
        return offsets

    @staticmethod
    def _estimate_page(
        char_offset: int,
        page_offsets: list[tuple[int, int]],
    ) -> int:
        """
        Estimate page number for a character at *char_offset*.

        Uses the [PAGE N] index when available; falls back to dividing by
        _CHARS_PER_PAGE.
        """
        if page_offsets:
            page = 1
            for off, pg in page_offsets:
                if off <= char_offset:
                    page = pg
                else:
                    break
            return page
        return max(1, math.ceil(char_offset / _CHARS_PER_PAGE))

    @staticmethod
    def _extract_sentence(text: str, match_start: int) -> str:
        """
        Return the sentence (or up to 300 chars) enclosing *match_start*.
        """
        # Search backwards for a sentence boundary
        boundary_re = re.compile(r"[.!?\n]")
        sent_start  = 0
        for m in boundary_re.finditer(text[:match_start][::-1]):
            sent_start = match_start - m.start()
            break

        # Search forwards for sentence end
        sent_end = len(text)
        for m in boundary_re.finditer(text[match_start:]):
            sent_end = match_start + m.end()
            break

        snippet = text[sent_start:sent_end].strip()
        if len(snippet) > 300:
            center = match_start - sent_start
            half   = 150
            lo     = max(0, center - half)
            hi     = min(len(snippet), center + half)
            snippet = ("…" if lo > 0 else "") + snippet[lo:hi] + ("…" if hi < len(snippet) else "")

        return re.sub(r"\s+", " ", snippet)


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

def extract_financials(
    raw_text: str,
    tables: list[dict[str, Any]],
    doc_type: str = "",
    fx_usd_inr: float = 83.5,
) -> dict[str, Any]:
    """
    One-shot helper: instantiate :class:`FinancialExtractor` and run on text.

    Returns the full structured extraction dict.
    """
    extractor = FinancialExtractor(fx_usd_inr=fx_usd_inr)
    return extractor.extract(raw_text, tables, doc_type=doc_type)


# ---------------------------------------------------------------------------
# Smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import sys
    import logging as _logging

    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    )

    # Optionally accept a JSON file produced by pdf_parser.py
    if len(sys.argv) >= 2:
        import pathlib
        src = pathlib.Path(sys.argv[1])
        data: dict[str, Any] = json.loads(src.read_text(encoding="utf-8"))
        raw_text = data.get("raw_text", "")
        tables   = data.get("tables", [])
        doc_type = data.get("doc_type", "")
    else:
        # Built-in minimal mock for quick validation
        raw_text = """
[PAGE 1]
Reliance Industries Limited — Integrated Annual Report 2023-24

Total Revenue from Operations: Rs. 9,01,532 Crores
EBITDA: Rs. 1,78,677 Crores
Profit After Tax (PAT): Rs. 79,020 Crores
Total Debt: Rs. 3,35,297 Crores
Net Worth: Rs. 7,58,000 Crores

Finance Costs (Interest Expense): Rs. 21,000 Crores
Total Current Assets: Rs. 2,50,000 Crores
Total Current Liabilities: Rs. 1,80,000 Crores

[PAGE 5]
Board of Directors
Mr. Mukesh D. Ambani — Chairman and Managing Director
Ms. Nita M. Ambani — Non-Executive Director
Shri Hital R. Meswani — Executive Director
Dr. Shumeet Banerji — Independent Director
Mr. Srikanth Venkatachari — Chief Financial Officer (CFO)

[PAGE 12]
The auditors have issued a qualified opinion regarding the valuation of
certain subsidiaries. There is going concern uncertainty noted in one
subsidiary. No overdue repayments as on the balance sheet date.

Revenue also reported as INR 9.0 Bn (alternate segment disclosure).
        """
        tables   = []
        doc_type = "ANNUAL_REPORT"

    result = extract_financials(raw_text, tables, doc_type=doc_type)
    print(json.dumps(result, indent=2, ensure_ascii=False))
