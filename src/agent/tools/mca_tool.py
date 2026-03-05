"""
mca_tool.py — MCA21 corporate intelligence tool for intelli_credit.

Queries the Indian Ministry of Corporate Affairs (MCA21) portal at
https://www.mca.gov.in to extract company master data, charge registry
information, and director details.

Public API
----------
    tool = MCATool()

    # Company master data
    master = tool.get_company_master("L17110MH1973PLC019786")
    master = tool.get_company_master("Reliance Industries")

    # Charge registry
    charges = tool.get_charges("L17110MH1973PLC019786")

    # Director lookup
    director = tool.get_director_din("Mukesh Ambani")

Notes
-----
* MCA21 v3 uses a React/SPA front-end; direct HTML scraping is augmented
  by targeting the underlying JSON API endpoints when discoverable.
* 2-second delays are inserted between every HTTP request.
* On any network failure / 503 / bot-block the tool falls back to
  pre-populated mock data for Reliance Industries and Tata Motors.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Project-root path resolution
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger("intelli_credit.agent.tools.mca_tool")

# ---------------------------------------------------------------------------
# HTTP constants
# ---------------------------------------------------------------------------
_BASE_URL        = "https://www.mca.gov.in"
_MCA_V3_COMPANY  = "https://efiling.mca.gov.in/eFiling/ApiService/v1/getCompanyMasterData"
_MCA_CHARGES_URL = "https://efiling.mca.gov.in/eFiling/ApiService/v1/getChargeDetails"
_MCA_DIN_SEARCH  = "https://www.mca.gov.in/content/mca/global/en/mca/master-data/DIN.html"
_REQUEST_DELAY   = 2        # seconds between HTTP requests
_MAX_RETRIES     = 2
_TIMEOUT         = 15
_BS_OVERDUE_YEARS = 2       # flag if balance-sheet filing is older than this

_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/html, */*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection":      "keep-alive",
    "Referer":         _BASE_URL,
    "DNT":             "1",
}

# ---------------------------------------------------------------------------
# CIN regex
# ---------------------------------------------------------------------------
_CIN_RE = re.compile(
    r"^[A-Z]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}$", re.IGNORECASE
)


def _is_cin(value: str) -> bool:
    return bool(_CIN_RE.match(value.strip()))


# ---------------------------------------------------------------------------
# Mock / fallback data
# ---------------------------------------------------------------------------
# Loaded from the raw JSON files shipped in the repo; supplemented with
# charge and director fixtures so demos are fully self-contained.

def _load_mock_db() -> dict[str, Any]:
    """Build the mock database from the checked-in JSON files + inline fixtures."""
    db: dict[str, Any] = {}

    for fname, keys in [
        ("mca_reliance.json", ["reliance industries limited", "L17110MH1973PLC019786", "ril"]),
        ("mca_tata.json",     ["tata motors limited",        "L28920MH1945PLC004520", "tata motors"]),
    ]:
        path = _PROJECT_ROOT / "data" / "raw" / fname
        try:
            raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            raw = {}

        # Attach mock charges and director stubs that aren't in the JSON files
        raw.setdefault("_charges", _MOCK_CHARGES.get(fname, []))
        raw.setdefault("_directors_detail", _MOCK_DIRECTORS.get(fname, []))

        for k in keys:
            db[k.lower()] = raw

    return db


# Mock charge records
_MOCK_CHARGES: dict[str, list[dict[str, Any]]] = {
    "mca_reliance.json": [
        {
            "charge_id":    "10012345",
            "charge_holder": "State Bank of India",
            "amount":        500_00_00_000,    # ₹500 Cr
            "date_created":  "2019-04-15",
            "date_modified": "2022-06-30",
            "status":        "Open",
            "assets_under_charge": "Movable and immovable assets of RIL",
        },
        {
            "charge_id":    "10023456",
            "charge_holder": "HDFC Bank Limited",
            "amount":        200_00_00_000,    # ₹200 Cr
            "date_created":  "2020-11-20",
            "date_modified": "2023-03-01",
            "status":        "Satisfied",
            "assets_under_charge": "Plant & Machinery, Petrochemicals Division",
        },
        {
            "charge_id":    "10034567",
            "charge_holder": "ICICI Bank Limited",
            "amount":        300_00_00_000,    # ₹300 Cr
            "date_created":  "2021-07-08",
            "date_modified": "2024-01-15",
            "status":        "Open",
            "assets_under_charge": "Book debts, Retail & Telecom Division",
        },
    ],
    "mca_tata.json": [
        {
            "charge_id":    "20056789",
            "charge_holder": "Axis Bank Limited",
            "amount":        150_00_00_000,    # ₹150 Cr
            "date_created":  "2018-03-22",
            "date_modified": "2022-09-14",
            "status":        "Open",
            "assets_under_charge": "Commercial vehicles inventory",
        },
        {
            "charge_id":    "20067890",
            "charge_holder": "Bank of Baroda",
            "amount":        250_00_00_000,    # ₹250 Cr
            "date_created":  "2020-05-10",
            "date_modified": "2023-12-01",
            "status":        "Open",
            "assets_under_charge": "Pune manufacturing plant, land & building",
        },
        {
            "charge_id":    "20078901",
            "charge_holder": "Kotak Mahindra Bank",
            "amount":        80_00_00_000,     # ₹80 Cr
            "date_created":  "2022-01-17",
            "date_modified": "2024-06-30",
            "status":        "Satisfied",
            "assets_under_charge": "Working capital assets",
        },
    ],
}

# Mock director detail records (name → {din, companies[]})
_MOCK_DIRECTORS: dict[str, list[dict[str, Any]]] = {
    "mca_reliance.json": [
        {
            "name":        "MUKESH DHIRUBHAI AMBANI",
            "din":         "00001695",
            "designation": "Chairman and Managing Director",
            "din_status":  "Approved",
            "companies":   [
                "RELIANCE INDUSTRIES LIMITED",
                "RELIANCE RETAIL LIMITED",
                "RELIANCE JIO INFOCOMM LIMITED",
                "RELIANCE PROJECTS AND PROPERTY MANAGEMENT SERVICES LIMITED",
                "RELIANCE INDUSTRIAL INVESTMENTS AND HOLDINGS LIMITED",
            ],
        },
    ],
    "mca_tata.json": [
        {
            "name":        "CHANDRASEKARAN NATARAJAN",
            "din":         "00121863",
            "designation": "Non-Executive Chairman",
            "din_status":  "Approved",
            "companies":   [
                "TATA MOTORS LIMITED",
                "TATA CONSULTANCY SERVICES LIMITED",
                "TATA STEEL LIMITED",
                "TATA POWER COMPANY LIMITED",
                "TATA CHEMICALS LIMITED",
                "TITAN COMPANY LIMITED",
                "TATA CONSUMER PRODUCTS LIMITED",
                "TATA COMMUNICATIONS LIMITED",
                "TATA ELXSI LIMITED",
                "AIR INDIA LIMITED",
                "TATA SONS PRIVATE LIMITED",
                "TATA CAPITAL LIMITED",
            ],
        },
    ],
}

# Shell-company indicator: director associated with > 10 companies
_SHELL_DIRECTOR_THRESHOLD = 10

# Hidden-debt flag: MCA open charges exceed declared debt by this ratio
_HIDDEN_DEBT_RATIO = 1.25   # 25% more than declared


# ===========================================================================
# MCATool
# ===========================================================================

class MCATool:
    """
    Fetch and analyse MCA21 corporate data for credit-risk assessment.

    Parameters
    ----------
    request_delay : float
        Seconds to sleep between HTTP calls (default 2).
    timeout : int
        HTTP timeout in seconds (default 15).
    use_mock_on_block : bool
        Fall back to built-in mock data when MCA21 is unreachable
        (default True).
    """

    def __init__(
        self,
        request_delay:     float = _REQUEST_DELAY,
        timeout:           int   = _TIMEOUT,
        use_mock_on_block: bool  = True,
    ) -> None:
        self.request_delay     = request_delay
        self.timeout           = timeout
        self.use_mock_on_block = use_mock_on_block
        self._session          = None       # lazy requests.Session
        self._mock_db_cache: dict[str, Any] | None = None  # lazy mock DB

    # ------------------------------------------------------------------
    # 1. get_company_master
    # ------------------------------------------------------------------

    def get_company_master(self, company_name_or_cin: str) -> dict[str, Any]:
        """
        Retrieve company master data from MCA21.

        Accepts either a CIN (e.g. ``L17110MH1973PLC019786``) or a fuzzy
        company name (e.g. ``"Reliance Industries"``).

        Extracted Fields
        ----------------
        cin, company_name, date_of_incorporation, registered_address,
        authorized_capital_inr, paid_up_capital_inr, company_status,
        last_agm_date, last_bs_filing_date.

        Compliance Flags
        ----------------
        * ``bs_filing_overdue``  — True if balance-sheet filing is older than
          2 years (compliance risk).
        * ``company_active``     — False if status is "Struck Off" / "Dormant".
        * ``agm_overdue``        — True if last AGM > 15 months ago.

        Returns
        -------
        dict — company master report.
        """
        query = company_name_or_cin.strip()
        logger.info("MCA get_company_master: %r", query)

        raw, source = self._fetch_company_master(query)
        return self._build_master_report(raw, source)

    # ------------------------------------------------------------------
    # 2. get_charges
    # ------------------------------------------------------------------

    def get_charges(
        self,
        cin: str,
        declared_debt_inr: float | None = None,
    ) -> dict[str, Any]:
        """
        Retrieve all registered charges from the MCA charges registry.

        Parameters
        ----------
        cin :
            Company Identification Number.
        declared_debt_inr :
            Total debt as declared in the latest annual report (optional).
            When provided, the tool compares MCA open-charge total against
            this figure and sets ``hidden_debt_flag`` if the difference
            exceeds 25%.

        Extracted Fields (per charge)
        -----------------------------
        charge_id, charge_holder, amount, date_created, status
        (Open / Satisfied).

        Returns
        -------
        dict — charges report with aggregates and optional hidden-debt flag.
        """
        cin = cin.strip().upper()
        logger.info("MCA get_charges: %r  declared_debt=%s", cin, declared_debt_inr)

        charges, source = self._fetch_charges(cin)
        return self._build_charges_report(charges, source, declared_debt_inr)

    # ------------------------------------------------------------------
    # 3. get_director_din
    # ------------------------------------------------------------------

    def get_director_din(self, director_name: str) -> dict[str, Any]:
        """
        Search for a director by name and return DIN + associated companies.

        Shell-Company Indicator
        -----------------------
        If the director is associated with more than 10 companies, the flag
        ``shell_company_indicator`` is set to True.  (MCA regulations cap
        non-independent director appointments at 20, but > 10 is a
        heuristic risk signal used internally.)

        Returns
        -------
        dict — director report.
        """
        name = director_name.strip()
        logger.info("MCA get_director_din: %r", name)

        details, source = self._fetch_director(name)
        return self._build_director_report(details, source)

    # ------------------------------------------------------------------
    # Internal: fetch company master
    # ------------------------------------------------------------------

    def _fetch_company_master(
        self, query: str
    ) -> tuple[dict[str, Any], str]:
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                data = self._scrape_company_master(query)
                return data, "live"
            except _MCABlocked as exc:
                logger.warning(
                    "MCA blocked attempt %d/%d: %s", attempt, _MAX_RETRIES, exc
                )
                time.sleep(self.request_delay * 2)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "MCA company-master fail attempt %d/%d: %s",
                    attempt, _MAX_RETRIES, exc,
                )
                time.sleep(self.request_delay)

        if self.use_mock_on_block:
            logger.info("Falling back to mock data for %r", query)
            return self._mock_company(query), "mock"
        return {}, "failed"

    def _scrape_company_master(self, query: str) -> dict[str, Any]:
        """
        Attempt to retrieve company master data from MCA21 v3.

        Strategy
        --------
        1. If *query* looks like a CIN, hit the eFiling JSON API directly.
        2. Otherwise GET the MCA master-data search page and parse the
           result table with BeautifulSoup.
        """
        import requests  # noqa: PLC0415
        from bs4 import BeautifulSoup  # noqa: PLC0415

        session = self._get_session()

        if _is_cin(query):
            # ── JSON API path ──────────────────────────────────────────
            url = f"{_MCA_V3_COMPANY}?companyID={query.upper()}"
            logger.debug("GET %s", url)
            resp = session.get(url, timeout=self.timeout, headers=_HEADERS)
            _check_response(resp)
            time.sleep(self.request_delay)
            return _parse_company_json(resp.json(), query)

        # ── HTML search path ──────────────────────────────────────────
        search_url = (
            f"{_BASE_URL}/content/mca/global/en/mca/master-data/MDS.html"
            f"?companyName={query.replace(' ', '+')}"
        )
        logger.debug("GET %s", search_url)
        resp = session.get(search_url, timeout=self.timeout, headers=_HEADERS)
        _check_response(resp)
        time.sleep(self.request_delay)

        soup = BeautifulSoup(resp.text, "html.parser")
        return _parse_company_html(soup, query)

    # ------------------------------------------------------------------
    # Internal: fetch charges
    # ------------------------------------------------------------------

    def _fetch_charges(
        self, cin: str
    ) -> tuple[list[dict[str, Any]], str]:
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                charges = self._scrape_charges(cin)
                return charges, "live"
            except _MCABlocked as exc:
                logger.warning(
                    "MCA charges blocked attempt %d/%d: %s",
                    attempt, _MAX_RETRIES, exc,
                )
                time.sleep(self.request_delay * 2)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "MCA charges fail attempt %d/%d: %s",
                    attempt, _MAX_RETRIES, exc,
                )
                time.sleep(self.request_delay)

        if self.use_mock_on_block:
            logger.info("Falling back to mock charges for CIN %r", cin)
            return self._mock_charges(cin), "mock"
        return [], "failed"

    def _scrape_charges(self, cin: str) -> list[dict[str, Any]]:
        import requests  # noqa: PLC0415
        from bs4 import BeautifulSoup  # noqa: PLC0415

        session = self._get_session()
        url = f"{_MCA_CHARGES_URL}?companyID={cin}"
        logger.debug("GET %s", url)
        resp = session.get(url, timeout=self.timeout, headers=_HEADERS)
        _check_response(resp)
        time.sleep(self.request_delay)

        # Try JSON first; fall back to HTML table parsing
        try:
            payload = resp.json()
            return _parse_charges_json(payload)
        except Exception:
            pass

        from bs4 import BeautifulSoup  # noqa: PLC0415  (re-import OK)
        soup = BeautifulSoup(resp.text, "html.parser")
        return _parse_charges_html(soup)

    # ------------------------------------------------------------------
    # Internal: fetch director
    # ------------------------------------------------------------------

    def _fetch_director(
        self, name: str
    ) -> tuple[dict[str, Any], str]:
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                data = self._scrape_director(name)
                return data, "live"
            except _MCABlocked as exc:
                logger.warning(
                    "MCA DIN blocked attempt %d/%d: %s",
                    attempt, _MAX_RETRIES, exc,
                )
                time.sleep(self.request_delay * 2)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "MCA DIN fail attempt %d/%d: %s",
                    attempt, _MAX_RETRIES, exc,
                )
                time.sleep(self.request_delay)

        if self.use_mock_on_block:
            logger.info("Falling back to mock director data for %r", name)
            return self._mock_director(name), "mock"
        return {}, "failed"

    def _scrape_director(self, name: str) -> dict[str, Any]:
        import requests  # noqa: PLC0415
        from bs4 import BeautifulSoup  # noqa: PLC0415

        session = self._get_session()
        params  = {"directorName": name}
        logger.debug("GET %s  params=%r", _MCA_DIN_SEARCH, params)
        resp = session.get(
            _MCA_DIN_SEARCH, params=params, timeout=self.timeout, headers=_HEADERS
        )
        _check_response(resp)
        time.sleep(self.request_delay)

        soup = BeautifulSoup(resp.text, "html.parser")
        return _parse_director_html(soup, name)

    # ------------------------------------------------------------------
    # Report builders
    # ------------------------------------------------------------------

    def _build_master_report(
        self, raw: dict[str, Any], source: str
    ) -> dict[str, Any]:
        bs_date_str:  str | None = raw.get("last_bs_filing_date")
        agm_date_str: str | None = raw.get("last_agm_date")
        status: str = raw.get("company_status", "Unknown")

        # Compliance checks
        bs_overdue  = _is_bs_overdue(bs_date_str)
        agm_overdue = _is_agm_overdue(agm_date_str)
        active      = status.lower() not in ("struck off", "dissolved", "dormant")

        compliance_flags: dict[str, Any] = {
            "bs_filing_overdue":  bs_overdue,
            "agm_overdue":        agm_overdue,
            "company_active":     active,
        }
        if bs_overdue:
            compliance_flags["bs_overdue_reason"] = (
                f"Last balance-sheet filing ({bs_date_str}) is older than "
                f"{_BS_OVERDUE_YEARS} years — compliance risk."
            )
        if not active:
            compliance_flags["status_reason"] = (
                f"Company status is '{status}' — potential credit risk."
            )

        return {
            "queried_at":             datetime.now(tz=timezone.utc).isoformat(),
            "data_source":            source,
            "cin":                    raw.get("cin", ""),
            "company_name":           raw.get("company_name", ""),
            "date_of_incorporation":  raw.get("date_of_incorporation"),
            "registered_address":     raw.get("registered_address"),
            "authorized_capital_inr": raw.get("authorized_capital_inr"),
            "paid_up_capital_inr":    raw.get("paid_up_capital_inr"),
            "company_status":         status,
            "last_agm_date":          agm_date_str,
            "last_bs_filing_date":    bs_date_str,
            "roc":                    raw.get("roc"),
            "listed_on_exchange":     raw.get("listed_on_exchange"),
            "directors":              raw.get("directors", []),
            "compliance_flags":       compliance_flags,
        }

    def _build_charges_report(
        self,
        charges:           list[dict[str, Any]],
        source:            str,
        declared_debt_inr: float | None,
    ) -> dict[str, Any]:
        open_charges    = [c for c in charges if c.get("status", "").lower() == "open"]
        sat_charges     = [c for c in charges if c.get("status", "").lower() == "satisfied"]
        total_open_amt  = sum(c.get("amount", 0) for c in open_charges)
        total_all_amt   = sum(c.get("amount", 0) for c in charges)

        # Hidden-debt detection
        hidden_debt_flag   = False
        hidden_debt_detail: str | None = None
        if declared_debt_inr and declared_debt_inr > 0 and total_open_amt > 0:
            ratio = total_open_amt / declared_debt_inr
            if ratio > _HIDDEN_DEBT_RATIO:
                hidden_debt_flag   = True
                hidden_debt_detail = (
                    f"MCA open charges ({_fmt_inr(total_open_amt)}) exceed "
                    f"declared debt ({_fmt_inr(declared_debt_inr)}) by "
                    f"{(ratio - 1) * 100:.1f}% — possible hidden debt."
                )

        return {
            "queried_at":                datetime.now(tz=timezone.utc).isoformat(),
            "data_source":               source,
            "total_charges":             len(charges),
            "open_charges_count":        len(open_charges),
            "satisfied_charges_count":   len(sat_charges),
            "total_open_charges_amount": total_open_amt,
            "total_all_charges_amount":  total_all_amt,
            "declared_debt_inr":         declared_debt_inr,
            "hidden_debt_flag":          hidden_debt_flag,
            "hidden_debt_detail":        hidden_debt_detail,
            "charges":                   charges,
        }

    def _build_director_report(
        self, details: dict[str, Any], source: str
    ) -> dict[str, Any]:
        companies    = details.get("companies", [])
        count        = len(companies)
        shell_flag   = count > _SHELL_DIRECTOR_THRESHOLD

        return {
            "queried_at":              datetime.now(tz=timezone.utc).isoformat(),
            "data_source":             source,
            "name":                    details.get("name", ""),
            "din":                     details.get("din", ""),
            "din_status":              details.get("din_status", ""),
            "designation":             details.get("designation", ""),
            "associated_companies":    companies,
            "company_count":           count,
            "shell_company_indicator": shell_flag,
            "shell_flag_reason": (
                f"Director is associated with {count} companies "
                f"(threshold: {_SHELL_DIRECTOR_THRESHOLD}) — "
                "possible shell-company network."
            ) if shell_flag else None,
        }

    # ------------------------------------------------------------------
    # Mock DB helpers
    # ------------------------------------------------------------------

    def _mock_db(self) -> dict[str, Any]:
        if self._mock_db_cache is None:
            self._mock_db_cache = _load_mock_db()
        return self._mock_db_cache

    def _mock_company(self, query: str) -> dict[str, Any]:
        db = self._mock_db()
        needle = query.lower().strip()
        # Exact match first
        if needle in db:
            return db[needle]
        # Partial-token match: query tokens all present in a db key (or vice-versa)
        q_tokens = set(needle.split())
        for key, val in db.items():
            k_tokens = set(key.split())
            if q_tokens <= k_tokens or k_tokens <= q_tokens:
                return val
        return _GENERIC_MOCK_COMPANY

    def _mock_charges(self, cin: str) -> list[dict[str, Any]]:
        db = self._mock_db()
        # Find entry by CIN
        for v in db.values():
            if isinstance(v, dict) and v.get("cin", "").upper() == cin.upper():
                return list(v.get("_charges", []))
        return list(_GENERIC_MOCK_CHARGES)

    def _mock_director(self, name: str) -> dict[str, Any]:
        db = self._mock_db()
        # Match if ALL tokens in the query appear somewhere in the director's full name
        q_tokens = set(name.lower().split())
        for v in db.values():
            if not isinstance(v, dict):
                continue
            for d in v.get("_directors_detail", []):
                d_tokens = set(d.get("name", "").lower().split())
                if q_tokens <= d_tokens or (q_tokens & d_tokens and len(q_tokens & d_tokens) >= 1):
                    return d
        return _GENERIC_MOCK_DIRECTOR

    # ------------------------------------------------------------------
    # requests.Session
    # ------------------------------------------------------------------

    def _get_session(self):  # type: ignore[return]
        if self._session is None:
            import requests  # noqa: PLC0415
            s = requests.Session()
            s.headers.update(_HEADERS)
            self._session = s
        return self._session


# ---------------------------------------------------------------------------
# Generic mock stubs (used when company not in known-mock list)
# ---------------------------------------------------------------------------

_GENERIC_MOCK_COMPANY: dict[str, Any] = {
    "cin":                    "U12345MH2000PTC123456",
    "company_name":           "GENERIC DEMO COMPANY PRIVATE LIMITED",
    "date_of_incorporation":  "2000-01-01",
    "registered_address":     "123 Demo Street, Mumbai, Maharashtra - 400001",
    "authorized_capital_inr": 10_00_00_000,
    "paid_up_capital_inr":    5_00_00_000,
    "company_status":         "Active",
    "last_agm_date":          "2022-09-30",
    "last_bs_filing_date":    "2021-03-31",     # > 2 yrs old → BS overdue
    "roc":                    "ROC Mumbai",
    "listed_on_exchange":     False,
    "directors":              ["DEMO DIRECTOR ONE", "DEMO DIRECTOR TWO"],
}

_GENERIC_MOCK_CHARGES: list[dict[str, Any]] = [
    {
        "charge_id":    "99900001",
        "charge_holder": "Indian Overseas Bank",
        "amount":        50_00_00_000,
        "date_created":  "2020-05-01",
        "date_modified": "2023-01-01",
        "status":        "Open",
        "assets_under_charge": "All assets",
    }
]

_GENERIC_MOCK_DIRECTOR: dict[str, Any] = {
    "name":        "DEMO DIRECTOR ONE",
    "din":         "00000001",
    "designation": "Director",
    "din_status":  "Approved",
    "companies":   ["GENERIC DEMO COMPANY PRIVATE LIMITED"],
}


# ---------------------------------------------------------------------------
# HTML / JSON parsing helpers
# ---------------------------------------------------------------------------

def _parse_company_json(payload: Any, cin: str) -> dict[str, Any]:
    """Map MCA21 eFiling JSON response to the canonical schema."""
    if not payload or not isinstance(payload, dict):
        raise ValueError(f"Empty/invalid JSON from MCA for CIN {cin!r}")
    body = payload.get("data") or payload.get("companyMasterData") or payload
    return {
        "cin":                    body.get("cin") or cin,
        "company_name":           body.get("companyName", ""),
        "date_of_incorporation":  _norm_date(body.get("dateOfIncorporation")),
        "registered_address":     body.get("registeredOfficeAddress", ""),
        "authorized_capital_inr": _parse_amount(body.get("authorisedCapital")),
        "paid_up_capital_inr":    _parse_amount(body.get("paidUpCapital")),
        "company_status":         body.get("companyStatus", ""),
        "last_agm_date":          _norm_date(body.get("dateOfLastAgm")),
        "last_bs_filing_date":    _norm_date(body.get("dateOfBalanceSheet")),
        "roc":                    body.get("rocCode", ""),
        "listed_on_exchange":     body.get("listedOnExchange", False),
        "directors":              [],
    }


def _parse_company_html(soup: Any, query: str) -> dict[str, Any]:
    """
    Parse company master data from an MCA HTML search results page.

    MCA renders results in a table with headers like "CIN", "Company Name",
    "Date of Incorporation", etc.
    """
    table = (
        soup.find("table", id="masterDataTable")
        or soup.find("table", class_="table")
        or soup.find("table")
    )
    if not table:
        raise ValueError(f"No company-master table found in MCA HTML for {query!r}")

    headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
    rows    = table.find_all("tr")

    result: dict[str, Any] = {}
    for row in rows[1:]:
        cols = [td.get_text(strip=True) for td in row.find_all("td")]
        if not any(cols):
            continue
        for i, h in enumerate(headers):
            val = cols[i] if i < len(cols) else ""
            if "cin" in h:
                result["cin"] = val
            elif "company name" in h:
                result["company_name"] = val
            elif "incorporation" in h:
                result["date_of_incorporation"] = _norm_date(val)
            elif "address" in h:
                result["registered_address"] = val
            elif "authoris" in h or "authoriz" in h:
                result["authorized_capital_inr"] = _parse_amount(val)
            elif "paid" in h:
                result["paid_up_capital_inr"] = _parse_amount(val)
            elif "status" in h:
                result["company_status"] = val
            elif "agm" in h:
                result["last_agm_date"] = _norm_date(val)
            elif "balance" in h:
                result["last_bs_filing_date"] = _norm_date(val)
        if result:
            break   # take first matching row

    if not result:
        raise ValueError(f"Could not extract company data from HTML for {query!r}")
    result.setdefault("directors", [])
    return result


def _parse_charges_json(payload: Any) -> list[dict[str, Any]]:
    """Map MCA charges JSON response to the canonical schema."""
    records = []
    items = payload if isinstance(payload, list) else (
        payload.get("data") or payload.get("charges") or []
    )
    for item in items:
        records.append({
            "charge_id":          str(item.get("chargeId", "")),
            "charge_holder":      item.get("chargeHolder", ""),
            "amount":             _parse_amount(item.get("amount")),
            "date_created":       _norm_date(item.get("dateOfCreation")),
            "date_modified":      _norm_date(item.get("dateOfModification")),
            "status":             item.get("chargeStatus", ""),
            "assets_under_charge": item.get("assetsUnderCharge", ""),
        })
    return records


def _parse_charges_html(soup: Any) -> list[dict[str, Any]]:
    """Parse the MCA charges registry HTML table."""
    table = (
        soup.find("table", id="chargesTable")
        or soup.find("table", class_="charges")
        or soup.find("table")
    )
    if not table:
        return []

    charges: list[dict[str, Any]] = []
    rows = table.find_all("tr")
    for row in rows[1:]:
        cols = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cols) < 4:
            continue
        charges.append({
            "charge_id":          cols[0] if len(cols) > 0 else "",
            "charge_holder":      cols[1] if len(cols) > 1 else "",
            "amount":             _parse_amount(cols[2]) if len(cols) > 2 else 0,
            "date_created":       _norm_date(cols[3]) if len(cols) > 3 else None,
            "date_modified":      _norm_date(cols[4]) if len(cols) > 4 else None,
            "status":             cols[5] if len(cols) > 5 else "",
            "assets_under_charge": cols[6] if len(cols) > 6 else "",
        })
    return charges


def _parse_director_html(soup: Any, name: str) -> dict[str, Any]:
    """Parse the MCA director / DIN search result page."""
    table = (
        soup.find("table", id="directorSearch")
        or soup.find("table", class_="din")
        or soup.find("table")
    )
    result: dict[str, Any] = {
        "name": name, "din": "", "din_status": "", "designation": "", "companies": []
    }
    if not table:
        return result

    rows = table.find_all("tr")
    for row in rows[1:]:
        cols = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cols) >= 2:
            if not result["din"]:
                result["din"]        = cols[0] if len(cols) > 0 else ""
                result["din_status"] = cols[2] if len(cols) > 2 else ""
            company = cols[3] if len(cols) > 3 else ""
            if company:
                result["companies"].append(company)
    return result


# ---------------------------------------------------------------------------
# Compliance date helpers
# ---------------------------------------------------------------------------

def _is_bs_overdue(date_str: str | None) -> bool:
    """True if the balance-sheet filing date is more than 2 years ago."""
    d = _parse_date(date_str)
    if d is None:
        return False
    age_years = (date.today() - d).days / 365.25
    return age_years > _BS_OVERDUE_YEARS


def _is_agm_overdue(date_str: str | None) -> bool:
    """True if the last AGM was held more than 15 months ago."""
    d = _parse_date(date_str)
    if d is None:
        return False
    age_months = (date.today() - d).days / 30.5
    return age_months > 15


def _parse_date(date_str: str | None) -> date | None:
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y", "%B %d, %Y"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------

_DATE_PATTERNS = [
    re.compile(r"(\d{2})[/-](\d{2})[/-](\d{4})"),    # DD-MM-YYYY
    re.compile(r"(\d{4})[/-](\d{2})[/-](\d{2})"),    # YYYY-MM-DD
    re.compile(r"(\d{2})-([A-Za-z]{3})-(\d{4})"),    # DD-Mon-YYYY
]
_MONTH_ABBR = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "may": "05", "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}


def _norm_date(raw: Any) -> str | None:
    """Normalise Indian date formats to ISO-8601 (YYYY-MM-DD)."""
    if not raw:
        return None
    s = str(raw).strip()
    for pat in _DATE_PATTERNS:
        m = pat.search(s)
        if m:
            g = m.groups()
            if len(g[0]) == 4:
                return f"{g[0]}-{g[1]}-{g[2]}"
            if g[1].isalpha():
                mo = _MONTH_ABBR.get(g[1].lower()[:3], "00")
                return f"{g[2]}-{mo}-{g[0]}"
            return f"{g[2]}-{g[1]}-{g[0]}"
    return s or None


def _parse_amount(raw: Any) -> float:
    """Parse ₹-amount strings like '5,00,00,000' or '500 Cr' to float."""
    if raw is None:
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).replace(",", "").replace("₹", "").strip()
    # Handle 'X Cr' / 'X Lakh' shorthand
    multiplier = 1.0
    lc = s.lower()
    if "cr" in lc:
        multiplier = 1_00_00_000
        s = re.sub(r"[^\d.]", "", s)
    elif "lakh" in lc or "lac" in lc:
        multiplier = 1_00_000
        s = re.sub(r"[^\d.]", "", s)
    else:
        s = re.sub(r"[^\d.]", "", s)
    try:
        return float(s) * multiplier
    except ValueError:
        return 0.0


def _fmt_inr(amount: float) -> str:
    """Format large INR amounts as '₹X.XX Cr'."""
    cr = amount / 1_00_00_000
    return f"₹{cr:.2f} Cr"


# ---------------------------------------------------------------------------
# HTTP response guard
# ---------------------------------------------------------------------------

class _MCABlocked(Exception):
    """Raised when MCA21 returns 503 / 403 / bot-detection page."""


def _check_response(resp: Any) -> None:
    if resp.status_code in (503, 429):
        raise _MCABlocked(f"HTTP {resp.status_code} from {resp.url}")
    if resp.status_code == 403:
        raise _MCABlocked(f"403 Forbidden from {resp.url}")
    lower = resp.text[:2000].lower()
    if resp.status_code == 200 and (
        "captcha" in lower
        or "checking your browser" in lower
        or "access denied" in lower
        or "cloudflare" in lower
    ):
        raise _MCABlocked("Bot-detection / CAPTCHA page from MCA21.")
    resp.raise_for_status()


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import logging as _logging

    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    )

    tool = MCATool()

    for company, cin, director, declared_debt in [
        ("Reliance Industries", "L17110MH1973PLC019786", "Mukesh Ambani",   2_000_00_00_000),
        ("Tata Motors",         "L28920MH1945PLC004520", "N Chandrasekaran", 500_00_00_000),
    ]:
        print(f"\n{'='*65}")
        print(f"  Company : {company}")
        print(f"{'='*65}")

        master = tool.get_company_master(company)
        print(f"  CIN              : {master['cin']}")
        print(f"  Status           : {master['company_status']}")
        print(f"  Auth Capital     : {_fmt_inr(master['authorized_capital_inr'] or 0)}")
        print(f"  Paid-Up Capital  : {_fmt_inr(master['paid_up_capital_inr'] or 0)}")
        print(f"  Last BS Filing   : {master['last_bs_filing_date']}")
        print(f"  BS Overdue Flag  : {master['compliance_flags']['bs_filing_overdue']}")
        print(f"  Data Source      : {master['data_source']}")

        charges = tool.get_charges(cin, declared_debt_inr=declared_debt)
        print(f"\n  Charges          : {charges['total_charges']} total, "
              f"{charges['open_charges_count']} open")
        print(f"  Open Charge Amt  : {_fmt_inr(charges['total_open_charges_amount'])}")
        print(f"  Hidden Debt Flag : {charges['hidden_debt_flag']}")
        if charges["hidden_debt_detail"]:
            print(f"  Hidden Debt Note : {charges['hidden_debt_detail']}")

        din_report = tool.get_director_din(director)
        print(f"\n  Director         : {din_report['name']}")
        print(f"  DIN              : {din_report['din']}")
        print(f"  Companies        : {din_report['company_count']}")
        print(f"  Shell Indicator  : {din_report['shell_company_indicator']}")

    print(f"\n{'='*65}\n")
