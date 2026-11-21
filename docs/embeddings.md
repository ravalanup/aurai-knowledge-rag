# Embeddings

The service calls one gateway alias, `aurai-embed`, through the OpenAI-compatible `/v1/embeddings` endpoint with the `knowledge` team's key. Which model sits behind the alias is a gateway setting, so this repo ships two overlays rather than choosing for you.

| Option | Overlay | Where text goes | Use for |
|---|---|---|---|
| Gemini | `gateway/embed-gemini.values.yaml` (`gemini/gemini-embedding-001`) | Provider API under the enterprise terms the model catalog assumes | Demos and collections cleared for that provider |
| Ollama | `gateway/embed-ollama.values.yaml` (`ollama/nomic-embed-text`) | Stays in the platform | Confidential or restricted collections |

Apply an overlay to the gateway release (needs the `litellm.modelOverrides` value from `aurai-gateway`):

```powershell
helm upgrade aurai-gateway ..\aurai-gateway\charts\aurai-gateway -n aurai-gateway --reuse-values -f gateway\embed-gemini.values.yaml
```

Update the `aurai-embed` entry in `aurai-gateway/config/model-catalog.yaml` to match the option you choose (provider, data handling, region). The catalog is the record of what leaves the platform. Confirm the provider model name against its current model list before deploying; it is the only place the vendor name appears.

## Dimensions

The index is created with the size the model returns. If you change model or size, ingestion stops with a dimension mismatch instead of mixing vectors; see the runbook to rebuild. Some models accept a smaller output size; set `config.embedDimensions` (chart) or `AURAI_EMBED_DIMENSIONS` to use it. Queries and documents must use the same setting.

## The gateway's data policy applies to this traffic

The `knowledge` team is rated T3 (restricted data, and a wrong passage can mislead a decision), and the gateway's PII guardrail inspects embedding input as well as chat:

- At T3 it **blocks** identifiers (card numbers, SSNs and similar) and **masks** contact details, names and locations before the model sees the text.
- A document the gateway refuses is rejected at ingestion with the reason code (never the content), and any older copy is removed. A query the gateway refuses returns 422.
- Because names and places are replaced with placeholders in both documents and queries, two chunks that differ mainly by a place name look more alike. This can lower retrieval quality for questions about specific people and places, and it is not measured yet. Run the golden set against a live gateway (`aurai-knowledge eval --url ...`) after choosing a model and compare with the offline numbers.

If masking proves too costly for a collection, the right fix is a conversation with the data owner and the platform team about the tier and the policy, not bypassing the gateway.

## Batching and limits

`config.embedBatchSize` (default 16) caps how many chunks go in one request. Some providers accept one input per request; LiteLLM batches those internally, but lower the setting if the gateway reports timeouts. Failures that are not policy refusals (timeouts, 5xx) are retried twice, then fail the run so the job is retried rather than silently skipping documents.
