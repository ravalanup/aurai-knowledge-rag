"""Search: resolve entitlements from the verified identity, embed the query, filter inside the vector query."""

from __future__ import annotations

from dataclasses import dataclass

from .embeddings import Embedder, EmbeddingError, EmbeddingRejected
from .entitlements import EntitlementPolicy
from .models import Hit, Identity
from .store import QdrantStore, StoreError


class Forbidden(Exception):
    """The caller has no access to any of the collections in scope."""


class QueryRejected(Exception):
    """The gateway's data policy refused the query text (for example it contains an identifier)."""


class Unavailable(Exception):
    """The index or the embedding provider is not available."""


@dataclass(frozen=True)
class Outcome:
    hits: list[Hit]
    collections_searched: list[str]


class SearchService:
    def __init__(self, policy: EntitlementPolicy, store: QdrantStore, embedder: Embedder, min_score: float = 0.0):
        self._policy = policy
        self._store = store
        self._embedder = embedder
        self._min_score = min_score

    def ready(self) -> bool:
        return self._store.healthy()

    def search(self, identity: Identity, query: str, collections: list[str] | None, top_k: int) -> Outcome:
        entitlement = self._policy.resolve(identity.groups)
        scope = entitlement.narrowed(collections)
        if scope.is_empty():
            # Same answer whether the collection does not exist or the caller may not read it.
            raise Forbidden("no readable collections in scope")
        try:
            vector = self._embedder.embed([query])[0]
            hits = self._store.search(vector, entitlement, top_k, collections)
        except EmbeddingRejected as exc:
            raise QueryRejected(str(exc)) from exc
        except (EmbeddingError, StoreError) as exc:
            raise Unavailable(type(exc).__name__) from exc
        kept = [h for h in hits if _normalise(h.score) >= self._min_score]
        return Outcome(kept, sorted(scope.collections))


def _normalise(score: float) -> float:
    """Cosine similarity is in [-1, 1]; the contract's score is in [0, 1], so negatives clamp to 0."""
    return max(0.0, min(1.0, score))


normalise_score = _normalise
