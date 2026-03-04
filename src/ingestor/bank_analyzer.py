"""
bank_analyzer.py — Bank statement ingestion and forensic analytics.

Accepts:
  • A CSV / Excel file exported directly from a bank portal.
  • A list of table-dicts produced by :class:`PDFParser` for PDF bank statements.

Public interface
────────────────
  analyzer = BankStatementAnalyzer()
  analyzer.load_transactions(filepath_or_tables)
  metrics   = analyzer.compute_metrics()
  anomalies = analyzer.flag_anomalies()
  result    = analyzer.analyze(filepath_or_tables)   # all-in-one

Column normalisation
────────────────────
The loader detects column names from a large synonym dictionary covering
HDFC, SBI, ICICI, Axis, Kotak and generic exports, then renames them to the
canonical set:  date | description | debit | credit | balance

All monetary values are stored as float (INR; no crore conversion here).
"""

from __future__ import annotations

import io
import logging
import re
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Union

import pandas as pd

logger = logging.getLogger("intelli_credit.ingestor.bank_analyzer")

# ---------------------------------------------------------------------------
# Column-synonym dictionary
# Canonical name → list of raw header variants (case-insensitive, stripped)
# ---------------------------------------------------------------------------

_COL_SYNONYMS: dict[str, list[str]] = {
    "date": [
        "date", "txn date", "transaction date", "value date",
        "posting date", "trans date", "tran date", "dt", "dated",
        "transaction_date", "txndate",
    ],
    "description": [
        "description", "narration", "particulars", "remarks",
        "transaction remarks", "details", "transaction details",
        "transaction description", "desc", "narrative",
        "transaction_narration", "transaction_details",
    ],
    "debit": [
        "debit", "withdrawal", "withdrawals", "dr", "dr amount",
        "debit amount", "debit(dr)", "withdrawal amount",
        "amount debited", "debit_amount", "debit(inr)",
        # HDFC / SBI common variants
        "withdrawal amt.", "withdrawal amt", "withdrl amt",
        "debit amt.", "debit amt", "dr.",
        "paid out", "money out",
    ],
    "credit": [
        "credit", "deposit", "deposits", "cr", "cr amount",
        "credit amount", "credit(cr)", "deposit amount",
        "amount credited", "credit_amount", "credit(inr)",
        # HDFC / SBI common variants
        "deposit amt.", "deposit amt", "credit amt.", "credit amt",
        "cr.", "paid in", "money in",
    ],
    "balance": [
        "balance", "closing balance", "running balance", "ledger balance",
        "available balance", "bal", "balance(inr)", "closing_balance",
        "balance amount", "closing bal", "closing bal.", "bal.",
        # Account-aggregator / open-banking API column names
        "currentbalance", "current balance", "current_balance",
        "availablebalance", "available_balance",
    ],
    "date": [
        # extra entries to supplement the existing "date" list above
        "valuedatetime", "valuedate", "value_date",
        "transactiontimestamp", "transaction_timestamp", "txntimestamp",
    ],
}

# Pre-compute reverse map: lower(raw_header) → canonical
_HEADER_TO_CANONICAL: dict[str, str] = {}
for _canonical, _variants in _COL_SYNONYMS.items():
    for _v in _variants:
        _HEADER_TO_CANONICAL[_v.lower().strip()] = _canonical


# ---------------------------------------------------------------------------
# Transaction-category detection helpers
# ---------------------------------------------------------------------------

_UPI_RE    = re.compile(r"\bupi\b|upi[-/]|@upi", re.IGNORECASE)
_CASH_RE   = re.compile(r"\bcash\b|\batm\b|cash deposit|cdm\b|coin\b", re.IGNORECASE)
_BOUNCE_RE = re.compile(r"\breturn\b|\bbounce\b|\bunchg\b|\bdishonour\b", re.IGNORECASE)
_EMI_RE    = re.compile(r"\bemi\b|instalment|installment", re.IGNORECASE)
_SALARY_RE = re.compile(r"\bsalary\b|\bsal\b|\bpayroll\b", re.IGNORECASE)


