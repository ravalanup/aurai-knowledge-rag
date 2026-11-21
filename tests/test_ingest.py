from datetime import date

import pytest
from qdrant_client import QdrantClient

from aurai_knowledge.embeddings import HashEmbedder
from aurai_knowledge.freshness import freshness_report
from aurai_knowledge.ingest import Ingestor, parse_manifest, validate_corpus
from aurai_knowledge.sources import LocalSource
from aurai_knowledge.store import DimensionMismatch, QdrantStore

from .conftest import ROOT

MANIFEST = "collection: docs\nteam: t\nowner: o\nclassification: internal\n"


def make_store():
    return QdrantStore(QdrantClient(":memory:"), "t")


def write(root, collection, name, text, manifest=MANIFEST):
    folder = root / collection
    folder.mkdir(parents=True, exist_ok=True)
    if manifest is not None:
        (folder / "collection.yaml").write_text(manifest)
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")


def run(root, store, today=date(2026, 11, 1), **kw):
    return Ingestor(LocalSource(root), store, HashEmbedder(), today=today, **kw).run()


def test_shipped_corpus_validates_cleanly():
    assert validate_corpus(LocalSource(ROOT / "corpus")) == []


def test_every_chunk_carries_complete_metadata(store):
    points, _ = store._client.scroll("test", limit=1000, with_payload=True)
    assert len(points) > 20
    required = {"doc_id", "collection", "team", "classification", "classification_rank", "title", "ingested_at", "text"}
    for point in points:
        assert required <= point.payload.keys()
        assert point.payload["team"] and point.payload["collection"]


def test_front_matter_can_raise_classification(store):
    docs = store.indexed_docs()
    points, _ = store._client.scroll("test", limit=1000, with_payload=True)
    by_doc = {p.payload["doc_id"]: p.payload["classification"] for p in points}
    assert by_doc["guest-services/refund-policy.md"] == "public"
    assert by_doc["guest-services/service-recovery-playbook.md"] == "internal"
    assert by_doc["hr-policies/compensation-bands-2026.md"] == "restricted"
    assert "finance-reporting/capex-plan-fy27.md" in docs


def test_rerun_is_incremental(tmp_path):
    write(tmp_path, "docs", "a.md", "# A\n\nAlpha text.")
    store = make_store()
    first = run(tmp_path, store)
    assert first.ingested == ["docs/a.md"] and first.chunks_written == 1
    second = run(tmp_path, store)
    assert second.unchanged == ["docs/a.md"] and second.chunks_written == 0


def test_unchanged_documents_get_a_fresh_verification_date(tmp_path):
    write(tmp_path, "docs", "a.md", "# A\n\nAlpha text.")
    store = make_store()
    run(tmp_path, store, today=date(2026, 11, 1))
    run(tmp_path, store, today=date(2026, 11, 8))
    assert store.indexed_docs()["docs/a.md"].ingested_at == "2026-11-08"


def test_changed_document_replaces_old_chunks(tmp_path):
    write(tmp_path, "docs", "a.md", "# A\n\n" + "\n\n".join(f"Paragraph {i}. " + "filler " * 60 for i in range(6)))
    store = make_store()
    run(tmp_path, store)
    before = store._client.count("t").count
    assert before > 1
    write(tmp_path, "docs", "a.md", "# A\n\nNow a single short paragraph.")
    report = run(tmp_path, store)
    assert report.ingested == ["docs/a.md"]
    assert store._client.count("t").count == 1  # surplus chunks from the longer version are gone


def test_deleted_source_documents_are_removed(tmp_path):
    write(tmp_path, "docs", "a.md", "# A\n\nAlpha text.")
    write(tmp_path, "docs", "b.md", "# B\n\nBeta text.")
    store = make_store()
    run(tmp_path, store)
    (tmp_path / "docs" / "b.md").unlink()
    report = run(tmp_path, store)
    assert report.removed == ["docs/b.md"]
    assert set(store.indexed_docs()) == {"docs/a.md"}


def test_collection_removed_from_source_is_removed_from_index(tmp_path):
    write(tmp_path, "docs", "a.md", "# A\n\nAlpha text.")
    write(tmp_path, "other", "c.md", "# C\n\nGamma text.", manifest=MANIFEST.replace("docs", "other"))
    store = make_store()
    run(tmp_path, store)
    import shutil

    shutil.rmtree(tmp_path / "other")
    assert run(tmp_path, store).removed == ["other/c.md"]


