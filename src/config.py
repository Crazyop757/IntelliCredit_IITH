"""
config.py — Central configuration for intelli_credit.

Loads Databricks credentials from .env, defines all file-path constants,
and provides DeltaLakeManager (with a transparent local-Parquet fallback
when Databricks is unavailable).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
# Resolve project root no matter where this module is imported from.
PROJECT_ROOT = Path(__file__).resolve().parent.parent   # …/intelli_credit/

load_dotenv(PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# File-path constants
# ---------------------------------------------------------------------------
DATA_DIR    = PROJECT_ROOT / "data"
DATA_RAW    = DATA_DIR / "raw"
DATA_BRONZE = DATA_DIR / "bronze"
DATA_SILVER = DATA_DIR / "silver"
DATA_GOLD   = DATA_DIR / "gold"

# Ensure local directories exist so the fallback layer can always write.
for _dir in (DATA_RAW, DATA_BRONZE, DATA_SILVER, DATA_GOLD):
    _dir.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Databricks connection settings
# ---------------------------------------------------------------------------
DATABRICKS_HOST  = os.getenv("DATABRICKS_HOST", "")
DATABRICKS_TOKEN = os.getenv("DATABRICKS_TOKEN", "")

# Databricks catalog / database (override via .env if needed)
DATABRICKS_CATALOG  = os.getenv("DATABRICKS_CATALOG", "hive_metastore")
DATABRICKS_DATABASE = os.getenv("DATABRICKS_DATABASE", "intelli_credit")

# Spark / Delta remote connection string (used when running outside a cluster)
DATABRICKS_CLUSTER_ID = os.getenv("DATABRICKS_CLUSTER_ID", "")

# ---------------------------------------------------------------------------
# Table names
# ---------------------------------------------------------------------------
TABLE_BRONZE_DOCUMENTS  = f"{DATABRICKS_DATABASE}.bronze_documents"
TABLE_SILVER_FINANCIALS = f"{DATABRICKS_DATABASE}.silver_financials"
TABLE_GOLD_FEATURES     = f"{DATABRICKS_DATABASE}.gold_features"

# Local Parquet paths (fallback)
LOCAL_BRONZE_DOCUMENTS  = DATA_BRONZE / "bronze_documents"
LOCAL_SILVER_FINANCIALS = DATA_SILVER / "silver_financials"
LOCAL_GOLD_FEATURES     = DATA_GOLD   / "gold_features"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger("intelli_credit.config")

# ---------------------------------------------------------------------------
# DeltaLakeManager
# ---------------------------------------------------------------------------

class DeltaLakeManager:
    """
    Manages Delta table creation and basic I/O for intelli_credit.

    On initialisation the class tries to reach Databricks.  If the connection
    fails (or credentials are missing), it silently switches to *local mode*
    where data is stored as Parquet files under ``data/``.

    Parameters
    ----------
    force_local : bool
        Set ``True`` to skip the Databricks probe and always use local Parquet.
    """

    def __init__(self, force_local: bool = False) -> None:
        self._spark = None
        self._local_mode: bool = force_local

        if not force_local:
            self._local_mode = not self._try_connect_databricks()

        mode_label = "LOCAL (Parquet)" if self._local_mode else "Databricks Delta Lake"
        logger.info("DeltaLakeManager initialised in %s mode.", mode_label)

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------

    def _try_connect_databricks(self) -> bool:
        """
        Attempt to build a SparkSession connected to Databricks.

        Returns ``True`` on success, ``False`` on any failure.
        """
        if not DATABRICKS_HOST or not DATABRICKS_TOKEN:
            logger.warning(
                "DATABRICKS_HOST / DATABRICKS_TOKEN not set — falling back to local mode."
            )
            return False

        try:
            from pyspark.sql import SparkSession  # noqa: PLC0415

            builder = (
                SparkSession.builder.appName("intelli_credit")
                .config("spark.databricks.service.address", DATABRICKS_HOST)
                .config("spark.databricks.service.token",   DATABRICKS_TOKEN)
            )
            if DATABRICKS_CLUSTER_ID:
                builder = builder.config(
                    "spark.databricks.service.clusterId", DATABRICKS_CLUSTER_ID
                )

            self._spark = builder.getOrCreate()

            # Lightweight probe — list databases.
            self._spark.sql("SHOW DATABASES").collect()
            logger.info("Databricks connection established: %s", DATABRICKS_HOST)
            return True

        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Databricks connection failed (%s) — falling back to local mode.", exc
            )
            self._spark = None
            return False

    @property
    def spark(self):
        """Return the active SparkSession (Databricks or local)."""
        if self._spark is None:
            try:
                from pyspark.sql import SparkSession  # noqa: PLC0415

                self._spark = (
                    SparkSession.builder.appName("intelli_credit_local")
                    .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
                    .config(
                        "spark.sql.catalog.spark_catalog",
                        "org.apache.spark.sql.delta.catalog.DeltaCatalog",
                    )
                    .getOrCreate()
                )
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(
                    "PySpark is not available. Install it with: pip install pyspark delta-spark"
                ) from exc
        return self._spark

    # ------------------------------------------------------------------
    # Table DDL helpers
    # ------------------------------------------------------------------

    def _ensure_database(self) -> None:
        """Create the Databricks database if it does not exist."""
        self.spark.sql(
            f"CREATE DATABASE IF NOT EXISTS {DATABRICKS_DATABASE}"
        )

    def _create_bronze_documents(self) -> None:
        """
        bronze_documents
        ────────────────
        Raw documents ingested from any source (PDF, CSV, API, etc.).
        """
        ddl = f"""
        CREATE TABLE IF NOT EXISTS {TABLE_BRONZE_DOCUMENTS} (
            id                STRING    NOT NULL COMMENT 'Unique document identifier (UUID)',
            source_type       STRING    NOT NULL COMMENT 'Document origin: pdf | csv | api | bank_statement',
            raw_content       STRING             COMMENT 'Raw extracted text / JSON payload',
            upload_timestamp  TIMESTAMP NOT NULL COMMENT 'Ingestion timestamp (UTC)',
            company_id        STRING    NOT NULL COMMENT 'Company this document belongs to'
        )
        USING DELTA
        COMMENT 'Bronze layer: raw ingested documents, no transformations applied'
        PARTITIONED BY (company_id)
        TBLPROPERTIES (
            'delta.autoOptimize.optimizeWrite' = 'true',
            'delta.autoOptimize.autoCompact'   = 'true'
        )
        """
        self.spark.sql(ddl)
        logger.info("Table ready: %s", TABLE_BRONZE_DOCUMENTS)

    def _create_silver_financials(self) -> None:
        """
        silver_financials
        ─────────────────
        Cleaned and structured financial KPIs extracted from bronze documents.
        """
        ddl = f"""
        CREATE TABLE IF NOT EXISTS {TABLE_SILVER_FINANCIALS} (
            company_id       STRING  NOT NULL COMMENT 'Unique company identifier',
            year             INT     NOT NULL COMMENT 'Financial year (e.g. 2024)',
            revenue          DOUBLE           COMMENT 'Total revenue in INR crores',
            ebitda           DOUBLE           COMMENT 'EBITDA in INR crores',
            pat              DOUBLE           COMMENT 'Profit After Tax in INR crores',
            total_debt       DOUBLE           COMMENT 'Total outstanding debt in INR crores',
            net_worth        DOUBLE           COMMENT 'Net worth / shareholders equity in INR crores',
            current_ratio    DOUBLE           COMMENT 'Current assets / current liabilities',
            debt_to_equity   DOUBLE           COMMENT 'Total debt / net worth',
            dscr             DOUBLE           COMMENT 'Debt Service Coverage Ratio',
            extracted_at     TIMESTAMP        COMMENT 'Timestamp when this record was extracted / updated'
        )
        USING DELTA
        COMMENT 'Silver layer: cleaned financial KPIs, one row per (company, year)'
        PARTITIONED BY (year)
        TBLPROPERTIES (
            'delta.autoOptimize.optimizeWrite' = 'true',
            'delta.autoOptimize.autoCompact'   = 'true'
        )
        """
        self.spark.sql(ddl)
        logger.info("Table ready: %s", TABLE_SILVER_FINANCIALS)

    def _create_gold_features(self) -> None:
        """
        gold_features
        ─────────────
        ML-ready feature vector per company: individual risk-feature columns
        plus the aggregated credit score.
        """
        ddl = f"""
        CREATE TABLE IF NOT EXISTS {TABLE_GOLD_FEATURES} (
            company_id              STRING    NOT NULL COMMENT 'Unique company identifier',

            -- Profitability features
            revenue_growth_yoy      DOUBLE    COMMENT 'Year-over-year revenue growth rate',
            ebitda_margin           DOUBLE    COMMENT 'EBITDA / Revenue',
            pat_margin              DOUBLE    COMMENT 'PAT / Revenue',
            roe                     DOUBLE    COMMENT 'Return on Equity (PAT / Net Worth)',
            roa                     DOUBLE    COMMENT 'Return on Assets',

            -- Leverage / solvency features
            debt_to_equity          DOUBLE    COMMENT 'Total Debt / Net Worth',
            leverage_ratio          DOUBLE    COMMENT 'Total Assets / Net Worth',
            interest_coverage_ratio DOUBLE    COMMENT 'EBIT / Interest Expense',
            dscr                    DOUBLE    COMMENT 'Debt Service Coverage Ratio',
            debt_to_ebitda          DOUBLE    COMMENT 'Total Debt / EBITDA',

            -- Liquidity features
            current_ratio           DOUBLE    COMMENT 'Current Assets / Current Liabilities',
            quick_ratio             DOUBLE    COMMENT '(Current Assets - Inventory) / Current Liabilities',
            working_capital_ratio   DOUBLE    COMMENT 'Working Capital / Total Assets',
            cash_ratio              DOUBLE    COMMENT 'Cash & Equivalents / Current Liabilities',

            -- Efficiency features
            asset_turnover          DOUBLE    COMMENT 'Revenue / Total Assets',
            inventory_turnover      DOUBLE    COMMENT 'COGS / Average Inventory',

            -- Composite risk scores (0–100 scale, higher = healthier)
            liquidity_score         DOUBLE    COMMENT 'Composite liquidity risk score',
            profitability_score     DOUBLE    COMMENT 'Composite profitability score',
            solvency_score          DOUBLE    COMMENT 'Composite solvency / leverage score',
            efficiency_score        DOUBLE    COMMENT 'Composite operational efficiency score',

            -- Final output
            final_score             DOUBLE    NOT NULL COMMENT 'Aggregated credit risk score (0–100)',
            risk_band               STRING    COMMENT 'Bucketed label: LOW | MEDIUM | HIGH | CRITICAL',
            processed_at            TIMESTAMP NOT NULL COMMENT 'Feature computation timestamp (UTC)'
        )
        USING DELTA
        COMMENT 'Gold layer: ML-ready feature vectors and credit scores, one row per company'
        PARTITIONED BY (risk_band)
        TBLPROPERTIES (
            'delta.autoOptimize.optimizeWrite' = 'true',
            'delta.autoOptimize.autoCompact'   = 'true'
        )
        """
        self.spark.sql(ddl)
        logger.info("Table ready: %s", TABLE_GOLD_FEATURES)

    # ------------------------------------------------------------------
    # Public API — individual table creation (idempotent)
    # ------------------------------------------------------------------

    def create_bronze_table(self) -> None:
        """
        Idempotently create (or verify) the bronze_documents table.

        Local mode: ensures ``data/bronze/bronze_documents/`` directory exists.
        """
        if self._local_mode:
            LOCAL_BRONZE_DOCUMENTS.mkdir(parents=True, exist_ok=True)
            logger.info("[local] bronze_documents directory ready: %s", LOCAL_BRONZE_DOCUMENTS)
            return
        self._ensure_database()
        self._create_bronze_documents()

    def create_silver_table(self) -> None:
        """
        Idempotently create (or verify) the silver_financials table.

        Local mode: ensures ``data/silver/silver_financials/`` directory exists.
        """
        if self._local_mode:
            LOCAL_SILVER_FINANCIALS.mkdir(parents=True, exist_ok=True)
            logger.info("[local] silver_financials directory ready: %s", LOCAL_SILVER_FINANCIALS)
            return
        self._ensure_database()
        self._create_silver_financials()

    def create_gold_table(self) -> None:
        """
        Idempotently create (or verify) the gold_features table.

        Local mode: ensures ``data/gold/gold_features/`` directory exists.
        """
        if self._local_mode:
            LOCAL_GOLD_FEATURES.mkdir(parents=True, exist_ok=True)
            logger.info("[local] gold_features directory ready: %s", LOCAL_GOLD_FEATURES)
            return
        self._ensure_database()
        self._create_gold_features()

    def create_all_tables(self) -> None:
        """
        Idempotently create (or verify) all three Delta tables.

        In local mode, ensures all Parquet directories exist instead of
        running Spark DDL.
        """
        self.create_bronze_table()
        self.create_silver_table()
        self.create_gold_table()
        logger.info("All Delta tables initialized successfully")
        print("All Delta tables initialized successfully")

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    def read_bronze_documents(self, company_id: str | None = None):
        """
        Return a Spark DataFrame (Delta) or a pandas DataFrame (Parquet).

        Parameters
        ----------
        company_id : str or None
            When given, filters to that company only.
        """
        if self._local_mode:
            return self._read_local_parquet(LOCAL_BRONZE_DOCUMENTS, company_id)
        df = self.spark.read.table(TABLE_BRONZE_DOCUMENTS)
        if company_id:
            df = df.filter(df.company_id == company_id)
        return df

    def read_silver_financials(self, company_id: str | None = None):
        """Return silver_financials, optionally filtered by company_id."""
        if self._local_mode:
            return self._read_local_parquet(LOCAL_SILVER_FINANCIALS, company_id)
        df = self.spark.read.table(TABLE_SILVER_FINANCIALS)
        if company_id:
            df = df.filter(df.company_id == company_id)
        return df

    def read_silver(self, company_id: str | None = None):
        """Short alias for :meth:`read_silver_financials`."""
        return self.read_silver_financials(company_id)

    def read_gold_features(self, company_id: str | None = None):
        """Return gold_features, optionally filtered by company_id."""
        if self._local_mode:
            return self._read_local_parquet(LOCAL_GOLD_FEATURES, company_id)
        df = self.spark.read.table(TABLE_GOLD_FEATURES)
        if company_id:
            df = df.filter(df.company_id == company_id)
        return df

    # ------------------------------------------------------------------
    # Write helpers
    # ------------------------------------------------------------------

    def write_bronze_documents(self, df, mode: str = "append") -> None:
        """Persist a DataFrame to the bronze_documents table / Parquet path."""
        self._write(df, TABLE_BRONZE_DOCUMENTS, LOCAL_BRONZE_DOCUMENTS, mode)

    def write_bronze(self, df, table_name: str, mode: str = "append") -> None:
        """
        Write *df* to an arbitrary bronze table (or local sub-directory).

        Parameters
        ----------
        df : Spark or pandas DataFrame
            Data to persist.
        table_name : str
            Unqualified table name (e.g. ``"bronze_documents"``).  In Delta
            mode this becomes ``{database}.{table_name}``; in local mode it
            becomes ``data/bronze/{table_name}/``.
        mode : str
            ``"append"`` (default) or ``"overwrite"``.
        """
        delta_table = f"{DATABRICKS_DATABASE}.{table_name}"
        local_path  = DATA_BRONZE / table_name
        self._write(df, delta_table, local_path, mode)

    def write_silver_financials(self, df, mode: str = "overwrite") -> None:
        """Persist a DataFrame to the silver_financials table / Parquet path."""
        self._write(df, TABLE_SILVER_FINANCIALS, LOCAL_SILVER_FINANCIALS, mode)

    def write_gold_features(self, df, mode: str = "overwrite") -> None:
        """Persist a DataFrame to the gold_features table / Parquet path."""
        self._write(df, TABLE_GOLD_FEATURES, LOCAL_GOLD_FEATURES, mode)

    # ------------------------------------------------------------------
    # Internal I/O
    # ------------------------------------------------------------------

    def _write(self, df, delta_table: str, local_path: Path, mode: str) -> None:
        if self._local_mode:
            self._write_local_parquet(df, local_path, mode)
        else:
            df.write.format("delta").mode(mode).saveAsTable(delta_table)
            logger.info("Written to Delta table: %s  (mode=%s)", delta_table, mode)

    def _read_local_parquet(self, local_path: Path, company_id: str | None):
        """
        Read a local Parquet directory.

        Returns a **pandas** DataFrame when PySpark is unavailable, otherwise
        a Spark DataFrame.
        """
        if not local_path.exists():
            raise FileNotFoundError(
                f"Local Parquet path not found: {local_path}\n"
                "Has data been written to this table yet?"
            )
        try:
            df = self.spark.read.parquet(str(local_path))
            if company_id:
                df = df.filter(df.company_id == company_id)
            return df
        except Exception:  # noqa: BLE001 — PySpark unavailable
            import pandas as pd  # noqa: PLC0415

            df = pd.read_parquet(local_path)
            if company_id:
                df = df[df["company_id"] == company_id]
            return df

    def _write_local_parquet(self, df, local_path: Path, mode: str) -> None:
        """
        Write to a local Parquet directory.

        Accepts both Spark and pandas DataFrames.
        """
        try:
            # Spark DataFrame
            write_op = df.write.format("parquet")
            if mode == "overwrite":
                write_op = write_op.mode("overwrite")
            write_op.save(str(local_path))
            logger.info("Written to local Parquet: %s  (mode=%s)", local_path, mode)
        except AttributeError:
            # pandas DataFrame
            import pandas as pd  # noqa: PLC0415

            if mode == "overwrite" and local_path.exists():
                import shutil

                shutil.rmtree(local_path)
            local_path.mkdir(parents=True, exist_ok=True)
            df.to_parquet(local_path / "part-0.parquet", index=False)
            logger.info("Written to local Parquet (pandas): %s", local_path)

    # ------------------------------------------------------------------
    # Dunder methods
    # ------------------------------------------------------------------

    def __repr__(self) -> str:  # noqa: D105
        mode = "local" if self._local_mode else "databricks"
        return f"DeltaLakeManager(mode={mode!r})"


# ---------------------------------------------------------------------------
# Module-level singleton (lazily initialised)
# ---------------------------------------------------------------------------
_manager: DeltaLakeManager | None = None


def get_manager(force_local: bool = False) -> DeltaLakeManager:
    """
    Return the module-level DeltaLakeManager singleton.

    Calling this multiple times is safe — the connection is established only
    once.  Pass ``force_local=True`` to skip the Databricks probe entirely.
    """
    global _manager  # noqa: PLW0603
    if _manager is None:
        _manager = DeltaLakeManager(force_local=force_local)
    return _manager


# ---------------------------------------------------------------------------
# Quick smoke-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    mgr = get_manager()
    mgr.create_all_tables()
