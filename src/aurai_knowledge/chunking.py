"""Markdown-aware chunking: split on headings, pack paragraphs up to a size, carry a small overlap."""

from __future__ import annotations

import re
from dataclasses import dataclass

_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class TextChunk:
    text: str
    section: str


def _sections(text: str) -> list[tuple[str, str]]:
    """(heading path, body) pairs. Text before the first heading has an empty path."""
    stack: list[tuple[int, str]] = []
    sections: list[tuple[str, list[str]]] = [("", [])]
    for line in text.splitlines():
        match = _HEADING.match(line)
        if match:
            level = len(match.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, match.group(2)))
            sections.append((" > ".join(name for _, name in stack), []))
        else:
            sections[-1][1].append(line)
    return [(path, "\n".join(body).strip()) for path, body in sections if "\n".join(body).strip()]


def _split_long(paragraph: str, max_chars: int) -> list[str]:
    if len(paragraph) <= max_chars:
        return [paragraph]
    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE.split(paragraph):
        while len(sentence) > max_chars:  # a single run-on sentence: split on words
            cut = sentence.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            if current:
                pieces.append(current)
                current = ""
            pieces.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if current and len(current) + 1 + len(sentence) > max_chars:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


def _tail(text: str, overlap: int) -> str:
    if overlap <= 0 or len(text) <= overlap:
        return text if overlap > 0 else ""
    tail = text[-overlap:]
    space = tail.find(" ")
    return tail[space + 1 :] if space != -1 else tail


def chunk_text(text: str, max_chars: int = 900, overlap: int = 120) -> list[TextChunk]:
    if max_chars < 100 or overlap < 0 or overlap >= max_chars:
        raise ValueError("max_chars must be at least 100 and overlap must be smaller than max_chars")
    chunks: list[TextChunk] = []
    for path, body in _sections(text):
        paragraphs = [p for raw in re.split(r"\n\s*\n", body) for p in _split_long(raw.strip(), max_chars) if p]
        current = ""
        for paragraph in paragraphs:
            if current and len(current) + 2 + len(paragraph) > max_chars:
                chunks.append(TextChunk(current, path))
                seed = _tail(current, overlap)
                current = (
                    f"{seed}\n\n{paragraph}" if seed and len(seed) + 2 + len(paragraph) <= max_chars else paragraph
                )
            else:
                current = f"{current}\n\n{paragraph}".strip()
        if current:
            chunks.append(TextChunk(current, path))
    return chunks
