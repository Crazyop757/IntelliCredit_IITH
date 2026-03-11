"""
Async Job Store — tracks background pipeline / research / CAM jobs.
Thread-safe for concurrent FastAPI requests.
"""
from __future__ import annotations

import asyncio
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from src.api.config import settings


class JobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"


class Job:
    __slots__ = (
        "job_id",
        "job_type",
        "status",
        "created_at",
        "updated_at",
        "result",
        "error",
        "meta",
        "progress_pct",
        "current_stage",
    )

    def __init__(self, job_type: str, meta: dict[str, Any] | None = None):
        self.job_id: str = str(uuid.uuid4())
        self.job_type: str = job_type
        self.status: JobStatus = JobStatus.PENDING
        self.created_at: datetime = datetime.now(timezone.utc)
        self.updated_at: datetime = self.created_at
        self.result: Any = None
        self.error: str | None = None
        self.meta: dict[str, Any] = meta or {}
        self.progress_pct: int = 0
        self.current_stage: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "result": self.result,
            "error": self.error,
            "meta": self.meta,
            "progress_pct": self.progress_pct,
            "current_stage": self.current_stage,
        }


class JobStore:
    """Thread-safe in-memory job registry.

    For production scale, swap _store for a Redis-backed implementation
    without changing the interface.
    """

    def __init__(self, max_size: int = settings.job_store_max_size):
        self._store: OrderedDict[str, Job] = OrderedDict()
        self._lock = asyncio.Lock()
        self._max_size = max_size

    async def create(self, job_type: str, meta: dict[str, Any] | None = None) -> Job:
        job = Job(job_type=job_type, meta=meta or {})
        async with self._lock:
            self._store[job.job_id] = job
            self._evict_if_needed()
        return job

    async def get(self, job_id: str) -> Job | None:
        async with self._lock:
            return self._store.get(job_id)

    async def update(
        self,
        job_id: str,
        status: JobStatus,
        result: Any = None,
        error: str | None = None,
    ) -> None:
        async with self._lock:
            job = self._store.get(job_id)
            if job:
                job.status = status
                job.result = result
                job.error = error
                job.updated_at = datetime.now(timezone.utc)

    def set_progress(self, job_id: str, pct: int, stage: str) -> None:
        """Update progress from a background thread (no lock — GIL-safe for primitive writes)."""
        job = self._store.get(job_id)
        if job:
            job.progress_pct = pct
            job.current_stage = stage
            job.updated_at = datetime.now(timezone.utc)

    def _evict_if_needed(self) -> None:
        """Remove oldest completed jobs when over capacity (lock already held)."""
        while len(self._store) > self._max_size:
            key, oldest = next(iter(self._store.items()))
            if oldest.status in (JobStatus.DONE, JobStatus.FAILED):
                del self._store[key]
            else:
                break  # don't evict running jobs


# Module-level singleton shared across all routers
job_store = JobStore()
