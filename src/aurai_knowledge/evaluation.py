"""Retrieval-quality evaluation (KN-5): does the right source come back, and does anything leak?

Metrics
  hit_rate   share of answerable cases where at least one expected document is in the top-k
  mrr        mean reciprocal rank of the first expected document (0 when absent)
  leaks      passages returned that the persona may not read, or that a case marks as forbidden (must be 0)
  empty_ok   share of 'expect_empty' cases that correctly returned nothing relevant
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import yaml

from .entitlements import EntitlementPolicy
from .models import Classification

# A search function takes (persona groups, query, top_k, collections) and returns
# [(doc_id, collection, classification)]. A refused search (403) is an empty list.
SearchFn = Callable[[frozenset[str], str, int, "list[str] | None"], list[tuple[str, str, str]]]


@dataclass
class CaseResult:
    case_id: str
    persona: str
    ranked: list[str]
    hit: bool | None
    reciprocal_rank: float | None
    leaks: list[str]
    note: str = ""


@dataclass
class EvalReport:
    top_k: int
    cases: list[CaseResult] = field(default_factory=list)
    thresholds: dict[str, float] = field(default_factory=dict)

    @property
    def answerable(self) -> list[CaseResult]:
        return [c for c in self.cases if c.hit is not None]

    @property
    def hit_rate(self) -> float:
        rows = self.answerable
        return sum(1 for c in rows if c.hit) / len(rows) if rows else 0.0

    @property
    def mrr(self) -> float:
        rows = self.answerable
        return sum(c.reciprocal_rank or 0.0 for c in rows) / len(rows) if rows else 0.0

    @property
    def leaks(self) -> int:
        return sum(len(c.leaks) for c in self.cases)

    def failures(self) -> list[str]:
        out: list[str] = []
        t = self.thresholds
        if self.hit_rate < t.get("hit_rate", 0.0):
            out.append(f"hit_rate {self.hit_rate:.2f} is below {t['hit_rate']:.2f}")
        if self.mrr < t.get("mrr", 0.0):
            out.append(f"mrr {self.mrr:.2f} is below {t['mrr']:.2f}")
        if self.leaks > t.get("max_leaks", 0):
            out.append(f"{self.leaks} leaked passage(s); the limit is {int(t.get('max_leaks', 0))}")
        for c in self.cases:
            if c.note:
                out.append(f"case {c.case_id}: {c.note}")
        return out

    def to_dict(self) -> dict[str, Any]:
        """Machine-readable summary. aurai-eval-governance imports this as retrieval evidence."""
        return {
            "version": 1,
            "top_k": self.top_k,
            "cases": len(self.cases),
            "answerable": len(self.answerable),
            "hit_rate": round(self.hit_rate, 4),
            "mrr": round(self.mrr, 4),
            "leaks": self.leaks,
            "thresholds": dict(self.thresholds),
            "failures": self.failures(),
        }

    def render(self) -> str:
        lines = [f"cases={len(self.cases)} top_k={self.top_k}"]
        lines.append(f"hit_rate={self.hit_rate:.2f} mrr={self.mrr:.2f} leaks={self.leaks}")
        for c in self.cases:
            status = "n/a" if c.hit is None else ("hit" if c.hit else "MISS")
            lines.append(f"  {c.case_id:<28} {c.persona:<10} {status:<4} {', '.join(c.ranked[:3])}")
            for leak in c.leaks:
                lines.append(f"    LEAK: {leak}")
        return "\n".join(lines)


def load_golden(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict) or data.get("version") != 1 or not data.get("cases"):
        raise ValueError("golden set must be a mapping with version: 1 and a non-empty 'cases' list")
    personas = data.get("personas") or {}
    for case in data["cases"]:
        if case.get("persona") not in personas:
            raise ValueError(f"case {case.get('id')!r} uses unknown persona {case.get('persona')!r}")
        if not (case.get("expected") or case.get("expect_empty") or case.get("forbidden")):
            raise ValueError(f"case {case.get('id')!r} needs 'expected', 'forbidden' or expect_empty: true")
    return data


def evaluate(golden: dict[str, Any], policy: EntitlementPolicy, search: SearchFn, top_k: int = 5) -> EvalReport:
    report = EvalReport(top_k=top_k, thresholds=dict(golden.get("thresholds") or {}))
    personas = golden["personas"]
    for case in golden["cases"]:
        groups = frozenset(personas[case["persona"]]["groups"])
        entitlement = policy.resolve(groups)
        results = search(groups, case["query"], top_k, case.get("collections"))
        ranked: list[str] = []
        for doc_id, _, _ in results:
            if doc_id not in ranked:
                ranked.append(doc_id)
        leaks = [
            doc_id
            for doc_id, collection, classification in results
            if not entitlement.permits(collection, Classification.parse(classification))
        ]
        leaks += [d for d in ranked if d in set(case.get("forbidden") or []) and d not in leaks]
        expected = list(case.get("expected") or [])
        if not expected and not case.get("expect_empty"):  # a pure leak probe: only the leak check applies
            report.cases.append(CaseResult(case["id"], case["persona"], ranked, None, None, leaks))
            continue
        if case.get("expect_empty"):
            note = "expected no results for this persona but passages were returned" if ranked else ""
            report.cases.append(CaseResult(case["id"], case["persona"], ranked, None, None, leaks, note))
            continue
        rank = next((i + 1 for i, d in enumerate(ranked) if d in expected), None)
        report.cases.append(
            CaseResult(case["id"], case["persona"], ranked, rank is not None, 1 / rank if rank else 0.0, leaks)
        )
    return report
