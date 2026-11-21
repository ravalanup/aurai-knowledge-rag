"""Turn source bytes into text plus metadata. Markdown and text may carry YAML front matter."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

import yaml

SUPPORTED = (".md", ".txt", ".pdf")
_FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


class ParseError(ValueError):
    """The document cannot be turned into usable text."""


@dataclass(frozen=True)
class ParsedDoc:
    title: str
    text: str
    front_matter: dict[str, Any] = field(default_factory=dict)


def is_supported(key: str) -> bool:
    return PurePosixPath(key).suffix.lower() in SUPPORTED


def parse_document(key: str, data: bytes) -> ParsedDoc:
    suffix = PurePosixPath(key).suffix.lower()
    stem = PurePosixPath(key).stem.replace("-", " ").replace("_", " ").strip().title()
    if suffix == ".pdf":
        return _parse_pdf(data, stem)
    if suffix not in (".md", ".txt"):
        raise ParseError(f"unsupported file type {suffix or '(none)'}")
    try:
        raw = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ParseError("file is not valid UTF-8") from exc
    front: dict[str, Any] = {}
    match = _FRONT.match(raw)
    if match:
        try:
            loaded = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError as exc:
            raise ParseError("front matter is not valid YAML") from exc
        if not isinstance(loaded, dict):
            raise ParseError("front matter must be a mapping")
        front = loaded
        raw = raw[match.end() :]
    text = raw.strip()
    if not text:
        raise ParseError("document is empty")
    title = str(front.get("title") or _first_heading(text) or stem)
    return ParsedDoc(title=title, text=text, front_matter=front)


def _first_heading(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _parse_pdf(data: bytes, stem: str) -> ParsedDoc:
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
        meta_title = (reader.metadata.title if reader.metadata else None) or ""
    except (PyPdfError, ValueError, OSError) as exc:
        raise ParseError("PDF could not be read") from exc
    text = "\n\n".join(p for p in pages if p)
    if not text:
        raise ParseError("PDF has no extractable text (scanned documents need OCR, which is not included)")
    return ParsedDoc(title=str(meta_title).strip() or stem, text=text)
