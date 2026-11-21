"""Tracing with the Aurai span conventions (see aurai-eval-governance): retrieval spans carry the use case,
team, risk tier, the collections searched and how many distinct sources came back. Query text is never recorded."""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

SPAN_RETRIEVAL = "aurai.retrieval"
ATTR_USE_CASE = "aurai.use_case.id"
ATTR_TEAM = "aurai.team.id"
ATTR_TIER = "aurai.risk_tier"
ATTR_COLLECTION = "aurai.retrieval.collection"
ATTR_SOURCE_COUNT = "aurai.retrieval.source_count"
ATTR_RESULT_COUNT = "aurai.retrieval.result_count"
ATTR_TOP_K = "aurai.retrieval.top_k"
ATTR_WORKSPACE_TRACE = "aurai.workspace.trace_id"


def setup_tracing(otlp_endpoint: str, service_name: str = "aurai-knowledge") -> trace.Tracer:
    """Export to the OTel collector when an endpoint is set; otherwise spans are created and dropped."""
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    if otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint.rstrip("/") + "/v1/traces"))
        )
    return provider.get_tracer("aurai.knowledge")
