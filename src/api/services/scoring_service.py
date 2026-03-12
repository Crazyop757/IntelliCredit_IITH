"""
Credit scoring service.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

_FEATURE_LABELS: dict[str, str] = {}   # populated lazily from credit_scorer module


def _get_feature_labels() -> dict[str, str]:
    global _FEATURE_LABELS
    if not _FEATURE_LABELS:
        try:
            from src.scorer.credit_scorer import _FEATURE_LABELS as _fl
            _FEATURE_LABELS = _fl
        except ImportError:
            pass
    return _FEATURE_LABELS


def score_from_vector(
    feature_vector: dict[str, float],
    qualitative_delta: float | None = None,
    company_id: str | None = None,
) -> dict[str, Any]:
    """Run CreditScorer on an explicit feature vector."""
    from src.scorer.credit_scorer import CreditScorer

    scorer = CreditScorer()
    result = scorer.score(feature_vector)

    if qualitative_delta is not None:
        result = scorer.apply_qualitative_adjustment(result, qualitative_delta)

    return _format_score_result(result, company_id=company_id, delta=qualitative_delta)


def score_from_company(
    company_id: str,
    qualitative_delta: float | None = None,
    run_ews_live: bool = False,
    run_research_live: bool = False,
) -> dict[str, Any]:
    """Build feature vector from data lake then score."""
    from src.scorer.feature_builder import FeatureBuilder
    from src.scorer.credit_scorer import CreditScorer

    fb = FeatureBuilder(
        run_ews_live=run_ews_live,
        run_research_live=run_research_live,
    )
    feat_vec, feat_names = fb.build_feature_vector(company_id)

    scorer = CreditScorer()
    result = scorer.score(feat_vec)

    if qualitative_delta is not None:
        result = scorer.apply_qualitative_adjustment(result, qualitative_delta)

    r = _format_score_result(result, company_id=company_id, delta=qualitative_delta)
    r["feature_vector"] = feat_vec
    return r


def build_feature_vector(
    company_id: str,
    run_ews_live: bool = False,
    run_research_live: bool = False,
) -> dict[str, Any]:
    from src.scorer.feature_builder import FeatureBuilder

    fb = FeatureBuilder(
        run_ews_live=run_ews_live,
        run_research_live=run_research_live,
    )
    feat_vec, feat_names = fb.build_feature_vector(company_id)
    return {"company_id": company_id, "feature_vector": feat_vec, "feature_names": feat_names}


def compute_qualitative(form_data: dict[str, Any]) -> dict[str, Any]:
    from src.scorer.qualitative_scorer import QualitativeScorer

    scorer = QualitativeScorer()
    return scorer.compute_adjustment(form_data)


def apply_qualitative_to_score(
    scoring_result: dict[str, Any],
    adjustment: float,
) -> dict[str, Any]:
    from src.scorer.credit_scorer import CreditScorer

    scorer = CreditScorer()
    return scorer.apply_qualitative_adjustment(scoring_result, adjustment)


# ── Formatting helper ─────────────────────────────────────────────────────────

def _format_score_result(
    result: dict[str, Any],
    company_id: str | None,
    delta: float | None,
) -> dict[str, Any]:
    labels = _get_feature_labels()
    shap = result.get("shap_explanations", {})

    def _fmt_factors(raw: list[dict]) -> list[dict]:
        out = []
        for item in raw or []:
            # scorer returns "feature_name"; fall back to "feature" for backwards compat
            feat = item.get("feature_name") or item.get("feature", "")
            label = item.get("human_readable_name") or labels.get(feat, feat)
            sv = item.get("shap_value", 0.0)
            out.append(
                {
                    "feature": feat,
                    "label": label,
                    "shap_value": sv,
                    "direction": "RISK_DRIVER" if sv > 0 else "PROTECTIVE",
                }
            )
        return out

    return {
        "company_id": company_id,
        "default_probability": result.get("default_probability", 0.0),
        "risk_score": result.get("risk_score", 0.0),
        "risk_band": result.get("risk_band", "UNKNOWN"),
        "raw_lgbm_proba": result.get("raw_lgbm_proba"),
        "qualitative_adjusted": delta is not None,
        "qualitative_delta": delta,
        "top_risk_factors": _fmt_factors(shap.get("top_risk_factors", [])),
        "top_positive_factors": _fmt_factors(shap.get("top_positive_factors", [])),
        "shap_base_value": shap.get("base_value"),
    }
