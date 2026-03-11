"""
test_feature_builder.py — Unit tests for FeatureBuilder.

Tests feature vector construction, imputation tracking, and FEATURE_NAMES
integrity — all without requiring real data files.

Usage:
    python tests/test_feature_builder.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

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


# ── Imports ───────────────────────────────────────────────────────────────────
from src.scorer.feature_builder import FeatureBuilder


def test_feature_names_integrity():
    """FEATURE_NAMES must be exactly 35 unique strings."""
    print(f"\n{_CYAN}{_BOLD}── FEATURE_NAMES Integrity ──{_RESET}")
    fb = FeatureBuilder()
    names = fb.FEATURE_NAMES
    check("FEATURE_NAMES length is 35", len(names) == 35, f"got {len(names)}")
    check("All names are strings", all(isinstance(n, str) for n in names))
    check("All names are unique", len(set(names)) == len(names))
    check("No empty names", all(len(n.strip()) > 0 for n in names))
    # Check specific expected features
    expected = {
        "debt_to_equity", "bounce_count", "gst_health_score",
        "news_risk_score", "ews_score", "qualitative_adjustment",
    }
    check("Expected features present", expected.issubset(set(names)),
          f"missing: {expected - set(names)}")


def test_build_returns_correct_shape():
    """build_feature_vector should return (dict[35 keys], list[35 names])."""
    print(f"\n{_CYAN}{_BOLD}── build_feature_vector shape ──{_RESET}")
    fb = FeatureBuilder()

    # Patch all data loaders to return empty/defaults
    with patch.object(fb, '_load_silver', return_value={}), \
         patch.object(fb, '_load_bank_metrics', return_value={}), \
         patch.object(fb, '_load_ews', return_value={}), \
         patch.object(fb, '_load_research', return_value={}), \
         patch.object(fb, '_load_qualitative', return_value={}), \
         patch.object(fb, '_persist_gold', return_value=None):

        fv, names = fb.build_feature_vector("TEST_COMPANY")

        check("Feature dict is a dict", isinstance(fv, dict))
        check("Feature dict has 35 keys", len(fv) == 35, f"got {len(fv)}")
        check("Feature names list has 35 items", len(names) == 35)
        check("All values are numeric", all(isinstance(v, (int, float)) for v in fv.values()))
        check("Names match FEATURE_NAMES", names == fb.FEATURE_NAMES)


def test_imputed_defaults_on_empty_data():
    """When all data sources are empty, vector should still be valid with safe defaults."""
    print(f"\n{_CYAN}{_BOLD}── Imputed defaults ──{_RESET}")
    fb = FeatureBuilder()

    with patch.object(fb, '_load_silver', return_value={}), \
         patch.object(fb, '_load_bank_metrics', return_value={}), \
         patch.object(fb, '_load_ews', return_value={}), \
         patch.object(fb, '_load_research', return_value={}), \
         patch.object(fb, '_load_qualitative', return_value={}), \
         patch.object(fb, '_persist_gold', return_value=None):

        fv, _ = fb.build_feature_vector("EMPTY_CO")

        # All values should be finite numbers (no NaN, no inf)
        import math
        check("No NaN values", not any(math.isnan(v) for v in fv.values()))
        check("No inf values", not any(math.isinf(v) for v in fv.values()))

        # Safe defaults from config should be used
        from src.config import SAFE_DEFAULT_GST_HEALTH, SAFE_DEFAULT_NEWS_RISK
        check("GST health uses safe default",
              fv.get("gst_health_score", -1) == SAFE_DEFAULT_GST_HEALTH,
              f"got {fv.get('gst_health_score')}")
        check("News risk uses safe default",
              fv.get("news_risk_score", -1) == SAFE_DEFAULT_NEWS_RISK,
              f"got {fv.get('news_risk_score')}")


def test_company_id_normalisation():
    """Company ID should be stripped and uppercased."""
    print(f"\n{_CYAN}{_BOLD}── Company ID normalisation ──{_RESET}")
    fb = FeatureBuilder()

    captured_ids = []

    original_load = fb._load_silver

    def spy_silver(cid):
        captured_ids.append(cid)
        return {}

    with patch.object(fb, '_load_silver', side_effect=spy_silver), \
         patch.object(fb, '_load_bank_metrics', return_value={}), \
         patch.object(fb, '_load_ews', return_value={}), \
         patch.object(fb, '_load_research', return_value={}), \
         patch.object(fb, '_load_qualitative', return_value={}), \
         patch.object(fb, '_persist_gold', return_value=None):

        fb.build_feature_vector("  test_co  ")
        check("Company ID uppercased", captured_ids[0] == "TEST_CO")


def test_with_populated_silver():
    """When Silver data is present, financial ratios should be extracted."""
    print(f"\n{_CYAN}{_BOLD}── With Silver data ──{_RESET}")
    fb = FeatureBuilder()

    silver_data = {
        "debt_to_equity": 1.5,
        "current_ratio": 2.0,
        "interest_coverage": 3.5,
        "dscr": 1.8,
        "pat_margin": 0.12,
        "roce": 0.15,
        "revenue_growth_3y": 0.08,
    }

    with patch.object(fb, '_load_silver', return_value=silver_data), \
         patch.object(fb, '_load_bank_metrics', return_value={}), \
         patch.object(fb, '_load_ews', return_value={}), \
         patch.object(fb, '_load_research', return_value={}), \
         patch.object(fb, '_load_qualitative', return_value={}), \
         patch.object(fb, '_persist_gold', return_value=None):

        fv, _ = fb.build_feature_vector("SILVER_CO")

        check("debt_to_equity from silver", fv["debt_to_equity"] == 1.5)
        check("current_ratio from silver", fv["current_ratio"] == 2.0)
        check("pat_margin from silver", fv["pat_margin"] == 0.12)


def test_with_bank_metrics():
    """Bank metrics should flow into feature vector."""
    print(f"\n{_CYAN}{_BOLD}── With Bank metrics ──{_RESET}")
    fb = FeatureBuilder()

    bank_data = {
        "avg_monthly_balance": 5000000.0,
        "debit_credit_ratio": 0.85,
        "bounce_count": 3,
        "upi_concentration": 0.25,
    }

    with patch.object(fb, '_load_silver', return_value={}), \
         patch.object(fb, '_load_bank_metrics', return_value=bank_data), \
         patch.object(fb, '_load_ews', return_value={}), \
         patch.object(fb, '_load_research', return_value={}), \
         patch.object(fb, '_load_qualitative', return_value={}), \
         patch.object(fb, '_persist_gold', return_value=None):

        fv, _ = fb.build_feature_vector("BANK_CO")

        check("bounce_count from bank", fv["bounce_count"] == 3)
        check("debit_credit_ratio from bank", fv["debit_credit_ratio"] == 0.85)


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n{_BOLD}{'='*60}")
    print(f"  FeatureBuilder Unit Tests")
    print(f"{'='*60}{_RESET}")

    test_feature_names_integrity()
    test_build_returns_correct_shape()
    test_imputed_defaults_on_empty_data()
    test_company_id_normalisation()
    test_with_populated_silver()
    test_with_bank_metrics()

    exit_code = report()
    sys.exit(exit_code)
