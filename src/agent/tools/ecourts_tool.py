"""
ecourts_tool.py — eCourts litigation intelligence tool for intelli_credit.

Queries the Indian eCourts portal (https://ecourts.gov.in/) by party name,
parses the case list, classifies each case by severity, and computes an
aggregated litigation risk score.

Public API
----------
    tool = ECourtsTool()
    report = tool.search_cases("Tata Steel Limited", state="Maharashtra")
    # report: {cases, litigation_risk_score, nclt_override, severity_breakdown, …}

Notes
-----
* eCourts uses a CSRF-token + session-cookie flow.  This tool mimics a
  browser session to obtain the token before POSTing.
* If the portal returns 503 / blocks the request after retries, the tool
  transparently falls back to a built-in mock dataset so downstream code
  always receives a well-formed response.
* A 2-second sleep is inserted between every HTTP request to avoid
  triggering rate-limit defences.
"""

from __future__ import annotations

import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Project-root path resolution
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger("intelli_credit.agent.tools.ecourts_tool")

# ---------------------------------------------------------------------------
# HTTP constants
# ---------------------------------------------------------------------------
_BASE_URL          = "https://ecourts.gov.in/ecourts_home/"
_SEARCH_ENDPOINT   = "https://ecourts.gov.in/ecourts_home/index.php"
_REQUEST_DELAY_SEC = 2          # polite inter-request delay
_MAX_RETRIES       = 2
_TIMEOUT_SEC       = 15

# Browser-like headers to reduce bot-detection risk
_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Content-Type":    "application/x-www-form-urlencoded",
    "Origin":          "https://ecourts.gov.in",
    "Referer":         _BASE_URL,
    "Connection":      "keep-alive",
    "DNT":             "1",
}

# ---------------------------------------------------------------------------
# Severity classification
# ---------------------------------------------------------------------------

# Maps substrings (lower-cased) found in case_type to severity
_SEVERITY_MAP: list[tuple[str, str]] = [
    # CRITICAL
    ("insolvency",              "CRITICAL"),
    ("nclt",                    "CRITICAL"),
    ("national company law",    "CRITICAL"),
    ("winding up",              "CRITICAL"),
    ("sarfaesi",                "CRITICAL"),
    ("criminal",                "CRITICAL"),
    ("ipc",                     "CRITICAL"),
    ("crpc",                    "CRITICAL"),
    ("prevention of corruption","CRITICAL"),
    ("pmla",                    "CRITICAL"),
    ("money laundering",        "CRITICAL"),
    ("fraud",                   "CRITICAL"),
    # HIGH
    ("ni act",                  "HIGH"),
    ("negotiable instruments",  "HIGH"),
    ("138",                     "HIGH"),     # S.138 NI Act cheque bounce
    ("cheque",                  "HIGH"),
    ("recovery",                "HIGH"),     # may be refined by amount below
    ("debt recovery",           "HIGH"),
    ("drt",                     "HIGH"),
    ("arbitration",             "HIGH"),
    # MEDIUM
    ("civil suit",              "MEDIUM"),
    ("civil appeal",            "MEDIUM"),
    ("civil misc",              "MEDIUM"),
    ("injunction",              "MEDIUM"),
    ("specific performance",    "MEDIUM"),
    ("writ petition",           "MEDIUM"),
    # LOW
    ("consumer",                "LOW"),
    ("labour",                  "LOW"),
    ("service",                 "LOW"),
    ("rent",                    "LOW"),
    ("property",                "LOW"),
]

# Severity weights for risk scoring
_SEVERITY_WEIGHT: dict[str, float] = {
    "CRITICAL": 3.0,
    "HIGH":     2.0,
    "MEDIUM":   1.0,
    "LOW":      0.5,
}

# ---------------------------------------------------------------------------
# Mock / fallback data
# ---------------------------------------------------------------------------
# Returned when eCourts is unreachable so downstream code can always proceed.