def _clean_amount(val: Any) -> float:
    """
    Convert a raw cell value to float.

    Handles: None, NaN, empty string, comma-formatted numbers,
    leading `+`/`-`, parenthesised negatives like ``(1,234.56)``.
    """
    if val is None:
        return 0.0
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", "-", "nil"):
        return 0.0
    # parenthesised negative  e.g. (1,234.56)
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    # strip currency symbols and commas
    s = re.sub(r"[₹$€£,\s]", "", s)
    try:
        return float(s)
    except ValueError:
        return 0.0


def _parse_date(val: Any) -> datetime | None:
    """Try a broad set of date formats; return None on failure."""
    if val is None:
        return None
    if isinstance(val, (datetime, pd.Timestamp)):
        return pd.Timestamp(val).to_pydatetime()
    s = str(val).strip()
    _FMTS = [
        "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y",
        "%Y-%m-%d", "%Y/%m/%d",
        "%d %b %Y", "%d %B %Y",
        "%d-%b-%Y", "%d-%b-%y",
        "%m/%d/%Y", "%m-%d-%Y",
        "%d.%m.%Y", "%d.%m.%y",
    ]
    for fmt in _FMTS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Column normaliser
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Type-amount format detector & splitter
# Handles CSVs where a single ``amount`` column + a ``type`` column
# (values: DEBIT / CREDIT / DR / CR) replace separate debit/credit columns.
# ---------------------------------------------------------------------------

_TYPE_DEBIT_RE  = re.compile(r"^deb|^dr", re.IGNORECASE)
_TYPE_CREDIT_RE = re.compile(r"^cred|^cr", re.IGNORECASE)


def _split_type_amount_format(df: pd.DataFrame) -> pd.DataFrame:
    """
    Detect and transform a ``type + amount`` layout into explicit
    ``debit`` / ``credit`` columns.

    Triggers when the DataFrame has both:
      * a column whose *cleaned* name is ``"type"`` or ``"txntype"`` and
        whose values look like DEBIT/CREDIT/DR/CR, **and**
      * a column whose cleaned name is ``"amount"`` or ``"transactionamount"``.

    Also normalises bank-API date/description columns:
      * ``transactionTimestamp`` / ``valueDate``   → ``date``
      * ``narration`` / ``mode`` merged            → ``description``
      * ``currentBalance``                         → ``balance``
    """
    lower_cols = {str(c).lower().strip(): c for c in df.columns}

    # Detect type column
    type_col_raw = (
        lower_cols.get("type")
        or lower_cols.get("txntype")
        or lower_cols.get("transaction type")
        or lower_cols.get("dr/cr")
    )
    # Detect amount column
    amount_col_raw = (
        lower_cols.get("amount")
        or lower_cols.get("transactionamount")
        or lower_cols.get("transaction amount")
        or lower_cols.get("txn amount")
    )

    if type_col_raw is None or amount_col_raw is None:
        return df  # not this format; leave as-is

    # Confirm type column has DEBIT/CREDIT-like values
    sample_types = df[type_col_raw].dropna().astype(str).str.strip().unique()
    if not any(_TYPE_DEBIT_RE.match(v) or _TYPE_CREDIT_RE.match(v) for v in sample_types):
        return df

    df = df.copy()
    amounts = df[amount_col_raw].apply(_clean_amount)
    txn_type = df[type_col_raw].astype(str).str.strip()

    df["debit"]  = amounts.where(txn_type.str.match(r"^(deb|dr)", case=False), other=0.0)
    df["credit"] = amounts.where(txn_type.str.match(r"^(cred|cr)", case=False), other=0.0)

    # Date: prefer transactionTimestamp, fall back to valueDate
    for ts_col_key in ("transactiontimestamp", "transaction_timestamp", "txntimestamp"):
        if ts_col_key in lower_cols and "date" not in lower_cols:
            df["date"] = df[lower_cols[ts_col_key]]
            break
    for vd_key in ("valuedate", "value_date", "valuedatetime"):
        if vd_key in lower_cols and "date" not in lower_cols:
            df["date"] = df[lower_cols[vd_key]]
            break

    # Balance: currentBalance / availableBalance
    for bal_key in ("currentbalance", "current_balance", "availablebalance"):
        if bal_key in lower_cols and "balance" not in lower_cols:
            df["balance"] = df[lower_cols[bal_key]].apply(_clean_amount)
            break

    # Description: prefer narration; append mode if present
    narr_col = lower_cols.get("narration") or lower_cols.get("description") or lower_cols.get("particulars")
    mode_col = lower_cols.get("mode")
    if narr_col is not None and "description" not in lower_cols:
        if mode_col is not None:
            df["description"] = (
                df[narr_col].fillna("").astype(str)
                + " [" + df[mode_col].fillna("").astype(str) + "]"
            )
        else:
            df["description"] = df[narr_col].fillna("").astype(str)

    return df


