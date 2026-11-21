"""Where approved documents come from. A source is a set of collections; each collection is a folder (or
bucket prefix) holding a collection.yaml manifest and the documents themselves."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

MANIFEST = "collection.yaml"


@dataclass(frozen=True)
class SourceObject:
    key: str  # path within the collection, always '/'-separated
    read: Callable[[], bytes]


class DocumentSource(Protocol):
    def collections(self) -> list[str]: ...
    def manifest(self, collection: str) -> bytes | None: ...
    def objects(self, collection: str) -> Iterator[SourceObject]: ...


class LocalSource:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    def collections(self) -> list[str]:
        if not self._root.is_dir():
            raise FileNotFoundError(f"corpus folder not found: {self._root}")
        return sorted(p.name for p in self._root.iterdir() if p.is_dir() and not p.name.startswith("."))

    def manifest(self, collection: str) -> bytes | None:
        path = self._root / collection / MANIFEST
        return path.read_bytes() if path.is_file() else None

    def objects(self, collection: str) -> Iterator[SourceObject]:
        base = self._root / collection
        for path in sorted(base.rglob("*")):
            if path.is_file() and path.name != MANIFEST and not path.name.startswith("."):
                yield SourceObject(path.relative_to(base).as_posix(), path.read_bytes)


class S3Source:
    """Reads s3://bucket/prefix/<collection>/... Credentials come from the standard AWS chain (IRSA on EKS)."""

    def __init__(self, bucket: str, prefix: str = "", client: Any | None = None) -> None:
        if client is None:
            import boto3  # optional dependency: pip install "aurai-knowledge-rag[s3]"

            client = boto3.client("s3")
        self._s3 = client
        self._bucket = bucket
        self._prefix = prefix.strip("/") + "/" if prefix.strip("/") else ""

    def collections(self) -> list[str]:
        names: list[str] = []
        for page in self._s3.get_paginator("list_objects_v2").paginate(
            Bucket=self._bucket, Prefix=self._prefix, Delimiter="/"
        ):
            for common in page.get("CommonPrefixes", []):
                names.append(common["Prefix"][len(self._prefix) :].strip("/"))
        return sorted(names)

    def manifest(self, collection: str) -> bytes | None:
        try:
            body = self._s3.get_object(Bucket=self._bucket, Key=f"{self._prefix}{collection}/{MANIFEST}")["Body"]
        except self._s3.exceptions.NoSuchKey:
            return None
        return body.read()

    def objects(self, collection: str) -> Iterator[SourceObject]:
        base = f"{self._prefix}{collection}/"
        for page in self._s3.get_paginator("list_objects_v2").paginate(Bucket=self._bucket, Prefix=base):
            for item in page.get("Contents", []):
                key = item["Key"][len(base) :]
                if not key or key.endswith("/") or key == MANIFEST:
                    continue
                yield SourceObject(
                    key, lambda k=item["Key"]: self._s3.get_object(Bucket=self._bucket, Key=k)["Body"].read()
                )


def open_source(location: str) -> DocumentSource:
    """'s3://bucket/prefix' or a local folder."""
    if location.startswith("s3://"):
        bucket, _, prefix = location[5:].partition("/")
        if not bucket:
            raise ValueError("s3 location needs a bucket: s3://bucket/prefix")
        return S3Source(bucket, prefix)
    return LocalSource(location)
