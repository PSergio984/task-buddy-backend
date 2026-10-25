"""OpenTelemetry + Prometheus wiring.

Traces export via OTLP when OTEL_EXPORTER_OTLP_ENDPOINT is set (Tempo in
compose, any OTLP collector otherwise); /metrics is always exposed for
Prometheus scraping; otelTraceID/otelSpanID are injected into log records so
structured logs correlate with traces.
"""

import os

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_fastapi_instrumentator import Instrumentator


def setup_observability(app: FastAPI) -> None:
    service_name = os.getenv("OTEL_SERVICE_NAME", "task-buddy-backend")
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if endpoint:
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True))
        )
    trace.set_tracer_provider(provider)

    LoggingInstrumentor().instrument()
    FastAPIInstrumentor.instrument_app(app)
    # Default lowr buckets cap at 1s, which would make the >3s p95 alert
    # unable to ever fire — extend them to cover the SLO-relevant range.
    Instrumentator().instrument(
        app,
        latency_lowr_buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
    ).expose(app, endpoint="/metrics", include_in_schema=False)
