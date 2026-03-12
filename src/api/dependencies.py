"""
Dependency injection — singletons lazily loaded at first request
and cached for the lifetime of the process.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, AsyncGenerator

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.api.config import settings
from src.api.job_store import JobStore, job_store as _job_store

_bearer = HTTPBearer(auto_error=False)

log = logging.getLogger(__name__)

# ── Component health state (populated at startup, exposed via /health) ────────
_component_health: dict[str, str] = {}


def get_component_health() -> dict[str, str]:
    return dict(_component_health)


# ── Thread-pool for sync-heavy tasks (PDF parsing, ML inference) ──────────────
_executor: concurrent.futures.ThreadPoolExecutor | None = None


def get_executor() -> concurrent.futures.ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=settings.max_pipeline_workers,
            thread_name_prefix="finsight_worker",
        )
    return _executor


def get_active_worker_count() -> int:
    """Return number of currently active threads in the executor."""
    ex = get_executor()
    # ThreadPoolExecutor tracks pending work items
    return getattr(ex, '_work_queue', None) and ex._work_queue.qsize() or 0


async def run_in_thread(fn, *args, **kwargs):
    """Run a synchronous callable in the thread-pool and await the result."""
    loop = asyncio.get_running_loop()
    executor = get_executor()
    if kwargs:
        import functools
        fn = functools.partial(fn, **kwargs)
    return await loop.run_in_executor(executor, fn, *args)


# ── Job Store DI ──────────────────────────────────────────────────────────────
def get_job_store() -> JobStore:
    return _job_store


# ── Supabase JWT Auth ─────────────────────────────────────────────────────────

def _decode_supabase_jwt(token: str) -> dict:
    """Validate a Supabase JWT by calling admin.auth.get_user() — no JWT secret needed."""
    from src.database.supabase_client import get_supabase_admin_client
    admin = get_supabase_admin_client()
    if admin is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication not configured on this server.",
        )
    try:
        response = admin.auth.get_user(token)
        if response.user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user = response.user
        return {
            "sub": str(user.id),
            "email": user.email or "",
            "user_metadata": user.user_metadata or {},
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token validation failed: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """FastAPI dependency: extract + verify Supabase JWT, return payload dict."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _decode_supabase_jwt(credentials.credentials)


# ── Repository DI ─────────────────────────────────────────────────────────────

def get_appraisal_repository():
    from src.database.appraisal_repository import AppraisalRepository
    return AppraisalRepository()


def get_company_repository():
    from src.database.company_repository import CompanyRepository
    return CompanyRepository()


# ── API Key Auth ──────────────────────────────────────────────────────────────
async def verify_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    if settings.disable_auth:
        return
    if x_api_key is None or x_api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Pass it in the X-API-Key header.",
        )


# ── Singleton model wrappers (lazy load on first use) ─────────────────────────
_credit_scorer = None
_credit_scorer_lock = asyncio.Lock()
_scorer_trained: bool = False


async def get_credit_scorer():
    global _credit_scorer, _scorer_trained
    if _credit_scorer is not None:
        return _credit_scorer
    async with _credit_scorer_lock:
        if _credit_scorer is None:
            from src.scorer.credit_scorer import CreditScorer
            log.info("Loading CreditScorer model…")
            try:
                scorer = await run_in_thread(
                    lambda: CreditScorer()
                )
                # Try to load model to verify it works
                try:
                    scorer._load_model()
                    _scorer_trained = True
                    _component_health["lightgbm"] = "loaded"
                    log.info("CreditScorer ready (model loaded).")
                except FileNotFoundError:
                    _scorer_trained = False
                    _component_health["lightgbm"] = "untrained"
                    log.warning("CreditScorer model .pkl not found — scorer untrained.")
                except Exception as exc:
                    _scorer_trained = False
                    _component_health["lightgbm"] = "error"
                    log.error("CreditScorer model load error: %s", exc)
                _credit_scorer = scorer
            except Exception as exc:
                _component_health["lightgbm"] = "error"
                log.error("CreditScorer initialization failed: %s", exc)
                raise
    return _credit_scorer


def is_scorer_trained() -> bool:
    return _scorer_trained


_ner_extractor = None
_ner_lock = asyncio.Lock()