def test_scoped_run_leaves_other_collections_alone(tmp_path):
    write(tmp_path, "docs", "a.md", "# A\n\nAlpha text.")
    write(tmp_path, "other", "c.md", "# C\n\nGamma text.", manifest=MANIFEST.replace("docs", "other"))
    store = make_store()
    run(tmp_path, store)
    (tmp_path / "other" / "c.md").unlink()
    report = Ingestor(LocalSource(tmp_path), store, HashEmbedder(), today=date(2026, 11, 1)).run(only=["docs"])
    assert report.removed == [] and "other/c.md" in store.indexed_docs()


@pytest.mark.parametrize(
    "manifest,reason",
    [
        (None, "collection.yaml is missing"),
        ("team: t\nowner: o\n", "classification"),
        ("classification: internal\nowner: o\n", "team"),
        ("team: t\nclassification: internal\n", "owner"),
        ("team: t\nowner: o\nclassification: top-secret\n", "unknown classification"),
        ("team: t\nowner: o\nclassification: internal\ncollection: elsewhere\n", "elsewhere"),
    ],
)
def test_collection_without_valid_metadata_is_not_ingested(tmp_path, manifest, reason):
    write(tmp_path, "docs", "a.md", "# A\n\nAlpha text.", manifest=manifest)
    store = make_store()
    report = run(tmp_path, store)
    assert report.ingested == [] and store._client.count("t").count == 0
    assert any(reason in r.reason for r in report.rejected)


def test_document_cannot_lower_its_classification(tmp_path):
    write(tmp_path, "docs", "a.md", "---\nclassification: public\n---\n# A\n\nAlpha text.")
    report = run(tmp_path, make_store())
    assert report.ingested == []
    assert "never lower" in report.rejected[0].reason


def test_a_document_that_becomes_invalid_is_removed_from_the_index(tmp_path):
    write(tmp_path, "docs", "a.md", "# A\n\nAlpha text.")
    store = make_store()
    run(tmp_path, store)
    write(tmp_path, "docs", "a.md", "---\nclassification: public\n---\n# A\n\nAlpha text.")
    report = run(tmp_path, store)
    assert report.removed == ["docs/a.md"] and store._client.count("t").count == 0


def test_changing_the_manifest_reingests(tmp_path):
    write(tmp_path, "docs", "a.md", "# A\n\nAlpha text.")
    store = make_store()
    run(tmp_path, store)
    write(tmp_path, "docs", "a.md", "# A\n\nAlpha text.", manifest=MANIFEST.replace("internal", "confidential"))
    assert run(tmp_path, store).ingested == ["docs/a.md"]
    assert store._client.scroll("t", limit=1, with_payload=True)[0][0].payload["classification"] == "confidential"


def test_bad_files_are_rejected_not_fatal(tmp_path):
    write(tmp_path, "docs", "good.md", "# Good\n\nGood text.")
    write(tmp_path, "docs", "empty.md", "   ")
    write(tmp_path, "docs", "binary.md", b"\xff\xfe\x00bad")
    write(tmp_path, "docs", "image.png", b"\x89PNG")
    report = run(tmp_path, make_store())
    assert report.ingested == ["docs/good.md"]
    assert {r.doc_id for r in report.rejected} == {"docs/empty.md", "docs/binary.md"}
    assert report.skipped_unsupported == ["docs/image.png"]


def test_pdf_ingestion(tmp_path):
    from io import BytesIO

    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.setTitle("Dock Safety Notice")
    pdf.drawString(72, 720, "Life jackets are mandatory on every harbor dock.")
    pdf.save()
    write(tmp_path, "docs", "notice.pdf", buffer.getvalue())
    store = make_store()
    assert run(tmp_path, store).ingested == ["docs/notice.pdf"]
    payload = store._client.scroll("t", limit=1, with_payload=True)[0][0].payload
    assert payload["title"] == "Dock Safety Notice" and "life jackets" in payload["text"].lower()


def test_pdf_without_text_is_rejected(tmp_path):
    from io import BytesIO

    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    canvas.Canvas(buffer).save()
    write(tmp_path, "docs", "scan.pdf", buffer.getvalue())
    report = run(tmp_path, make_store())
    assert "no extractable text" in report.rejected[0].reason


