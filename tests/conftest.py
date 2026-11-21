from __future__ import annotations

import time
from datetime import date
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from qdrant_client import QdrantClient

from aurai_knowledge.api import create_app
from aurai_knowledge.auth import TokenVerifier
from aurai_knowledge.embeddings import HashEmbedder
from aurai_knowledge.entitlements import load_policy
from aurai_knowledge.ingest import Ingestor
from aurai_knowledge.service import SearchService
from aurai_knowledge.settings import Settings
from aurai_knowledge.sources import LocalSource
from aurai_knowledge.store import QdrantStore

ROOT = Path(__file__).resolve().parent.parent
ISSUER = "http://keycloak.test/realms/aurai"
AUDIENCE = "litellm"


@pytest.fixture(scope="session")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="session")
def other_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def mint(rsa_key):
    def _mint(groups=("workspace-members",), key=None, **overrides):
        claims = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "user-1234",
            "exp": int(time.time()) + 600,
            "iat": int(time.time()),
            "groups": None if groups is None else list(groups),
            "roles": ["member"],
        }
        claims.update(overrides)
        return jwt.encode({k: v for k, v in claims.items() if v is not None}, key or rsa_key, algorithm="RS256")

    return _mint


@pytest.fixture
def verifier(rsa_key):
    return TokenVerifier(ISSUER, AUDIENCE, key_resolver=lambda _token: rsa_key.public_key())


@pytest.fixture
def policy():
    return load_policy(ROOT / "config" / "entitlements.yaml")


@pytest.fixture
def embedder():
    return HashEmbedder()


@pytest.fixture
def store(embedder):
    store = QdrantStore(QdrantClient(":memory:"), "test")
    Ingestor(LocalSource(ROOT / "corpus"), store, embedder, today=date(2026, 11, 1)).run()
    return store


@pytest.fixture
def span_exporter():
    return InMemorySpanExporter()


@pytest.fixture
def client(policy, store, embedder, verifier, span_exporter):
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    app = create_app(Settings(), SearchService(policy, store, embedder), verifier, provider.get_tracer("test"))
    return TestClient(app)


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