# Additional substring-based fallback keywords (canonical → substrings to look for)
_COL_SUBSTRINGS: dict[str, list[str]] = {
    "date":        ["date", "dt"],
    "description": ["narrat", "particular", "remark", "detail", "desc", "descript"],
    "debit":       ["withdrawal", "withdrl", "debit", "paid out", "money out"],
    "credit":      ["deposit", "credit", "paid in", "money in"],
    "balance":     ["balance", "closing bal"],
}


def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Rename DataFrame columns to the canonical set, drop unrecognised extras.

    Two-pass strategy:
    1. Exact match against the full synonym dictionary.
    2. Substring match using _COL_SUBSTRINGS for any remaining unmapped columns.

    Raises ``ValueError`` if fewer than 3 canonical columns can be mapped.
    """
    already_mapped: set[str] = set()   # canonical names already assigned
    rename_map: dict[str, str] = {}

    # Any canonical column already present (added by _split_type_amount_format)
    # must not be mapped again — doing so would create duplicate labels.
    _canonical = {"date", "description", "debit", "credit", "balance"}
    for col in _canonical:
        if col in df.columns:
            already_mapped.add(col)

    # Pass 1 — exact match
    for raw_col in df.columns:
        if raw_col in _canonical:  # already canonical, skip renaming
            continue
        key = str(raw_col).lower().strip()
        canonical = _HEADER_TO_CANONICAL.get(key)
        if canonical and canonical not in already_mapped:
            rename_map[raw_col] = canonical
            already_mapped.add(canonical)

    # Pass 2 — substring fallback for unmapped columns
    for raw_col in df.columns:
        if raw_col in rename_map:
            continue
        key = str(raw_col).lower().strip()
        for canonical, substrings in _COL_SUBSTRINGS.items():
            if canonical in already_mapped:
                continue
            if any(sub in key for sub in substrings):
                rename_map[raw_col] = canonical
                already_mapped.add(canonical)
                break

    # Count total canonical coverage: pre-existing + newly renamed
    total_canonical = len(already_mapped)
    if total_canonical < 3:
        raise ValueError(
            f"Cannot map columns to canonical names. "
            f"Detected only {total_canonical} of 5 expected canonical columns from: "
            f"{list(df.columns)}"
        )

    df = df.rename(columns=rename_map)

    # Ensure every canonical column exists (fill missing with 0/NaN)
    for col in ("date", "description", "debit", "credit", "balance"):
        if col not in df.columns:
            df[col] = "" if col in ("date", "description") else 0.0

    return df[["date", "description", "debit", "credit", "balance"]]


# ---------------------------------------------------------------------------
# PDF-table flattening
# ---------------------------------------------------------------------------

def _tables_to_dataframe(tables: list[dict]) -> pd.DataFrame:
    """
    Convert PDFParser table-dicts into a flat DataFrame.

    Each dict has ``headers`` and ``rows``; we concatenate all tables,
    using headers as column names, then normalise.
    """
    frames: list[pd.DataFrame] = []
    for tbl in tables:
        headers = tbl.get("headers") or []
        rows    = tbl.get("rows")   or []
        if not rows:
            continue
        try:
            frame = pd.DataFrame(rows, columns=headers if len(headers) == len(rows[0]) else None)
        except Exception:
            continue
        frames.append(frame)

    if not frames:
        raise ValueError("No usable tables found in PDFParser output.")

    combined = pd.concat(frames, ignore_index=True)
    return _normalise_columns(combined)


# ---------------------------------------------------------------------------
# BankStatementAnalyzer
# ---------------------------------------------------------------------------

class BankStatementAnalyzer:
    """
    Ingests and analyses a bank statement (CSV, Excel, or PDF-parsed tables).

    Typical usage::

        analyzer = BankStatementAnalyzer()
        analyzer.load_transactions("data/raw/hdfc_statement.csv")
        metrics   = analyzer.compute_metrics()
        anomalies = analyzer.flag_anomalies()
        result    = analyzer.analyze("data/raw/hdfc_statement.csv")

    Attributes
    ----------
    transactions : pd.DataFrame | None
        Normalised transaction table with columns:
        ``date, description, debit, credit, balance``.
    """

    def __init__(self) -> None:
        self.transactions: pd.DataFrame | None = None
        self._source_label: str = "<none>"

    # ------------------------------------------------------------------
    # 1. load_transactions
    # ------------------------------------------------------------------

    def load_transactions(
        self,
        source: Union[str, Path, list[dict]],
        *,
        encoding: str = "utf-8-sig",
        sheet_name: int | str = 0,
        skip_rows: int = 0,
    ) -> pd.DataFrame:
        """
        Load and normalise bank transactions from a file or PDF-parsed tables.

        Parameters
        ----------
        source      : file path (str / Path) to a CSV or Excel file,
                      **or** a list of table-dicts from ``PDFParser.parse()["tables"]``.
        encoding    : character encoding for CSV files (default UTF-8 with BOM).
        sheet_name  : for Excel files — which sheet to read.
        skip_rows   : number of header rows to skip at the top of the file.

        Returns
        -------
        Normalised ``pd.DataFrame`` (also stored as ``self.transactions``).

        Raises
        ------
        ValueError  : if the source cannot be parsed or columns cannot be mapped.
        FileNotFoundError : if a file path is given but the file does not exist.
        """
        if isinstance(source, list):
            # PDF-parsed tables
            self._source_label = "pdf_tables"
            df = _tables_to_dataframe(source)
        else:
            path = Path(source)
            if not path.exists():
                raise FileNotFoundError(f"Bank statement file not found: {path}")

            self._source_label = path.name
            suffix = path.suffix.lower()

            if suffix == ".csv":
                df = self._read_csv(path, encoding=encoding, skip_rows=skip_rows)
            elif suffix in (".xlsx", ".xls", ".ods"):
                df = self._read_excel(path, sheet_name=sheet_name, skip_rows=skip_rows)
            else:
                # Try CSV as default
                df = self._read_csv(path, encoding=encoding, skip_rows=skip_rows)

        df = self._coerce_types(df)
        self.transactions = df
        logger.info(
            "Loaded %d transactions from '%s'.",
            len(df), self._source_label,
        )
        return df

    def _read_csv(
        self, path: Path, encoding: str, skip_rows: int
    ) -> pd.DataFrame:
        """Read CSV, auto-sniff delimiter, gracefully fall back encodings."""
        for enc in (encoding, "latin-1", "cp1252"):
            try:
                raw = pd.read_csv(
                    path,
                    encoding=enc,
                    skiprows=skip_rows,
                    dtype=str,
                    skip_blank_lines=True,
                    on_bad_lines="skip",
                )
                raw = _split_type_amount_format(raw)
                return _normalise_columns(raw)
            except UnicodeDecodeError:
                continue
            except Exception as exc:
                logger.debug("CSV read failed with %s (%s), retrying.", enc, exc)
                continue
        raise ValueError(f"Could not read CSV file: {path}")

    def _read_excel(
        self, path: Path, sheet_name: int | str, skip_rows: int
    ) -> pd.DataFrame:
        try:
            raw = pd.read_excel(
                path,
                sheet_name=sheet_name,
                skiprows=skip_rows,
                dtype=str,
            )
            return _normalise_columns(raw)
        except Exception as exc:
            raise ValueError(f"Could not read Excel file: {path}") from exc

    @staticmethod
    def _coerce_types(df: pd.DataFrame) -> pd.DataFrame:
        """Parse amounts and dates; drop rows that are entirely empty."""
        df = df.copy()
        df["debit"]   = df["debit"].apply(_clean_amount)
        df["credit"]  = df["credit"].apply(_clean_amount)
        df["balance"] = df["balance"].apply(_clean_amount)
        df["date_dt"] = df["date"].apply(_parse_date)
        df["description"] = df["description"].fillna("").astype(str).str.strip()

        # Drop rows with no useful data
        df = df[
            (df["debit"] != 0) | (df["credit"] != 0) | (df["balance"] != 0)
            | (df["description"] != "")
        ].reset_index(drop=True)

        # Add derived columns
        df["_month"]       = df["date_dt"].apply(lambda d: d.strftime("%Y-%m") if d else None)
        df["_is_upi"]      = df["description"].apply(lambda d: bool(_UPI_RE.search(d)))
        df["_is_cash"]     = df["description"].apply(lambda d: bool(_CASH_RE.search(d)))
        df["_is_bounce"]   = df["description"].apply(lambda d: bool(_BOUNCE_RE.search(d)))

        return df

    # ------------------------------------------------------------------
    # 2. compute_metrics
    # ------------------------------------------------------------------

    def compute_metrics(self) -> dict:
        """
        Compute financial health metrics from loaded transactions.

        Returns
        -------
        dict with keys:

        ========================  ==========================================
        average_monthly_balance   Mean of end-of-month closing balances
        total_annual_credits      Sum of all credit entries
        total_annual_debits       Sum of all debit entries
        debit_credit_ratio        total_debits / total_credits  (0 = no debits)
        bounce_count              Rows containing RETURN / BOUNCE keywords
        upi_percentage            UPI transactions as % of total transaction count
        cash_deposit_concentration Cash credits as % of total credits
        largest_single_debit      Max single debit amount
        largest_single_credit     Max single credit amount
        credit_volatility         Std-dev of monthly credit totals
        monthly_credits           dict {YYYY-MM: total_credit}
        monthly_debits            dict {YYYY-MM: total_debit}
        transaction_count         Total row count
        ========================  ==========================================
        """
        self._require_loaded()
        df = self.transactions

        total_credits = float(df["credit"].sum())
        total_debits  = float(df["debit"].sum())
        n_total       = len(df)

        # Monthly aggregates
        monthly_credits: dict[str, float] = {}
        monthly_debits:  dict[str, float] = {}
        monthly_balances: dict[str, float] = {}

        for month, grp in df.groupby("_month", dropna=True):
            monthly_credits[month] = float(grp["credit"].sum())
            monthly_debits[month]  = float(grp["debit"].sum())
            # Use the last balance of the month as the closing balance
            last_row = grp.sort_values("date_dt").iloc[-1]
            monthly_balances[month] = float(last_row["balance"])

        avg_monthly_balance = (
            float(statistics.mean(monthly_balances.values()))
            if monthly_balances else 0.0
        )

        # Credit volatility (std dev of monthly credits)
        credit_vol = 0.0
        if len(monthly_credits) > 1:
            credit_vol = float(statistics.stdev(monthly_credits.values()))

        # UPI percentage
        n_upi = int(df["_is_upi"].sum())
        upi_pct = (n_upi / n_total * 100.0) if n_total else 0.0

        # Cash deposit concentration
        cash_credit_total = float(df.loc[df["_is_cash"], "credit"].sum())
        cash_conc = (cash_credit_total / total_credits * 100.0) if total_credits else 0.0

        # Bounce count
        bounce_count = int(df["_is_bounce"].sum())

        return {
            "average_monthly_balance":      round(avg_monthly_balance, 2),
            "total_annual_credits":         round(total_credits, 2),
            "total_annual_debits":          round(total_debits, 2),
            "debit_credit_ratio":           round(total_debits / total_credits, 4)
                                            if total_credits else 0.0,
            "bounce_count":                 bounce_count,
            "upi_percentage":               round(upi_pct, 2),
            "cash_deposit_concentration":   round(cash_conc, 2),
            "largest_single_debit":         round(float(df["debit"].max()), 2),
            "largest_single_credit":        round(float(df["credit"].max()), 2),
            "credit_volatility":            round(credit_vol, 2),
            "monthly_credits":              {k: round(v, 2) for k, v in sorted(monthly_credits.items())},
            "monthly_debits":               {k: round(v, 2) for k, v in sorted(monthly_debits.items())},
            "transaction_count":            n_total,
        }

    # ------------------------------------------------------------------
    # 3. flag_anomalies
    # ------------------------------------------------------------------

    def flag_anomalies(self) -> list[dict]:
        """
        Detect suspicious transaction patterns.

        Three checks:

        1. **round_number_transactions** — credit amounts that are exact
           multiples of 100 000 (≥ ₹1 lakh).  Common in inflated revenue
           scenarios; real organic credits rarely land on round crore/lakh figures.

        2. **same_day_credit_debit_pairs** — dates where a significant credit
           is matched by a debit of equal or near-equal magnitude on the same
           day.  Threshold: credit ≥ ₹50 000 and |credit − debit| / credit < 5%.
           Indicative of possible layering / pass-through transactions.

        3. **unusually_large_single_credits** — individual credits that exceed
           3× the average monthly credit total.

        Returns
        -------
        List of anomaly dicts, each containing:
            ``type, description, amount, date, severity``
        """
        self._require_loaded()
        df = self.transactions
        anomalies: list[dict] = []

        # ── 1. Round-number credits ──────────────────────────────────────
        _ROUND_NUM_THRESHOLD = 100_000.0    # ₹1 lakh
        round_credits = df[
            (df["credit"] >= _ROUND_NUM_THRESHOLD)
            & (df["credit"] % _ROUND_NUM_THRESHOLD == 0.0)
        ]
        for _, row in round_credits.iterrows():
            anomalies.append({
                "type":        "round_number_transaction",
                "description": row["description"],
                "amount":      float(row["credit"]),
                "date":        str(row["date"]),
                "severity":    "MEDIUM",
                "detail":      f"Credit of ₹{row['credit']:,.0f} is an exact round number "
                               f"(multiple of ₹{_ROUND_NUM_THRESHOLD:,.0f}).",
            })

        # ── 2. Same-day credit-debit pairs (layering) ───────────────────
        _MIN_AMOUNT     = 50_000.0
        _TOLERANCE_PCT  = 0.05          # within 5% is considered "matching"

        credit_df = df[df["credit"] >= _MIN_AMOUNT][["date_dt", "_month", "description", "credit"]].copy()
        debit_df  = df[df["debit"]  >= _MIN_AMOUNT][["date_dt", "description", "debit"]].copy()

        # Group by date
        credits_by_date: dict = defaultdict(list)
        for _, row in credit_df.iterrows():
            key = row["date_dt"]
            if key is not None:
                credits_by_date[key].append(row)

        debits_by_date: dict = defaultdict(list)
        for _, row in debit_df.iterrows():
            key = row["date_dt"]
            if key is not None:
                debits_by_date[key].append(row)

        for dt, credit_rows in credits_by_date.items():
            debit_rows = debits_by_date.get(dt, [])
            if not debit_rows:
                continue
            for cr in credit_rows:
                for dr in debit_rows:
                    credit_amt = float(cr["credit"])
                    debit_amt  = float(dr["debit"])
                    diff_ratio = abs(credit_amt - debit_amt) / credit_amt
                    if diff_ratio <= _TOLERANCE_PCT:
                        anomalies.append({
                            "type":        "same_day_credit_debit_pair",
                            "description": (
                                f"Credit: {cr['description']!r} | "
                                f"Debit: {dr['description']!r}"
                            ),
                            "amount":      credit_amt,
                            "date":        str(cr.get("date_dt", dt)),
                            "severity":    "HIGH",
                            "detail":      (
                                f"Credit ₹{credit_amt:,.0f} and debit ₹{debit_amt:,.0f} "
                                f"on same day — difference {diff_ratio*100:.1f}% "
                                f"(possible layering / pass-through)."
                            ),
                        })

        # ── 3. Unusually large single credits (> 3× avg monthly credit) ─
        monthly_totals = df.groupby("_month", dropna=True)["credit"].sum()
        if len(monthly_totals) > 0:
            avg_monthly = float(monthly_totals.mean())
            threshold   = 3.0 * avg_monthly
            large_credits = df[df["credit"] > threshold]
            for _, row in large_credits.iterrows():
                anomalies.append({
                    "type":        "unusually_large_single_credit",
                    "description": row["description"],
                    "amount":      float(row["credit"]),
                    "date":        str(row["date"]),
                    "severity":    "HIGH",
                    "detail":      (
                        f"Credit ₹{row['credit']:,.0f} exceeds 3× average "
                        f"monthly credit (₹{avg_monthly:,.0f}). "
                        f"Threshold: ₹{threshold:,.0f}."
                    ),
                })

        logger.info(
            "flag_anomalies: %d anomaly record(s) detected "
            "(round=%d, layering=%d, large=%d).",
            len(anomalies),
            sum(1 for a in anomalies if a["type"] == "round_number_transaction"),
            sum(1 for a in anomalies if a["type"] == "same_day_credit_debit_pair"),
            sum(1 for a in anomalies if a["type"] == "unusually_large_single_credit"),
        )
        return anomalies

    # ------------------------------------------------------------------
    # 4. analyze  (convenience all-in-one)
    # ------------------------------------------------------------------

    def analyze(
        self,
        source: Union[str, Path, list[dict]],
        *,
        company_id: str = "UNKNOWN",
        encoding: str = "utf-8-sig",
        sheet_name: int | str = 0,
        skip_rows: int = 0,
    ) -> dict:
        """
        Load, compute metrics, and flag anomalies in one call.

        Returns a structured dict ready for the Silver layer::

            {
              "company_id":   str,
              "source_file":  str,
              "metrics":      {…},
              "anomalies":    [{…}, …],
              "anomaly_summary": {
                  "total": int,
                  "HIGH":  int,
                  "MEDIUM": int,
                  "LOW":    int,
              },
              "analyzed_at":  str,   # ISO-8601 UTC
            }
        """
        self.load_transactions(
            source,
            encoding=encoding,
            sheet_name=sheet_name,
            skip_rows=skip_rows,
        )
        metrics   = self.compute_metrics()
        anomalies = self.flag_anomalies()

        severity_counts: dict[str, int] = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for a in anomalies:
            sev = a.get("severity", "LOW")
            severity_counts[sev] = severity_counts.get(sev, 0) + 1

        from datetime import timezone
        analyzed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        return {
            "company_id":      company_id,
            "source_file":     self._source_label,
            "metrics":         metrics,
            "anomalies":       anomalies,
            "anomaly_summary": {
                "total": len(anomalies),
                **severity_counts,
            },
            "analyzed_at":     analyzed_at,
        }

    # ------------------------------------------------------------------
    # Internal guard
    # ------------------------------------------------------------------

    def _require_loaded(self) -> None:
        if self.transactions is None or self.transactions.empty:
            raise RuntimeError(
                "No transactions loaded. Call load_transactions() first."
            )


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

def analyze_bank_statement(
    source: Union[str, Path, list[dict]],
    company_id: str = "UNKNOWN",
    **kwargs,
) -> dict:
    """One-liner wrapper around :class:`BankStatementAnalyzer`."""
    return BankStatementAnalyzer().analyze(source, company_id=company_id, **kwargs)


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    from io import StringIO

    # Synthetic bank statement — realistic HDFC-style CSV
    _SAMPLE_CSV = """Date,Narration,Withdrawal Amt.,Deposit Amt.,Closing Balance
