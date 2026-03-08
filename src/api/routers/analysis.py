"""
Full pipeline endpoints:
  POST /analysis/pipeline       — async: run 5-stage pipeline, returns job_id
  GET  /analysis/jobs/{id}      — poll job status + results
  GET  /analysis/{company_id}/latest — get latest pipeline results stored for company
"""
from __future__ import annotations

import asyncio
import re
from typing import Annotated, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status

from src.api.dependencies import AuthDep, JobStoreDep, run_in_thread
from src.api.job_store import JobStatus
from src.api.schemas.common import JobRef, JobStatusResponse

router = APIRouter(prefix="/analysis", tags=["analysis"])

_MAX_MB = 50


def _slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]", "_", name).upper()
    return re.sub(r"_+", "_", s).strip("_")[:40]


# ── POST /analysis/pipeline ───────────────────────────────────────────────────

@router.post(
    "/pipeline",
    response_model=JobRef,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run the full 5-stage credit analysis pipeline (async)",
    description="""
Upload all company documents and trigger the pipeline:

1. **PDF extraction** — financial figures, ratios, directors, NER, sentiment
2. **Bank analysis** — bounce count, average balance, anomaly flags
3. **GST reconciliation** — ITC gap, fictitious vendors, health score
4. **External research** — news, eCourts, MCA, RBI via LangGraph agent
5. **Credit scoring** — LightGBM model + SHAP explanations + decision

Returns a `job_id` immediately.  Poll `GET /analysis/jobs/{job_id}` for results.
""",
)
async def run_pipeline(
    _auth: AuthDep,
    store: JobStoreDep,
    request: Request,
    # ── Metadata fields ──────────────────────────────────────────────
    company_name: Annotated[str, Form()],
    company_id: Annotated[Optional[str], Form()] = None,
    cin: Annotated[Optional[str], Form()] = None,
    loan_amount_requested: Annotated[Optional[float], Form()] = None,
    loan_tenure_months: Annotated[Optional[int], Form()] = None,
    fiscal_year: Annotated[Optional[int], Form()] = None,
    # ── File uploads ─────────────────────────────────────────────────
    pdf_file: Annotated[Optional[UploadFile], File(description="Annual report PDF")] = None,
    bank_file: Annotated[Optional[UploadFile], File(description="Bank statement CSV/Excel")] = None,
    gst_files: Annotated[Optional[List[UploadFile]], File(description="GSTR JSON files")] = None,
) -> JobRef:
    cid = company_id or _slug(company_name)

    # Read all bytes eagerly (cannot read in background after response)
    pdf_bytes: bytes | None = None
    pdf_fname = "upload.pdf"
    if pdf_file and pdf_file.filename:
        pdf_bytes = await pdf_file.read()
        if len(pdf_bytes) > _MAX_MB * 1024 * 1024:
            raise HTTPException(413, "PDF file exceeds 50 MB limit")
        pdf_fname = pdf_file.filename

    bank_bytes: bytes | None = None
    bank_fname = "bank.csv"
    if bank_file and bank_file.filename:
        bank_bytes = await bank_file.read()
        bank_fname = bank_file.filename

    gst_tuples: list[tuple[str, bytes]] = []
    if gst_files:
        for gf in gst_files:
            if gf and gf.filename:
                bc = await gf.read()
                gst_tuples.append((gf.filename, bc))

    job = await store.create(
        "pipeline",
        meta={
            "company_id": cid,
            "company_name": company_name,
            "has_pdf": pdf_bytes is not None,
            "has_bank": bank_bytes is not None,
            "gst_file_count": len(gst_tuples),
        },
    )

    async def _bg():
        await store.update(job.job_id, JobStatus.RUNNING)
        progress: list[tuple[int, str]] = []

        def _cb(pct: int, msg: str):
            progress.append((pct, msg))

        try:
            from src.api.services.pipeline_service import run_full_pipeline
            result = await run_in_thread(
                run_full_pipeline,
                company_name,
                cid,
                cin,
                loan_amount_requested,
                loan_tenure_months,
                fiscal_year,
                pdf_bytes,
                pdf_fname,
                bank_bytes,
                bank_fname,
                gst_tuples,
                _cb,
            )
            result["_progress"] = progress
            await store.update(job.job_id, JobStatus.DONE, result=result)
        except Exception as exc:
            await store.update(job.job_id, JobStatus.FAILED, error=str(exc))

    asyncio.create_task(_bg())

    base = str(request.base_url).rstrip("/")
    return JobRef(
        job_id=job.job_id,
        job_type="pipeline",
        status=job.status.value,
        poll_url=f"{base}/api/v1/analysis/jobs/{job.job_id}",
        created_at=job.created_at,
    )


# ── GET /analysis/jobs/{job_id} ───────────────────────────────────────────────

@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    summary="Poll a pipeline job for status and results",
)
async def get_pipeline_job(
    _auth: AuthDep,
    job_id: str,
    store: JobStoreDep,
) -> JobStatusResponse:
    job = await store.get(job_id)
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Job {job_id!r} not found")
    return JobStatusResponse(**job.to_dict())
