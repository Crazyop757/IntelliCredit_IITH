"""
Companies data-lake endpoints:
  GET /companies                       — list companies with data in the lake
  GET /companies/{company_id}          — full data summary
  GET /companies/{company_id}/bronze   — raw ingestion records
  GET /companies/{company_id}/silver   — cleaned silver financials
  GET /companies/{company_id}/gold     — ML-ready feature rows
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, Query, status

from src.api.dependencies import AuthDep, run_in_thread

router = APIRouter(prefix="/companies", tags=["companies"])
log = logging.getLogger(__name__)


@router.get(
    "",
    summary="List companies that have data in the Delta Lake",
)
async def list_companies(_auth: AuthDep) -> dict[str, Any]:
    try:
        from src.ingestor.delta_writer import DeltaWriter
        result = await run_in_thread(_list_companies_sync)
    except Exception as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc))
    return result


def _list_companies_sync() -> dict[str, Any]:
    import os
    from pathlib import Path

    data_root = Path("data")
    companies: list[dict] = []

    # Scan bronze JSONL files
    bronze_root = data_root / "bronze" / "bronze_documents"
    if not bronze_root.exists():
        # Check per-company dirs
        bronze_root = data_root / "bronze"

    silver_root = data_root / "silver"

    seen: set[str] = set()

    for jsonl_path in list(data_root.rglob("bronze_documents.jsonl")):
        company_dir = jsonl_path.parent.name
        if company_dir not in seen:
            seen.add(company_dir)
            companies.append({"company_id": company_dir, "has_bronze": True})

    # Also scan silver dirs
    if silver_root.exists():
        for entry in silver_root.iterdir():
            if entry.is_dir() and entry.name not in seen:
                seen.add(entry.name)
                companies.append({"company_id": entry.name, "has_bronze": False})

    return {"companies": companies, "total": len(companies)}


@router.get(
    "/{company_id}",
    summary="Get full data summary for a company",
)
async def get_company(
    _auth: AuthDep,
    company_id: str,
) -> dict[str, Any]:
    try:
        result = await run_in_thread(_get_company_sync, company_id)
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    except Exception as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc))
    return result


def _get_company_sync(company_id: str) -> dict[str, Any]:
    from src.ingestor.delta_writer import DeltaWriter

    writer = DeltaWriter()
    data = writer.read_company_data(company_id)
    if not data:
        raise FileNotFoundError(f"No data found for company_id={company_id!r}")
    return data


@router.get(
    "/{company_id}/bronze",
    summary="Read raw bronze ingestion records",
)
async def get_bronze(
    _auth: AuthDep,
    company_id: str,
) -> dict[str, Any]:
    try:
        result = await run_in_thread(_read_bronze_sync, company_id)
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    except Exception as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc))
    return result


def _read_bronze_sync(company_id: str) -> dict[str, Any]:
    import json
    from pathlib import Path

    jsonl_path = Path("data") / "bronze" / company_id / "bronze_documents.jsonl"
    if not jsonl_path.exists():
        raise FileNotFoundError(f"No bronze data for company_id={company_id!r}")
    records = []
    with jsonl_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return {"company_id": company_id, "records": records, "count": len(records)}


@router.get(
    "/{company_id}/silver",
    summary="Read cleaned silver financial records",
)
async def get_silver(
    _auth: AuthDep,
    company_id: str,
) -> dict[str, Any]:
    try:
        result = await run_in_thread(_read_silver_sync, company_id)
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    except Exception as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc))
    return result


def _read_silver_sync(company_id: str) -> dict[str, Any]:
    from src.ingestor.delta_writer import DeltaWriter
    writer = DeltaWriter()
    data = writer.read_company_data(company_id)
    if not data or not data.get("records"):
        raise FileNotFoundError(f"No silver data for company_id={company_id!r}")
    return data


@router.get(
    "/{company_id}/gold",
    summary="Read ML-ready gold feature rows",
)
async def get_gold(
    _auth: AuthDep,
    company_id: str,
) -> dict[str, Any]:
    try:
        result = await run_in_thread(_read_gold_sync, company_id)
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    except Exception as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc))
    return result


def _read_gold_sync(company_id: str) -> dict[str, Any]:
    import json
    from pathlib import Path

    gold_dir = Path("data") / "gold" / "gold_features"
    records: list[dict] = []

    # Read per-company JSON files (e.g. RIL_features.json, RIL_ews.json)
    for json_file in sorted(gold_dir.glob(f"{company_id}_*.json")):
        try:
            with json_file.open(encoding="utf-8") as fh:
                payload = json.load(fh)
            file_type = json_file.stem.replace(f"{company_id}_", "")
            records.append({"source": file_type, **payload})
        except Exception:
            pass

    # Fallback: shared part-0.parquet filtered by company_id
    if not records:
        parquet_path = gold_dir / "part-0.parquet"
        if parquet_path.exists():
            try:
                import pandas as pd
                df = pd.read_parquet(parquet_path)
                if "company_id" in df.columns:
                    df = df[df["company_id"] == company_id]
                records = df.to_dict(orient="records")
            except Exception:
                pass

    if not records:
        raise FileNotFoundError(f"No gold data for company_id={company_id!r}")
    return {"company_id": company_id, "records": records, "count": len(records)}
