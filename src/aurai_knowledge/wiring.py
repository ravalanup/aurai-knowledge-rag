"""Builds the production object graph from environment settings. Run with:
uvicorn aurai_knowledge.wiring:build_app --factory --host 0.0.0.0 --port 8000"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from .api import create_app
from .auth import TokenVerifier
from .embeddings import build_embedder
from .entitlements import load_policy
from .service import SearchService
from .settings import Settings
from .store import QdrantStore
from .tracing import setup_tracing


def build_store(settings: Settings) -> QdrantStore:
    return QdrantStore.connect(settings.qdrant_url, settings.qdrant_api_key, settings.qdrant_collection)


def build_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    policy = load_policy(settings.entitlements_file)
    service = SearchService(policy, build_store(settings), build_embedder(settings), settings.min_score)
    verifier = TokenVerifier(settings.oidc_issuer, settings.oidc_audience, jwks_url=settings.jwks_url)
    return create_app(settings, service, verifier, setup_tracing(settings.otlp_endpoint))
