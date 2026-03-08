"""
Custom ASGI middleware:
  1. RequestIDMiddleware  — attaches a unique request-id to every request
  2. TimingMiddleware     — logs method, path, status, latency
"""
from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

log = logging.getLogger("intelli.access")


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach X-Request-ID header to each request & response."""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class TimingMiddleware(BaseHTTPMiddleware):
    """Log structured access logs with latency for every HTTP request."""

    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        response: Response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        req_id = getattr(request.state, "request_id", "-")
        log.info(
            "%s %s %d %.1fms req_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            req_id,
        )
        return response
