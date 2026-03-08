"""
Ingestion endpoints:
  POST /ingest/pdf          — upload PDF annual report
  POST /ingest/bank         — upload bank statement CSV/Excel
  POST /ingest/gst          — upload one or more GST JSON files
  POST /ingest/full         — upload all files at once (triggers full ingest)
"""
from __future__ import annotations

import re
from typing import Annotated, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from src.api.dependencies import AuthDep, run_in_thread
from src.api.schemas.ingest import (
    BankIngestResponse,
    FullIngestResponse,
    GSTIngestResponse,
    PDFIngestResponse,
)

router = APIRouter(prefix="/ingest", tags=["ingestion"])

_MAX_PDF_MB = 50
_MAX_BANK_MB = 20
_MAX_GST_MB = 10


def _slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]", "_", name).upper()
    return re.sub(r"_+", "_", s).strip("_")[:40]


# ── PDF ───────────────────────────────────────────────────────────────────────

@router.post(
    "/pdf",
    response_model=PDFIngestResponse,
    summary="Ingest a PDF annual report",
    status_code=status.HTTP_200_OK,
)
async def ingest_pdf(
    _auth: AuthDep,
    file: Annotated[UploadFile, File(description="PDF file (max 50 MB)")],
    company_name: Annotated[str, Form()],
    company_id: Annotated[Optional[str], Form()] = None,
    fiscal_year: Annotated[Optional[int], Form()] = None,
    persist: Annotated[bool, Form()] = True,
) -> PDFIngestResponse:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only .pdf files are accepted")

    content = await file.read()
    if len(content) > _MAX_PDF_MB * 1024 * 1024:
        raise HTTPException(413, f"PDF exceeds {_MAX_PDF_MB} MB limit")

    cid = company_id or _slug(company_name)

    from src.api.services.ingest_service import ingest_pdf as _svc
    result = await run_in_thread(
        _svc,
        content,
        company_name,
        cid,
        fiscal_year,
        persist,
        file.filename,
    )
    return PDFIngestResponse(**_normalise_pdf(result))


def _normalise_pdf(r: dict) -> dict:
    """Normalise raw service result into PDFIngestResponse fields."""
    from src.api.schemas.ingest import Director, FinancialFigures, FinancialRatios, RiskClause

    figures = r.get("figures") or {}
    ratios = r.get("ratios") or {}
    directors_raw = r.get("directors") or []
    rc_raw = r.get("risk_clauses") or []

    directors = []
    for d in directors_raw:
        if isinstance(d, dict):
            directors.append(Director(
                name=d.get("name", ""),
                designation=d.get("designation"),
                din=d.get("din"),
            ))

    risk_clauses = []
    for rc in rc_raw:
        if isinstance(rc, dict):
            risk_clauses.append(RiskClause(
                clause_text=rc.get("clause_text", ""),
                matched_phrase=rc.get("matched_phrase", ""),
                severity=rc.get("severity", "LOW"),
                context_snippet=rc.get("context_snippet", ""),
            ))

    return {
        "company_id": r["company_id"],
        "company_name": r["company_name"],
        "doc_type": r.get("doc_type", "UNKNOWN"),
        "pages_processed": r.get("pages_processed", 0),
        "fiscal_year": r.get("fiscal_year"),
        "figures": FinancialFigures(**{k: figures.get(k) for k in FinancialFigures.model_fields}),
        "ratios": FinancialRatios(**{k: ratios.get(k) for k in FinancialRatios.model_fields}),
        "directors": directors,
        "risk_clauses": risk_clauses,
        "sentiment": r.get("sentiment"),
        "auditor_sentiment": r.get("auditor_sentiment"),
        "entities": r.get("entities"),
        "bronze_id": r.get("bronze_id"),
        "quality_flag": r.get("quality_flag"),
    }


# ── Bank ──────────────────────────────────────────────────────────────────────

