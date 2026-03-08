"""
Dependency injection — singletons lazily loaded at first request
and cached for the lifetime of the process.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from functools import lru_cache
from typing import Annotated, AsyncGenerator

from fastapi import Depends, Header, HTTPException, status

from src.api.config import settings
from src.api.job_store import JobStore, job_store as _job_store

log = logging.getLogger(__name__)

# ── Thread-pool for sync-heavy tasks (PDF parsing, ML inference) ──────────────
_executor: concurrent.futures.ThreadPoolExecutor | None = None


def get_executor() -> concurrent.futures.ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=settings.max_pipeline_workers,
            thread_name_prefix="intelli_worker",
        )
    return _executor


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


async def get_credit_scorer():
    global _credit_scorer
    if _credit_scorer is not None:
        return _credit_scorer
    async with _credit_scorer_lock:
        if _credit_scorer is None:
            from src.scorer.credit_scorer import CreditScorer
            log.info("Loading CreditScorer model…")
            _credit_scorer = await run_in_thread(
                lambda: CreditScorer(model_path=settings.model_path)
            )
            log.info("CreditScorer ready.")
    return _credit_scorer


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
            _ner_extractor = await run_in_thread(NERExtractor)
            log.info("NERExtractor ready.")
    return _ner_extractor


# Type aliases for annotated DI
JobStoreDep = Annotated[JobStore, Depends(get_job_store)]
AuthDep = Annotated[None, Depends(verify_api_key)]
