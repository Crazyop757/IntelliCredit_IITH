"""
test_credit_scorer.py — Unit tests for CreditScorer.

Tests risk band classification, qualitative adjustment, and score()
with a mock model. Does NOT require a trained model on disk.

Usage:
    python tests/test_credit_scorer.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import numpy as np

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ── ANSI helpers ──────────────────────────────────────────────────────────────
_GREEN = "\033[92m"
_RED   = "\033[91m"
_CYAN  = "\033[96m"
_RESET = "\033[0m"
_BOLD  = "\033[1m"

_results: list[tuple[str, bool, str]] = []


def check(name: str, expr: bool, detail: str = ""):
    tag = f"{_GREEN}PASS{_RESET}" if expr else f"{_RED}FAIL{_RESET}"
    _results.append((name, expr, detail))
    print(f"  [{tag}] {name}" + (f"  ({detail})" if detail and not expr else ""))


def report():
    passed = sum(1 for _, ok, _ in _results if ok)
    failed = sum(1 for _, ok, _ in _results if not ok)
    print(f"\n{_BOLD}{'='*60}")
    print(f"  {_GREEN}{passed} passed{_RESET}, {_RED}{failed} failed{_RESET}")
    print(f"{'='*60}{_RESET}")
    return 0 if failed == 0 else 1


# ── Import ────────────────────────────────────────────────────────────────────
from src.scorer.credit_scorer import CreditScorer, _classify_risk_band


def test_risk_band_classification():
    """_classify_risk_band maps score to PRIME/LOW/MEDIUM/HIGH correctly."""
    print(f"\n{_CYAN}{_BOLD}── Risk Band Classification ──{_RESET}")
    check("score 10.0 → PRIME", _classify_risk_band(10.0) == "PRIME")
    check("score 7.0 → PRIME", _classify_risk_band(7.0) == "PRIME")
    check("score 6.9 → LOW", _classify_risk_band(6.9) == "LOW")
    check("score 5.0 → LOW", _classify_risk_band(5.0) == "LOW")
    check("score 4.9 → MEDIUM", _classify_risk_band(4.9) == "MEDIUM")
    check("score 3.0 → MEDIUM", _classify_risk_band(3.0) == "MEDIUM")
    check("score 2.9 → HIGH", _classify_risk_band(2.9) == "HIGH")
    check("score 0.0 → HIGH", _classify_risk_band(0.0) == "HIGH")


def test_qualitative_adjustment_positive():
    """Positive delta (good qualitative) should lower risk score (improve it)."""
    print(f"\n{_CYAN}{_BOLD}── Qualitative Adjustment (positive) ──{_RESET}")
    scorer = CreditScorer()

    base = {"risk_score": 6.0, "risk_band": "LOW", "default_probability": 0.40}
    result = scorer.apply_qualitative_adjustment(base, 1.0)

    check("adjusted_risk_score = 5.0", result["adjusted_risk_score"] == 5.0)
    check("adjusted_risk_band = LOW", result["adjusted_risk_band"] == "LOW")
    check("model_risk_score_before_adj preserved", result["model_risk_score_before_adj"] == 6.0)
    check("delta recorded", result["qualitative_delta_applied"] == 1.0)
    check("note mentions lowered", "lowered" in result["qualitative_adjustment_note"])


def test_qualitative_adjustment_negative():
    """Negative delta (bad qualitative) should raise risk score (worsen it)."""
    print(f"\n{_CYAN}{_BOLD}── Qualitative Adjustment (negative) ──{_RESET}")
    scorer = CreditScorer()

    base = {"risk_score": 6.0, "risk_band": "LOW", "default_probability": 0.40}
    result = scorer.apply_qualitative_adjustment(base, -2.0)

    check("adjusted_risk_score = 8.0", result["adjusted_risk_score"] == 8.0)
    check("adjusted_risk_band = PRIME", result["adjusted_risk_band"] == "PRIME")
    check("note mentions raised", "raised" in result["qualitative_adjustment_note"])


def test_qualitative_adjustment_clamping():
    """Adjusted score should be clamped to [0.0, 10.0]."""
    print(f"\n{_CYAN}{_BOLD}── Qualitative Adjustment clamping ──{_RESET}")
    scorer = CreditScorer()

    # Floor to 0
    base = {"risk_score": 2.0, "risk_band": "HIGH"}
    result = scorer.apply_qualitative_adjustment(base, 5.0)
    check("Clamped to 0.0 minimum", result["adjusted_risk_score"] == 0.0)

    # Ceiling to 10
    base2 = {"risk_score": 8.0, "risk_band": "PRIME"}
    result2 = scorer.apply_qualitative_adjustment(base2, -5.0)
    check("Clamped to 10.0 maximum", result2["adjusted_risk_score"] == 10.0)


def _make_mock_artefact(feature_names, default_prob=0.15):
    """Build a mock model artefact that mimics the loaded .pkl structure."""
    mock_model = MagicMock()
    mock_model.predict_proba.return_value = np.array([[1 - default_prob, default_prob]])

    mock_scaler = MagicMock()
    mock_scaler.transform.return_value = np.zeros((1, len(feature_names)))

    return {
        "feature_names": feature_names,
        "model": mock_model,
        "scaler": mock_scaler,
    }


def test_score_with_mock_model():
    """score() should return correct dict shape with mocked model."""
    print(f"\n{_CYAN}{_BOLD}── Score with mock model ──{_RESET}")
    from src.scorer.feature_builder import FeatureBuilder
    feature_names = FeatureBuilder.FEATURE_NAMES

    scorer = CreditScorer()
    artefact = _make_mock_artefact(feature_names, default_prob=0.15)

    # Patch _load_model to return our mock artefact
    with patch.object(scorer, '_load_model', return_value=artefact), \
         patch.object(scorer, '_compute_shap', return_value={
             "top_risk_factors": [], "top_positive_factors": []
         }):

        fv = {name: 0.0 for name in feature_names}
        result = scorer.score(fv)

        check("result is dict", isinstance(result, dict))
        check("default_probability present", "default_probability" in result)
        check("risk_score present", "risk_score" in result)
        check("risk_band present", "risk_band" in result)
        check("shap_explanations present", "shap_explanations" in result)

        dp = result["default_probability"]
        check("default_probability = 0.15", dp == 0.15, f"got {dp}")

        rs = result["risk_score"]
        expected_rs = round(10.0 * (1 - 0.15), 4)
        check(f"risk_score = {expected_rs}", rs == expected_rs, f"got {rs}")

        check("risk_band = PRIME", result["risk_band"] == "PRIME",
              f"got {result['risk_band']}")


def test_score_high_risk():
    """A high default probability should produce a HIGH risk band."""
    print(f"\n{_CYAN}{_BOLD}── Score high risk ──{_RESET}")
    from src.scorer.feature_builder import FeatureBuilder
    feature_names = FeatureBuilder.FEATURE_NAMES

    scorer = CreditScorer()
    artefact = _make_mock_artefact(feature_names, default_prob=0.85)

    with patch.object(scorer, '_load_model', return_value=artefact), \
         patch.object(scorer, '_compute_shap', return_value={
             "top_risk_factors": [], "top_positive_factors": []
         }):

        fv = {name: 0.0 for name in feature_names}
        result = scorer.score(fv)

        check("risk_band = HIGH", result["risk_band"] == "HIGH",
              f"got {result['risk_band']}")
        check("risk_score < 3.0", result["risk_score"] < 3.0,
              f"got {result['risk_score']}")


def test_score_missing_features_filled():
    """score() should handle partial feature vectors gracefully."""
    print(f"\n{_CYAN}{_BOLD}── Partial feature vector ──{_RESET}")
    from src.scorer.feature_builder import FeatureBuilder
    feature_names = FeatureBuilder.FEATURE_NAMES

    scorer = CreditScorer()
    artefact = _make_mock_artefact(feature_names, default_prob=0.30)

    with patch.object(scorer, '_load_model', return_value=artefact), \
         patch.object(scorer, '_compute_shap', return_value={
             "top_risk_factors": [], "top_positive_factors": []
         }):

        # Only pass 3 out of 35 features
        fv = {"debt_to_equity": 1.5, "bounce_count": 3, "ews_score": 2.0}
        try:
            result = scorer.score(fv)
            check("Partial vector accepted", True)
            check("Returns valid result", "risk_band" in result)
        except Exception as e:
            check("Partial vector accepted", False, str(e))


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n{_BOLD}{'='*60}")
    print(f"  CreditScorer Unit Tests")
    print(f"{'='*60}{_RESET}")

    test_risk_band_classification()
    test_qualitative_adjustment_positive()
    test_qualitative_adjustment_negative()
    test_qualitative_adjustment_clamping()
    test_score_with_mock_model()
    test_score_high_risk()
    test_score_missing_features_filled()

    exit_code = report()
    sys.exit(exit_code)
