"""
test_analysis_router.py — API tests for /analysis/* endpoints.

Tests pipeline submission, job polling, and debug endpoints using
FastAPI TestClient with mocked pipeline execution.

Usage:
    python tests/test_analysis_router.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

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


# ── Helpers ───────────────────────────────────────────────────────────────────

_API_KEY = "dev-key-change-in-production"
_HEADERS = {"X-API-Key": _API_KEY}


def _get_test_client():
    """Create a TestClient with startup validation disabled."""
    from fastapi.testclient import TestClient
    from src.api.main import create_app
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def noop_lifespan(app):
        yield

    app = create_app()
    app.router.lifespan_context = noop_lifespan  # type: ignore
    return TestClient(app)


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_pipeline_requires_auth():
    """POST /analysis/pipeline without API key should 401."""
    print(f"\n{_CYAN}{_BOLD}── Pipeline auth required ──{_RESET}")
    client = _get_test_client()
    resp = client.post(
        "/api/v1/analysis/pipeline",
        data={"company_name": "Test Corp"},
    )
    check("No auth → 401", resp.status_code == 401, f"got {resp.status_code}")


def test_pipeline_requires_company_name():
    """POST /analysis/pipeline without company_name should 422."""
    print(f"\n{_CYAN}{_BOLD}── Pipeline requires company_name ──{_RESET}")
    client = _get_test_client()
    resp = client.post(
        "/api/v1/analysis/pipeline",
        headers=_HEADERS,
    )
    check("Missing company_name → 422", resp.status_code == 422,
          f"got {resp.status_code}")


def test_pipeline_submit_returns_job():
    """POST /analysis/pipeline with valid data returns 202 + job_id."""
    print(f"\n{_CYAN}{_BOLD}── Pipeline submit ──{_RESET}")
    client = _get_test_client()

    resp = client.post(
        "/api/v1/analysis/pipeline",
        headers=_HEADERS,
        data={"company_name": "Test Corp", "cin": "L12345MH2000PLC123456"},
    )
    check("Returns 202", resp.status_code == 202, f"got {resp.status_code}")
    data = resp.json()
    check("job_id present", "job_id" in data)
    check("job_type = pipeline", data.get("job_type") == "pipeline")
    check("poll_url present", "poll_url" in data)
    check("status = PENDING", data.get("status") == "PENDING")


def test_job_polling():
    """GET /analysis/jobs/{id} returns job status."""
    print(f"\n{_CYAN}{_BOLD}── Job polling ──{_RESET}")
    client = _get_test_client()

    # Create a job
    resp = client.post(
        "/api/v1/analysis/pipeline",
        headers=_HEADERS,
        data={"company_name": "Poll Test Corp"},
    )
    job_id = resp.json()["job_id"]

    # Poll it
    resp2 = client.get(f"/api/v1/analysis/jobs/{job_id}", headers=_HEADERS)
    check("Poll returns 200", resp2.status_code == 200, f"got {resp2.status_code}")
    data = resp2.json()
    check("job_id matches", data.get("job_id") == job_id)
    check("status is string", isinstance(data.get("status"), str))


def test_job_not_found():
    """GET /analysis/jobs/{bad_id} returns 404."""
    print(f"\n{_CYAN}{_BOLD}── Job not found ──{_RESET}")
    client = _get_test_client()
    resp = client.get(
        "/api/v1/analysis/jobs/nonexistent-id-123",
        headers=_HEADERS,
    )
    check("Not found → 404", resp.status_code == 404, f"got {resp.status_code}")


def test_debug_trace_not_found():
    """GET /debug/pipeline/{bad_id}/trace returns 404."""
    print(f"\n{_CYAN}{_BOLD}── Debug trace not found ──{_RESET}")
    client = _get_test_client()
    resp = client.get(
        "/api/v1/analysis/debug/pipeline/nonexistent/trace",
        headers=_HEADERS,
    )
    check("Trace not found → 404", resp.status_code == 404,
          f"got {resp.status_code}")


def test_debug_trace_returns_structure():
    """GET /debug/pipeline/{id}/trace returns correct trace structure."""
    print(f"\n{_CYAN}{_BOLD}── Debug trace structure ──{_RESET}")
    client = _get_test_client()

    # Create a job first
    resp = client.post(
        "/api/v1/analysis/pipeline",
        headers=_HEADERS,
        data={"company_name": "Trace Test Corp"},
    )
    job_id = resp.json()["job_id"]

    resp2 = client.get(
        f"/api/v1/analysis/debug/pipeline/{job_id}/trace",
        headers=_HEADERS,
    )
    check("Trace returns 200", resp2.status_code == 200, f"got {resp2.status_code}")
    data = resp2.json()
    check("job_id in trace", data.get("job_id") == job_id)
    check("status in trace", "status" in data)
    check("stage_results in trace", "stage_results" in data)
    check("data_quality_report in trace", "data_quality_report" in data)


def test_slug_normalisation():
    """Company name should be slug-normalised when no company_id provided."""
    print(f"\n{_CYAN}{_BOLD}── Slug normalisation ──{_RESET}")
    from src.api.routers.analysis import _slug
    check("Basic slug", _slug("Test Corp") == "TEST_CORP")
    check("Special chars removed", _slug("RIL (India) Ltd.") == "RIL_INDIA_LTD")
    check("Max 40 chars", len(_slug("A" * 60)) <= 40)


def test_pipeline_with_pdf():
    """POST /analysis/pipeline with a PDF file should accept it."""
    print(f"\n{_CYAN}{_BOLD}── Pipeline with PDF ──{_RESET}")
    client = _get_test_client()

    # Create a minimal fake PDF
    fake_pdf = b"%PDF-1.0 fake content for testing"

    resp = client.post(
        "/api/v1/analysis/pipeline",
        headers=_HEADERS,
        data={"company_name": "PDF Test Corp"},
        files={"pdf_file": ("test.pdf", fake_pdf, "application/pdf")},
    )
    check("PDF upload → 202", resp.status_code == 202, f"got {resp.status_code}")
    check("job_id present", "job_id" in resp.json())


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n{_BOLD}{'='*60}")
    print(f"  Analysis Router API Tests")
    print(f"{'='*60}{_RESET}")

    test_pipeline_requires_auth()
    test_pipeline_requires_company_name()
    test_pipeline_submit_returns_job()
    test_job_polling()
    test_job_not_found()
    test_debug_trace_not_found()
    test_debug_trace_returns_structure()
    test_slug_normalisation()
    test_pipeline_with_pdf()

    exit_code = report()
    sys.exit(exit_code)
