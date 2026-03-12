"""
CAM generation endpoints:
  POST /cam/generate          — async: generate CAM PDF (via LaTeX), returns job_id
  GET  /cam/jobs/{id}         — poll job / check status
  GET  /cam/jobs/{id}/download — stream the PDF document
  POST /cam/five-cs           — generate Five C's narrative (sync)
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse

from src.api.dependencies import AuthDep, JobStoreDep, run_in_thread
from src.api.job_store import JobStatus
from src.api.schemas.cam import (
    CAMGenerateRequest,
    CAMStatusResponse,
    FiveCsText,
    FiveCsWriteRequest,
)
from src.api.schemas.common import JobRef

router = APIRouter(prefix="/cam", tags=["cam"])


@router.post(
    "/generate",
    response_model=JobRef,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Asynchronously generate a Credit Assessment Memorandum (PDF via LaTeX)",
)
async def generate_cam(
    _auth: AuthDep,
    body: CAMGenerateRequest,
    store: JobStoreDep,
    request: Request,
) -> JobRef:
    job = await store.create(
        "cam_generate",
        meta={"company_id": body.company_id, "company_name": body.company_name},
    )

    async def _bg():
        await store.update(job.job_id, JobStatus.RUNNING)
        try:
            result = await run_in_thread(_generate_cam_sync, body, job.job_id)
            await store.update(job.job_id, JobStatus.DONE, result=result)
        except Exception as exc:
            await store.update(job.job_id, JobStatus.FAILED, error=str(exc))

    asyncio.create_task(_bg())

    base = str(request.base_url).rstrip("/")
    return JobRef(
        job_id=job.job_id,
        job_type="cam_generate",
        status=job.status.value,
        poll_url=f"{base}/api/v1/cam/jobs/{job.job_id}",
        created_at=job.created_at,
    )


def _generate_cam_sync(body: CAMGenerateRequest, job_id: str) -> dict:
    """Synchronous CAM generation — runs in thread pool."""
    from src.api.services.cam_service import generate_cam, generate_five_cs
    from src.api.config import settings

    # Build five_cs if not supplied
    five_cs = body.five_cs_text.model_dump() if body.five_cs_text else None
    if not five_cs:
        five_cs = generate_five_cs(
            company_data={
                "name": body.company_name,
                "cin": body.cin or "",
                "directors": [],
            },
            financials={},
            research_report=body.research_report or {},
            scoring_result=body.scoring_result or {},
        )

    company_data = {
        "name": body.company_name,
        "cin": body.cin or "",
        "loan_amount_requested": body.loan_amount_requested,
        "tenure": body.loan_tenure_months,
        "decision": body.decision or "PENDING",
        "recommended_amount": body.recommended_amount,
        "interest_rate": body.interest_rate,
    }

    scoring = body.scoring_result or {
        "risk_score": 5.0,
        "risk_band": "MEDIUM",
        "default_probability": 0.35,
    }
    research = body.research_report or {}

    out_path = settings.outputs_dir / f"CAM_{body.company_id}_{job_id[:8]}.pdf"
    path = generate_cam(
        company_data=company_data,
        scoring_result=scoring,
        research_report=research,
        five_cs_text=five_cs,
        output_path=out_path,
    )

    return {
        "file_path": str(path),
        "file_name": path.name,
        "download_url": f"/api/v1/cam/jobs/{job_id}/download",
    }


@router.get(
    "/jobs/{job_id}",
    response_model=CAMStatusResponse,
    summary="Poll CAM generation job status",
)
async def cam_job_status(
    _auth: AuthDep,
    job_id: str,
    store: JobStoreDep,
) -> CAMStatusResponse:
    job = await store.get(job_id)
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Job {job_id!r} not found")

    download_url = None
    file_name = None
    if job.status == JobStatus.DONE and job.result:
        download_url = job.result.get("download_url")
        file_name = job.result.get("file_name")

    return CAMStatusResponse(
        job_id=job.job_id,
        status=job.status.value,
        download_url=download_url,
        file_name=file_name,
        error=job.error,
    )


@router.get(
    "/jobs/{job_id}/download",
    summary="Download the generated CAM PDF document",
)
async def download_cam(
    _auth: AuthDep,
    job_id: str,
    store: JobStoreDep,
):
    job = await store.get(job_id)
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Job {job_id!r} not found")
    if job.status != JobStatus.DONE:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Job is {job.status.value} — not yet ready for download",
        )
    if not job.result:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "No file result in job")

    file_path = Path(job.result.get("file_path", ""))
    if not file_path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "CAM file not found on server")

    suffix = file_path.suffix.lower()
    media_type = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if suffix == ".docx"
        else "application/pdf"
    )

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=file_path.name,
    )


@router.post(
    "/five-cs",
    summary="Generate Five C's narrative sections (synchronous, uses LLM writer)",
)
async def five_cs(
    _auth: AuthDep,
    body: FiveCsWriteRequest,
) -> dict:
    try:
        from src.api.services.cam_service import generate_five_cs
        result = await run_in_thread(
            generate_five_cs,
            body.company_data,
            body.financials,
            body.research_report,
            body.scoring_result,
        )
    except Exception as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc))
    return result
