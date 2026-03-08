"""
Credit scoring endpoints:
  POST /scoring/credit           — score from feature vector or company_id
  POST /scoring/qualitative      — compute qualitative adjustment
  POST /scoring/qualitative/apply — apply delta to existing score result
  POST /scoring/feature-vector   — build 35-feature vector for a company
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from src.api.dependencies import AuthDep, run_in_thread
from src.api.schemas.scoring import (
    ApplyQualitativeRequest,
    CreditScoreRequest,
    CreditScoreResponse,
    FeatureVectorRequest,
    FeatureVectorResponse,
    QualitativeFormData,
    QualitativeScoreResponse,
    SHAPFactor,
)

router = APIRouter(prefix="/scoring", tags=["scoring"])


@router.post(
    "/credit",
    response_model=CreditScoreResponse,
    summary="Run the LightGBM credit scoring model",
)
async def credit_score(
    _auth: AuthDep,
    body: CreditScoreRequest,
) -> CreditScoreResponse:
    if not body.company_id and not body.feature_vector:
        raise HTTPException(400, "Provide either company_id or feature_vector")

    try:
        if body.feature_vector:
            from src.api.services.scoring_service import score_from_vector
            result = await run_in_thread(
                score_from_vector,
                body.feature_vector,
                body.qualitative_delta,
                body.company_id,
            )
        else:
            from src.api.services.scoring_service import score_from_company
            result = await run_in_thread(
                score_from_company,
                body.company_id,
                body.qualitative_delta,
            )
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    except Exception as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc))

    return _to_score_response(result)


@router.post(
    "/qualitative",
    response_model=QualitativeScoreResponse,
    summary="Compute qualitative credit adjustment from form data",
)
async def qualitative_score(
    _auth: AuthDep,
    body: QualitativeFormData,
) -> QualitativeScoreResponse:
    try:
        from src.api.services.scoring_service import compute_qualitative
        result = await run_in_thread(compute_qualitative, body.model_dump(exclude_none=True))
    except Exception as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc))

    return QualitativeScoreResponse(
        total_adjustment=result.get("total_adjustment", 0.0),
        severity=result.get("severity", "NEUTRAL"),
        red_flags_found=result.get("red_flags_found", []),
        breakdown=result.get("breakdown", {}),
        summary_text=result.get("summary_text", ""),
    )


@router.post(
    "/qualitative/apply",
    response_model=CreditScoreResponse,
    summary="Apply a qualitative delta to an existing credit score",
)
async def apply_qualitative(
    _auth: AuthDep,
    body: ApplyQualitativeRequest,
) -> CreditScoreResponse:
    try:
        from src.api.services.scoring_service import apply_qualitative_to_score
        result = await run_in_thread(
            apply_qualitative_to_score,
            body.scoring_result.model_dump(),
            body.qualitative_adjustment,
        )
    except Exception as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc))

    return _to_score_response(result)


@router.post(
    "/feature-vector",
    response_model=FeatureVectorResponse,
    summary="Build the 35-feature ML vector for a company from the data lake",
)
async def feature_vector(
    _auth: AuthDep,
    body: FeatureVectorRequest,
) -> FeatureVectorResponse:
    try:
        from src.api.services.scoring_service import build_feature_vector
        result = await run_in_thread(
            build_feature_vector,
            body.company_id,
            body.run_ews_live,
            body.run_research_live,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    except Exception as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc))

    return FeatureVectorResponse(**result)


# ── helpers ───────────────────────────────────────────────────────────────────

def _to_score_response(r: dict) -> CreditScoreResponse:
    def _shap(lst) -> list[SHAPFactor]:
        return [SHAPFactor(**f) for f in (lst or [])]

    return CreditScoreResponse(
        company_id=r.get("company_id"),
        default_probability=r.get("default_probability", 0.0),
        risk_score=r.get("risk_score", 0.0),
        risk_band=r.get("risk_band", "UNKNOWN"),
        raw_lgbm_proba=r.get("raw_lgbm_proba"),
        qualitative_adjusted=r.get("qualitative_adjusted", False),
        qualitative_delta=r.get("qualitative_delta"),
        top_risk_factors=_shap(r.get("top_risk_factors")),
        top_positive_factors=_shap(r.get("top_positive_factors")),
        shap_base_value=r.get("shap_base_value"),
    )
