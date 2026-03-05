"""
OpenTelemetry + Phoenix tracing setup.
Call configure_tracing() once at app startup in each service.
"""

import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def configure_tracing(service_name: str) -> trace.Tracer:
    """
    Wire up OpenTelemetry → Phoenix (via OTLP gRPC).

    Args:
        service_name: Identifier shown in Phoenix UI (e.g. 'search-mcp').

    Returns:
        A tracer you can use for custom spans in the calling service.
    """
    endpoint = os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:4317")

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    return trace.get_tracer(service_name)


def get_tracer(service_name: str) -> trace.Tracer:
    """Shorthand — returns existing tracer if already configured."""
    return trace.get_tracer(service_name)
