"""
FinSight FastAPI application.

Start with:
  python -m uvicorn src.api.main:app --reload --port 8000

Or via the convenience script:
  python run_api.py
"""
from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.config import settings
from src.api.middleware import RequestIDMiddleware, TimingMiddleware

# ── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("finsight.api")


# ── Lifespan: warm up heavy singletons at startup ─────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("FinSight API starting up...")
    settings.outputs_dir.mkdir(parents=True, exist_ok=True)

    # Run full startup validation (Tectonic, API keys, GNN, NER, LightGBM)
    try:
        from src.api.dependencies import run_startup_validation
        await run_startup_validation()
    except Exception as exc:
        log.warning("Startup validation had errors (non-fatal): %s", exc)

    yield

    log.info("FinSight API shutting down...")
    from src.api.dependencies import get_executor
    executor = get_executor()
    executor.shutdown(wait=False)


# ── App factory ────────────────────────────────────────────────────────────────
def create_app() -> FastAPI:
    app = FastAPI(
        title="FinSight API",
        description="""
## FinSight — Production-Grade Credit Intelligence Platform

A unified REST API for the complete credit analysis workflow:

| Stage | Endpoint group | Description |
|-------|---------------|-------------|
| 1 | `/ingest` | PDF, bank CSV, and GST JSON ingestion |
| 2 | `/gst` | GST reconciliation, EWS, GNN fraud detection |
| 3 | `/scoring` | LightGBM credit scoring + qualitative adjustments |
| 4 | `/research` | External intelligence (news · eCourts · MCA · RBI) |
| 5 | `/cam` | Credit Assessment Memorandum (.docx) generation |
| — | `/analysis/pipeline` | Full 5-stage pipeline in one async job |
| — | `/companies` | Delta Lake read endpoints |
| — | `/health` | Liveness / readiness probes |

### Authentication
Pass your API key in the **`X-API-Key`** header.  
Set `FINSIGHT_API_KEY` environment variable (or `.env` file) to configure the key.

### Async Jobs
Long-running operations return a `job_id` instantly.  
Poll `GET .../jobs/{job_id}` until `status == "DONE"`.
        """,
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # ── Middleware (Starlette LIFO: last add_middleware call = outermost layer) ─
    # RequestIDMiddleware first (innermost), CORS last (outermost)
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(TimingMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=r"https://.*\.hf\.space",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Exception handlers ────────────────────────────────────────────────────
    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "success": False,
                "error": "Validation error",
                "detail": exc.errors(),
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @app.exception_handler(Exception)
    async def generic_error_handler(request: Request, exc: Exception):
        log.error("Unhandled exception: %s", exc, exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "error": "Internal server error",
                "detail": str(exc),
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    # ── Routers ───────────────────────────────────────────────────────────────
    from src.api.routers.health import router as health_router
    from src.api.routers.ingest import router as ingest_router
    from src.api.routers.gst import router as gst_router
    from src.api.routers.scoring import router as scoring_router
    from src.api.routers.research import router as research_router
    from src.api.routers.cam import router as cam_router
    from src.api.routers.companies import router as companies_router
    from src.api.routers.analysis import router as analysis_router
    from src.api.routers.auth import router as auth_router

    API_PREFIX = "/api/v1"

    # Health — no prefix so k8s probes work at /health
    app.include_router(health_router)
    # Also mount under API prefix so frontend client can reach it
    app.include_router(health_router, prefix=API_PREFIX)

    app.include_router(ingest_router, prefix=API_PREFIX)
    app.include_router(gst_router, prefix=API_PREFIX)
    app.include_router(scoring_router, prefix=API_PREFIX)
    app.include_router(research_router, prefix=API_PREFIX)
    app.include_router(cam_router, prefix=API_PREFIX)
    app.include_router(companies_router, prefix=API_PREFIX)
    app.include_router(analysis_router, prefix=API_PREFIX)
    app.include_router(auth_router, prefix=API_PREFIX)

    # ── Security headers middleware ────────────────────────────────────────────
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Allow HF Spaces to embed this app in its iframe
        response.headers["Content-Security-Policy"] = "frame-ancestors 'self' https://*.hf.space https://huggingface.co"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response

    # ── Serve built frontend if present (single-container deployment) ─────
    frontend_dir = Path("frontend_dist")
    if frontend_dir.is_dir():
        from fastapi.staticfiles import StaticFiles
        from fastapi.responses import FileResponse

        @app.get("/", include_in_schema=False)
        async def serve_index():
            return FileResponse(frontend_dir / "index.html")

        # Catch-all for SPA client-side routing (must be after API routes)
        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_spa(full_path: str):
            file_path = frontend_dir / full_path
            if file_path.is_file():
                return FileResponse(file_path)
            return FileResponse(frontend_dir / "index.html")

        log.info("Frontend static files served from %s", frontend_dir.resolve())
    else:
        # No frontend build — just show API info at root
        @app.get("/", include_in_schema=False)
        async def root() -> dict[str, Any]:
            return {
                "service": "finsight-api",
                "version": "1.0.0",
                "docs": "/docs",
                "health": "/health",
            }

    return app


app = create_app()