_MOCK_CASES: dict[str, list[dict[str, Any]]] = {
    "__default__": [
        {
            "case_number":      "CP(IB)/123/MB/2023",
            "court_name":       "National Company Law Tribunal, Mumbai",
            "filing_date":      "2023-06-15",
            "case_type":        "NCLT – Insolvency and Bankruptcy",
            "party_names":      ["Sample Corp Ltd", "Creditor Bank"],
            "case_status":      "pending",
            "next_hearing_date": "2026-04-10",
            "_mock":            True,
        },
        {
            "case_number":      "CC/4521/2022",
            "court_name":       "Metropolitan Magistrate Court, Mumbai",
            "filing_date":      "2022-11-20",
            "case_type":        "NI Act S.138 – Cheque Dishonour",
            "party_names":      ["Sample Corp Ltd", "Vendor X Pvt Ltd"],
            "case_status":      "pending",
            "next_hearing_date": "2026-03-28",
            "_mock":            True,
        },
        {
            "case_number":      "CS/1045/2021",
            "court_name":       "Bombay High Court",
            "filing_date":      "2021-03-05",
            "case_type":        "Civil Recovery",
            "party_names":      ["Sample Corp Ltd", "Supplier Z Ltd"],
            "case_status":      "decided",
            "next_hearing_date": None,
            "_mock":            True,
        },
    ],
    # Specific company overrides can be added here keyed by lower-cased name
    "tata steel limited": [],   # clean company — no litigation
}


# ===========================================================================
# ECourtsTool
# ===========================================================================

