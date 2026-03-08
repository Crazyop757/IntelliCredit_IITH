"""
Research agent endpoints:
  POST /research/run          — async: start full agent run, returns job_id
  GET  /research/jobs/{id}    — poll job
  POST /research/synthesize   — synchronously synthesize pre-fetched sub-reports
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request, status

from src.api.dependencies import AuthDep, JobStoreDep, run_in_thread
from src.api.job_store import JobStatus
from src.api.schemas.common import JobRef, JobStatusResponse
from src.api.schemas.research import ResearchRequest, ResearchResponse, SynthesizeRequest

router = APIRouter(prefix="/research", tags=["research"])


@router.post(
    "/run",
    response_model=JobRef,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a full external intelligence research run (async)",
)
async def run_research(
    _auth: AuthDep,
    body: ResearchRequest,
    store: JobStoreDep,
    request: Request,
) -> JobRef:
    job = await store.create(
        "research",
        meta={"company_name": body.company_name, "cin": body.company_cin},
    )

    async def _bg():
        await store.update(job.job_id, JobStatus.RUNNING)
        try:
            from src.api.services.research_service import run_research as _svc
            result = await run_in_thread(
                _svc,
                body.company_name,
                body.company_cin,
                body.director_names,
            )
            await store.update(job.job_id, JobStatus.DONE, result=result)
        except Exception as exc:
            await store.update(job.job_id, JobStatus.FAILED, error=str(exc))

    asyncio.create_task(_bg())

    base = str(request.base_url).rstrip("/")
    return JobRef(
        job_id=job.job_id,
        job_type="research",
        status=job.status.value,
        poll_url=f"{base}/api/v1/research/jobs/{job.job_id}",
        created_at=job.created_at,
    )


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    summary="Poll a research job",
)
async def get_job(
    _auth: AuthDep,
    job_id: str,
    store: JobStoreDep,
) -> JobStatusResponse:
    job = await store.get(job_id)
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Job {job_id!r} not found")
    d = job.to_dict()
    return JobStatusResponse(**d)


@router.post(
    "/synthesize",
    response_model=ResearchResponse,
    summary="Synthesize pre-fetched sub-reports (synchronous)",
)
async def synthesize(
    _auth: AuthDep,
    body: SynthesizeRequest,
) -> ResearchResponse:
    try:
        from src.api.services.research_service import synthesize_reports
        result = await run_in_thread(
            synthesize_reports,
            body.news_report,
            body.ecourts_report,
            body.mca_report,
            body.rbi_report,
        )
    except Exception as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc))

    prf = result.get("promoter_risk_flag")
    if isinstance(prf, str):
        prf = {"level": prf}

    return ResearchResponse(
        company_name="",
        overall_external_risk_score=result.get("overall_external_risk_score", 5.0),
        promoter_risk_flag=prf,
        litigation_summary=result.get("litigation_summary"),
        news_summary=result.get("news_summary"),
        regulatory_compliance_summary=result.get("regulatory_compliance_summary"),
        key_red_flags=result.get("key_red_flags", []),
        positive_signals=result.get("positive_signals", []),
        recommended_action=result.get("recommended_action"),
        synthesis_method=result.get("synthesis_method"),
    )
