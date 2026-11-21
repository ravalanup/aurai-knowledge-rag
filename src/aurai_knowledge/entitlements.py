"""Entitlements as code: which token groups may read which collections, up to which classification.

The mapping lives in config/entitlements.yaml and is reviewed like any other code change. The service
resolves it from the verified token's groups on every request; nothing in a request body can widen it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .models import Classification


class EntitlementError(ValueError):
    """The entitlement file is invalid."""


@dataclass(frozen=True)
class Entitlement:
    """What one caller may read: a classification ceiling per collection. Empty means nothing."""

    ceilings: dict[str, Classification]

    @property
    def collections(self) -> frozenset[str]:
        return frozenset(self.ceilings)

    def is_empty(self) -> bool:
        return not self.ceilings

    def narrowed(self, requested: list[str] | None) -> Entitlement:
        """Intersect with a caller-requested subset. Names the caller may not read are dropped."""
        if not requested:
            return self
        return Entitlement({c: r for c, r in self.ceilings.items() if c in set(requested)})

    def permits(self, collection: str, classification: Classification) -> bool:
        ceiling = self.ceilings.get(collection)
        return ceiling is not None and classification <= ceiling


@dataclass(frozen=True)
class EntitlementPolicy:
    collections: frozenset[str]
    grants: dict[str, dict[str, Classification]]  # group -> collection -> ceiling

    def resolve(self, groups: frozenset[str]) -> Entitlement:
        """Union of the grants of every group the caller belongs to; the highest ceiling wins."""
        merged: dict[str, Classification] = {}
        for group in groups:
            for collection, ceiling in self.grants.get(group, {}).items():
                if collection not in merged or ceiling > merged[collection]:
                    merged[collection] = ceiling
        return Entitlement(merged)


def parse_policy(data: dict[str, Any]) -> EntitlementPolicy:
    if not isinstance(data, dict) or data.get("version") != 1:
        raise EntitlementError("entitlements file must be a mapping with version: 1")
    collections = data.get("collections")
    if not isinstance(collections, list) or not collections:
        raise EntitlementError("'collections' must be a non-empty list of collection names")
    names = frozenset(str(c) for c in collections)
    grants: dict[str, dict[str, Classification]] = {}
    for entry in data.get("grants") or []:
        group = entry.get("group")
        if not group:
            raise EntitlementError("every grant needs a 'group'")
        if group in grants:
            raise EntitlementError(f"group {group!r} appears in more than one grant")
        per_collection: dict[str, Classification] = {}
        for collection, level in (entry.get("collections") or {}).items():
            if collection not in names:
                raise EntitlementError(f"grant for {group!r} names unknown collection {collection!r}")
            try:
                per_collection[collection] = Classification.parse(level)
            except ValueError as exc:
                raise EntitlementError(f"grant for {group!r}, collection {collection!r}: {exc}") from exc
        grants[group] = per_collection
    return EntitlementPolicy(collections=names, grants=grants)


def load_policy(path: str | Path) -> EntitlementPolicy:
    with open(path, encoding="utf-8") as handle:
        return parse_policy(yaml.safe_load(handle))