class ECourtsTool:
    """
    Scrape the eCourts portal for litigation records and compute a risk score.

    Parameters
    ----------
    request_delay : float
        Seconds to sleep between HTTP requests (default 2).
    timeout : int
        HTTP request timeout in seconds (default 15).
    use_mock_on_block : bool
        When True (default), fall back to mock data if the portal is
        unreachable or returns 503.
    """

    def __init__(
        self,
        request_delay:     float = _REQUEST_DELAY_SEC,
        timeout:           int   = _TIMEOUT_SEC,
        use_mock_on_block: bool  = True,
    ) -> None:
        self.request_delay     = request_delay
        self.timeout           = timeout
        self.use_mock_on_block = use_mock_on_block
        self._session          = None   # lazily created requests.Session

    # ------------------------------------------------------------------
    # Public API — search_cases
    # ------------------------------------------------------------------

    def search_cases(
        self,
        party_name: str,
        state:      str | None = None,
    ) -> dict[str, Any]:
        """
        Search eCourts for all cases involving *party_name*.

        Steps
        -----
        1. Open a browser-like session and fetch the search page to obtain
           a CSRF token / session cookie.
        2. POST to the search endpoint with party-name search mode.
        3. Parse the HTML response table with BeautifulSoup.
        4. For each extracted case, classify severity and tag status.
        5. Compute the litigation risk score.
        6. Return a complete litigation intelligence report.

        Fallback
        --------
        If the portal is blocked / unreachable (after ``_MAX_RETRIES``
        attempts), mock data is returned and flagged with
        ``"data_source": "mock"``.

        Parameters
        ----------
        party_name :
            Full or partial company / promoter name.
        state :
            Optional Indian state name to narrow the search
            (e.g. ``"Maharashtra"``).  Passed as the ``state_code`` POST
            field when provided.

        Returns
        -------
        dict — full litigation intelligence report.
        """
        logger.info("eCourts search: party_name=%r state=%r", party_name, state)

        cases, data_source = self._fetch_cases(party_name, state)

        cases = [self._enrich_case(c) for c in cases]

        risk_score, severity_breakdown, nclt_override = (
            self.compute_litigation_risk_score(cases)
        )

        return self._build_report(
            party_name        = party_name,
            state             = state,
            cases             = cases,
            risk_score        = risk_score,
            severity_breakdown = severity_breakdown,
            nclt_override     = nclt_override,
            data_source       = data_source,
        )

    # ------------------------------------------------------------------
    # Step 2: classify_case_severity
    # ------------------------------------------------------------------

    @staticmethod
    def classify_case_severity(case_type: str) -> str:
        """
        Map a case-type string to one of: ``CRITICAL``, ``HIGH``,
        ``MEDIUM``, ``LOW``.

        Rules (in priority order)
        -------------------------
        * NCLT / Insolvency / IBC / Winding-up      → CRITICAL
        * Criminal / IPC / PMLA / Money-laundering   → CRITICAL
        * SARFAESI                                   → CRITICAL
        * NI Act S.138 (cheque bounce)               → HIGH
        * Debt Recovery / DRT / Arbitration          → HIGH
        * Civil Recovery (generic)                   → HIGH
        * Civil Suit / Writ / Injunction             → MEDIUM
        * Consumer / Labour / Property               → LOW
        * Unrecognised                               → MEDIUM  (conservative)
        """
        needle = case_type.lower()
        for keyword, severity in _SEVERITY_MAP:
            if keyword in needle:
                return severity
        return "MEDIUM"     # conservative default for unknown types

    # ------------------------------------------------------------------
    # Step 3: compute_litigation_risk_score
    # ------------------------------------------------------------------

    @staticmethod
    def compute_litigation_risk_score(
        cases: list[dict[str, Any]],
    ) -> tuple[float, dict[str, int], bool]:
        """
        Calculate a weighted litigation risk score capped at 10.

        Weights
        -------
        CRITICAL  × 3.0
        HIGH      × 2.0
        MEDIUM    × 1.0
        LOW       × 0.5

        NCLT override
        -------------
        If ANY case is ``CRITICAL`` **and** the case type contains
        ``"nclt"`` or ``"insolvency"``, ``nclt_override`` is set to
        ``True``, which should trigger an automatic ``HIGH_RISK`` flag
        in the downstream EWS engine regardless of the numeric score.

        Returns
        -------
        (risk_score: float, severity_breakdown: dict, nclt_override: bool)
        """
        severity_breakdown: dict[str, int] = {
            "CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0,
        }
        raw_score   = 0.0
        nclt_override = False

        for case in cases:
            sev = case.get("severity", "MEDIUM")
            severity_breakdown[sev] = severity_breakdown.get(sev, 0) + 1
            raw_score += _SEVERITY_WEIGHT.get(sev, 1.0)

            # NCLT override check
            ct = case.get("case_type", "").lower()
            if sev == "CRITICAL" and ("nclt" in ct or "insolvency" in ct):
                nclt_override = True

        risk_score = round(min(raw_score, 10.0), 2)
        return risk_score, severity_breakdown, nclt_override

    # ------------------------------------------------------------------
    # Internal: fetch from portal or fall back to mock
    # ------------------------------------------------------------------

    def _fetch_cases(
        self,
        party_name: str,
        state:      str | None,
    ) -> tuple[list[dict[str, Any]], str]:
        """
        Attempt to scrape eCourts.  Returns ``(cases, data_source)`` where
        ``data_source`` is ``"live"`` or ``"mock"``.
        """
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                cases = self._scrape_ecourts(party_name, state)
                return cases, "live"
            except _ECourtsBocked:
                logger.warning(
                    "eCourts blocked / 503 on attempt %d/%d — retrying after delay.",
                    attempt, _MAX_RETRIES,
                )
                time.sleep(self.request_delay * 2)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "eCourts scrape attempt %d/%d failed: %s",
                    attempt, _MAX_RETRIES, exc,
                )
                time.sleep(self.request_delay)

        # All retries exhausted
        if self.use_mock_on_block:
            logger.info(
                "Falling back to mock data for party_name=%r.", party_name
            )
            mock = self._get_mock_cases(party_name)
            return mock, "mock"

        return [], "failed"

    def _scrape_ecourts(
        self,
        party_name: str,
        state:      str | None,
    ) -> list[dict[str, Any]]:
        """
        Perform the actual HTTP session against eCourts.

        Flow
        ----
        1. GET the home page → capture session cookie + CSRF token
        2. Sleep (polite delay)
        3. POST party-name search → parse HTML table
        """
        import requests  # noqa: PLC0415
        from bs4 import BeautifulSoup  # noqa: PLC0415

        session = self._get_session()

        # ── Step 1: GET home page for session cookie + CSRF token ─────
        logger.debug("GET %s", _BASE_URL)
        resp = session.get(_BASE_URL, timeout=self.timeout, headers=_HEADERS)
        _check_response(resp)
        time.sleep(self.request_delay)

        csrf_token = _extract_csrf_token(resp.text)
        logger.debug("CSRF token: %s", csrf_token)

        # ── Step 2: POST party-name search ────────────────────────────
        payload: dict[str, str] = {
            "stype":        "3",        # 3 = Party Name search
            "search_party_name": party_name,
            "fcourt_type":  "0",        # all court types
        }
        if state:
            payload["state_code"] = _state_name_to_code(state)
        if csrf_token:
            payload["csrf_token"] = csrf_token
            payload["_token"]     = csrf_token  # some versions use this key

        logger.debug("POST %s  payload=%r", _SEARCH_ENDPOINT, payload)
        resp2 = session.post(
            _SEARCH_ENDPOINT,
            data=payload,
            timeout=self.timeout,
            headers=_HEADERS,
        )
        _check_response(resp2)
        time.sleep(self.request_delay)

        # ── Step 3: Parse HTML ────────────────────────────────────────
        soup = BeautifulSoup(resp2.text, "html.parser")
        return _parse_case_table(soup)

    # ------------------------------------------------------------------
    # Case enrichment
    # ------------------------------------------------------------------

    def _enrich_case(self, case: dict[str, Any]) -> dict[str, Any]:
        """Attach ``severity`` field to a raw case dict."""
        case["severity"] = self.classify_case_severity(
            case.get("case_type", "")
        )
        return case

    # ------------------------------------------------------------------
    # Report assembly
    # ------------------------------------------------------------------

    @staticmethod
    def _build_report(
        party_name:        str,
        state:             str | None,
        cases:             list[dict[str, Any]],
        risk_score:        float,
        severity_breakdown: dict[str, int],
        nclt_override:     bool,
        data_source:       str,
    ) -> dict[str, Any]:
        pending_cases = [c for c in cases if c.get("case_status") == "pending"]
        decided_cases = [c for c in cases if c.get("case_status") == "decided"]
        critical_cases = [c for c in cases if c.get("severity") == "CRITICAL"]

        return {
            # ── Identity ──────────────────────────────────────────────
            "party_name":         party_name,
            "state_filter":       state,
            "queried_at":         datetime.now(tz=timezone.utc).isoformat(),
            "data_source":        data_source,   # "live" | "mock" | "failed"

            # ── Risk output ───────────────────────────────────────────
            "litigation_risk_score": risk_score,       # 0–10
            "nclt_override":         nclt_override,    # auto HIGH_RISK if True
            "severity_breakdown":    severity_breakdown,

            # ── Case statistics ───────────────────────────────────────
            "total_cases":         len(cases),
            "pending_cases":       len(pending_cases),
            "decided_cases":       len(decided_cases),
            "critical_case_count": len(critical_cases),

            # ── Case detail ───────────────────────────────────────────
            "critical_cases":      critical_cases,
            "cases":               cases,
        }

    # ------------------------------------------------------------------
    # Mock data lookup
    # ------------------------------------------------------------------

    @staticmethod
    def _get_mock_cases(party_name: str) -> list[dict[str, Any]]:
        key = party_name.lower().strip()
        if key in _MOCK_CASES:
            return list(_MOCK_CASES[key])
        return list(_MOCK_CASES["__default__"])

    # ------------------------------------------------------------------
    # requests.Session
    # ------------------------------------------------------------------

    def _get_session(self):  # type: ignore[return]
        """Create (or reuse) a requests.Session with browser-like headers."""
        if self._session is None:
            import requests  # noqa: PLC0415
            s = requests.Session()
            s.headers.update(_HEADERS)
            self._session = s
        return self._session