def test_changing_embedding_dimensions_is_caught(tmp_path):
    write(tmp_path, "docs", "a.md", "# A\n\nAlpha text.")
    store = make_store()
    run(tmp_path, store)
    with pytest.raises(DimensionMismatch):
        Ingestor(LocalSource(tmp_path), store, HashEmbedder(64), today=date(2026, 11, 1)).run()


def test_manifest_defaults():
    manifest = parse_manifest("docs", MANIFEST.encode())
    assert manifest.max_age_days == 7


def test_freshness_flags_collections_older_than_their_limit(tmp_path):
    write(tmp_path, "docs", "a.md", "# A\n\nAlpha text.", manifest=MANIFEST + "max_age_days: 7\n")
    store = make_store()
    run(tmp_path, store, today=date(2026, 11, 1))
    fresh = freshness_report(store, LocalSource(tmp_path), today=date(2026, 11, 5))
    stale = freshness_report(store, LocalSource(tmp_path), today=date(2026, 11, 20))
    assert not fresh[0].stale and stale[0].stale and stale[0].age_days == 19


def test_s3_source_reads_the_same_layout():
    import boto3
    from botocore.stub import Stubber  # noqa: F401 - ensures botocore is present

    from aurai_knowledge.sources import S3Source

    class Body:
        def __init__(self, data):
            self._d = data

        def read(self):
            return self._d

    objects = {
        "kb/docs/collection.yaml": MANIFEST.encode(),
        "kb/docs/a.md": b"# A\n\nAlpha text.",
        "kb/docs/sub/b.md": b"# B\n\nBeta text.",
    }

    class Paginator:
        def __init__(self, delimiter_mode):
            pass

        def paginate(self, Bucket, Prefix, Delimiter=None):  # noqa: N803
            if Delimiter:
                return [{"CommonPrefixes": [{"Prefix": "kb/docs/"}]}]
            return [{"Contents": [{"Key": k} for k in objects if k.startswith(Prefix)]}]

    class Client:
        class exceptions:  # noqa: N801
            class NoSuchKey(Exception):
                pass

        def get_paginator(self, _name):
            return Paginator(None)

        def get_object(self, Bucket, Key):  # noqa: N803
            if Key not in objects:
                raise self.exceptions.NoSuchKey()
            return {"Body": Body(objects[Key])}

    assert boto3  # the real client is injected only to keep the test offline
    source = S3Source("bucket", "kb", client=Client())
    assert source.collections() == ["docs"]
    assert source.manifest("docs") == MANIFEST.encode()
    assert [o.key for o in source.objects("docs")] == ["a.md", "sub/b.md"]
    store = make_store()
    assert Ingestor(source, store, HashEmbedder(), today=date(2026, 11, 1)).run().ingested == [
        "docs/a.md",
        "docs/sub/b.md",
    ]


class RejectingEmbedder(HashEmbedder):
    """Refuses any text containing the word 'forbidden', like a gateway PII policy would."""

    def embed(self, texts):
        from aurai_knowledge.embeddings import EmbeddingRejected

        if any("forbidden" in t.lower() for t in texts):
            raise EmbeddingRejected("input rejected by the gateway (pii_blocked)")
        return super().embed(texts)


def test_document_refused_by_the_gateway_is_rejected_and_its_old_copy_removed(tmp_path):
    write(tmp_path, "docs", "a.md", "# A\n\nAlpha text.")
    write(tmp_path, "docs", "b.md", "# B\n\nBeta text.")
    store = make_store()
    Ingestor(LocalSource(tmp_path), store, RejectingEmbedder(), today=date(2026, 11, 1)).run()
    assert set(store.indexed_docs()) == {"docs/a.md", "docs/b.md"}
    write(tmp_path, "docs", "b.md", "# B\n\nBeta text with a forbidden identifier.")
    report = Ingestor(LocalSource(tmp_path), store, RejectingEmbedder(), today=date(2026, 11, 2)).run()
    assert [r.doc_id for r in report.rejected] == ["docs/b.md"] and "pii_blocked" in report.rejected[0].reason
    assert report.removed == ["docs/b.md"] and set(store.indexed_docs()) == {"docs/a.md"}
