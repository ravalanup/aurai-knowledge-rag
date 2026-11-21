"""Shared types: classification levels and the metadata every chunk must carry."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class Classification(IntEnum):
    """Data classification, ordered so that a ceiling check is a simple comparison."""

    PUBLIC = 0
    INTERNAL = 1
    CONFIDENTIAL = 2
    RESTRICTED = 3

    @classmethod
    def parse(cls, value: object) -> Classification:
        if isinstance(value, Classification):
            return value
        if isinstance(value, str):
            try:
                return cls[value.strip().upper()]
            except KeyError:
                pass
        raise ValueError(f"unknown classification {value!r}; expected one of {', '.join(c.label for c in cls)}")

    @property
    def label(self) -> str:
        return self.name.lower()


@dataclass(frozen=True)
class Identity:
    """The caller, as established from a verified token. Never built from request bodies."""

    subject: str
    groups: frozenset[str]
    roles: frozenset[str]


@dataclass(frozen=True)
class Chunk:
    """A passage ready to be embedded and stored. All metadata fields are mandatory."""

    doc_id: str
    chunk_index: int
    text: str
    embed_text: str
    collection: str
    team: str
    classification: Classification
    title: str
    uri: str
    section: str
    doc_hash: str
    ingested_at: str  # ISO date

    def payload(self) -> dict[str, object]:
        return {
            "doc_id": self.doc_id,
            "chunk_index": self.chunk_index,
            "text": self.text,
            "collection": self.collection,
            "team": self.team,
            "classification": self.classification.label,
            "classification_rank": int(self.classification),
            "title": self.title,
            "uri": self.uri,
            "section": self.section,
            "doc_hash": self.doc_hash,
            "ingested_at": self.ingested_at,
        }


@dataclass(frozen=True)
class Hit:
    """A stored passage returned by the vector store."""

    chunk_id: str
    score: float
    text: str
    doc_id: str
    title: str
    uri: str
    collection: str
    classification: Classification
    ingested_at: str