# ---------------------------------------------------------------------------
# HTML parsing helpers
# ---------------------------------------------------------------------------

def _parse_case_table(soup: Any) -> list[dict[str, Any]]:
    """
    Extract case rows from the eCourts search-result HTML.

    eCourts renders results in a ``<table>`` with id ``resultTable`` or
    class ``case_details``.  Falls back to scanning all tables for rows
    that look like case data.
    """
    cases: list[dict[str, Any]] = []

    # Try the known table ids / classes first
    table = (
        soup.find("table", id="resultTable")
        or soup.find("table", class_="case_details")
        or soup.find("table", class_="table")
    )

    if table is None:
        # Heuristic fallback: find the largest table with ≥ 4 columns
        tables = soup.find_all("table")
        for t in tables:
            headers = t.find_all("th")
            if len(headers) >= 4:
                table = t
                break

    if table is None:
        logger.info("No case table found in eCourts response.")
        return []

    rows = table.find_all("tr")
    for row in rows[1:]:   # skip header row
        cols = row.find_all(["td", "th"])
        if len(cols) < 4:
            continue
        texts = [c.get_text(strip=True) for c in cols]
        case = _map_row_to_case(texts)
        if case:
            cases.append(case)

    logger.info("Parsed %d case rows from eCourts HTML.", len(cases))
    return cases


