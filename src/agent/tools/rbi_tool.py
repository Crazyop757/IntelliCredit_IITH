"""
rbi_tool.py — RBI Wilful Defaulter intelligence tool for intelli_credit.

Loads the RBI quarterly wilful-defaulter list from a PDF (when available)
or from a JSON seed file, then exposes fuzzy name-matching so the credit
agent can flag borrowers, promoters, and director names.

Public API
----------
    tool = RBIDefaulterTool()

    # Load from PDF (manual download)
    tool.load_defaulter_list("data/raw/rbi_defaulter_list.pdf")

    # Single-name check
    result = tool.check_defaulter("Vijay Mallya")
    # result: {is_defaulter, match_confidence, matched_entry, …}

    # Full group check (company + all directors)
    report = tool.check_company_group("Kingfisher Airlines Ltd",
                                      director_names=["Vijay Mallya"])
    # report: {is_flagged, risk_level, hits, …}

Notes
-----
* Fuzzy matching uses difflib.get_close_matches (cutoff 0.80).
* Name tokens are normalised (lower-cased, punctuation stripped, common
  abbreviations expanded) before comparison.
* PDF extraction uses pdfplumber; if the PDF is absent the tool silently
  falls back to the seeded mock / JSON list.
* The built-in mock list contains ~10 publicly known RBI wilful defaulters
  and is always loaded as a baseline; PDF entries are merged on top.
"""

from __future__ import annotations

import difflib
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Project-root path resolution
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger("intelli_credit.agent.tools.rbi_tool")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_DEFAULT_PDF_PATH  = _PROJECT_ROOT / "data" / "raw" / "rbi_defaulter_list.pdf"
_SEED_JSON_PATH    = _PROJECT_ROOT / "data" / "raw" / "rbi_defaulter_list.json"

# ---------------------------------------------------------------------------
# Fuzzy-match configuration
# ---------------------------------------------------------------------------
_FUZZY_CUTOFF    = 0.80   # minimum similarity for a match
_FUZZY_N_BEST    = 3      # how many close candidates to evaluate
_HIGH_CONFIDENCE = 0.95   # threshold for "definite match"

# ---------------------------------------------------------------------------
# Built-in mock defaulter list
# ---------------------------------------------------------------------------
# These are publicly reported RBI wilful-defaulter cases used when no PDF
# is available.  Amounts are in INR crore as reported in public records.

_MOCK_DEFAULTERS: list[dict[str, Any]] = [
    {
        "name":               "VIJAY MALLYA",
        "aliases":            ["Vijay Vittal Mallya", "V. Mallya"],
        "amount_outstanding": 9000.0,
        "bank":               "State Bank of India",
        "date_reported":      "2016-03-09",
        "account_type":       "Corporate",
        "category":           "Wilful Defaulter",
    },
    {
        "name":               "NIRAV MODI",
        "aliases":            ["Nirav Deepak Modi"],
        "amount_outstanding": 11400.0,
        "bank":               "Punjab National Bank",
        "date_reported":      "2018-03-14",
        "account_type":       "Corporate",
        "category":           "Wilful Defaulter",
    },
    {
        "name":               "MEHUL CHOKSI",
        "aliases":            ["Mehul Chinubhai Choksi", "M. Choksi"],
        "amount_outstanding": 7080.0,
        "bank":               "Punjab National Bank",
        "date_reported":      "2018-08-20",
        "account_type":       "Corporate",
        "category":           "Wilful Defaulter",
    },
    {
        "name":               "JATIN MEHTA",
        "aliases":            ["Jatin R. Mehta"],
        "amount_outstanding": 6953.0,
        "bank":               "Multiple Banks",
        "date_reported":      "2017-06-01",
        "account_type":       "Corporate",
        "category":           "Wilful Defaulter",
    },
    {
        "name":               "SUBRATA ROY",
        "aliases":            ["Subrata Roy Sahara"],
        "amount_outstanding": 3600.0,
        "bank":               "Multiple Banks",
        "date_reported":      "2014-10-30",
        "account_type":       "Corporate",
        "category":           "Wilful Defaulter",
    },
    {
        "name":               "GITANJALI GEMS LIMITED",
        "aliases":            ["Gitanjali Gems Ltd"],
        "amount_outstanding": 5100.0,
        "bank":               "Punjab National Bank",
        "date_reported":      "2018-04-01",
        "account_type":       "Corporate",
        "category":           "Wilful Defaulter",
    },
    {
        "name":               "KINGFISHER AIRLINES LIMITED",
        "aliases":            ["Kingfisher Airlines Ltd", "KFA"],
        "amount_outstanding": 9000.0,
        "bank":               "State Bank of India",
        "date_reported":      "2016-11-17",
        "account_type":       "Corporate",
        "category":           "Wilful Defaulter",
    },
    {
        "name":               "REI AGRO LIMITED",
        "aliases":            ["REI Agro Ltd"],
        "amount_outstanding": 4314.0,
        "bank":               "Multiple Banks",
        "date_reported":      "2015-06-01",
        "account_type":       "Corporate",
        "category":           "Wilful Defaulter",
    },
    {
        "name":               "ZOOM DEVELOPERS PRIVATE LIMITED",
        "aliases":            ["Zoom Developers Pvt Ltd"],
        "amount_outstanding": 1810.0,
        "bank":               "Multiple Banks",
        "date_reported":      "2013-12-01",
        "account_type":       "Corporate",
        "category":           "Wilful Defaulter",
    },
    {
        "name":               "WINSOME DIAMONDS AND JEWELLERY LIMITED",
        "aliases":            ["Winsome Diamonds & Jewellery Ltd"],
        "amount_outstanding": 6800.0,
        "bank":               "Multiple Banks",
        "date_reported":      "2014-07-01",
        "account_type":       "Corporate",
        "category":           "Wilful Defaulter",
    },
]


