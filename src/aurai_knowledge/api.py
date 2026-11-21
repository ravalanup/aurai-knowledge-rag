"""HTTP API implementing contracts/knowledge-service.openapi.yaml."""

import logging
import time
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import tracing
from .auth import AuthError, TokenVerifier
from .models import Identity
from .service import Forbidden, QueryRejected, SearchService, Unavailable, normalise_score
from .settings import Settings

log = logging.getLogger("aurai.knowledge")


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=2000)
    collections: list[str] | None = None
    top_k: int = Field(default=5, ge=1, le=20)

    @field_validator("query")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be blank")
        return value


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    uri: str | None = None
    collection: str
    classification: str
    freshness: str | None = None


class Passage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chunk_id: str
    text: str
    score: float = Field(ge=0, le=1)
    source: Source


class SearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    results: list[Passage]


def create_app(
    settings: Settings, service: SearchService, verifier: TokenVerifier, tracer: trace.Tracer | None = None
) -> FastAPI:
    app = FastAPI(title="Aurai Knowledge Service", version="0.1.0")
    tracer = tracer or trace.get_tracer("aurai.knowledge")

    def current_identity(authorization: Annotated[str | None, Header()] = None) -> Identity:
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise HTTPException(401, "missing bearer token", headers={"WWW-Authenticate": "Bearer"})
        try:
            return verifier.verify(token.strip())
        except AuthError:
            raise HTTPException(401, "invalid token", headers={"WWW-Authenticate": "Bearer"}) from None

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> JSONResponse:
        ready = service.ready()
        return JSONResponse({"status": "ready" if ready else "index unavailable"}, status_code=200 if ready else 503)

    @app.post("/v1/search", response_model=SearchResponse, response_model_exclude_none=True)
    def search(
        body: SearchRequest,
        request: Request,
        identity: Annotated[Identity, Depends(current_identity)],
        x_aurai_trace_id: Annotated[str | None, Header()] = None,
    ) -> SearchResponse:
        started = time.monotonic()
        with tracer.start_as_current_span(tracing.SPAN_RETRIEVAL) as span:
            span.set_attribute(tracing.ATTR_USE_CASE, settings.use_case_id)
            span.set_attribute(tracing.ATTR_TEAM, settings.team_id)
            span.set_attribute(tracing.ATTR_TIER, settings.risk_tier)
            span.set_attribute(tracing.ATTR_TOP_K, body.top_k)
            if x_aurai_trace_id:
                span.set_attribute(tracing.ATTR_WORKSPACE_TRACE, x_aurai_trace_id[:128])
            try:
                outcome = service.search(identity, body.query, body.collections, body.top_k)
            except Forbidden:
                span.set_attribute(tracing.ATTR_COLLECTION, "")
                span.set_attribute(tracing.ATTR_SOURCE_COUNT, 0)
                _log(identity, 0, started, "forbidden")
                raise HTTPException(403, "no readable collections in scope") from None
            except QueryRejected:
                span.set_attribute(tracing.ATTR_COLLECTION, "")
                span.set_attribute(tracing.ATTR_SOURCE_COUNT, 0)
                _log(identity, 0, started, "rejected")
                raise HTTPException(422, "query rejected by the data policy") from None
            except Unavailable:
                span.set_attribute(tracing.ATTR_COLLECTION, "")
                span.set_attribute(tracing.ATTR_SOURCE_COUNT, 0)
                _log(identity, 0, started, "unavailable")
                raise HTTPException(503, "knowledge index unavailable") from None
            span.set_attribute(tracing.ATTR_COLLECTION, ",".join(outcome.collections_searched))
            span.set_attribute(tracing.ATTR_SOURCE_COUNT, len({h.doc_id for h in outcome.hits}))
            span.set_attribute(tracing.ATTR_RESULT_COUNT, len(outcome.hits))
        _log(identity, len(outcome.hits), started, "ok")
        return SearchResponse(
            results=[
                Passage(
                    chunk_id=h.chunk_id,
                    text=h.text,
                    score=normalise_score(h.score),
                    source=Source(
                        title=h.title,
                        uri=h.uri or None,
                        collection=h.collection,
                        classification=h.classification.label,
                        freshness=h.ingested_at,
                    ),
                )
                for h in outcome.hits
            ]
        )

    return app


def _log(identity: Identity, results: int, started: float, outcome: str) -> None:
    # The query text and the passages are never logged; the subject is the token's opaque id.
    log.info(
        "search outcome=%s results=%d sub=%s ms=%d",
        outcome,
        results,
        identity.subject,
        (time.monotonic() - started) * 1000,
    )