01/04/2024,SALARY CREDITS PAYROLL,0.00,3500000.00,3500000.00
02/04/2024,UPI/VENDOR PAYMENT/789012,50000.00,0.00,3450000.00
03/04/2024,UPI/SUPPLIER INVOICE/990011,75000.00,0.00,3375000.00
05/04/2024,CASH DEPOSIT CDM BRANCH,0.00,200000.00,3575000.00
07/04/2024,NEFT TRANSFER INWARD,0.00,1000000.00,4575000.00
07/04/2024,NEFT TRANSFER OUTWARD,990000.00,0.00,3585000.00
10/04/2024,EMI HDFC LOAN 123,85000.00,0.00,3500000.00
15/04/2024,UPI/GROCERY STORE/112233,1200.00,0.00,3498800.00
20/04/2024,CHEQUE RETURN BOUNCE,0.00,0.00,3498800.00
25/04/2024,DIVIDEND RECD FROM RIL,0.00,5000000.00,8498800.00
28/04/2024,NEFT OUTWARD TO VENDOR,4950000.00,0.00,3548800.00
01/05/2024,UPI/RENT MAY/445566,50000.00,0.00,3498800.00
05/05/2024,CASH DEPOSIT ATM,0.00,100000.00,3598800.00
10/05/2024,UPI/INSURANCE PREMIUM,25000.00,0.00,3573800.00
15/05/2024,SALARY CREDITS PAYROLL,0.00,3500000.00,7073800.00
20/05/2024,FD MATURITY PROCEEDS,0.00,10000000.00,17073800.00
25/05/2024,INTER TRANSFER,9900000.00,0.00,7173800.00
"""

    print("─" * 60)
    print("BankStatementAnalyzer smoke-test (synthetic CSV)")
    print("─" * 60)

    # Write to temp file
    import tempfile, os
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(_SAMPLE_CSV)
        tmp_path = tmp.name

    try:
        result = analyze_bank_statement(tmp_path, company_id="DEMO_CORP")
    finally:
        os.unlink(tmp_path)

    m = result["metrics"]
    print(f"\n── Metrics ──")
    print(f"  Transactions loaded     : {m['transaction_count']}")
    print(f"  Total credits           : ₹{m['total_annual_credits']:>15,.2f}")
    print(f"  Total debits            : ₹{m['total_annual_debits']:>15,.2f}")
    print(f"  Debit/credit ratio      : {m['debit_credit_ratio']:.4f}")
    print(f"  Avg monthly balance     : ₹{m['average_monthly_balance']:>15,.2f}")
    print(f"  Bounce count            : {m['bounce_count']}")
    print(f"  UPI percentage          : {m['upi_percentage']:.2f}%")
    print(f"  Cash deposit conc.      : {m['cash_deposit_concentration']:.2f}%")
    print(f"  Largest single credit   : ₹{m['largest_single_credit']:>15,.2f}")
    print(f"  Largest single debit    : ₹{m['largest_single_debit']:>15,.2f}")
    print(f"  Credit volatility (σ)   : ₹{m['credit_volatility']:>15,.2f}")
    print(f"\n  Monthly credits:")
    for mo, amt in m["monthly_credits"].items():
        print(f"    {mo}  ₹{amt:>15,.2f}")

    print(f"\n── Anomalies ─ total={result['anomaly_summary']['total']} "
          f"(HIGH={result['anomaly_summary']['HIGH']}, "
          f"MEDIUM={result['anomaly_summary']['MEDIUM']}) ──")
    for a in result["anomalies"]:
        print(f"  [{a['severity']:6s}] {a['type']}")
        print(f"           {a['detail']}")

    print("\n✓ BankStatementAnalyzer smoke-test complete.")