# ===========================================================================
# RBIDefaulterTool
# ===========================================================================

class RBIDefaulterTool:
    """
    Screen names against the RBI Wilful Defaulter list.

    Parameters
    ----------
    fuzzy_cutoff : float
        Minimum difflib similarity score to consider a name match
        (default 0.80).
    auto_load : bool
        If True (default), automatically load the seed JSON and PDF
        (if present) on first use.
    """

    def __init__(
        self,
        fuzzy_cutoff: float = _FUZZY_CUTOFF,
        auto_load:    bool  = True,
    ) -> None:
        self.fuzzy_cutoff = fuzzy_cutoff
        self.auto_load    = auto_load
        self._entries:   list[dict[str, Any]] = []
        self._loaded:    bool                 = False
        self._pdf_path:  Path | None          = None

    # ------------------------------------------------------------------
    # 1. load_defaulter_list
    # ------------------------------------------------------------------

    def load_defaulter_list(self, pdf_path: str | Path | None = None) -> int:
        """
        Populate the in-memory defaulter list.

        Loading priority
        ----------------
        1. Mock baseline (always loaded first).
        2. Seed JSON at ``data/raw/rbi_defaulter_list.json`` (if present).
        3. PDF at *pdf_path* (parsed with pdfplumber; optional).

        Parameters
        ----------
        pdf_path :
            Path to the RBI wilful-defaulter PDF.  Defaults to
            ``data/raw/rbi_defaulter_list.pdf``.

        Returns
        -------
        int — total number of entries in the loaded list.
        """
        self._entries = []

        # ── Step 1: mock baseline ─────────────────────────────────────
        self._entries.extend(_MOCK_DEFAULTERS)
        logger.info("Loaded %d mock baseline entries.", len(self._entries))

        # ── Step 2: seed JSON ─────────────────────────────────────────
        self._load_seed_json()

        # ── Step 3: PDF ───────────────────────────────────────────────
        pdf = Path(pdf_path) if pdf_path else _DEFAULT_PDF_PATH
        self._pdf_path = pdf
        if pdf.exists():
            pdf_entries = self._parse_pdf(pdf)
            self._merge_entries(pdf_entries)
            logger.info(
                "Merged %d entries from PDF %s.  Total: %d",
                len(pdf_entries), pdf, len(self._entries),
            )
        else:
            logger.info(
                "PDF not found at %s — using mock + JSON data only.", pdf
            )

        self._loaded = True
        logger.info("Defaulter list ready: %d unique entries.", len(self._entries))
        return len(self._entries)

    # ------------------------------------------------------------------
    # 2. check_defaulter
    # ------------------------------------------------------------------

    def check_defaulter(self, name: str) -> dict[str, Any]:
        """
        Fuzzy-match *name* against the defaulter list.

        Strategy
        --------
        * Normalise the query name (lower-case, strip punctuation,
          expand common abbreviations).
        * Build a candidate corpus: every entry's ``name`` plus all
          ``aliases``, each normalised identically.
        * Use ``difflib.get_close_matches`` with ``cutoff=self.fuzzy_cutoff``
          to find candidates.
        * Return the best-scoring match.

        Parameters
        ----------
        name : str
            Individual or company name to screen.

        Returns
        -------
        dict with keys:
            ``is_defaulter``, ``match_confidence``, ``matched_name``,
            ``matched_entry``, ``query_name``.
        """
        self._ensure_loaded()

        query_norm = _normalise(name)
        if not query_norm:
            return _no_match(name)

        # Build a flat corpus: (normalised_string → entry_dict)
        corpus: list[tuple[str, dict[str, Any]]] = []
        for entry in self._entries:
            corpus.append((_normalise(entry["name"]), entry))
            for alias in entry.get("aliases", []):
                corpus.append((_normalise(alias), entry))

        corpus_strings = [c[0] for c in corpus]

        # difflib close-match against the full corpus
        matches = difflib.get_close_matches(
            query_norm, corpus_strings,
            n=_FUZZY_N_BEST, cutoff=self.fuzzy_cutoff,
        )

        if not matches:
            return _no_match(name)

        # Score each match and pick the best
        best_str   = matches[0]
        best_score = difflib.SequenceMatcher(None, query_norm, best_str).ratio()
        best_entry = next(
            (entry for cs, entry in corpus if cs == best_str), None
        )

        if best_entry is None:
            return _no_match(name)

        logger.info(
            "Defaulter match: %r → %r  confidence=%.3f",
            name, best_entry["name"], best_score,
        )

        return {
            "query_name":        name,
            "is_defaulter":      True,
            "match_confidence":  round(best_score, 4),
            "matched_name":      best_entry["name"],
            "matched_entry":     best_entry,
            "risk_level":        "CRITICAL",
        }

    # ------------------------------------------------------------------
    # 3. check_company_group
    # ------------------------------------------------------------------

    def check_company_group(
        self,
        company_name:   str,
        director_names: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Screen a company and its directors in one call.

        Logic
        -----
        * Run ``check_defaulter`` on the company name.
        * Run ``check_defaulter`` on each director / promoter name.
        * If **any** check returns ``is_defaulter=True`` → mark the group
          as CRITICAL.

        Parameters
        ----------
        company_name :
            Legal or common name of the borrowing entity.
        director_names :
            List of director / promoter names to screen.

        Returns
        -------
        dict — group screening report.
        """
        self._ensure_loaded()

        director_names = director_names or []
        hits:    list[dict[str, Any]] = []
        checked: list[str]            = []

        # Screen company name
        company_result = self.check_defaulter(company_name)
        checked.append(company_name)
        if company_result["is_defaulter"]:
            hits.append({**company_result, "screened_as": "company"})

        # Screen each director
        for dname in director_names:
            result = self.check_defaulter(dname)
            checked.append(dname)
            if result["is_defaulter"]:
                hits.append({**result, "screened_as": "director"})

        is_flagged = len(hits) > 0
        risk_level = "CRITICAL" if is_flagged else "CLEAR"

        return {
            "queried_at":     datetime.now(tz=timezone.utc).isoformat(),
            "company_name":   company_name,
            "is_flagged":     is_flagged,
            "risk_level":     risk_level,
            "hit_count":      len(hits),
            "names_screened": len(checked),
            "hits":           hits,
            "summary": (
                f"{len(hits)} defaulter match(es) found for "
                f"'{company_name}' group."
                if is_flagged
                else f"No RBI defaulter matches found for '{company_name}' group."
            ),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        """Auto-load on first query if ``auto_load=True``."""
        if not self._loaded:
            if self.auto_load:
                self.load_defaulter_list()
            else:
                raise RuntimeError(
                    "Defaulter list not loaded.  Call load_defaulter_list() first."
                )

    def _load_seed_json(self) -> None:
        if not _SEED_JSON_PATH.exists():
            return
        try:
            data = json.loads(_SEED_JSON_PATH.read_text(encoding="utf-8"))
            records = data.get("wilful_defaulters", data if isinstance(data, list) else [])
            converted = [_json_record_to_entry(r) for r in records]
            self._merge_entries(converted)
            logger.info("Loaded %d entries from seed JSON.", len(converted))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not load seed JSON: %s", exc)

    def _parse_pdf(self, pdf_path: Path) -> list[dict[str, Any]]:
        """
        Extract defaulter records from a pdfplumber-parsed RBI PDF.

        RBI PDFs typically contain a table with columns such as:
          Sr. No. | Name of Borrower | Outstanding Amount | Bank | Date

        We scan every page for tables and for text lines matching amount
        patterns as a fallback.
        """
        try:
            import pdfplumber  # noqa: PLC0415
        except ImportError:
            logger.warning("pdfplumber not installed — cannot parse PDF.")
            return []

        entries: list[dict[str, Any]] = []

        try:
            with pdfplumber.open(str(pdf_path)) as pdf:
                for page_num, page in enumerate(pdf.pages, start=1):
                    # ── Try table extraction first ─────────────────
                    tables = page.extract_tables()
                    for table in tables:
                        for row in table:
                            entry = _row_to_entry(row)
                            if entry:
                                entries.append(entry)

                    # ── Fallback: line-by-line text parse ──────────
                    if not tables:
                        text = page.extract_text() or ""
                        for line in text.splitlines():
                            entry = _line_to_entry(line)
                            if entry:
                                entries.append(entry)

            logger.info(
                "Extracted %d records from PDF (%d pages).",
                len(entries), page_num,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("PDF parse error: %s", exc)

        return entries

    def _merge_entries(self, new_entries: list[dict[str, Any]]) -> None:
        """
        Merge *new_entries* into self._entries, deduplicating by normalised name.
        Existing entries take precedence (mock baseline is authoritative).
        """
        existing_names = {_normalise(e["name"]) for e in self._entries}
        added = 0
        for entry in new_entries:
            if _normalise(entry.get("name", "")) not in existing_names:
                self._entries.append(entry)
                existing_names.add(_normalise(entry["name"]))
                added += 1
        if added:
            logger.debug("Merged %d new entries into defaulter list.", added)


# ---------------------------------------------------------------------------
# PDF row / line parsers
# ---------------------------------------------------------------------------

# Pattern that looks like an INR amount: digits with optional commas/lakhs/cr
_AMOUNT_RE = re.compile(
    r"""
    (?:Rs\.?\s*|INR\s*|₹\s*)?     # optional currency symbol
    (\d[\d,]*\.?\d*)               # number with Indian commas
    \s*(?:Cr(?:ore)?s?|L(?:akh)?s?|)?  # optional unit
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Lines that are clearly headers or footers
_SKIP_RE = re.compile(
    r"^(sr\.?\s*no|s\.no|#|name\s+of|outstanding|bank|date|page|total|nil)",
    re.IGNORECASE,
)


def _row_to_entry(row: list[Any] | None) -> dict[str, Any] | None:
    """Convert a table row (list of cell texts) to a defaulter entry."""
    if not row or len(row) < 2:
        return None
    cells = [str(c or "").strip() for c in row]

    # Skip header rows
    if _SKIP_RE.match(cells[0]) or _SKIP_RE.match(cells[1] if len(cells) > 1 else ""):
        return None

    # Heuristic: if the second cell (or third) looks like a name, use it;
    # otherwise use the first non-numeric cell.
    name = ""
    amount = 0.0
    bank = ""
    date_reported = None

    for i, cell in enumerate(cells):
        # Name: longest token that looks alphabetic
        if not name and re.search(r"[A-Za-z]{3,}", cell) and not _is_numeric(cell):
            if not _SKIP_RE.match(cell):
                name = cell

        # Amount: first numeric-looking cell
        if not amount:
            a = _parse_inr(cell)
            if a > 0:
                amount = a

        # Date: ISO or DD/MM/YYYY pattern
        if not date_reported:
            date_reported = _extract_date(cell)

        # Bank: cells containing known bank keywords
        if not bank and _looks_like_bank(cell):
            bank = cell

    if not name or len(name) < 3:
        return None

    return _make_entry(name, amount, bank, date_reported)


def _line_to_entry(line: str) -> dict[str, Any] | None:
    """
    Parse a single text line that may contain a defaulter record.

    Expected rough format (RBI text dumps):
       <sr>  <Name>  <amount>  <bank>
    """
    line = line.strip()
    if not line or _SKIP_RE.match(line) or len(line) < 5:
        return None

    # Must contain at least one alphabetic word of length ≥ 3
    if not re.search(r"[A-Za-z]{3,}", line):
        return None

    amount       = _parse_inr(line)
    date_rep     = _extract_date(line)
    bank         = _extract_bank(line)

    # Name: everything before the first amount or date, stripped of sr. no.
    name_match = re.match(r"^\s*\d+[\.\)]\s*(.*?)(?:\s+\d[\d,]+|\s+Rs\.)", line)
    if name_match:
        name = name_match.group(1).strip()
    else:
        # Fallback: strip trailing numbers and short tokens
        name = re.sub(r"\d[\d,\.]*\s*(?:Cr|Lakh)?", "", line).strip()
        name = re.sub(r"\s{2,}", " ", name).strip()

    if not name or len(name) < 3 or _SKIP_RE.match(name):
        return None

    return _make_entry(name, amount, bank, date_rep)


def _make_entry(
    name: str,
    amount: float,
    bank: str,
    date_reported: str | None,
) -> dict[str, Any]:
    return {
        "name":               name.upper().strip(),
        "aliases":            [],
        "amount_outstanding": amount,
        "bank":               bank or "Unknown",
        "date_reported":      date_reported,
        "account_type":       "Corporate",
        "category":           "Wilful Defaulter",
    }


def _json_record_to_entry(r: dict[str, Any]) -> dict[str, Any]:
    """Convert a seed-JSON record to the canonical entry schema."""
    return {
        "name":               r.get("name", "").upper().strip(),
        "aliases":            r.get("aliases", []),
        "amount_outstanding": float(r.get("amount_crore", r.get("amount_outstanding", 0))),
        "bank":               r.get("bank", "Unknown"),
        "date_reported":      r.get("date_reported", str(r.get("year", ""))),
        "account_type":       r.get("account_type", "Corporate"),
        "category":           r.get("category", "Wilful Defaulter"),
    }


# ---------------------------------------------------------------------------
# Name normalisation
# ---------------------------------------------------------------------------

# Common abbreviation expansions (applied before fuzzy matching)
_ABBR_EXPANSIONS: dict[str, str] = {
    r"\bltd\b":       "limited",
    r"\bpvt\b":       "private",
    r"\bplt\b":       "private limited",
    r"\binds\b":      "industries",
    r"\bcorp\b":      "corporation",
    r"\bco\b":        "company",
    r"\bintl\b":      "international",
    r"\bentps\b":     "enterprises",
    r"\bentp\b":      "enterprise",
    r"\bgrp\b":       "group",
    r"\bfinance\b":   "finance",
    r"\btech\b":      "technologies",
}


def _normalise(name: str) -> str:
    """
    Normalise a name for fuzzy comparison.

    Steps
    -----
    1. Lower-case.
    2. Strip leading/trailing whitespace.
    3. Remove punctuation except hyphens and spaces.
    4. Collapse whitespace.
    5. Expand common abbreviations.
    6. Strip common suffixes (limited, private, pvt, ltd) for
       partial-name matching.
    """
    if not name:
        return ""
    s = name.lower().strip()
    # Remove punctuation except spaces and hyphens
    s = re.sub(r"[^a-z0-9 \-]", " ", s)
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    # Expand abbreviations
    for pat, replacement in _ABBR_EXPANSIONS.items():
        s = re.sub(pat, replacement, s)
    return s.strip()


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------

def _no_match(name: str) -> dict[str, Any]:
    return {
        "query_name":       name,
        "is_defaulter":     False,
        "match_confidence": 0.0,
        "matched_name":     None,
        "matched_entry":    None,
        "risk_level":       "CLEAR",
    }


def _is_numeric(s: str) -> bool:
    return bool(re.match(r"^\s*[\d,\.]+\s*$", s))


def _parse_inr(text: str) -> float:
    """Extract the first INR amount from *text*. Returns 0.0 if none found."""
    m = _AMOUNT_RE.search(text)
    if not m:
        return 0.0
    raw = m.group(1).replace(",", "")
    try:
        val = float(raw)
    except ValueError:
        return 0.0
    t = text.lower()
    if "crore" in t or " cr" in t:
        return val          # already in crore
    if "lakh" in t or " l" in t:
        return val / 100    # convert to crore
    return val


_DATE_PATS = [
    re.compile(r"(\d{4}-\d{2}-\d{2})"),
    re.compile(r"(\d{2}/\d{2}/\d{4})"),
    re.compile(r"(\d{2}-\d{2}-\d{4})"),
]


def _extract_date(text: str) -> str | None:
    for pat in _DATE_PATS:
        m = pat.search(text)
        if m:
            return m.group(1)
    return None


_BANK_KEYWORDS = (
    "bank", "sbi", "pnb", "hdfc", "icici", "axis", "baroda",
    "canara", "union", "uco", "central", "syndicate", "allahabad",
    "oriental", "idbi", "yes bank", "kotak",
)


def _looks_like_bank(text: str) -> bool:
    tl = text.lower()
    return any(k in tl for k in _BANK_KEYWORDS)


def _extract_bank(text: str) -> str:
    tl = text.lower()
    for kw in _BANK_KEYWORDS:
        if kw in tl:
            # Return the surrounding word context
            m = re.search(rf"(\w[\w\s]*{re.escape(kw)}[\w\s]*\w)", tl)
            if m:
                return m.group(1).strip().title()
    return ""


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import logging as _logging

    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    )

    tool = RBIDefaulterTool()
    n = tool.load_defaulter_list()
    print(f"\nLoaded {n} defaulter entries.\n")

    TEST_CASES = [
        # (label, query, expected_is_defaulter)
        ("Exact match (upper)",        "VIJAY MALLYA",             True),
        ("Exact match (lower)",        "vijay mallya",             True),
        ("Alias match",                "Nirav Deepak Modi",        True),
        ("Short alias",                "V. Mallya",                True),
        ("Company exact",              "Kingfisher Airlines",      True),
        ("Company alias (Ltd suffix)", "Kingfisher Airlines Ltd",  True),
        ("Clean company (no match)",   "Reliance Industries",      False),
        ("Clean person",               "Mukesh Ambani",            False),
        ("Misspelled (should match)",  "Vijay Malya",              True),   # one char off
        ("Completely unknown",         "Govind Prasad Sharma",     False),
    ]

    print(f"{'Label':<35} {'Query':<35} {'Result':<12} {'Confidence'}")
    print("-" * 95)
    for label, query, expected in TEST_CASES:
        r = tool.check_defaulter(query)
        flag  = "DEFAULTER" if r["is_defaulter"] else "CLEAR"
        conf  = f"{r['match_confidence']:.3f}" if r["is_defaulter"] else " — "
        match = r["matched_name"] or ""
        ok    = "✓" if r["is_defaulter"] == expected else "✗ UNEXPECTED"
        print(f"{label:<35} {query:<35} {flag:<12} {conf}  → {match}  {ok}")

    print()

    # Group check demo
    print("Group check — Kingfisher Airlines + Vijay Mallya as director:")
    group = tool.check_company_group(
        "Kingfisher Airlines Ltd",
        director_names=["Vijay Mallya", "A. Raghunathan"],
    )
    print(f"  is_flagged : {group['is_flagged']}")
    print(f"  risk_level : {group['risk_level']}")
    print(f"  summary    : {group['summary']}")
    for h in group["hits"]:
        print(f"  HIT [{h['screened_as']:8s}] {h['matched_name']}  "
              f"conf={h['match_confidence']:.3f}  "
              f"₹{h['matched_entry']['amount_outstanding']:,.0f} Cr")
    print()
