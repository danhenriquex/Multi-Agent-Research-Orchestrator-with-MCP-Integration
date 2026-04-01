"""
OpenTelemetry + Phoenix tracing setup.
Call configure_tracing() once at app startup in each service.

Includes OpenAI auto-instrumentation so Phoenix and LangSmith
receive token counts, model names, and prompt/completion pairs
automatically for every OpenAI API call.
"""

import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def configure_tracing(service_name: str, endpoint: str | None = None) -> trace.Tracer:
    """
    Wire up OpenTelemetry → Phoenix (via OTLP gRPC).
    Also auto-instruments OpenAI client so token counts and
    prompt/completion pairs appear in Phoenix and LangSmith.

    Args:
        service_name: Identifier shown in Phoenix UI (e.g. 'search-agent').
        endpoint:     OTLP collector endpoint (overrides PHOENIX_COLLECTOR_ENDPOINT env var).

    Returns:
        A tracer you can use for custom spans in the calling service.
    """
    resolved = endpoint or os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:4317")

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    exporter = OTLPSpanExporter(endpoint=resolved, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)

    # ── OpenAI auto-instrumentation ───────────────────────────────────────────
    # This makes Phoenix show token counts, model names, and prompt/response
    # pairs as native LLM spans instead of "unknown" kind spans.
    try:
        from openinference.instrumentation.openai import OpenAIInstrumentor

        OpenAIInstrumentor().instrument(tracer_provider=provider)
    except ImportError:
        pass  # openinference-instrumentation-openai not installed — skip silently

    return trace.get_tracer(service_name)


def get_tracer(service_name: str) -> trace.Tracer:
    """Shorthand — returns existing tracer if already configured."""
    return trace.get_tracer(service_name)
