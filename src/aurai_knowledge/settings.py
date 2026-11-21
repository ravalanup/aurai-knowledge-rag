"""Runtime configuration, read from the environment. Secrets are only ever read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _int(name: str, default: int | None) -> int | None:
    raw = os.environ.get(name, "")
    return int(raw) if raw else default


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name, "")
    return float(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    qdrant_url: str = "http://qdrant.aurai-system.svc.cluster.local:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "aurai_knowledge"

    embedder: str = "gateway"  # gateway | hash (hash is for tests and offline demos only)
    gateway_url: str = "http://litellm.aurai-gateway.svc.cluster.local:4000"
    gateway_key: str = ""
    embed_model: str = "aurai-embed"
    embed_dimensions: int | None = None
    embed_batch_size: int = 16

    oidc_issuer: str = "http://keycloak.aurai-system.svc.cluster.local:8080/realms/aurai"
    oidc_jwks_url: str = ""
    oidc_audience: str = "litellm"

    entitlements_file: str = "config/entitlements.yaml"
    min_score: float = 0.0

    otlp_endpoint: str = ""
    use_case_id: str = "knowledge-search"
    team_id: str = "knowledge"
    risk_tier: str = "T2"

    @property
    def jwks_url(self) -> str:
        return self.oidc_jwks_url or f"{self.oidc_issuer.rstrip('/')}/protocol/openid-connect/certs"

    @classmethod
    def from_env(cls) -> Settings:
        e = os.environ.get
        d = cls()
        return cls(
            qdrant_url=e("AURAI_QDRANT_URL", d.qdrant_url),
            qdrant_api_key=e("AURAI_QDRANT_API_KEY", ""),
            qdrant_collection=e("AURAI_QDRANT_COLLECTION", d.qdrant_collection),
            embedder=e("AURAI_EMBEDDER", d.embedder),
            gateway_url=e("AURAI_GATEWAY_URL", d.gateway_url),
            gateway_key=e("AURAI_GATEWAY_KEY", ""),
            embed_model=e("AURAI_EMBED_MODEL", d.embed_model),
            embed_dimensions=_int("AURAI_EMBED_DIMENSIONS", None),
            embed_batch_size=_int("AURAI_EMBED_BATCH_SIZE", d.embed_batch_size) or d.embed_batch_size,
            oidc_issuer=e("AURAI_OIDC_ISSUER", d.oidc_issuer),
            oidc_jwks_url=e("AURAI_OIDC_JWKS_URL", ""),
            oidc_audience=e("AURAI_OIDC_AUDIENCE", d.oidc_audience),
            entitlements_file=e("AURAI_ENTITLEMENTS_FILE", d.entitlements_file),
            min_score=_float("AURAI_MIN_SCORE", d.min_score),
            otlp_endpoint=e("AURAI_OTLP_ENDPOINT", ""),
            use_case_id=e("AURAI_USE_CASE_ID", d.use_case_id),
            team_id=e("AURAI_TEAM_ID", d.team_id),
            risk_tier=e("AURAI_RISK_TIER", d.risk_tier),
        )
