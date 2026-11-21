"""Embedding providers. The service only knows the gateway alias (default 'aurai-embed'); which model sits
behind that alias is a gateway decision (see gateway/ for the Gemini and Ollama overlays)."""

from __future__ import annotations

import hashlib
import math
import re
import time
from typing import Protocol

import httpx


class EmbeddingError(RuntimeError):
    """The embedding provider failed or returned something unusable."""


class EmbeddingRejected(EmbeddingError):
    """The provider refused this input (for example the gateway's PII policy blocked it). Retrying cannot help."""


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class GatewayEmbedder:
    """Calls the gateway's OpenAI-compatible /v1/embeddings endpoint with a team virtual key."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str = "aurai-embed",
        dimensions: int | None = None,
        batch_size: int = 16,
        timeout: float = 30.0,
        retries: int = 2,
        client: httpx.Client | None = None,
    ) -> None:
        self._url = base_url.rstrip("/") + "/v1/embeddings"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._model = model
        self._dimensions = dimensions
        self._batch = max(1, batch_size)
        self._retries = retries
        self._client = client or httpx.Client(timeout=timeout)

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch):
            vectors.extend(self._embed_batch(texts[start : start + self._batch]))
        return vectors

    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        body: dict[str, object] = {"model": self._model, "input": batch}
        if self._dimensions:
            body["dimensions"] = self._dimensions
        last: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                response = self._client.post(self._url, json=body, headers=self._headers)
                if response.status_code == 400:
                    raise EmbeddingRejected(f"input rejected by the gateway ({_error_code(response)})")
                if response.status_code in (429, 500, 502, 503, 504) and attempt < self._retries:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                response.raise_for_status()
                data = sorted(response.json()["data"], key=lambda item: item["index"])
                vectors = [list(map(float, item["embedding"])) for item in data]
                if len(vectors) != len(batch):
                    raise EmbeddingError(f"asked for {len(batch)} embeddings, received {len(vectors)}")
                return vectors
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                last = exc
                if attempt < self._retries:
                    time.sleep(0.5 * (attempt + 1))
        raise EmbeddingError(f"embedding request failed: {type(last).__name__}") from last


def _error_code(response: httpx.Response) -> str:
    """The gateway's machine-readable reason, such as pii_blocked. Never the message, which may echo input."""
    try:
        error = response.json().get("error")
        code = error.get("code") or error.get("type") if isinstance(error, dict) else error
        return str(code)[:40] if code else "bad request"
    except (ValueError, AttributeError):
        return "bad request"


_TOKEN = re.compile(r"[a-z0-9]+")


class HashEmbedder:
    """Deterministic bag-of-words embedder. For tests and offline demos only: it matches on shared words,
    not meaning, so it must never be used to judge real retrieval quality."""

    def __init__(self, dimensions: int = 256) -> None:
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(text) for text in texts]

    def _one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in _TOKEN.findall(text.lower()):
            if len(token) < 3:
                continue
            digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]


def build_embedder(settings) -> Embedder:  # noqa: ANN001 - Settings imported lazily to avoid a cycle in docs
    if settings.embedder == "hash":
        return HashEmbedder(settings.embed_dimensions or 256)
    if settings.embedder == "gateway":
        if not settings.gateway_key:
            raise EmbeddingError("AURAI_GATEWAY_KEY is not set")
        return GatewayEmbedder(
            settings.gateway_url,
            settings.gateway_key,
            model=settings.embed_model,
            dimensions=settings.embed_dimensions,
            batch_size=settings.embed_batch_size,
        )
    raise EmbeddingError(f"unknown embedder {settings.embedder!r}; expected 'gateway' or 'hash'")
