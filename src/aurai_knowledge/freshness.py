"""Freshness tracking (KN-4): how old is each collection's content, against the age its owner allows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .ingest import parse_manifest
from .sources import DocumentSource
from .store import QdrantStore


@dataclass(frozen=True)
class CollectionFreshness:
    collection: str
    documents: int
    oldest_ingested: str
    newest_ingested: str
    max_age_days: int
    age_days: int
    stale: bool


def freshness_report(
    store: QdrantStore, source: DocumentSource | None, today: date | None = None
) -> list[CollectionFreshness]:
    today = today or date.today()
    limits: dict[str, int] = {}
    if source is not None:
        for name in source.collections():
            try:
                limits[name] = parse_manifest(name, source.manifest(name)).max_age_days
            except ValueError:
                continue
    by_collection: dict[str, list[str]] = {}
    for doc in store.indexed_docs().values():
        by_collection.setdefault(doc.collection, []).append(doc.ingested_at)
    rows: list[CollectionFreshness] = []
    for name in sorted(by_collection):
        dates = sorted(by_collection[name])
        age = (today - date.fromisoformat(dates[0])).days  # the oldest document sets the age
        limit = limits.get(name, 7)
        rows.append(CollectionFreshness(name, len(dates), dates[0], dates[-1], limit, age, age > limit))
    return rows
