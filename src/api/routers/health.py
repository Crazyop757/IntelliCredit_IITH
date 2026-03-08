"""
Health check endpoints — no auth required.
"""
from __future__ import annotations

import sys
from typing import Any

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness probe")
async def health() -> dict[str, Any]:
    return {"status": "ok", "service": "intelli-credit-api"}


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
