# Ingestion and freshness

## Corpus layout

```text
corpus/
  guest-services/
    collection.yaml        team, owner, classification (default), max_age_days
    refund-policy.md       Markdown or text, optional front matter
    seasonal-hours.txt
  hr-policies/
    collection.yaml
    compensation-bands-2026.md
```

The same layout works under an S3 prefix: `s3://bucket/prefix/<collection>/...`.

`collection.yaml`:

| Field | Required | Meaning |
|---|---|---|
| `team` | yes | Owning team, stored on every chunk |
| `owner` | yes | Accountable role for approving content |
| `classification` | yes | Default for every document in the collection |
| `max_age_days` | no (7) | How old the collection's oldest document may get before the freshness report flags it |

Front matter (Markdown and text): `title`, `uri` (shown in citations; default `kb://<collection>/<path>`), and `classification` (may raise, never lower). PDFs use the collection defaults and the PDF's title or file name; they must contain real text (scans need OCR, which is not included).

## Commands

```powershell
aurai-knowledge validate-corpus --source corpus          # no network: manifests, metadata, parsing
aurai-knowledge ingest --source corpus                   # needs Qdrant and the gateway
aurai-knowledge ingest --source s3://bucket/prefix --only hr-policies
aurai-knowledge freshness --source corpus --fail-on-stale
```

`ingest` exits non-zero if any document was rejected, so a scheduled job surfaces bad content instead of hiding it.

## What happens to each document

| Situation | Result |
|---|---|
| New or changed | Chunked, embedded, written; chunks from a longer previous version are removed |
| Unchanged | Skipped; its freshness date is set to today, because the source was just confirmed |
| Removed from the source (or whole collection removed) | Deleted from the index |
| Missing or invalid metadata, lower classification than the collection, empty, unreadable | Rejected and reported; any older copy is deleted |
| Refused by the gateway's data policy | Rejected with the reason code; any older copy is deleted |
| Unsupported file type | Skipped and listed |
| Gateway or Qdrant unavailable | The run fails; the job is retried. Nothing is partially skipped |

A `--only` run touches only the named collections.

## Freshness (KN-4)

Each chunk records `ingested_at`, the last day the source was confirmed. Citations show it as `freshness`. The scheduled job (chart value `ingestion.schedule`, daily by default) re-checks every collection. `aurai-knowledge freshness` prints, per collection, its document count, oldest and newest date, allowed age and whether it is stale. A document deleted at the source disappears from search at the next run, so the schedule is also the worst-case time to withdraw content. For an urgent withdrawal run `scripts\ingest-now.ps1` or `ingest --only <collection>`.

## Chunking

Sections split on Markdown headings and keep their heading path (for example `Policy > Refunds`). Paragraphs are packed up to 900 characters with a 120-character overlap; very long paragraphs split at sentences, then words. The title and section go into the text that is embedded, not into the stored passage. Tune with `--max-chars` and `--overlap`; changing them re-ingests everything because they are part of each document's hash.
