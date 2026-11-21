# Retrieval evaluation (KN-5)

`eval/golden-set.yaml` holds questions, the documents that should answer them, and checks that restricted content does not leak.

## Metrics

| Metric | Definition | Threshold |
|---|---|---|
| `hit_rate` | Share of answerable cases with an expected document in the top 5 | 0.85 |
| `mrr` | Mean reciprocal rank of the first expected document | 0.60 |
| `leaks` | Passages returned that the persona may not read, or that a case marks `forbidden` | 0 |

A persona is a set of token groups. Leaks are checked against the policy file, independently of the `forbidden` lists, so a new leak path is caught even if nobody wrote a case for it.

## Case types

- **Answerable:** `expected` lists acceptable documents.
- **Leak probe:** `forbidden` lists documents the persona must never receive; the question is asked in a way that would surface them if the filter were wrong.
- **Refusal:** `expect_empty: true`, optionally with `collections`, for requests that must return 403 or nothing.

## Running it

```powershell
aurai-knowledge eval                                   # offline: in-memory index, hash embedder, real service code
aurai-knowledge eval --url http://localhost:8000       # against a running service and the real embedding model
aurai-knowledge eval --url http://localhost:8000 --json eval-report.json   # also write a machine-readable report
```

The JSON report carries the hit rate, MRR, leak count, the thresholds used and the SHA-256 of the golden set. `aurai-governance evals import-retrieval` turns an online report into evidence for the promotion gate; an offline report is recorded as offline and never counts.

Online mode needs an access token per persona in `AURAI_EVAL_TOKEN_<PERSONA>` (for example `AURAI_EVAL_TOKEN_FINANCE`); `scripts\get-token.ps1` shows one way to get them in a non-production realm. The exit code is non-zero when a threshold fails, so either mode can gate a pipeline.

## How to read the offline numbers

The offline run uses a bag-of-words embedder. It proves the plumbing: ingestion metadata, the filter, ranking order, refusals and the leak check. It says little about semantic quality, and on a corpus of 20 short documents a high hit rate is expected. The numbers that matter for quality come from the online run with the chosen embedding model and a larger, realistic golden set written with the collection owners.

The test suite also checks the harness itself: a deliberately leaky retriever and a deliberately irrelevant one must both fail the evaluation.

## Next

`aurai-eval-governance` part 2 reads the JSON report as retrieval evidence for the `knowledge-search` use case (`governance/knowledge-search.use-case.yaml` registers it at the sandbox stage). It pins the golden set by SHA-256, so editing `eval/golden-set.yaml` means re-running the evaluation and updating the pin there.