def _map_row_to_case(cols: list[str]) -> dict[str, Any] | None:
    """
    Map a list of cell texts to the canonical case schema.

    eCourts columns vary by court type but typically follow:
      0: Sr. No.
      1: Case Number / CNR
      2: Case Type
      3: Filing Date
      4: Party Names
      5: Court Name
      6: Case Status
      7: Next Hearing Date  (optional)
    """
    # Skip rows that are clearly headers or empty
    if not any(cols):
        return None
    if cols[0].lower() in ("sr", "sr.", "s.no", "#", "no."):
        return None

    def _col(index: int, default: str = "") -> str:
        return cols[index].strip() if index < len(cols) else default

    # Determine status
    raw_status  = _col(6).lower()
    case_status: str
    if any(k in raw_status for k in ("decide", "disposed", "closed", "judgment")):
        case_status = "decided"
    else:
        case_status = "pending"

    # Hearing date
    hearing_raw = _col(7)
    next_hearing = hearing_raw if hearing_raw and hearing_raw not in ("-", "NA", "N/A") else None

    return {
        "case_number":       _col(1) or _col(0),
        "court_name":        _col(5),
        "filing_date":       _normalise_date(_col(3)),
        "case_type":         _col(2),
        "party_names":       [p.strip() for p in _col(4).split("VS") if p.strip()],
        "case_status":       case_status,
        "next_hearing_date": _normalise_date(next_hearing) if next_hearing else None,
        "_mock":             False,
    }


# ---------------------------------------------------------------------------
# CSRF / token extraction
# ---------------------------------------------------------------------------

def _extract_csrf_token(html: str) -> str | None:
    """
    Try to extract a CSRF token from the HTML page.

    Looks for common patterns:
    * ``<input name="csrf_token" value="…">``
    * ``<meta name="csrf-token" content="…">``
    * ``<input name="_token" value="…">``
    """
    from bs4 import BeautifulSoup  # noqa: PLC0415

    soup = BeautifulSoup(html, "html.parser")

    # input tags
    for name in ("csrf_token", "_token", "token"):
        tag = soup.find("input", {"name": name})
        if tag and tag.get("value"):
            return tag["value"]

    # meta tags
    for name in ("csrf-token", "csrf_token"):
        tag = soup.find("meta", {"name": name})
        if tag and tag.get("content"):
            return tag["content"]

    return None


# ---------------------------------------------------------------------------
# State-name → eCourts state-code mapping
# ---------------------------------------------------------------------------

_STATE_CODES: dict[str, str] = {
    "andhra pradesh": "1", "arunachal pradesh": "2", "assam": "3",
    "bihar": "4", "chhattisgarh": "5", "goa": "6", "gujarat": "7",
    "haryana": "8", "himachal pradesh": "9", "jharkhand": "10",
    "karnataka": "11", "kerala": "12", "madhya pradesh": "13",
    "maharashtra": "14", "manipur": "15", "meghalaya": "16",
    "mizoram": "17", "nagaland": "18", "odisha": "19", "punjab": "20",
    "rajasthan": "21", "sikkim": "22", "tamil nadu": "23",
    "telangana": "24", "tripura": "25", "uttar pradesh": "26",
    "uttarakhand": "27", "west bengal": "28",
    "delhi": "29", "new delhi": "29",
}