@router.post(
    "/bank",
    response_model=BankIngestResponse,
    summary="Ingest a bank statement CSV or Excel file",
)
async def ingest_bank(
    _auth: AuthDep,
    file: Annotated[UploadFile, File(description="CSV or Excel bank statement (max 20 MB)")],
    company_id: Annotated[str, Form()],
) -> BankIngestResponse:
    fname = file.filename or ""
    if not any(fname.lower().endswith(ext) for ext in (".csv", ".xlsx", ".xls")):
        raise HTTPException(400, "Only .csv / .xlsx / .xls files are accepted")

    content = await file.read()
    if len(content) > _MAX_BANK_MB * 1024 * 1024:
        raise HTTPException(413, f"Bank file exceeds {_MAX_BANK_MB} MB limit")

    from src.api.services.ingest_service import ingest_bank as _svc
    result = await run_in_thread(_svc, content, company_id, fname)
    return BankIngestResponse(**result)


# ── GST ───────────────────────────────────────────────────────────────────────

@router.post(
    "/gst",
    response_model=GSTIngestResponse,
    summary="Ingest one or more GST JSON files (GSTR-1, GSTR-2A, GSTR-3B)",
)
async def ingest_gst(
    _auth: AuthDep,
    files: Annotated[List[UploadFile], File(description="One or more GST JSON files")],
    company_id: Annotated[str, Form()],
) -> GSTIngestResponse:
    if not files:
        raise HTTPException(400, "At least one GST JSON file is required")

    gst_files: list[tuple[str, bytes]] = []
    for f in files:
        if not (f.filename or "").lower().endswith(".json"):
            raise HTTPException(400, f"File {f.filename!r} must be a .json file")
        content = await f.read()
        if len(content) > _MAX_GST_MB * 1024 * 1024:
            raise HTTPException(413, f"GST file {f.filename} exceeds {_MAX_GST_MB} MB")
        gst_files.append((f.filename or "gst.json", content))

    from src.api.services.ingest_service import ingest_gst as _svc
    result = await run_in_thread(_svc, gst_files, company_id)
    return GSTIngestResponse(**result)


# ── Full (all files at once) ──────────────────────────────────────────────────

@router.post(
    "/full",
    response_model=FullIngestResponse,
    summary="Ingest PDF + bank + GST in one request",
)
async def ingest_full(
    _auth: AuthDep,
    company_name: Annotated[str, Form()],
    company_id: Annotated[Optional[str], Form()] = None,
    fiscal_year: Annotated[Optional[int], Form()] = None,
    persist: Annotated[bool, Form()] = True,
    pdf_file: Annotated[Optional[UploadFile], File()] = None,
    bank_file: Annotated[Optional[UploadFile], File()] = None,
    gst_files: Annotated[Optional[List[UploadFile]], File()] = None,
) -> FullIngestResponse:
    cid = company_id or _slug(company_name)
    errs: list[str] = []

    pdf_result = None
    bank_result = None
    gst_result = None

    if pdf_file and pdf_file.filename:
        try:
            pdf_bytes = await pdf_file.read()
            from src.api.services.ingest_service import ingest_pdf as _pdf_svc
            pdf_raw = await run_in_thread(
                _pdf_svc, pdf_bytes, company_name, cid, fiscal_year, persist, pdf_file.filename
            )
            pdf_result = PDFIngestResponse(**_normalise_pdf(pdf_raw))
        except Exception as exc:
            errs.append(f"PDF: {exc}")

    if bank_file and bank_file.filename:
        try:
            bank_bytes = await bank_file.read()
            from src.api.services.ingest_service import ingest_bank as _bank_svc
            bank_raw = await run_in_thread(_bank_svc, bank_bytes, cid, bank_file.filename)
            bank_result = BankIngestResponse(**bank_raw)
        except Exception as exc:
            errs.append(f"Bank: {exc}")

    if gst_files:
        try:
            gst_tuples = []
            for gf in gst_files:
                if gf and gf.filename:
                    bc = await gf.read()
                    gst_tuples.append((gf.filename, bc))
            if gst_tuples:
                from src.api.services.ingest_service import ingest_gst as _gst_svc
                gst_raw = await run_in_thread(_gst_svc, gst_tuples, cid)
                gst_result = GSTIngestResponse(**gst_raw)
        except Exception as exc:
            errs.append(f"GST: {exc}")

    return FullIngestResponse(
        company_id=cid,
        company_name=company_name,
        pdf=pdf_result,
        bank=bank_result,
        gst=gst_result,
        errors=errs,
    )
