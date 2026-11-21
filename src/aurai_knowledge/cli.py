"""Command line: serve, ingest, validate-corpus, freshness and eval."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import httpx

from . import __version__
from .embeddings import HashEmbedder, build_embedder
from .entitlements import load_policy
from .evaluation import evaluate, load_golden
from .freshness import freshness_report
from .ingest import Ingestor, validate_corpus
from .settings import Settings
from .sources import open_source
from .store import QdrantStore


def _offline_search(policy_path: str, corpus: str):
    """An in-memory index built with the hash embedder, searched through the real service code."""
    from qdrant_client import QdrantClient

    from .models import Identity
    from .service import SearchService

    policy = load_policy(policy_path)
    store = QdrantStore(QdrantClient(":memory:"), "eval")
    embedder = HashEmbedder()
    report = Ingestor(open_source(corpus), store, embedder, fingerprint="offline").run()
    if report.rejected:
        raise SystemExit(
            "corpus has rejected documents:\n" + "\n".join(f"  {r.doc_id}: {r.reason}" for r in report.rejected)
        )
    service = SearchService(policy, store, embedder)

    def search(groups, query, top_k, collections):
        from .service import Forbidden

        try:
            outcome = service.search(Identity("eval", groups, frozenset()), query, collections, top_k)
        except Forbidden:
            return []
        return [(h.doc_id, h.collection, h.classification.label) for h in outcome.hits]

    return policy, search


def _online_search(url: str, policy_path: str):
    policy = load_policy(policy_path)

    def search(groups, query, top_k, collections):
        persona = next((p for p, g in _PERSONA_GROUPS.items() if g == groups), None)
        token = os.environ.get(f"AURAI_EVAL_TOKEN_{(persona or '').upper().replace('-', '_')}", "")
        if not token:
            raise SystemExit(
                f"set AURAI_EVAL_TOKEN_{(persona or '?').upper()} to an access token for persona {persona}"
            )
        r = httpx.post(
            url.rstrip("/") + "/v1/search",
            json={"query": query, "top_k": top_k, **({"collections": collections} if collections else {})},
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        if r.status_code == 403:
            return []
        r.raise_for_status()
        return [
            (p["source"].get("uri", "").removeprefix("kb://"), p["source"]["collection"], p["source"]["classification"])
            for p in r.json()["results"]
        ]

    return policy, search


_PERSONA_GROUPS: dict[str, frozenset[str]] = {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aurai-knowledge", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    s = sub.add_parser("serve", help="run the knowledge service")
    s.add_argument("--host", default="0.0.0.0")  # noqa: S104 - bound inside a pod behind a Service
    s.add_argument("--port", type=int, default=8000)

    i = sub.add_parser("ingest", help="ingest approved collections into Qdrant")
    i.add_argument("--source", required=True, help="a folder, or s3://bucket/prefix")
    i.add_argument("--only", action="append", help="limit to a collection (repeatable)")
    i.add_argument("--max-chars", type=int, default=900)
    i.add_argument("--overlap", type=int, default=120)

    v = sub.add_parser("validate-corpus", help="check manifests and metadata without touching Qdrant")
    v.add_argument("--source", required=True)

    f = sub.add_parser("freshness", help="report collection age against each manifest's max_age_days")
    f.add_argument("--source", help="read max_age_days from this source's manifests")
    f.add_argument("--fail-on-stale", action="store_true")

    e = sub.add_parser("eval", help="run the golden set and the leakage check")
    e.add_argument("--golden", default="eval/golden-set.yaml")
    e.add_argument("--json", metavar="PATH", help="also write a machine-readable report (used as governance evidence)")
    e.add_argument("--policy", default="config/entitlements.yaml")
    e.add_argument("--corpus", default="corpus", help="offline mode: corpus folder")
    e.add_argument("--url", help="online mode: base URL of a running service (tokens via AURAI_EVAL_TOKEN_<PERSONA>)")
    e.add_argument("--top-k", type=int, default=5)

    args = parser.parse_args(argv)

    if args.command == "serve":
        import uvicorn

        uvicorn.run("aurai_knowledge.wiring:build_app", factory=True, host=args.host, port=args.port)
        return 0

    if args.command == "validate-corpus":
        problems = validate_corpus(open_source(args.source))
        for p in problems:
            print(f"REJECT {p.doc_id}: {p.reason}")
        print("corpus ok" if not problems else f"{len(problems)} problem(s)")
        return 1 if problems else 0

    settings = Settings.from_env()

    if args.command == "ingest":
        store = QdrantStore.connect(settings.qdrant_url, settings.qdrant_api_key, settings.qdrant_collection)
        fingerprint = f"{settings.embed_model}:{settings.embed_dimensions or 'default'}"
        report = Ingestor(
            open_source(args.source),
            store,
            build_embedder(settings),
            fingerprint=fingerprint,
            max_chars=args.max_chars,
            overlap=args.overlap,
        ).run(args.only)
        for r in report.rejected:
            print(f"REJECT {r.doc_id}: {r.reason}", file=sys.stderr)
        print(report.summary())
        return 1 if report.rejected else 0

    if args.command == "freshness":
        store = QdrantStore.connect(settings.qdrant_url, settings.qdrant_api_key, settings.qdrant_collection)
        rows = freshness_report(store, open_source(args.source) if args.source else None, date.today())
        print(json.dumps([r.__dict__ for r in rows], indent=2))
        return 1 if args.fail_on_stale and any(r.stale for r in rows) else 0

    if args.command == "eval":
        golden = load_golden(args.golden)
        _PERSONA_GROUPS.update({k: frozenset(v["groups"]) for k, v in golden["personas"].items()})
        policy, search = (
            _online_search(args.url, args.policy) if args.url else _offline_search(args.policy, args.corpus)
        )
        report = evaluate(golden, policy, search, args.top_k)
        print(report.render())
        if args.json:
            import hashlib

            summary = report.to_dict()
            summary["golden_set_sha256"] = hashlib.sha256(
                Path(args.golden).read_bytes().replace(b"\r\n", b"\n")
            ).hexdigest()
            summary["mode"] = "live" if args.url else "offline"
            summary["executed_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            Path(args.json).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        failures = report.failures()
        for line in failures:
            print(f"FAIL {line}", file=sys.stderr)
        return 1 if failures else 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
