"""
delta_writer.py — Persistence layer for intelli_credit ingestion pipeline.

Consumes the combined output of:
  - :class:`PDFParser`          (raw text, tables, doc metadata)
  - :class:`FinancialExtractor` (figures, ratios, risk clauses, directors)
  - :class:`NERExtractor`       (sentiment, entities)

…and writes into two Delta / JSON layers:

  Bronze (``bronze_documents``)
  ─────────────────────────────
  One row per ingested document — raw content preserved, no transforms.

  Silver (``silver_financials``)
  ──────────────────────────────
  One row per (company_id, fiscal_year) — structured KPIs + NER outputs.

When Databricks / Spark is unavailable the class transparently falls back to
writing JSON-line files under ``data/bronze/`` and ``data/silver/``.

Data-quality flags
──────────────────
``HIGH_CONFIDENCE``  — revenue extracted and non-zero
``LOW_CONFIDENCE``   — revenue missing or zero (written anyway, flagged)
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

logger = logging.getLogger("intelli_credit.ingestor.delta_writer")

# ---------------------------------------------------------------------------
# Project-root & local fallback paths (resolved from this file's location)
# ---------------------------------------------------------------------------
_PROJECT_ROOT   = Path(__file__).resolve().parent.parent.parent
_LOCAL_BRONZE   = _PROJECT_ROOT / "data" / "bronze"
_LOCAL_SILVER   = _PROJECT_ROOT / "data" / "silver"

_LOCAL_BRONZE.mkdir(parents=True, exist_ok=True)
_LOCAL_SILVER.mkdir(parents=True, exist_ok=True)

# Quality-flag constants
QUALITY_HIGH = "HIGH_CONFIDENCE"
QUALITY_LOW  = "LOW_CONFIDENCE"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_utc() -> str:
    """Return current UTC time as ISO-8601 string (without microseconds)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _to_json_str(obj: Any) -> str:
    """Serialise *obj* to a compact JSON string; return '{}' on failure."""
    try:
        return json.dumps(obj, ensure_ascii=False)
    except (TypeError, ValueError):
        return "{}"


def _quality_flag(revenue: float | None) -> str:
    """Return quality flag based on revenue value."""
    if revenue is None or revenue == 0.0:
        return QUALITY_LOW
    return QUALITY_HIGH


def _append_jsonl(filepath: Path, record: dict) -> None:
    """Append *record* as a single JSON line to *filepath* (creates if absent).

    Uses a module-level lock to prevent concurrent writes from corrupting
    the file when multiple pipeline jobs run in parallel.
    """
    with _JSONL_LOCK:
        with filepath.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    logger.debug("Appended record to %s", filepath)


# Module-level write lock for JSONL file safety
_JSONL_LOCK = Lock()


def _read_jsonl(filepath: Path) -> list[dict]:
    """Read all JSON-line records from *filepath*; return empty list if absent."""
    if not filepath.exists():
        return []
    records = []
    with filepath.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


# ---------------------------------------------------------------------------
# Bronze record builder
# ---------------------------------------------------------------------------

def _build_bronze_record(
    pdf_result:  dict,
    company_id:  str,
    file_name:   str,
    doc_id:      str | None = None,
) -> dict:
    """
    Construct the Bronze layer record from PDFParser output.

    Parameters
    ----------
    pdf_result  : return value of ``PDFParser.parse()``
    company_id  : caller-supplied company identifier
    file_name   : original file name e.g. ``RIL_IAR_2024.pdf``
    doc_id      : optional; auto-generated UUID when omitted

    Returns
    -------
    dict with keys matching ``bronze_documents`` schema
    """
    tables_raw = pdf_result.get("tables", [])
    # Normalise: each table may already be a dict or a plain list row
    tables_serialisable = []
    for t in tables_raw:
        if isinstance(t, dict):
            tables_serialisable.append(t)
        else:
            tables_serialisable.append({"rows": t})

    return {
        "id":               doc_id or str(uuid.uuid4()),
        "company_id":       company_id,
        "source_type":      str(pdf_result.get("doc_type", "UNKNOWN")),
        "raw_text":         str(pdf_result.get("raw_text", "")),
        "extracted_tables": _to_json_str(tables_serialisable),
        "upload_timestamp": _now_utc(),
        "file_name":        file_name,
    }


