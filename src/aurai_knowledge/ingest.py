"""Ingestion: validate metadata, chunk, embed and write documents; keep the index in step with the source.

Fail closed: a document whose metadata is missing or invalid is rejected, and any copy of it already in the
index is removed. Without metadata a chunk cannot be filtered, so it is not allowed to exist."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import yaml

from .chunking import chunk_text
from .embeddings import Embedder, EmbeddingRejected
from .models import Chunk, Classification
from .parsing import is_supported, parse_document
from .sources import DocumentSource
from .store import QdrantStore

_REQUIRED_MANIFEST = ("team", "classification", "owner")


@dataclass(frozen=True)
class Rejection:
    doc_id: str
    reason: str


@dataclass(frozen=True)
class Manifest:
    collection: str
    team: str
    classification: Classification
    owner: str
    max_age_days: int


@dataclass
class IngestReport:
    ingested: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    rejected: list[Rejection] = field(default_factory=list)
    skipped_unsupported: list[str] = field(default_factory=list)
    chunks_written: int = 0

    def summary(self) -> str:
        return (
            f"ingested={len(self.ingested)} unchanged={len(self.unchanged)} removed={len(self.removed)} "
            f"rejected={len(self.rejected)} unsupported={len(self.skipped_unsupported)} chunks={self.chunks_written}"
        )


@dataclass(frozen=True)
class PreparedDoc:
    doc_id: str
    chunks: list[Chunk]
    doc_hash: str


def parse_manifest(collection: str, raw: bytes | None) -> Manifest:
    if raw is None:
        raise ValueError("collection.yaml is missing")
    try:
        data: Any = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        raise ValueError("collection.yaml is not valid YAML") from exc
    if not isinstance(data, dict):
        raise ValueError("collection.yaml must be a mapping")
    missing = [k for k in _REQUIRED_MANIFEST if not str(data.get(k) or "").strip()]
    if missing:
        raise ValueError(f"collection.yaml is missing required field(s): {', '.join(missing)}")
    if data.get("collection") not in (None, collection):
        raise ValueError(f"collection.yaml names {data['collection']!r} but lives in {collection!r}")
    try:
        classification = Classification.parse(data["classification"])
        max_age = int(data.get("max_age_days", 7))
    except (ValueError, TypeError) as exc:
        raise ValueError(str(exc)) from exc
    if max_age < 1:
        raise ValueError("max_age_days must be at least 1")
    return Manifest(collection, str(data["team"]).strip(), classification, str(data["owner"]).strip(), max_age)


def prepare_document(
    manifest: Manifest, key: str, data: bytes, today: str, fingerprint: str, max_chars: int, overlap: int
) -> PreparedDoc:
    """Raises ValueError (ParseError included) with a reason that is safe to show an operator."""
    parsed = parse_document(key, data)
    classification = manifest.classification
    front = parsed.front_matter
    if "classification" in front:
        declared = Classification.parse(front["classification"])
        if declared < manifest.classification:
            raise ValueError(
                f"document declares {declared.label} but the collection default is {manifest.classification.label}; "
                "a document may raise its classification, never lower it"
            )
        classification = declared
    doc_id = f"{manifest.collection}/{key}"
    uri = str(front.get("uri") or f"kb://{doc_id}")
    doc_hash = hashlib.sha256(
        data
        + json.dumps(
            [manifest.team, classification.label, parsed.title, uri, max_chars, overlap, fingerprint], sort_keys=True
        ).encode()
    ).hexdigest()
    pieces = chunk_text(parsed.text, max_chars=max_chars, overlap=overlap)
    if not pieces:
        raise ValueError("document produced no text chunks")
    chunks = [
        Chunk(
            doc_id=doc_id,
            chunk_index=i,
            text=piece.text,
            embed_text=f"{parsed.title}" + (f" - {piece.section}" if piece.section else "") + f"\n{piece.text}",
            collection=manifest.collection,
            team=manifest.team,
            classification=classification,
            title=parsed.title,
            uri=uri,
            section=piece.section,
            doc_hash=doc_hash,
            ingested_at=today,
        )
        for i, piece in enumerate(pieces)
    ]
    return PreparedDoc(doc_id, chunks, doc_hash)


def validate_corpus(source: DocumentSource, max_chars: int = 900, overlap: int = 120) -> list[Rejection]:
    """Check every collection and document without touching Qdrant or the embedder."""
    problems: list[Rejection] = []
    for collection in source.collections():
        try:
            manifest = parse_manifest(collection, source.manifest(collection))
        except ValueError as exc:
            problems.append(Rejection(f"{collection}/", str(exc)))
            continue
        for obj in source.objects(collection):
            if not is_supported(obj.key):
                continue
            try:
                prepare_document(manifest, obj.key, obj.read(), "1970-01-01", "validate", max_chars, overlap)
            except ValueError as exc:
                problems.append(Rejection(f"{collection}/{obj.key}", str(exc)))
    return problems


class Ingestor:
    def __init__(
        self,
        source: DocumentSource,
        store: QdrantStore,
        embedder: Embedder,
        *,
        fingerprint: str = "default",
        max_chars: int = 900,
        overlap: int = 120,
        today: date | None = None,
    ) -> None:
        self._source = source
        self._store = store
        self._embedder = embedder
        self._fingerprint = fingerprint
        self._max_chars = max_chars
        self._overlap = overlap
        self._today = (today or date.today()).isoformat()

    def run(self, only: list[str] | None = None) -> IngestReport:
        report = IngestReport()
        probe = self._embedder.embed(["dimension probe"])
        self._store.ensure_collection(len(probe[0]))

        available = self._source.collections()
        scanned = [c for c in available if only is None or c in only]
        indexed = self._store.indexed_docs(None if only is None else scanned)
        seen: set[str] = set()

        for collection in scanned:
            try:
                manifest = parse_manifest(collection, self._source.manifest(collection))
            except ValueError as exc:
                report.rejected.append(Rejection(f"{collection}/", str(exc)))
                continue
            for obj in self._source.objects(collection):
                doc_id = f"{collection}/{obj.key}"
                if not is_supported(obj.key):
                    report.skipped_unsupported.append(doc_id)
                    continue
                try:
                    doc = prepare_document(
                        manifest, obj.key, obj.read(), self._today, self._fingerprint, self._max_chars, self._overlap
                    )
                except ValueError as exc:
                    report.rejected.append(Rejection(doc_id, str(exc)))
                    continue  # not added to `seen`, so a stale copy is removed below
                seen.add(doc_id)
                existing = indexed.get(doc_id)
                if existing and existing.doc_hash == doc.doc_hash:
                    if existing.ingested_at != self._today:
                        self._store.touch_doc(doc_id, self._today)  # freshness = last confirmed against the source
                    report.unchanged.append(doc_id)
                    continue
                try:
                    vectors = self._embedder.embed([c.embed_text for c in doc.chunks])
                except EmbeddingRejected as exc:
                    # Refused by the gateway's data policy: not retrievable, and any older copy is removed below.
                    seen.discard(doc_id)
                    report.rejected.append(Rejection(doc_id, str(exc)))
                    continue
                self._store.upsert(doc.chunks, vectors)
                self._store.delete_doc(doc_id, from_index=len(doc.chunks))
                report.ingested.append(doc_id)
                report.chunks_written += len(doc.chunks)

        for doc_id in sorted(set(indexed) - seen):
            self._store.delete_doc(doc_id)
            report.removed.append(doc_id)
        return report
