# Runbook

## Signals

| Signal | Where | Meaning |
|---|---|---|
| `GET /readyz` returns 503 | Kubernetes readiness | Qdrant unreachable or the index does not exist yet |
| Ingestion job failed | `kubectl get jobs -n aurai-knowledge` | Rejected documents, or gateway or Qdrant unavailable. The log lists rejected document ids and reasons |
| `aurai.retrieval` spans | Langfuse / Phoenix | One per search, with collections searched and distinct sources returned |
| Log lines `search outcome=...` | Pod logs | `ok`, `forbidden`, `rejected` or `unavailable` with result count; never query or passage text |
| `freshness --fail-on-stale` exits 1 | Run by hand or in a job | A collection is older than its `max_age_days` |

## Common problems

| Symptom | Likely cause | Action |
|---|---|---|
| Everyone gets 401 | Wrong issuer or audience, or Keycloak keys unreachable | Compare the token's `iss` and `aud` with `config.oidcIssuer` and `config.oidcAudience`; check the pod can reach the JWKS URL |
| A user gets 403 for everything | None of their groups is in the policy | Check the `groups` claim; add a grant (reviewed) or add the user to the right group |
| 503 on search | Embedding or Qdrant unavailable | Check the gateway and the `knowledge` team budget; check Qdrant. The workspace tells the user; do not work around it |
| 422 on a normal question | The gateway's data policy refused the text | Expected for text with card numbers or similar identifiers |
| Search returns nothing relevant | Index empty, documents rejected, or a poor embedding fit | Look at the last ingestion log; run `eval --url`; check the model behind `aurai-embed` |
| Ingestion stops with a dimension mismatch | The embedding model or size changed | Rebuild the index (below) |

## Rebuild the index

Use after changing the embedding model, dimensions or chunking approach.

```powershell
kubectl port-forward -n aurai-system svc/qdrant 6333:6333
Invoke-RestMethod -Method Delete http://localhost:6333/collections/aurai_knowledge   # add an api-key header if Qdrant requires one
.\scripts\ingest-now.ps1
```

Search returns 503 between the delete and the end of the ingestion, so do this in a quiet period.

## Withdraw a document urgently

Remove or correct it at the source, then run `scripts\ingest-now.ps1` (or `aurai-knowledge ingest --only <collection>`). It is gone from search as soon as the job finishes. Without an urgent run it goes at the next scheduled ingestion.

## Pause the service

Pause the use case (`aurai-governance pause knowledge-search`) to stop the gateway team, which stops query embedding. To stop it completely, scale the deployment to zero: `kubectl scale deployment aurai-knowledge -n aurai-knowledge --replicas=0`.

## Rotate the gateway key

Issue a new key for the `knowledge` team, update the `knowledge-secrets` secret (`AURAI_GATEWAY_KEY`), then restart the deployment and re-run the ingestion job. Revoke the old key in the gateway.