# ---------------------------------------------------------------------------
# Silver record builder
# ---------------------------------------------------------------------------

def _build_silver_record(
    fin_result:  dict,
    ner_result:  dict | None,
    company_id:  str,
    fiscal_year: int,
) -> dict:
    """
    Construct the Silver layer record from FinancialExtractor + NERExtractor.

    Parameters
    ----------
    fin_result  : return value of ``FinancialExtractor.extract_financials()``
    ner_result  : return value of ``NERExtractor.analyze()``  (may be None)
    company_id  : caller-supplied company identifier
    fiscal_year : e.g. 2024

    Returns
    -------
    dict with keys matching ``silver_financials`` schema
    """
    figures   = fin_result.get("figures",  {}) or {}
    ratios    = fin_result.get("ratios",   {}) or {}
    risks     = fin_result.get("risk_clauses", []) or []
    directors = fin_result.get("directors",    []) or []

    # Figures
    revenue          = figures.get("revenue")
    ebitda           = figures.get("ebitda")
    pat              = figures.get("pat")
    total_debt       = figures.get("total_debt")
    net_worth        = figures.get("net_worth")
    interest_expense = figures.get("interest_expense")
    debt_service     = figures.get("debt_service")
    current_assets   = figures.get("current_assets")
    current_liab     = figures.get("current_liabilities")

    # Ratios
    current_ratio    = ratios.get("current_ratio")
    debt_to_equity   = ratios.get("debt_to_equity")
    interest_cov     = ratios.get("interest_coverage")
    dscr             = ratios.get("dscr")

    # NER outputs (optional)
    sentiment_score: float | None = None
    overall_sentiment: str | None = None
    auditor_flag: bool | None     = None
    entities_json: str            = "{}"

    if ner_result:
        sentiment_block = ner_result.get("sentiment") or {}
        sentiment_score    = sentiment_block.get("score")
        overall_sentiment  = sentiment_block.get("overall_sentiment")

        auditor_block    = ner_result.get("auditor") or {}
        auditor_flag     = auditor_block.get("qualified_opinion_flag")

        entities_block   = ner_result.get("entities") or {}
        entities_json    = _to_json_str(entities_block)

    # Serialise complex fields
    risk_clauses_json = _to_json_str(
        [
            {
                "clause_text":    getattr(r, "clause_text", r) if not isinstance(r, dict) else r.get("clause_text", ""),
                "matched_phrase": getattr(r, "matched_phrase", "") if not isinstance(r, dict) else r.get("matched_phrase", ""),
                "severity":       getattr(r, "severity", "") if not isinstance(r, dict) else r.get("severity", ""),
                "page_estimate":  getattr(r, "page_number_estimate", None) if not isinstance(r, dict) else r.get("page_number_estimate"),
                "context":        getattr(r, "context_snippet", "") if not isinstance(r, dict) else r.get("context_snippet", ""),
            }
            for r in risks
        ]
    )
    directors_json = _to_json_str(directors)

    quality = _quality_flag(revenue)
    if quality == QUALITY_LOW:
        logger.warning(
            "[company=%s year=%d] Revenue is missing/zero — flagging as %s.",
            company_id, fiscal_year, QUALITY_LOW,
        )

    return {
        "company_id":           company_id,
        "fiscal_year":          fiscal_year,
        # Figures
        "revenue":              revenue,
        "ebitda":               ebitda,
        "pat":                  pat,
        "total_debt":           total_debt,
        "net_worth":            net_worth,
        "interest_expense":     interest_expense,
        "debt_service":         debt_service,
        "current_assets":       current_assets,
        "current_liabilities":  current_liab,
        # Ratios
        "current_ratio":        current_ratio,
        "debt_to_equity":       debt_to_equity,
        "interest_coverage":    interest_cov,
        "dscr":                 dscr,
        # NER
        "sentiment_score":      sentiment_score,
        "overall_sentiment":    overall_sentiment,
        "auditor_flag":         auditor_flag,
        "entities_json":        entities_json,
        # Risk / governance
        "risk_clauses_json":    risk_clauses_json,
        "directors_json":       directors_json,
        # Meta
        "quality_flag":         quality,
        "extracted_at":         _now_utc(),
    }


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class DeltaWriter:
    """
    Persists ingestion pipeline outputs to Delta Lake (or local JSON files).

    Parameters
    ----------
    manager : DeltaLakeManager | None
        If provided, the writer uses the manager's Spark session.
        If ``None`` (default) the writer imports DeltaLakeManager from
        ``src.config`` — or quietly falls back to local JSON mode if PySpark
        is unavailable.
    """

    def __init__(self, manager=None) -> None:
        self._manager = manager
        self._local_mode: bool = True   # assume local until proven otherwise

        if self._manager is None:
            try:
                from src.config import get_manager  # noqa: PLC0415
                self._manager = get_manager()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "DeltaLakeManager unavailable (%s) — using local JSON mode.", exc
                )

        if self._manager is not None:
            self._local_mode = getattr(self._manager, "_local_mode", True)

        mode = "LOCAL (JSON)" if self._local_mode else "Databricks Delta Lake"
        logger.info("DeltaWriter initialised in %s mode.", mode)

    # ------------------------------------------------------------------
    # Public write entry-point
    # ------------------------------------------------------------------

    def write(
        self,
        pdf_result:  dict,
        fin_result:  dict,
        ner_result:  dict | None = None,
        *,
        company_id:  str,
        file_name:   str = "unknown.pdf",
        fiscal_year: int | None = None,
    ) -> dict[str, str]:
        """
        Orchestrate a full Bronze + Silver write for one document.

        Parameters
        ----------
        pdf_result   : ``PDFParser.parse()`` output
        fin_result   : ``FinancialExtractor.extract_financials()`` output
        ner_result   : ``NERExtractor.analyze()`` output (optional)
        company_id   : unique company key (e.g. ``"RIL"`` or ``"CIN12345"``)
        file_name    : original file name for provenance
        fiscal_year  : override fiscal year; auto-detected from the document
                       metadata or defaults to current calendar year

        Returns
        -------
        dict with ``{"bronze_id": str, "company_id": str, "fiscal_year": int,
                     "quality_flag": str}``
        """
        if fiscal_year is None:
            fiscal_year = self._infer_fiscal_year(pdf_result, fin_result)

        doc_id = str(uuid.uuid4())

        bronze_rec = _build_bronze_record(pdf_result, company_id, file_name, doc_id)
        silver_rec = _build_silver_record(fin_result, ner_result, company_id, fiscal_year)

        if self._local_mode:
            self._write_bronze_local(bronze_rec)
            self._write_silver_local(silver_rec)
        else:
            self._write_bronze_spark(bronze_rec)
            self._write_silver_spark(silver_rec)

        logger.info(
            "Wrote company=%s year=%d | bronze_id=%s | quality=%s",
            company_id, fiscal_year, doc_id, silver_rec["quality_flag"],
        )
        return {
            "bronze_id":    doc_id,
            "company_id":   company_id,
            "fiscal_year":  fiscal_year,
            "quality_flag": silver_rec["quality_flag"],
        }

    # ------------------------------------------------------------------
    # Bronze write
    # ------------------------------------------------------------------

    def write_bronze(
        self,
        pdf_result: dict,
        company_id: str,
        file_name:  str = "unknown.pdf",
        doc_id:     str | None = None,
    ) -> str:
        """
        Write only the Bronze layer for a document.

        Returns the ``id`` (UUID) assigned to the record.
        """
        rec    = _build_bronze_record(pdf_result, company_id, file_name, doc_id)
        doc_id = rec["id"]

        if self._local_mode:
            self._write_bronze_local(rec)
        else:
            self._write_bronze_spark(rec)

        logger.info("Bronze write: company=%s id=%s file=%s", company_id, doc_id, file_name)
        return doc_id

    # ------------------------------------------------------------------
    # Silver write
    # ------------------------------------------------------------------

    def write_silver(
        self,
        fin_result:  dict,
        ner_result:  dict | None = None,
        *,
        company_id:  str,
        fiscal_year: int,
    ) -> str:
        """
        Write only the Silver layer for a (company, fiscal_year) pair.

        Returns the ``quality_flag`` assigned to the record.
        """
        rec = _build_silver_record(fin_result, ner_result, company_id, fiscal_year)

        if self._local_mode:
            self._write_silver_local(rec)
        else:
            self._write_silver_spark(rec)

        logger.info(
            "Silver write: company=%s year=%d quality=%s",
            company_id, fiscal_year, rec["quality_flag"],
        )
        return rec["quality_flag"]

    # ------------------------------------------------------------------
    # Read / query
    # ------------------------------------------------------------------

    def read_company_data(self, company_id: str) -> dict:
        """
        Read all available Silver records for *company_id* and return a merged
        dict keyed by fiscal year.

        Returns
        -------
        {
          "company_id": str,
          "records": [ <silver_record>, ... ],   # sorted oldest → newest
          "latest": <silver_record> | None,
          "years_available": [int, ...],
        }
        """
        if self._local_mode:
            records = self._read_silver_local(company_id)
        else:
            records = self._read_silver_spark(company_id)

        records_sorted = sorted(records, key=lambda r: r.get("fiscal_year", 0))

        return {
            "company_id":       company_id,
            "records":          records_sorted,
            "latest":           records_sorted[-1] if records_sorted else None,
            "years_available":  [r["fiscal_year"] for r in records_sorted],
        }

    # ------------------------------------------------------------------
    # Local (JSON-line) backend
    # ------------------------------------------------------------------

    def _write_bronze_local(self, rec: dict) -> None:
        company_dir = _LOCAL_BRONZE / rec["company_id"]
        company_dir.mkdir(parents=True, exist_ok=True)
        dest = company_dir / "bronze_documents.jsonl"
        _append_jsonl(dest, rec)
        logger.debug("[local] bronze → %s", dest)

    def _write_silver_local(self, rec: dict) -> None:
        company_dir = _LOCAL_SILVER / rec["company_id"]
        company_dir.mkdir(parents=True, exist_ok=True)
        dest = company_dir / "silver_financials.jsonl"

        # Upsert semantics: replace existing row for same company+year
        existing = _read_jsonl(dest)
        updated  = [
            r for r in existing
            if r.get("fiscal_year") != rec["fiscal_year"]
        ]
        updated.append(rec)

        with dest.open("w", encoding="utf-8") as fh:
            for row in updated:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        logger.debug("[local] silver → %s", dest)

    def _read_silver_local(self, company_id: str) -> list[dict]:
        dest = _LOCAL_SILVER / company_id / "silver_financials.jsonl"
        return _read_jsonl(dest)

    # ------------------------------------------------------------------
    # Databricks / Spark backend
    # ------------------------------------------------------------------

    def _write_bronze_spark(self, rec: dict) -> None:
        """Append one row to ``bronze_documents`` Delta table."""
        try:
            from pyspark.sql import Row  # noqa: PLC0415

            spark = self._manager.spark
            row   = Row(**rec)
            df    = spark.createDataFrame([row])
            (
                df.write
                  .format("delta")
                  .mode("append")
                  .option("mergeSchema", "true")
                  .saveAsTable(f"{_db()}.bronze_documents")
            )
            logger.debug("[spark] bronze → %s.bronze_documents", _db())
        except Exception as exc:
            logger.error(
                "Spark bronze write failed (%s) — falling back to local.", exc
            )
            self._write_bronze_local(rec)

    def _write_silver_spark(self, rec: dict) -> None:
        """Upsert one row into ``silver_financials`` Delta table."""
        try:
            from delta.tables import DeltaTable  # noqa: PLC0415
            from pyspark.sql import Row           # noqa: PLC0415

            spark    = self._manager.spark
            row      = Row(**rec)
            df_new   = spark.createDataFrame([row])
            tbl_name = f"{_db()}.silver_financials"

            if DeltaTable.isDeltaTable(spark, tbl_name):
                dt = DeltaTable.forName(spark, tbl_name)
                (
                    dt.alias("old")
                    .merge(
                        df_new.alias("new"),
                        "old.company_id = new.company_id "
                        "AND old.fiscal_year = new.fiscal_year",
                    )
                    .whenMatchedUpdateAll()
                    .whenNotMatchedInsertAll()
                    .execute()
                )
            else:
                df_new.write.format("delta").mode("append").saveAsTable(tbl_name)

            logger.debug("[spark] silver → %s", tbl_name)

        except Exception as exc:
            logger.error(
                "Spark silver upsert failed (%s) — falling back to local.", exc
            )
            self._write_silver_local(rec)

    def _read_silver_spark(self, company_id: str) -> list[dict]:
        """Read Silver rows for *company_id* from Databricks."""
        try:
            spark = self._manager.spark
            df    = spark.sql(
                f"SELECT * FROM {_db()}.silver_financials "
                f"WHERE company_id = '{company_id}'"
            )
            return [row.asDict() for row in df.collect()]
        except Exception as exc:
            logger.error(
                "Spark silver read failed (%s) — falling back to local.", exc
            )
            return self._read_silver_local(company_id)

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _infer_fiscal_year(pdf_result: dict, fin_result: dict) -> int:
        """
        Best-effort fiscal-year extraction.

        Looks (in order):
        1. ``fin_result["metadata"]["fiscal_year"]``
        2. Regex search for "FY20XX" / "20XX-YY" in first 2 000 chars of raw text
        3. Current calendar year
        """
        fy = (fin_result.get("metadata") or {}).get("fiscal_year")
        if isinstance(fy, int) and 2000 <= fy <= 2099:
            return fy

        raw_text = pdf_result.get("raw_text", "")[:2000]
        import re
        m = re.search(r"(?:FY|F\.Y\.?)\s*(\d{4})", raw_text, re.IGNORECASE)
        if m:
            return int(m.group(1))
        m = re.search(r"\b(20\d{2})-\d{2}\b", raw_text)
        if m:
            return int(m.group(1))
        m = re.search(r"\b(20\d{2})\b", raw_text)
        if m:
            return int(m.group(1))

        return datetime.now(timezone.utc).year


