"""
test_health_router.py — Unit tests for /health and /health/ready endpoints.

Uses httpx + FastAPI TestClient to exercise the health router directly,
mocking dependencies to avoid needing real ML models.

Usage:
    python tests/test_health_router.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

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


# ── Setup ─────────────────────────────────────────────────────────────────────

def _get_test_client():
    """Create a TestClient with startup validation disabled."""
    from fastapi.testclient import TestClient
    from src.api.main import create_app

    # Patch lifespan to skip startup validation
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def noop_lifespan(app):
        yield

    app = create_app()
    # Override the lifespan to skip startup
    app.router.lifespan_context = noop_lifespan  # type: ignore
    return TestClient(app)


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_health_ok():
    """When all components are 'ok', status should be 'ok'."""
    print(f"\n{_CYAN}{_BOLD}── Health OK ──{_RESET}")

    all_ok = {
        "finbert": "ok", "bert_ner": "ok", "lightgbm": "ok",
        "gnn": "ok", "tectonic": "ok", "anthropic_api": "ok",
        "tavily_api": "ok", "delta_lake": "ok",
    }

    with patch("src.api.dependencies.get_component_health", return_value=dict(all_ok)):
        client = _get_test_client()
        resp = client.get("/health")
        check("status code 200", resp.status_code == 200)
        data = resp.json()
        check("status = ok", data["status"] == "ok")
        check("service name present", data["service"] == "intelli-credit-api")
        check("components dict present", "components" in data)


def test_health_degraded():
    """When some non-critical components are missing, status should be 'degraded'."""
    print(f"\n{_CYAN}{_BOLD}── Health Degraded ──{_RESET}")

    partial = {
        "finbert": "ok", "bert_ner": "ok", "lightgbm": "ok",
        "gnn": "missing", "tectonic": "ok", "anthropic_api": "missing",
        "tavily_api": "ok", "delta_lake": "ok",
    }

    with patch("src.api.dependencies.get_component_health", return_value=dict(partial)):
        client = _get_test_client()
        resp = client.get("/health")
        check("status code 200", resp.status_code == 200)
        data = resp.json()
        check("status = degraded", data["status"] == "degraded",
              f"got {data['status']}")


def test_health_offline():
    """When critical NER/finbert has error, status should be 'offline'."""
    print(f"\n{_CYAN}{_BOLD}── Health Offline ──{_RESET}")

    critical_fail = {
        "finbert": "error", "bert_ner": "ok", "lightgbm": "ok",
        "gnn": "ok", "tectonic": "ok", "anthropic_api": "ok",
        "tavily_api": "ok", "delta_lake": "ok",
    }

    with patch("src.api.dependencies.get_component_health", return_value=dict(critical_fail)):
        client = _get_test_client()
        resp = client.get("/health")
        data = resp.json()
        check("status = offline", data["status"] == "offline",
              f"got {data['status']}")


def test_health_ready():
    """GET /health/ready should return ready bool and checks dict."""
    print(f"\n{_CYAN}{_BOLD}── Health Ready ──{_RESET}")
    client = _get_test_client()
    resp = client.get("/health/ready")
    check("status code 200", resp.status_code == 200)
    data = resp.json()
    check("ready key present", "ready" in data)
    check("checks dict present", "checks" in data and isinstance(data["checks"], dict))
    checks = data.get("checks", {})
    check("python version in checks", "python" in checks)
    check("model_file in checks", "model_file" in checks)
    check("outputs_dir in checks", "outputs_dir" in checks)


def test_health_under_api_prefix():
    """Health should also be available under /api/v1/health."""
    print(f"\n{_CYAN}{_BOLD}── Health under API prefix ──{_RESET}")

    all_ok = {
        "finbert": "ok", "bert_ner": "ok", "lightgbm": "ok",
        "gnn": "ok", "tectonic": "ok", "anthropic_api": "ok",
        "tavily_api": "ok", "delta_lake": "ok",
    }

    with patch("src.api.dependencies.get_component_health", return_value=dict(all_ok)):
        client = _get_test_client()
        resp = client.get("/api/v1/health")
        check("API prefix 200", resp.status_code == 200)
        data = resp.json()
        check("API prefix status = ok", data["status"] == "ok")


def test_root_endpoint():
    """GET / should return service info."""
    print(f"\n{_CYAN}{_BOLD}── Root endpoint ──{_RESET}")
    client = _get_test_client()
    resp = client.get("/")
    check("root 200", resp.status_code == 200)
    data = resp.json()
    check("service name", data["service"] == "intelli-credit-api")
    check("version present", "version" in data)


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n{_BOLD}{'='*60}")
    print(f"  Health Router API Tests")
    print(f"{'='*60}{_RESET}")

    test_health_ok()
    test_health_degraded()
    test_health_offline()
    test_health_ready()
    test_health_under_api_prefix()
    test_root_endpoint()

    exit_code = report()
    sys.exit(exit_code)