def _state_name_to_code(state: str) -> str:
    return _STATE_CODES.get(state.lower().strip(), "0")


# ---------------------------------------------------------------------------
# Date normalisation
# ---------------------------------------------------------------------------

_DATE_PATTERNS = [
    re.compile(r"(\d{2})[/-](\d{2})[/-](\d{4})"),   # DD-MM-YYYY or DD/MM/YYYY
    re.compile(r"(\d{4})[/-](\d{2})[/-](\d{2})"),   # YYYY-MM-DD (already ISO)
    re.compile(r"(\d{2})-([A-Za-z]{3})-(\d{4})"),   # DD-Mon-YYYY
]

_MONTH_ABBR = {
    "jan":"01","feb":"02","mar":"03","apr":"04","may":"05","jun":"06",
    "jul":"07","aug":"08","sep":"09","oct":"10","nov":"11","dec":"12",
}


def _normalise_date(raw: str | None) -> str | None:
    """Convert common Indian court date formats to ISO-8601 (YYYY-MM-DD)."""
    if not raw:
        return None
    for pat in _DATE_PATTERNS:
        m = pat.search(raw)
        if m:
            g = m.groups()
            if len(g[0]) == 4:          # YYYY-MM-DD already
                return f"{g[0]}-{g[1]}-{g[2]}"
            if g[1].isalpha():          # DD-Mon-YYYY
                month = _MONTH_ABBR.get(g[1].lower()[:3], "00")
                return f"{g[2]}-{month}-{g[0]}"
            return f"{g[2]}-{g[1]}-{g[0]}"   # DD-MM-YYYY → YYYY-MM-DD
    return raw.strip() or None


# ---------------------------------------------------------------------------
# Response checker
# ---------------------------------------------------------------------------

class _ECourtsBocked(Exception):
    """Raised when eCourts returns 503 or an anti-bot page."""


def _check_response(resp: Any) -> None:
    """
    Raise ``_ECourtsBocked`` for 503 or bot-detection pages;
    raise ``requests.HTTPError`` for other 4xx/5xx codes.
    """
    if resp.status_code == 503:
        raise _ECourtsBocked(f"503 Service Unavailable from {resp.url}")
    if resp.status_code == 429:
        raise _ECourtsBocked(f"429 Too Many Requests from {resp.url}")
    # Detect Cloudflare / captcha pages without raising on valid HTML
    lower = resp.text[:2000].lower()
    if resp.status_code == 200 and (
        "captcha" in lower
        or "checking your browser" in lower
        or "ddos-guard" in lower
        or "cloudflare" in lower
    ):
        raise _ECourtsBocked("Bot-detection page returned.")
    resp.raise_for_status()


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import logging as _logging

    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    )

    company = sys.argv[1] if len(sys.argv) > 1 else "Tata Steel Limited"
    state   = sys.argv[2] if len(sys.argv) > 2 else None

    print(f"\n{'='*60}")
    print(f"ECourtsTool — smoke test for: {company}")
    if state:
        print(f"State filter: {state}")
    print(f"{'='*60}\n")

    tool   = ECourtsTool()
    report = tool.search_cases(company, state=state)

    print(f"  Data source            : {report['data_source']}")
    print(f"  Total cases            : {report['total_cases']}")
    print(f"  Pending cases          : {report['pending_cases']}")
    print(f"  Litigation risk score  : {report['litigation_risk_score']} / 10")
    print(f"  NCLT override          : {report['nclt_override']}")
    print(f"  Severity breakdown     : {report['severity_breakdown']}")

    if report["critical_cases"]:
        print(f"\n  Critical cases ({report['critical_case_count']}):")
        for c in report["critical_cases"]:
            mock_tag = "  [MOCK]" if c.get("_mock") else ""
            print(f"    {c['case_number']:30s}  {c['case_type'][:40]}{mock_tag}")
            print(f"    Filed: {c['filing_date']}  Status: {c['case_status']}")

    print(f"\n{'='*60}\n")
