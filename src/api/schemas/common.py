"""
Shared base schemas and envelope types used across all routers.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


# ── Generic response envelope ─────────────────────────────────────────────────
class APIResponse(BaseModel, Generic[T]):
    success: bool = True
    data: T
    message: str = "OK"
    request_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ErrorResponse(BaseModel):
    success: bool = False
    error: str
    detail: Optional[Any] = None
    request_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Pagination ────────────────────────────────────────────────────────────────
class PaginatedResponse(BaseModel, Generic[T]):
    success: bool = True
    data: List[T]
    total: int
    page: int
    page_size: int
    has_more: bool


# ── Job reference returned immediately for async endpoints ────────────────────
class JobRef(BaseModel):
    job_id: str
    job_type: str
    status: str
    poll_url: str = Field(description="URL to poll for job status")
    created_at: datetime


class JobStatusResponse(BaseModel):
    job_id: str
    job_type: str
    status: str
    created_at: datetime
    updated_at: datetime
    result: Optional[Any] = None
    error: Optional[str] = None
    meta: Optional[dict[str, Any]] = None
    progress_pct: Optional[int] = 0
    current_stage: Optional[str] = ""


# ── Risk band / decision constants ────────────────────────────────────────────
class RiskBand(str):
    PRIME = "PRIME"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Decision(str):
    APPROVE = "APPROVE"
    CONDITIONAL_APPROVE = "CONDITIONAL_APPROVE"
    REJECT = "REJECT"
    PENDING = "PENDING"
