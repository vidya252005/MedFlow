from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Iterator

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.trace import Span

_TRACER: trace.Tracer | None = None


def init_tracing(service_name: str) -> None:
    global _TRACER
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    _TRACER = trace.get_tracer(service_name)


def new_trace_id() -> str:
    return uuid.uuid4().hex


def tracer() -> trace.Tracer:
    return _TRACER or trace.get_tracer("medflow")


@contextmanager
def span(name: str, **attributes: str) -> Iterator[Span]:
    with tracer().start_as_current_span(name) as current:
        for key, value in attributes.items():
            current.set_attribute(key, value)
        yield current