def _db() -> str:
    """Return the Databricks database name from config (imported lazily)."""
    try:
        from src.config import DATABRICKS_DATABASE  # noqa: PLC0415
        return DATABRICKS_DATABASE
    except Exception:  # noqa: BLE001
        return "intelli_credit"


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

def get_writer(manager=None, force_local: bool = False) -> DeltaWriter:
    """
    Return a :class:`DeltaWriter` instance.

    Parameters
    ----------
    manager      : optional DeltaLakeManager (auto-resolved when None)
    force_local  : bypass Databricks probe and always use JSON mode
    """
    if force_local:
        # Wrap a local-mode manager so DeltaWriter sets _local_mode=True
        class _LocalManager:
            _local_mode = True
        return DeltaWriter(manager=_LocalManager())
    return DeltaWriter(manager=manager)


# ---------------------------------------------------------------------------
# Self-test (run as __main__)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json as _json

    # ── Minimal stub data that mirrors real pipeline outputs ────────────────
    _pdf_stub = {
        "doc_type":          "ANNUAL_REPORT",
        "company_name_guess": "Reliance Industries Limited",
        "pages_processed":   5,
        "raw_text":          (
            "Reliance Industries Limited FY2024 Annual Report.\n"
            "Total Revenue: Rs. 9,01,532 crore\n"
            "EBITDA: Rs. 1,78,677 crore\n"
            "[PAGE 1]\nINDEPENDENT AUDITOR'S REPORT …"
        ),
        "tables": [
            {
                "table_id": "t1",
                "headers":  ["Particulars", "FY2024", "FY2023"],
                "rows":     [["Total Revenue", "9,01,532", "8,80,014"]],
            }
        ],
        "metadata": {
            "page_count":           159,
            "is_scanned":           False,
            "digital_pages":        159,
            "scanned_pages":        0,
            "extraction_confidence": 1.0,
            "pdf_path":             "data/raw/RIL_IAR_2024.pdf",
            "ocr_lang":             "eng+hin",
        },
    }

    _fin_stub = {
        "figures": {
            "revenue":           901532.0,
            "ebitda":            178677.0,
            "pat":               69621.0,
            "total_debt":        None,
            "net_worth":         None,
            "interest_expense":  None,
            "debt_service":      None,
            "current_assets":    None,
            "current_liabilities": None,
        },
        "ratios": {
            "current_ratio":    None,
            "debt_to_equity":   None,
            "interest_coverage": None,
            "dscr":             None,
        },
        "risk_clauses": [],
        "directors":    [{"name": "Mukesh D. Ambani", "designation": "Chairman"}],
        "metadata":     {"fiscal_year": 2024},
    }

    _ner_stub = {
        "sentiment": {
            "overall_sentiment": "positive",
            "score":             0.1538,
            "chunk_count":       1,
        },
        "auditor": {
            "auditor_section_found": True,
            "overall_sentiment":     "neutral",
            "score":                 0.0123,
            "qualified_opinion_flag": False,
        },
        "entities": {
            "ORG":    ["Reliance Industries Limited"],
            "PERSON": [],
            "MONEY":  ["Rs. 9,01,532 crore", "Rs. 1,78,677 crore"],
            "MISC":   [],
        },
    }

    print("─" * 60)
    print("DeltaWriter smoke-test (local JSON mode)")
    print("─" * 60)

    writer = get_writer(force_local=True)

    result = writer.write(
        _pdf_stub,
        _fin_stub,
        _ner_stub,
        company_id="RIL",
        file_name="RIL_IAR_2024.pdf",
        fiscal_year=2024,
    )
    print("\nwrite() result:")
    print(_json.dumps(result, indent=2))

    # ── Second write with zero revenue → LOW_CONFIDENCE ────────────────────
    _fin_zero = dict(_fin_stub)
    _fin_zero["figures"] = dict(_fin_stub["figures"])
    _fin_zero["figures"]["revenue"] = 0.0
    _fin_zero["metadata"] = {"fiscal_year": 2023}

    result2 = writer.write(
        _pdf_stub,
        _fin_zero,
        None,
        company_id="RIL",
        file_name="RIL_IAR_2023.pdf",
        fiscal_year=2023,
    )
    print("\nwrite() result (zero revenue):")
    print(_json.dumps(result2, indent=2))

    # ── Read back ───────────────────────────────────────────────────────────
    company_data = writer.read_company_data("RIL")
    print(f"\nread_company_data('RIL') → {len(company_data['records'])} record(s)")
    print(f"  years_available : {company_data['years_available']}")
    latest = company_data["latest"]
    print(f"  latest year     : {latest['fiscal_year']}")
    print(f"  latest quality  : {latest['quality_flag']}")
    print(f"  revenue (Cr)    : {latest['revenue']}")
    print(f"  sentiment       : {latest['overall_sentiment']} ({latest['sentiment_score']})")
    ents = _json.loads(latest["entities_json"])
    print(f"  ORG entities    : {ents.get('ORG', [])}")
    print("\n✓ DeltaWriter smoke-test complete.")
