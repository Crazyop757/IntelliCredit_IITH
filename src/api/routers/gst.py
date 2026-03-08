"""
GST analysis endpoints:
  POST /gst/reconcile           — reconcile ITC + turnover for a stored company
  POST /gst/ews                 — run EWS engine
  POST /gst/gnn/predict         — GNN circular-trading fraud prediction
  GET  /gst/graph               — build & analyse transaction graph
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, HTTPException, Query, status

from src.api.dependencies import AuthDep, run_in_thread
from src.api.schemas.gst import (
    EWSRequest,
    EWSResponse,
    GNNPredictResponse,
    GSTReconcileRequest,
    GSTReconcileResponse,
    GraphBuildResponse,
)

router = APIRouter(prefix="/gst", tags=["gst"])


@router.post(
    "/reconcile",
    response_model=GSTReconcileResponse,
    summary="Run full GST reconciliation for a stored company",
)
async def reconcile(
    _auth: AuthDep,
    body: GSTReconcileRequest,
) -> GSTReconcileResponse:
    from src.api.services.gst_service import run_reconciliation
    from src.api.schemas.gst import (
        ITCMonthlyEntry,
        ITCReconciliationResult,
        ITCReconciliationSummary,
        TurnoverMonthlyEntry,
        TurnoverReconciliationResult,
        TurnoverReconciliationSummary,
        FictitiousVendorResult,
        GSTHealthScore,
    )

    try:
        report = await run_in_thread(run_reconciliation, body.company_id)
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    except Exception as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc))

    # ── ITC reconciliation ─────────────────────────────────────────────
    itc_raw = report.get("itc_reconciliation") or {}
    itc_monthly = [
        ITCMonthlyEntry(**{k: v for k, v in m.items() if k in ITCMonthlyEntry.model_fields})
        for m in (itc_raw.get("monthly") or [])
    ]
    itc_s = itc_raw.get("summary") or {}
    itc_result = ITCReconciliationResult(
        monthly=itc_monthly,
        summary=ITCReconciliationSummary(**{k: itc_s.get(k) for k in ITCReconciliationSummary.model_fields}),
    )

    # ── Turnover reconciliation ────────────────────────────────────────
    tv_raw = report.get("turnover_reconciliation") or {}
    tv_monthly = [
        TurnoverMonthlyEntry(**{k: v for k, v in m.items() if k in TurnoverMonthlyEntry.model_fields})
        for m in (tv_raw.get("monthly") or [])
    ]
    tv_s = tv_raw.get("summary") or {}
    tv_result = TurnoverReconciliationResult(
        monthly=tv_monthly,
        summary=TurnoverReconciliationSummary(**{k: tv_s.get(k) for k in TurnoverReconciliationSummary.model_fields}),
    )

    # ── Fictitious vendors ─────────────────────────────────────────────
    fv_raw = report.get("fictitious_vendors") or {}
    fv_s = fv_raw.get("summary") or {}
    fv_result = FictitiousVendorResult(
        fictitious_gstins=fv_raw.get("fictitious_gstins") or [],
        fictitious_vendor_count=fv_s.get("fictitious_vendor_count", 0),
        risk=fv_s.get("risk"),
        known_2a_supplier_count=fv_s.get("known_2a_supplier_count", 0),
        details=fv_raw.get("details"),
    )

    # ── Health score ───────────────────────────────────────────────────
    hs_raw = report.get("health_score") or {}
    hs = GSTHealthScore(
        score=float(hs_raw.get("score") or 0),
        max=float(hs_raw.get("max") or 10),
        grade=hs_raw.get("grade") or "D",
        components=hs_raw.get("components"),
    ) if hs_raw else None

    return GSTReconcileResponse(
        company_id=body.company_id,
        itc_reconciliation=itc_result,
        turnover_reconciliation=tv_result,
        fictitious_vendors=fv_result,
        health_score=hs,
    )


@router.post(
    "/ews",
    response_model=EWSResponse,
    summary="Run the 8-flag Early Warning System for a company",
)
async def ews(
    _auth: AuthDep,
    body: EWSRequest,
) -> EWSResponse:
    from src.api.services.gst_service import run_ews
    from src.api.schemas.gst import EWSFlag

    try:
        report = await run_in_thread(run_ews, body.company_id)
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    except Exception as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc))

    flags_raw = report.get("flags") or {}
    weights = report.get("weights") or {}
    flag_list = []
    for flag_name, level in flags_raw.items():
        w = float(weights.get(flag_name, 0))
        lvl_mult = {"HIGH": 1.0, "MEDIUM": 0.5, "LOW": 0.25, "CLEAR": 0.0}.get(level, 0.0)
        flag_list.append(
            EWSFlag(
                flag_name=flag_name,
                level=level,
                weight=w,
                weighted_contribution=round(w * lvl_mult, 4),
            )
        )

    return EWSResponse(
        company_id=body.company_id,
        ews_score=float(report.get("ews_score") or 0),
        sma_classification=report.get("sma_classification") or "SMA-0",
        flags=flag_list,
        summary=report.get("summary"),
        full_report=report,
    )


@router.post(
    "/gnn/predict",
    response_model=GNNPredictResponse,
    summary="GNN-based circular-trading fraud prediction",
)
async def gnn_predict(
    _auth: AuthDep,
    company_id: str,
) -> GNNPredictResponse:
    from src.api.services.gst_service import run_gnn_predict
    from src.api.schemas.gst import GNNPrediction

    try:
        result = await run_in_thread(run_gnn_predict, company_id)
    except Exception as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc))

    preds = [GNNPrediction(**p) for p in (result.get("predictions") or [])]
    return GNNPredictResponse(
        company_id=company_id,
        predictions=preds,
        circular_patterns=result.get("circular_patterns", []),
        suspicious_clusters=result.get("suspicious_clusters", []),
    )


@router.get(
    "/graph",
    response_model=GraphBuildResponse,
    summary="Build the GSTIN transaction graph across all loaded companies",
)
async def build_graph(
    _auth: AuthDep,
    visualize: Annotated[bool, Query(description="Save a PNG visualization to outputs/")] = False,
) -> GraphBuildResponse:
    from src.api.services.gst_service import build_graph as _svc

    try:
        result = await run_in_thread(_svc, None, visualize)
    except Exception as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc))

    return GraphBuildResponse(**result)
