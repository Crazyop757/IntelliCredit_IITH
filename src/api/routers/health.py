"""
Health check endpoints — no auth required.
"""
from __future__ import annotations

import sys
from typing import Any

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness probe + component health")
async def health() -> dict[str, Any]:
    """
    Returns overall system status and per-component health.

    status:
      - "ok"       : all components loaded
      - "degraded" : some components unavailable (system still functional)
      - "offline"  : critical components failed
    """
    from src.api.dependencies import get_component_health

    components = get_component_health()

    # Fill defaults for any components not yet validated
    defaults = {
        "finbert": "unknown",
        "bert_ner": "unknown",
        "lightgbm": "unknown",
        "gnn": "unknown",
        "tectonic": "unknown",
        "anthropic_api": "unknown",
        "tavily_api": "unknown",
        "delta_lake": "unknown",
    }
    for k, v in defaults.items():
        if k not in components:
            components[k] = v

    # Determine overall status
    error_components = [k for k, v in components.items() if v == "error"]
    degraded_indicators = ["missing", "untrained", "unknown", "error"]
    degraded_components = [
        k for k, v in components.items()
        if v in degraded_indicators
    ]

    # Critical components: if finbert or lightgbm has "error", system is degraded
    critical_errors = [k for k in error_components if k in ("finbert", "bert_ner")]

    if critical_errors:
        overall_status = "offline"
    elif degraded_components:
        overall_status = "degraded"
    else:
        overall_status = "ok"

    return {
        "status": overall_status,
        "service": "finsight-api",
        "components": components,
    }


@router.get("/health/ready", summary="Readiness probe — checks model loaded")
async def ready() -> dict[str, Any]:
    checks: dict[str, str] = {}

    # Python & key libs
    checks["python"] = sys.version.split()[0]

    # CreditScorer model file
    try:
        from src.api.config import settings
        checks["model_file"] = "found" if settings.model_path.exists() else "missing"
    except Exception as exc:
        checks["model_file"] = f"error: {exc}"

    # Output dir writable
    try:
        from src.api.config import settings
        test_file = settings.outputs_dir / ".probe"
        test_file.write_text("ok")
        test_file.unlink()
        checks["outputs_dir"] = "writable"
    except Exception as exc:
        checks["outputs_dir"] = f"error: {exc}"

    # Are key src modules importable?
    for mod in [
        "src.scorer.credit_scorer",
        "src.ingestor.pdf_parser",
        "src.gst.reconciler",
    ]:
        try:
            __import__(mod)
            checks[mod] = "ok"
        except Exception as exc:
            checks[mod] = f"import error: {exc}"

    ready = all(v in ("ok", "found", "writable") or not v.startswith("error")
                for v in checks.values())
    return {"ready": ready, "checks": checks}