async def get_ner_extractor():
    global _ner_extractor
    if _ner_extractor is not None:
        return _ner_extractor
    async with _ner_lock:
        if _ner_extractor is None:
            from src.ingestor.ner_extractor import NERExtractor
            log.info("Loading NERExtractor models…")
            try:
                _ner_extractor = await run_in_thread(NERExtractor)
                _component_health["finbert"] = "loaded"
                _component_health["bert_ner"] = "loaded"
                log.info("NERExtractor ready.")
            except Exception as exc:
                _component_health["finbert"] = "error"
                _component_health["bert_ner"] = "error"
                log.error("NERExtractor loading failed: %s", exc)
                raise
    return _ner_extractor


# ── GNN Model Singleton ──────────────────────────────────────────────────────
_gnn_available: bool = False


def is_gnn_available() -> bool:
    return _gnn_available


def validate_gnn_checkpoint() -> bool:
    """Check if GNN model checkpoint exists and is valid."""
    global _gnn_available
    gnn_path = Path("models/gnn_fraud_detector.pt")
    if not gnn_path.exists():
        _component_health["gnn"] = "untrained"
        log.warning("GNN checkpoint not found at %s — fraud detection will use rule-based fallback.", gnn_path)
        _gnn_available = False
        return False
    try:
        import torch
        dummy_model = torch.load(gnn_path, map_location="cpu", weights_only=False)
        _component_health["gnn"] = "loaded"
        _gnn_available = True
        log.info("GNN checkpoint validated: %s", gnn_path)
        return True
    except Exception as exc:
        _component_health["gnn"] = "error"
        _gnn_available = False
        log.critical("GNN checkpoint invalid at %s: %s", gnn_path, exc)
        return False


# ── Tectonic Validation ──────────────────────────────────────────────────────
_tectonic_available: bool = False


def is_tectonic_available() -> bool:
    return _tectonic_available


def validate_tectonic() -> bool:
    """Check if Tectonic LaTeX compiler is installed."""
    global _tectonic_available
    try:
        result = subprocess.run(
            ["tectonic", "--version"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            _component_health["tectonic"] = "available"
            _tectonic_available = True
            log.info("Tectonic available: %s", result.stdout.strip())
            return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    _tectonic_available = False
    log.warning("Tectonic not found — CAM PDF generation will be unavailable.")
    return False


# ── API Key Validation ────────────────────────────────────────────────────────
def validate_api_keys():
    """Check which external API keys are configured."""
    if settings.anthropic_api_key:
        _component_health["anthropic_api"] = "configured"
    else:
        _component_health["anthropic_api"] = "missing"
        log.warning("ANTHROPIC_API_KEY not set — LLM features will use rule-based fallback.")

    import os
    tavily_key = settings.tavily_api_key or os.getenv("TAVILY_API_KEY", "")
    if tavily_key:
        _component_health["tavily_api"] = "configured"
    else:
        _component_health["tavily_api"] = "missing"
        log.warning("TAVILY_API_KEY not set — news tool will return empty results.")


def validate_delta_lake():
    """Check Delta Lake / local fallback status."""
    try:
        from src.config import DATA_BRONZE, DATA_SILVER, DATA_GOLD
        if all(p.exists() for p in [DATA_BRONZE, DATA_SILVER, DATA_GOLD]):
            _component_health["delta_lake"] = "local_fallback"
        else:
            _component_health["delta_lake"] = "error"
    except Exception:
        _component_health["delta_lake"] = "error"


async def run_startup_validation():
    """Run all startup validations and populate component health."""
    log.info("Running startup validation…")
    validate_tectonic()
    validate_api_keys()
    validate_delta_lake()
    validate_gnn_checkpoint()

    # Pre-warm NER (loads FinBERT + BERT-NER)
    try:
        await get_ner_extractor()
    except Exception as exc:
        log.warning("NER pre-warm failed (non-fatal): %s", exc)

    # Pre-warm CreditScorer
    try:
        await get_credit_scorer()
    except Exception as exc:
        log.warning("CreditScorer pre-warm failed (non-fatal): %s", exc)

    log.info("Startup validation complete. Component health: %s", _component_health)


# Type aliases for annotated DI
JobStoreDep = Annotated[JobStore, Depends(get_job_store)]
AuthDep = Annotated[None, Depends(verify_api_key)]
