from __future__ import annotations

import time
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from medflow_shared.metrics import HTTP_ERRORS, HTTP_LATENCY, HTTP_REQUESTS
from medflow_shared.tracing import new_trace_id


class ObservabilityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, service_name: str) -> None:  # noqa: ANN001
        super().__init__(app)
        self.service_name = service_name

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        trace_id = request.headers.get("x-trace-id") or new_trace_id()
        request.state.trace_id = trace_id
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start
        path = request.url.path
        HTTP_REQUESTS.labels(self.service_name, request.method, path, str(response.status_code)).inc()
        HTTP_LATENCY.labels(self.service_name, request.method, path).observe(elapsed)
        if response.status_code >= 500:
            HTTP_ERRORS.labels(self.service_name).inc()
        response.headers["X-Trace-Id"] = trace_id
        remaining = getattr(request.state, "rate_remaining", None)
        if remaining is not None:
            response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response
