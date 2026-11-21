"""Qdrant access. Every search is built from an Entitlement, and an empty entitlement is refused here,
so no code path can issue an unfiltered query."""

from __future__ import annotations

import uuid
import warnings
from collections.abc import Iterable
from dataclasses import dataclass

from qdrant_client import QdrantClient, models

from .entitlements import Entitlement
from .models import Chunk, Classification, Hit

_NAMESPACE = uuid.UUID("6f1c2b0e-5a3d-4c7e-9a41-3d2f7c8b9e10")


class StoreError(RuntimeError):
    """The index is unavailable or in an unexpected state."""


class DimensionMismatch(StoreError):
    """The collection was built with a different embedding size than the current model produces."""


@dataclass(frozen=True)
class IndexedDoc:
    doc_id: str
    collection: str
    doc_hash: str
    ingested_at: str


def point_id(doc_id: str, chunk_index: int) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"{doc_id}:{chunk_index}"))


def entitlement_filter(entitlement: Entitlement, collections: list[str] | None = None) -> models.Filter:
    """One branch per granted collection: that collection AND a classification at or below the ceiling."""
    effective = entitlement.narrowed(collections)
    if effective.is_empty():
        raise ValueError("refusing to build a filter from an empty entitlement")
    return models.Filter(
        should=[
            models.Filter(
                must=[
                    models.FieldCondition(key="collection", match=models.MatchValue(value=name)),
                    models.FieldCondition(key="classification_rank", range=models.Range(lte=int(ceiling))),
                ]
            )
            for name, ceiling in sorted(effective.ceilings.items())
        ]
    )


class QdrantStore:
    def __init__(self, client: QdrantClient, collection: str = "aurai_knowledge") -> None:
        self._client = client
        self._collection = collection

    @classmethod
    def connect(cls, url: str, api_key: str = "", collection: str = "aurai_knowledge") -> QdrantStore:
        return cls(QdrantClient(url=url, api_key=api_key or None, timeout=20), collection)

    def ensure_collection(self, dimensions: int) -> None:
        try:
            if self._client.collection_exists(self._collection):
                existing = self._client.get_collection(self._collection).config.params.vectors
                size = existing.size if hasattr(existing, "size") else None
                if size is not None and size != dimensions:
                    raise DimensionMismatch(
                        f"index uses {size}-dimension vectors but the embedder produces {dimensions}; "
                        "re-create the index (see docs/runbook.md)"
                    )
                return
            self._client.create_collection(
                self._collection,
                vectors_config=models.VectorParams(size=dimensions, distance=models.Distance.COSINE),
            )
            with warnings.catch_warnings():  # the in-memory test client ignores payload indexes and says so
                warnings.simplefilter("ignore", UserWarning)
                self._create_indexes()
        except DimensionMismatch:
            raise
        except Exception as exc:
            raise StoreError(f"index unavailable: {type(exc).__name__}") from exc

    def _create_indexes(self) -> None:
        for key, schema in (
            ("collection", models.PayloadSchemaType.KEYWORD),
            ("doc_id", models.PayloadSchemaType.KEYWORD),
            ("team", models.PayloadSchemaType.KEYWORD),
            ("classification_rank", models.PayloadSchemaType.INTEGER),
            ("chunk_index", models.PayloadSchemaType.INTEGER),
        ):
            self._client.create_payload_index(self._collection, field_name=key, field_schema=schema)

    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        points = [
            models.PointStruct(id=point_id(c.doc_id, c.chunk_index), vector=v, payload=c.payload())
            for c, v in zip(chunks, vectors, strict=True)
        ]
        try:
            self._client.upsert(self._collection, points=points, wait=True)
        except Exception as exc:
            raise StoreError(f"upsert failed: {type(exc).__name__}") from exc

    def delete_doc(self, doc_id: str, from_index: int = 0) -> None:
        """Delete a document's chunks, or only those at or after from_index (used when a document shrinks)."""
        must = [models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))]
        if from_index:
            must.append(models.FieldCondition(key="chunk_index", range=models.Range(gte=from_index)))
        try:
            self._client.delete(
                self._collection,
                points_selector=models.FilterSelector(filter=models.Filter(must=must)),
                wait=True,
            )
        except Exception as exc:
            raise StoreError(f"delete failed: {type(exc).__name__}") from exc

    def touch_doc(self, doc_id: str, ingested_at: str) -> None:
        """Record that the source was checked and is unchanged, without re-embedding."""
        try:
            self._client.set_payload(
                self._collection,
                payload={"ingested_at": ingested_at},
                points=models.Filter(must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))]),
                wait=True,
            )
        except Exception as exc:
            raise StoreError(f"update failed: {type(exc).__name__}") from exc

    def indexed_docs(self, collections: Iterable[str] | None = None) -> dict[str, IndexedDoc]:
        """One record per indexed document, read from each document's first chunk."""
        conditions = [models.FieldCondition(key="chunk_index", match=models.MatchValue(value=0))]
        if collections is not None:
            conditions.append(
                models.FieldCondition(key="collection", match=models.MatchAny(any=sorted(set(collections))))
            )
        docs: dict[str, IndexedDoc] = {}
        offset = None
        try:
            while True:
                points, offset = self._client.scroll(
                    self._collection,
                    scroll_filter=models.Filter(must=conditions),
                    limit=256,
                    offset=offset,
                    with_payload=["doc_id", "collection", "doc_hash", "ingested_at"],
                    with_vectors=False,
                )
                for p in points:
                    pl = p.payload or {}
                    docs[pl["doc_id"]] = IndexedDoc(pl["doc_id"], pl["collection"], pl["doc_hash"], pl["ingested_at"])
                if offset is None:
                    break
        except Exception as exc:
            raise StoreError(f"scan failed: {type(exc).__name__}") from exc
        return docs

    def search(
        self,
        vector: list[float],
        entitlement: Entitlement,
        top_k: int,
        collections: list[str] | None = None,
    ) -> list[Hit]:
        query_filter = entitlement_filter(entitlement, collections)
        try:
            result = self._client.query_points(
                self._collection,
                query=vector,
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
                with_vectors=False,
            )
        except Exception as exc:
            raise StoreError(f"search failed: {type(exc).__name__}") from exc
        hits: list[Hit] = []
        for point in result.points:
            pl = point.payload or {}
            hits.append(
                Hit(
                    chunk_id=str(point.id),
                    score=float(point.score),
                    text=pl["text"],
                    doc_id=pl["doc_id"],
                    title=pl["title"],
                    uri=pl.get("uri", ""),
                    collection=pl["collection"],
                    classification=Classification.parse(pl["classification"]),
                    ingested_at=pl["ingested_at"],
                )
            )
        return hits

    def healthy(self) -> bool:
        try:
            return bool(self._client.collection_exists(self._collection))
        except Exception:
            return False
